"""Celery SOAP 任務的兩個生產缺陷回歸測試（2026-07-27 真跑實測後補）。

1. **intake 進不了 SOAP**：`_async_generate` 舊版自行重組 patient_info，只放
   name/gender/age、完全不讀 `sessions.intake_data`，害 `soap_generator` 的
   past_medical_history / medications / allergies / family_history 四個分支
   在生產路徑成為死碼。實測後果：session cb4972c5 的 intake 明載
   「父親：膀胱癌」，SOAP 的 `subjective.family_history` 卻寫「未提供」——
   而那正是血尿主訴 §3b 必記的風險因子。本檔的 intake_data fixture
   就是該場次的真實 DB 內容（jsonb 原樣照抄）。

2. **重試設定是假的**：task 宣告 `max_retries=2 / default_retry_delay=30`，
   但 body 從不呼叫 `self.retry()`，`app/tasks/__init__.py` 也沒設
   `autoretry_for` → Celery 根本不會重試；任一次 OpenAI 失敗就永久 FAILED，
   只能靠醫師端手動 regenerate。

不變式：**重試前絕不標 FAILED**（重試成功卻留下錯誤狀態），
只有重試耗盡或例外不值得重試才標 FAILED。
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date, datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest
from celery.exceptions import Retry

from app.core.exceptions import AIServiceUnavailableException, ValidationException
from app.models.enums import Gender, ReportStatus
from app.tasks import report_queue


# ──────────────────────────────────────────────────────────
# Fixtures：真實 DB 內容
# ──────────────────────────────────────────────────────────

# 真實 intake_data（sessions.id = cb4972c5-4d11-4a63-882b-ed1f4771f2a2）。
# 這就是 SOAP 寫「family_history: 未提供」那一場的原始資料。
REAL_INTAKE_DATA: dict[str, Any] = {
    "allergies": [],
    "family_history": [{"relation": "父親", "condition": "膀胱癌"}],
    "medical_history": [
        {"condition": "高血壓", "still_has": True, "years_ago": "10"},
        {"condition": "第二型糖尿病", "still_has": True, "years_ago": "6"},
    ],
    "no_known_allergies": True,
    "current_medications": [{"name": "aspirin", "frequency": "每日一次"}],
    "no_current_medications": False,
    "no_past_medical_history": False,
}


def _fake_conversation(seq: int, role: str, text: str) -> SimpleNamespace:
    return SimpleNamespace(
        sequence_number=seq,
        role=SimpleNamespace(value=role),
        content_text=text,
        created_at=datetime(2026, 7, 27, 9, seq, tzinfo=timezone.utc),
    )


def _fake_patient() -> SimpleNamespace:
    """刻意使用真的 `Gender` enum member（而非 SimpleNamespace(value=...)），
    才抓得到「enum 原樣塞進 dict → f-string 輸出 Gender.MALE」那個缺陷。"""
    return SimpleNamespace(
        name="王大明",
        gender=Gender.MALE,
        date_of_birth=date(1960, 1, 1),
        # patients 表上的長期欄位留空，確保下面斷言的值只可能來自 intake
        medical_history=None,
        current_medications=None,
        allergies=None,
    )


def _fake_session(intake_data: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        language="zh-TW",
        chief_complaint_text="血尿",
        intake_data=intake_data,
        patient=_fake_patient(),
        chief_complaint=SimpleNamespace(name="血尿", name_en="Hematuria"),
        conversations=[
            _fake_conversation(1, "assistant", "請描述症狀"),
            _fake_conversation(2, "patient", "小便有血兩天"),
        ],
    )


def _fake_report() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        subjective=None,
        objective=None,
        assessment=None,
        plan=None,
        raw_transcript=None,
        summary=None,
        icd10_codes=None,
        icd10_verified=None,
        ai_confidence_score=None,
        language=None,
        status=ReportStatus.GENERATING,
        generated_at=None,
    )


class _FakeResult:
    def __init__(self, obj: Any = None, rows: list[Any] | None = None):
        self._obj = obj
        self._rows = rows or []

    def scalar_one_or_none(self):
        return self._obj

    def scalars(self):
        return SimpleNamespace(all=lambda: self._rows)


class _FakeDB:
    def __init__(self, session_obj, report_obj):
        self._session_obj = session_obj
        self._report_obj = report_obj
        self.commits = 0
        self.rollbacks = 0

    async def execute(self, stmt):
        s = str(stmt)
        if "red_flag_alerts" in s:
            return _FakeResult(rows=[])
        if "soap_reports" in s:
            return _FakeResult(obj=self._report_obj)
        return _FakeResult(obj=self._session_obj)

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1

    async def flush(self):
        pass

    def add(self, obj):
        pass


class _FakeSessionFactory:
    def __init__(self, db: _FakeDB):
        self._db = db

    def __call__(self):
        return self

    async def __aenter__(self):
        return self._db

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeTask:
    """替身 Celery task instance。

    `bind=True` 的 task 無法注入 self，且在 worker 外呼叫真的 `task.retry()`
    會走 `called_directly` 分支（直接重拋原例外），測不到生產行為——
    故 `_run_task(task, session_id)` 收 task 參數，測試在此餵假的。
    """

    def __init__(self, retries: int = 0, max_retries: int = 2, delay: int = 30):
        self.request = SimpleNamespace(retries=retries)
        self.max_retries = max_retries
        self.default_retry_delay = delay
        self.retry_calls: list[dict[str, Any]] = []

    def retry(self, exc=None, countdown=None):
        self.retry_calls.append({"exc": exc, "countdown": countdown})
        raise Retry("retry scheduled")


# ──────────────────────────────────────────────────────────
# 共用 monkeypatch
# ──────────────────────────────────────────────────────────


def _install(monkeypatch, db: _FakeDB, *, generate):
    """把 `_async_generate` 的所有外部相依換成替身；`generate` 為
    SOAPGenerator.generate 的替身（可 return dict 或 raise）。"""
    import app.core.database as core_db
    import app.pipelines.soap_generator as sg_mod
    from app.services.notification_service import NotificationService
    from app.services.report_service import ReportService

    monkeypatch.setattr(core_db, "async_session_factory", _FakeSessionFactory(db))

    class _FakeGenerator:
        def __init__(self, _settings):
            pass

        async def generate(self, **kwargs):
            return await generate(**kwargs)

    monkeypatch.setattr(sg_mod, "SOAPGenerator", _FakeGenerator)

    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(ReportService, "_snapshot_revision", staticmethod(_noop))
    monkeypatch.setattr(
        NotificationService, "notify_report_ready", staticmethod(_noop)
    )
    monkeypatch.setattr(report_queue, "_publish_report_generated", _noop)


def _capturing_generator(captured: dict[str, Any]):
    async def _generate(**kwargs):
        captured.update(kwargs)
        return {
            "subjective": {"summary": "s"},
            "objective": {"summary": "o"},
            "assessment": {"summary": "a"},
            "plan": {"summary": "p"},
            "summary": "ok",
            "icd10_codes": ["R31.9"],
            "icd10_verified": True,
            "confidence_score": 0.9,
        }

    return _generate


def _raising_generator(exc: BaseException):
    async def _generate(**kwargs):
        raise exc

    return _generate


# ──────────────────────────────────────────────────────────
# (a) intake 四類欄位真的進得了 patient_info
# ──────────────────────────────────────────────────────────


def test_patient_info_carries_all_four_intake_sections(monkeypatch):
    """Celery 路徑必須把 sessions.intake_data 的四類病史送進 SOAPGenerator。

    舊版只送 name/gender/age，這四個 assert 全會紅——
    尤其 family_history，正是實測寫成「未提供」的那一欄。
    """
    session_obj = _fake_session(REAL_INTAKE_DATA)
    db = _FakeDB(session_obj, _fake_report())
    captured: dict[str, Any] = {}
    _install(monkeypatch, db, generate=_capturing_generator(captured))

    result = asyncio.run(report_queue._async_generate(str(session_obj.id)))
    assert result["status"] == "generated"

    info = captured["patient_info"]
    # 四類病史（值即 soap_generator 會插進 prompt 的字串）
    assert info["medical_history"] == "高血壓、第二型糖尿病"
    assert info["medications"] == "aspirin"
    # no_known_allergies=True → 明確的「無」，而非 None（讓 LLM 分得清
    # 「已表明沒有」與「還沒問」）
    assert info["allergies"] == "無"
    # §3b 血尿必記風險因子：泌尿癌家族史
    assert info["family_history"] == "父親：膀胱癌"


def test_family_history_reaches_soap_prompt_text(monkeypatch):
    """再往下釘一層：這些值必須真的出現在送進 LLM 的 prompt 文字裡。

    只斷言 patient_info 的 key 不夠——soap_generator 是用
    `if patient_info.get(...)` 逐項組字串的，任何一項為 None 就整行消失。
    """
    from app.pipelines.soap_generator import SOAPGenerator

    session_obj = _fake_session(REAL_INTAKE_DATA)
    db = _FakeDB(session_obj, _fake_report())
    captured: dict[str, Any] = {}
    _install(monkeypatch, db, generate=_capturing_generator(captured))
    asyncio.run(report_queue._async_generate(str(session_obj.id)))

    info = captured["patient_info"]
    # 照抄 soap_generator._build_user_message 的組裝規則
    parts = []
    for key, label in (
        ("medical_history", "Past medical history"),
        ("medications", "Current medications"),
        ("allergies", "Allergies"),
        ("family_history", "Family history"),
    ):
        if info.get(key):
            parts.append(f"{label}: {info[key]}")
    text = "\n".join(parts)

    assert "Family history: 父親：膀胱癌" in text
    assert "Past medical history: 高血壓、第二型糖尿病" in text
    assert "Allergies: 無" in text
    assert "Current medications: aspirin" in text
    assert SOAPGenerator is not None  # import 守衛：欄位標籤來源模組仍存在


def test_gender_enum_does_not_leak_into_prompt(monkeypatch):
    """gender 必須是 'male' 而非 Gender enum member。

    `Gender` 是 `str, Enum`，`Gender.MALE == 'male'` 為 True，
    所以要用 f-string 渲染後的字串比對才抓得到。
    """
    session_obj = _fake_session(REAL_INTAKE_DATA)
    db = _FakeDB(session_obj, _fake_report())
    captured: dict[str, Any] = {}
    _install(monkeypatch, db, generate=_capturing_generator(captured))
    asyncio.run(report_queue._async_generate(str(session_obj.id)))

    info = captured["patient_info"]
    assert f"Gender: {info['gender']}" == "Gender: male"
    assert "Gender." not in f"{info['gender']}"


def test_null_intake_data_does_not_crash(monkeypatch):
    """intake_data 為 NULL（真實 DB 中確實存在，如 session 0c0fac54）時
    不可炸；四類病史為 None，姓名／年齡／性別照常。"""
    session_obj = _fake_session(None)
    db = _FakeDB(session_obj, _fake_report())
    captured: dict[str, Any] = {}
    _install(monkeypatch, db, generate=_capturing_generator(captured))

    result = asyncio.run(report_queue._async_generate(str(session_obj.id)))

    assert result["status"] == "generated"
    info = captured["patient_info"]
    assert info["name"] == "王大明"
    assert info["gender"] == "male"
    assert info["age"] is not None
    assert info["medical_history"] is None
    assert info["family_history"] is None


# ──────────────────────────────────────────────────────────
# (b) 第一次失敗要重試，且不可標 FAILED
# ──────────────────────────────────────────────────────────


def test_first_openai_failure_retries_and_keeps_generating(monkeypatch):
    """OpenAI 失敗（含 JSON 解析失敗，兩者都經 AIServiceUnavailableException）
    第一次不可直接 FAILED，必須排重試且報告維持 GENERATING。"""
    session_obj = _fake_session(REAL_INTAKE_DATA)
    report_obj = _fake_report()
    db = _FakeDB(session_obj, report_obj)
    exc = AIServiceUnavailableException()
    _install(monkeypatch, db, generate=_raising_generator(exc))

    task = _FakeTask(retries=0, max_retries=2, delay=30)
    with pytest.raises(Retry):
        report_queue._run_task(task, str(session_obj.id))

    # 真的排了重試，帶原例外與宣告的 30 秒延遲
    assert len(task.retry_calls) == 1
    assert task.retry_calls[0]["exc"] is exc
    assert task.retry_calls[0]["countdown"] == 30
    # 關鍵不變式：重試前不可標 FAILED
    assert report_obj.status == ReportStatus.GENERATING
    # 失敗的交易要 rollback，不可把半套狀態 commit 出去
    assert db.rollbacks == 1


def test_second_attempt_still_retries(monkeypatch):
    """retries=1 < max_retries=2 → 還有一次機會，仍不可 FAILED。"""
    session_obj = _fake_session(REAL_INTAKE_DATA)
    report_obj = _fake_report()
    db = _FakeDB(session_obj, report_obj)
    _install(monkeypatch, db, generate=_raising_generator(AIServiceUnavailableException()))

    task = _FakeTask(retries=1, max_retries=2)
    with pytest.raises(Retry):
        report_queue._run_task(task, str(session_obj.id))

    assert len(task.retry_calls) == 1
    assert report_obj.status == ReportStatus.GENERATING


# ──────────────────────────────────────────────────────────
# (c) 重試用盡才 FAILED
# ──────────────────────────────────────────────────────────


def test_retries_exhausted_marks_failed(monkeypatch):
    """retries == max_retries → 不再重試，標 FAILED 並把原例外往上拋
    （讓 Celery 記錄失敗、on_failure 兜底）。"""
    session_obj = _fake_session(REAL_INTAKE_DATA)
    report_obj = _fake_report()
    db = _FakeDB(session_obj, report_obj)
    exc = AIServiceUnavailableException()
    _install(monkeypatch, db, generate=_raising_generator(exc))

    task = _FakeTask(retries=2, max_retries=2)
    with pytest.raises(AIServiceUnavailableException):
        report_queue._run_task(task, str(session_obj.id))

    assert task.retry_calls == []  # 沒有再排重試
    assert report_obj.status == ReportStatus.FAILED


def test_non_retryable_exception_fails_without_retry(monkeypatch):
    """資料本身有問題（ValidationException / NotFoundException）重跑也沒用，
    第一次就 FAILED，不浪費 2 次 OpenAI 呼叫與 60 秒。"""
    session_obj = _fake_session(REAL_INTAKE_DATA)
    report_obj = _fake_report()
    db = _FakeDB(session_obj, report_obj)
    _install(monkeypatch, db, generate=_raising_generator(ValidationException()))

    task = _FakeTask(retries=0, max_retries=2)
    with pytest.raises(ValidationException):
        report_queue._run_task(task, str(session_obj.id))

    assert task.retry_calls == []
    assert report_obj.status == ReportStatus.FAILED


def test_is_retryable_classification():
    """分類本身的直接斷言，免得日後有人動了名單卻沒發現。"""
    from app.core.exceptions import NotFoundException

    assert report_queue._is_retryable(AIServiceUnavailableException()) is True
    assert report_queue._is_retryable(TimeoutError("openai timeout")) is True
    assert report_queue._is_retryable(ValidationException()) is False
    assert report_queue._is_retryable(NotFoundException()) is False


def test_successful_run_does_not_retry_or_fail(monkeypatch):
    """成功路徑不受重試改動影響：回傳 generated，報告狀態為 GENERATED。"""
    session_obj = _fake_session(REAL_INTAKE_DATA)
    report_obj = _fake_report()
    db = _FakeDB(session_obj, report_obj)
    _install(monkeypatch, db, generate=_capturing_generator({}))

    task = _FakeTask()
    result = report_queue._run_task(task, str(session_obj.id))

    assert result["status"] == "generated"
    assert task.retry_calls == []
    assert report_obj.status == ReportStatus.GENERATED


# ──────────────────────────────────────────────────────────
# (d) session_not_found 要標 FAILED，不可停在 GENERATING
# ──────────────────────────────────────────────────────────


def test_session_not_found_marks_report_failed(monkeypatch):
    """場次查不到時舊版直接 return，報告永遠停在 GENERATING、
    醫師端連「重新生成」都等不到。現在必須標 FAILED。"""
    report_obj = _fake_report()
    db = _FakeDB(None, report_obj)  # session 查無，但報告列存在
    _install(monkeypatch, db, generate=_capturing_generator({}))

    result = asyncio.run(report_queue._async_generate(str(uuid.uuid4())))

    assert result["status"] == "failed"
    assert result["reason"] == "session_not_found"
    assert report_obj.status == ReportStatus.FAILED
    assert db.commits == 1  # 狀態有真的落地


def test_session_not_found_does_not_retry(monkeypatch):
    """session_not_found 走的是回傳而非拋例外，因此不會觸發重試。"""
    report_obj = _fake_report()
    db = _FakeDB(None, report_obj)
    _install(monkeypatch, db, generate=_capturing_generator({}))

    task = _FakeTask()
    result = report_queue._run_task(task, str(uuid.uuid4()))

    assert result["reason"] == "session_not_found"
    assert task.retry_calls == []
    assert report_obj.status == ReportStatus.FAILED
