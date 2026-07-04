"""
W1：紅旗規則層加固守護測試。

背景（見 backend/app/pipelines/red_flag_detector.py `_load_rules` /
`_get_fallback_rules` / `_collect_all_language_keywords` 的設計理由註解）：

1. red_flag_rules 表在生產環境從未被 seed，`_load_rules()` 查詢「成功但
   0 筆」時語意上等同「規則層從未被配置過」，應 fallback 到內建
   catalogue（shared.URO_RED_FLAGS），而非讓規則層恆為 []。
   `RED_FLAG_BUILTIN_RULES_FALLBACK` 提供 kill-switch 可翻案回舊行為。
   DB 查詢例外時的 fallback 不受此旗標影響（維持既有行為）。
2. 規則比對的關鍵字集合改為所有語言 triggers 的聯集（fail-open：跨語言
   混講時也不能漏偵測），且比對需大小寫不敏感。
3. 規則層與語意層同輪命中同一 canonical_id 時必須合併為一筆。
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.pipelines import red_flag_detector as rfd_module
from app.pipelines.red_flag_detector import RedFlagDetector
from app.pipelines.prompts.shared import URO_RED_FLAGS


def _run(coro):
    return asyncio.run(coro)


class _FakeScalars:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return self._rows


class _FakeResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> _FakeScalars:
        return _FakeScalars(self._rows)


class _FakeDB:
    """極簡 AsyncSession stub：execute 回傳指定 rows，或依需求拋例外。"""

    def __init__(self, rows: list[Any] | None = None, raise_exc: Exception | None = None) -> None:
        self._rows = rows or []
        self._raise_exc = raise_exc

    async def execute(self, _stmt) -> _FakeResult:
        if self._raise_exc is not None:
            raise self._raise_exc
        return _FakeResult(self._rows)


def _make_settings(fallback_enabled: bool = True) -> MagicMock:
    settings = MagicMock()
    settings.OPENAI_MODEL_RED_FLAG = "gpt-4o-mini"
    settings.OPENAI_TEMPERATURE_RED_FLAG = 0.2
    settings.RED_FLAG_BUILTIN_RULES_FALLBACK = fallback_enabled
    return settings


def _make_detector(
    monkeypatch: pytest.MonkeyPatch,
    db: _FakeDB,
    fallback_enabled: bool = True,
) -> RedFlagDetector:
    fake_client = MagicMock()
    monkeypatch.setattr(
        rfd_module, "get_openai_client", MagicMock(return_value=fake_client)
    )
    return RedFlagDetector(_make_settings(fallback_enabled), db)


def _make_db_rule(canonical_id: str = "custom_rule") -> Any:
    """造一筆假的 DB RedFlagRule row（只需帶 `_load_rules` 讀取的屬性）。"""
    row = MagicMock()
    row.id = "11111111-1111-1111-1111-111111111111"
    row.canonical_id = canonical_id
    row.name = "自訂規則"
    row.display_title_by_lang = {"zh-TW": "自訂規則", "en-US": "Custom Rule"}
    row.severity = "high"
    row.category = "custom"
    row.keywords = ["自訂關鍵字"]
    row.regex_pattern = None
    row.description = "desc"
    row.suggested_actions = []
    return row


# ── 1. 空表 fallback ─────────────────────────────────────


def test_empty_table_falls_back_to_builtin_catalogue_when_enabled(monkeypatch):
    """DB 查詢成功但 0 筆 + kill-switch 開（預設）→ fallback 到內建 catalogue。"""
    db = _FakeDB(rows=[])
    detector = _make_detector(monkeypatch, db, fallback_enabled=True)

    _run(detector._load_rules())

    assert detector._rules_loaded is True
    assert len(detector._rules) == len(URO_RED_FLAGS)
    canonical_ids = {r["canonical_id"] for r in detector._rules}
    assert canonical_ids == {f["canonical_id"] for f in URO_RED_FLAGS}


def test_empty_table_kill_switch_off_keeps_rules_empty(monkeypatch):
    """空表 + kill-switch 關 → 維持舊行為，規則層真的是空的。"""
    db = _FakeDB(rows=[])
    detector = _make_detector(monkeypatch, db, fallback_enabled=False)

    _run(detector._load_rules())

    assert detector._rules_loaded is True
    assert detector._rules == []


def test_db_has_one_rule_does_not_mix_with_builtin_fallback(monkeypatch):
    """DB 有 1 筆規則 → 尊重 DB 配置，不與內建 catalogue 混用（只回那 1 筆）。"""
    db = _FakeDB(rows=[_make_db_rule("custom_rule")])
    detector = _make_detector(monkeypatch, db, fallback_enabled=True)

    _run(detector._load_rules())

    assert len(detector._rules) == 1
    assert detector._rules[0]["canonical_id"] == "custom_rule"


def test_db_query_exception_falls_back_regardless_of_kill_switch(monkeypatch):
    """DB 查詢例外 → 照舊 fallback 到內建 catalogue（此路徑不受 kill-switch 控制）。"""
    db = _FakeDB(raise_exc=RuntimeError("connection refused"))
    detector = _make_detector(monkeypatch, db, fallback_enabled=False)

    _run(detector._load_rules())

    assert detector._rules_loaded is True
    assert len(detector._rules) == len(URO_RED_FLAGS)


def test_rules_loaded_only_computed_once(monkeypatch):
    """_rules_loaded 為 True 時,_load_rules 直接回傳,不重新查詢。"""
    db = _FakeDB(rows=[])
    detector = _make_detector(monkeypatch, db, fallback_enabled=True)

    _run(detector._load_rules())
    first_rules = detector._rules
    # 手動竄改 rules，確認第二次呼叫不會覆寫（代表沒有重新查詢）
    detector._rules = ["sentinel"]
    _run(detector._load_rules())
    assert detector._rules == ["sentinel"]
    assert first_rules  # 前一輪確實有載入資料，避免測試本身是假陽性


# ── 2 & 3. 多語 triggers 聯集 + 大小寫不敏感 ─────────────


def test_en_session_hits_gross_hematuria_keyword(monkeypatch):
    """en 場次講英文 → 命中 gross_hematuria（fallback 內建規則含 en-US triggers）。"""
    db = _FakeDB(rows=[])
    detector = _make_detector(monkeypatch, db, fallback_enabled=True)
    _run(detector._load_rules())

    alerts = detector._rule_based_detect(
        "I see blood in urine since yesterday", language="en-US"
    )
    canonical_ids = {a["canonical_id"] for a in alerts}
    assert "gross_hematuria" in canonical_ids


def test_en_session_keyword_match_is_case_insensitive(monkeypatch):
    """英文關鍵字比對需大小寫不敏感：全大寫描述仍應命中。"""
    db = _FakeDB(rows=[])
    detector = _make_detector(monkeypatch, db, fallback_enabled=True)
    _run(detector._load_rules())

    alerts = detector._rule_based_detect(
        "I SEE BLOOD IN URINE TODAY", language="en-US"
    )
    canonical_ids = {a["canonical_id"] for a in alerts}
    assert "gross_hematuria" in canonical_ids


def test_ja_session_hits_gross_hematuria_keyword(monkeypatch):
    """ja 場次講日文 → 命中 gross_hematuria（fallback 內建規則含 ja-JP triggers）。"""
    db = _FakeDB(rows=[])
    detector = _make_detector(monkeypatch, db, fallback_enabled=True)
    _run(detector._load_rules())

    alerts = detector._rule_based_detect(
        "最近ずっと赤い尿が出ます", language="ja-JP"
    )
    canonical_ids = {a["canonical_id"] for a in alerts}
    assert "gross_hematuria" in canonical_ids


def test_ja_session_can_match_english_keyword_cross_language_union(monkeypatch):
    """
    跨語言聯集：ja 場次的病患混用英文描述，也應該被規則層命中
    （W1 設計理由：keyword 集合不因 session.language 篩選）。
    """
    db = _FakeDB(rows=[])
    detector = _make_detector(monkeypatch, db, fallback_enabled=True)
    _run(detector._load_rules())

    alerts = detector._rule_based_detect(
        "I have blood in urine", language="ja-JP"
    )
    canonical_ids = {a["canonical_id"] for a in alerts}
    assert "gross_hematuria" in canonical_ids


def test_fallback_rule_keywords_include_all_language_triggers(monkeypatch):
    """fallback rule 的 keywords 必須是所有語言 triggers 的聯集(而非僅 zh-TW)。"""
    fallback = RedFlagDetector._get_fallback_rules()
    by_canonical = {r["canonical_id"]: r for r in fallback}

    for flag in URO_RED_FLAGS:
        rule = by_canonical[flag["canonical_id"]]
        for lang_keywords in (flag.get("triggers_by_lang") or {}).values():
            for kw in lang_keywords:
                assert kw in rule["keywords"], (
                    f"{flag['canonical_id']} 遺漏跨語言 keyword: {kw}"
                )


# ── 4. rule + semantic 同輪同 canonical 合併 ─────────────


def test_rule_and_semantic_same_round_merge_into_one(monkeypatch):
    """同一輪：規則層與語意層都命中 gross_hematuria → 合併為 1 筆 combined alert。"""
    db = _FakeDB(rows=[])
    detector = _make_detector(monkeypatch, db, fallback_enabled=True)

    semantic_alert = {
        "canonical_id": "gross_hematuria",
        "severity": "high",
        "title": "Gross Hematuria",
        "description": "",
        "trigger_reason": "patient reports red urine",
        "alert_type": "semantic",
        "confidence": "semantic_only",
        "suggested_actions": [],
        "matched_rule_id": None,
    }

    async def _fake_semantic(self, text, ctx, language=None):
        return [semantic_alert.copy()]

    monkeypatch.setattr(RedFlagDetector, "_semantic_detect", _fake_semantic)

    merged = _run(
        detector.detect(
            "I see blood in urine",
            {"session_id": "s1", "language": "en-US"},
        )
    )

    assert len(merged) == 1
    assert merged[0]["canonical_id"] == "gross_hematuria"
    assert merged[0]["alert_type"] == "combined"
    assert merged[0]["confidence"] == "rule_hit"
