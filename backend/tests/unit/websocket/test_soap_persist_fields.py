"""
WS 路徑 `_generate_soap_report_async` 的 SOAP 持久化欄位測試（B2/B3 = D4/D6）。

守護 E2E 稽核修復 B 群的三個承重點：

- B2 [D6]：early-check 同一 DB context 內解析 symptom_id（chief_complaint.name_en
  → snake_case slug）並傳入 `SOAPGenerator.generate()`——漏傳會讓 ICD-10 驗證層
  short-circuit、`icd10_verified` 永遠 False（B1 白名單形同死碼）。
- B3 [D4]：`SOAPReport(...)` 建構子必須設 `language`（先前漏設 → 落 server_default
  恆 zh-TW）與 `icd10_verified`。`or DEFAULT_LANGUAGE` fallback 是承重的：欄位
  nullable=False，None 會 IntegrityError 被誤當 UNIQUE 冪等撞擊 → SOAP 靜默消失。
- 冪等回歸：early-check 查到既有 SOAP 必須早退（不呼叫 LLM、不 add）。

Mock 策略：函式內為 function-local import ⇒ patch 來源模組屬性
（app.core.database.get_db_session / app.pipelines.soap_generator.SOAPGenerator），
仿 test_report_queue_i18n.py 的 _FakeDB/_FakeResult 寫法。
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest

import app.core.database as core_db
import app.pipelines.soap_generator as sg_mod
import app.websocket.conversation_handler as ch


# ──────────────────────────────────────────────────────────
# Fakes
# ──────────────────────────────────────────────────────────


class _FakeResult:
    def __init__(self, obj: Any = None, rows: list[Any] | None = None):
        self._obj = obj
        self._rows = rows or []

    def scalar_one_or_none(self):
        return self._obj

    def scalars(self):
        return SimpleNamespace(all=lambda: self._rows)


class _FakeDB:
    """依 str(stmt) 分流的最小 AsyncSession 替身。

    - 含 "soap_reports" 的 select → 回 `existing_soap_id`（None = 無既有 SOAP）。
    - 含 "sessions" 的 select → 回假 session（B2 的 symptom_id 來源）。
    早期檢查與 insert 前雙重檢查共用同一實例（兩次 get_db_session 都 yield 它）。
    """

    def __init__(
        self,
        session_obj: Any = None,
        existing_soap_id: Any = None,
        red_flags: list[Any] | None = None,
    ):
        self._session_obj = session_obj
        self._existing_soap_id = existing_soap_id
        self._red_flags = red_flags or []
        self.added: list[Any] = []

    async def execute(self, stmt):
        s = str(stmt)
        if "soap_reports" in s:
            return _FakeResult(obj=self._existing_soap_id)
        # A2：即時 SOAP 路徑會查本場次紅旗注入 generate()；測試無紅旗 → 回空。
        if "red_flag_alerts" in s:
            return _FakeResult(rows=list(self._red_flags))
        if "sessions" in s:
            return _FakeResult(obj=self._session_obj)
        raise AssertionError(f"unexpected stmt: {s}")

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        pass

    async def flush(self):
        pass


_DEFAULT_SOAP_DATA: dict[str, Any] = {
    "subjective": {"summary": "s"},
    "objective": {"summary": "o"},
    "assessment": {"summary": "a"},
    "plan": {"summary": "p"},
    "summary": "ok",
    "icd10_codes": ["R31.9"],
    "icd10_verified": True,
    "confidence_score": 0.9,
}

_DEFAULT = object()  # sentinel：與「刻意傳 None」區分


def _run(
    monkeypatch,
    *,
    session_obj: Any = _DEFAULT,
    existing_soap_id: Any = None,
    language: str | None = "zh-TW",
    soap_data: dict[str, Any] | None = None,
    red_flags: list[Any] | None = None,
) -> SimpleNamespace:
    """await `_generate_soap_report_async` 一輪，回傳 fakes 供斷言。"""
    if session_obj is _DEFAULT:
        session_obj = SimpleNamespace(
            chief_complaint=SimpleNamespace(name_en="Hematuria", name="血尿")
        )
    db = _FakeDB(
        session_obj=session_obj,
        existing_soap_id=existing_soap_id,
        red_flags=red_flags,
    )

    @asynccontextmanager
    async def _fake_get_db_session():
        yield db

    monkeypatch.setattr(core_db, "get_db_session", _fake_get_db_session)

    captured: dict[str, Any] = {}
    calls = {"generate": 0}
    data = dict(_DEFAULT_SOAP_DATA) if soap_data is None else dict(soap_data)

    class _FakeGenerator:
        def __init__(self, _settings):
            pass

        async def generate(self, **kwargs):
            calls["generate"] += 1
            captured.update(kwargs)
            return dict(data)

    monkeypatch.setattr(sg_mod, "SOAPGenerator", _FakeGenerator)

    session_context = {
        "session_id": str(uuid.uuid4()),
        "chief_complaint": "血尿",
        "patient_info": {"name": "測試病患"},
        "language": language,
    }
    # settings 只被 SOAPGenerator stub 與 B3 fallback 用到，SimpleNamespace 足矣
    settings = SimpleNamespace(DEFAULT_LANGUAGE="zh-TW")

    asyncio.run(
        ch._generate_soap_report_async(
            session_id=str(uuid.uuid4()),
            conversation_history=[
                {"role": "assistant", "content": "請描述症狀"},
                {"role": "patient", "content": "小便有血兩天"},
            ],
            session_context=session_context,
            settings=settings,
        )
    )

    return SimpleNamespace(
        db=db, captured=captured, generate_calls=calls["generate"]
    )


# ──────────────────────────────────────────────────────────
# B2：symptom_id 傳遞
# ──────────────────────────────────────────────────────────


def test_red_flags_from_db_passed_to_generator(monkeypatch):
    """A2：即時路徑查本場次 red_flag_alerts 並轉 dict 傳進 generate()。

    先前漏傳 → generate() red_flags=None → _enforce_red_flag_urgency 恆 no-op（死代碼）。
    """
    rf_row = SimpleNamespace(
        severity="critical",
        canonical_id="testicular_pain_severe",
        trigger_reason="睪丸劇痛",
        suggested_actions=["請立即告知現場醫護"],
    )
    r = _run(monkeypatch, red_flags=[rf_row])
    assert r.generate_calls == 1
    passed = r.captured["red_flags"]
    assert passed == [
        {
            "severity": "critical",
            "canonical_id": "testicular_pain_severe",
            "trigger_reason": "睪丸劇痛",
            "suggested_actions": ["請立即告知現場醫護"],
        }
    ]


def test_no_red_flags_passes_empty_list(monkeypatch):
    """無紅旗 → red_flags 傳空 list（非 None）；generate 仍正常呼叫。"""
    r = _run(monkeypatch)
    assert r.captured["red_flags"] == []


def test_symptom_id_passed_to_generator(monkeypatch):
    """假 session name_en="Hematuria" → slug "hematuria" 傳進 generate()。"""
    r = _run(monkeypatch)
    assert r.generate_calls == 1
    assert r.captured["symptom_id"] == "hematuria"
    # language 也照 session_context 傳給 generator（既有行為回歸守護）
    assert r.captured["language"] == "zh-TW"


def test_sentinel_or_missing_complaint_graceful(monkeypatch):
    """B2 graceful：主訴缺失 / 「其他」sentinel 都不 raise、不早退，照常 add。"""
    # 無主訴（chief_complaint=None）→ symptom_id=None
    r = _run(monkeypatch, session_obj=SimpleNamespace(chief_complaint=None))
    assert r.captured["symptom_id"] is None
    assert len(r.db.added) == 1  # 仍成功持久化

    # 「其他」sentinel（name_en="Other"）→ "other"（不在對映表 → unverified，見
    # test_symptom_resolve.py），SOAP 生成流程不受影響
    r2 = _run(
        monkeypatch,
        session_obj=SimpleNamespace(
            chief_complaint=SimpleNamespace(name_en="Other", name="其他")
        ),
    )
    assert r2.captured["symptom_id"] == "other"
    assert len(r2.db.added) == 1

    # 查無 session（scalar_one_or_none 回 None）→ resolve_symptom_id(None) 安全回 None
    r3 = _run(monkeypatch, session_obj=None)
    assert r3.captured["symptom_id"] is None
    assert len(r3.db.added) == 1


# ──────────────────────────────────────────────────────────
# B3：language / icd10_verified 持久化
# ──────────────────────────────────────────────────────────


def test_language_persisted_from_session_context(monkeypatch):
    """D4 根因：SOAP.language 必須跟 session 語言，不得恆落 server_default zh-TW。"""
    r = _run(monkeypatch, language="en-US")
    assert len(r.db.added) == 1
    assert r.db.added[0].language == "en-US"


def test_language_fallback_to_default_when_none(monkeypatch):
    """承重 fallback：session 語言為 None 時落 DEFAULT_LANGUAGE，絕不把 None
    傳進 nullable=False 欄位（否則 IntegrityError 被誤當冪等撞擊 → SOAP 靜默消失）。"""
    r = _run(monkeypatch, language=None)
    assert len(r.db.added) == 1
    assert r.db.added[0].language == "zh-TW"


@pytest.mark.parametrize(
    ("soap_data_verified", "expected"),
    [
        (True, True),
        (False, False),
        (_DEFAULT, False),  # generator 缺 icd10_verified key → 保守 False
    ],
)
def test_icd10_verified_persisted(monkeypatch, soap_data_verified, expected):
    """D6：validator 的驗證結果必須持久化（先前漏設 → 恆 server_default False）。"""
    data = dict(_DEFAULT_SOAP_DATA)
    if soap_data_verified is _DEFAULT:
        data.pop("icd10_verified")
    else:
        data["icd10_verified"] = soap_data_verified
    r = _run(monkeypatch, soap_data=data)
    assert len(r.db.added) == 1
    assert r.db.added[0].icd10_verified is expected


# ──────────────────────────────────────────────────────────
# 冪等回歸守護
# ──────────────────────────────────────────────────────────


def test_early_return_when_soap_exists(monkeypatch):
    """early-check 查到既有 SOAP → 早退：generator 未被呼叫、無任何 add。"""
    r = _run(monkeypatch, existing_soap_id=uuid.uuid4())
    assert r.generate_calls == 0
    assert r.db.added == []
