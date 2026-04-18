"""
TODO-M8：紅旗 confidence 三分支守護(rule_hit / semantic_only / uncovered_locale)
與 AlertService.create 寫入時的 audit log escalation。

場景:
  A) 規則層命中 → confidence=rule_hit
  B) 僅語意層命中且 locale 有覆蓋 → confidence=semantic_only
  C) 僅語意層命中但 session.language 無 trigger 覆蓋 → confidence=uncovered_locale
     + AlertService.create 須寫一筆 audit log(action=CREATE, resource_type=red_flag_alert,
     details.reason=uncovered_locale_escalation)
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from app.models.enums import AlertSeverity, AlertType, RedFlagConfidence
from app.pipelines import red_flag_detector as rfd_module
from app.pipelines.red_flag_detector import RedFlagDetector
from app.services.alert_service import AlertService


def _run(coro):
    return asyncio.run(coro)


# ── Helpers(與 test_red_flag_detector_i18n.py 同 pattern) ─────


def _make_detector(rules: list[dict[str, Any]], monkeypatch) -> RedFlagDetector:
    settings = MagicMock()
    settings.OPENAI_MODEL_RED_FLAG = "gpt-4o-mini"
    settings.OPENAI_TEMPERATURE_RED_FLAG = 0.2
    db = MagicMock()
    fake_client = MagicMock()
    monkeypatch.setattr(
        rfd_module, "get_openai_client", MagicMock(return_value=fake_client)
    )
    detector = RedFlagDetector(settings, db)
    detector._rules = rules
    detector._rules_loaded = True
    return detector


async def _stub_semantic_return(alerts_to_return: list[dict[str, Any]], monkeypatch):
    """讓 _semantic_detect 直接回傳指定 alerts(不打 OpenAI)。"""
    async def _fake(_self, _text, _ctx, language=None):
        return list(alerts_to_return)

    monkeypatch.setattr(RedFlagDetector, "_semantic_detect", _fake)


# ── 分支 A：rule_hit ────────────────────────────────────


def test_rule_hit_confidence_on_rule_layer_match(monkeypatch):
    """
    zh-TW session,規則層命中「血尿」關鍵字 → alert 帶 confidence=rule_hit。
    """
    rules = [
        {
            "id": None,
            "canonical_id": "gross_hematuria",
            "name": "肉眼血尿",
            "display_title_by_lang": {
                "zh-TW": "肉眼血尿",
                "en-US": "Gross Hematuria",
            },
            "severity": "high",
            "category": "urinary",
            "keywords": ["血尿"],
            "regex_pattern": None,
            "description": "",
            "suggested_actions": [],
        }
    ]
    detector = _make_detector(rules, monkeypatch)
    alerts = detector._rule_based_detect("今早開始有血尿", language="zh-TW")
    assert len(alerts) == 1
    assert alerts[0]["confidence"] == "rule_hit"
    assert alerts[0]["canonical_id"] == "gross_hematuria"
    # display title 依 language 渲染
    assert alerts[0]["title"] == "肉眼血尿"


def test_rule_hit_title_localized_en_us(monkeypatch):
    rules = [
        {
            "id": None,
            "canonical_id": "gross_hematuria",
            "name": "Gross Hematuria",
            "display_title_by_lang": {
                "zh-TW": "肉眼血尿",
                "en-US": "Gross Hematuria",
            },
            "severity": "high",
            "category": "urinary",
            "keywords": ["hematuria"],
            "regex_pattern": None,
            "description": "",
            "suggested_actions": [],
        }
    ]
    detector = _make_detector(rules, monkeypatch)
    alerts = detector._rule_based_detect(
        "I noticed hematuria this morning", language="en-US"
    )
    assert len(alerts) == 1
    assert alerts[0]["confidence"] == "rule_hit"
    assert alerts[0]["title"] == "Gross Hematuria"


# ── 分支 B：semantic_only ───────────────────────────────


def test_semantic_only_when_no_rule_layer_match(monkeypatch):
    """
    zh-TW session,規則層無命中,語意層回一筆「肉眼血尿」(catalogue 該項 zh-TW 有覆蓋)
    → confidence 保持 semantic_only(不降級為 uncovered_locale)。
    """
    detector = _make_detector([], monkeypatch)
    # stub 語意層
    semantic_alert = {
        "canonical_id": "gross_hematuria",
        "severity": "high",
        "title": "肉眼血尿",
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

    merged = _run(detector.detect("紅紅的尿", {"session_id": "s1", "language": "zh-TW"}))
    assert len(merged) == 1
    assert merged[0]["confidence"] == "semantic_only"
    assert merged[0]["canonical_id"] == "gross_hematuria"


# ── 分支 C：uncovered_locale ────────────────────────────


def test_uncovered_locale_escalation_for_unsupported_language(monkeypatch):
    """
    fr-FR session(catalogue 尚無 triggers_by_lang["fr-FR"]),語意層命中 gross_hematuria
    → detector 偵測到 has_locale_coverage(cid, 'fr-FR') 為 False,自動降級為 uncovered_locale。
    """
    detector = _make_detector([], monkeypatch)
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

    merged = _run(detector.detect(
        "red urine today", {"session_id": "s1", "language": "fr-FR"}
    ))
    assert len(merged) == 1
    assert merged[0]["confidence"] == "uncovered_locale", (
        "fr-FR 無該紅旗 trigger 覆蓋 → 必須降級為 uncovered_locale"
    )


def test_rule_hit_not_downgraded_even_in_unsupported_language(monkeypatch):
    """
    即使 session.language=fr-FR,只要規則層有命中(DB rule.keywords 有 hit),
    confidence=rule_hit 不該被降級為 uncovered_locale。
    """
    rules = [
        {
            "id": None,
            "canonical_id": "gross_hematuria",
            "name": "blood",
            "display_title_by_lang": {
                "zh-TW": "肉眼血尿",
                "en-US": "Gross Hematuria",
            },
            "severity": "high",
            "category": "urinary",
            "keywords": ["blood"],
            "regex_pattern": None,
            "description": "",
            "suggested_actions": [],
        }
    ]
    detector = _make_detector(rules, monkeypatch)

    async def _empty_semantic(self, text, ctx, language=None):
        return []

    monkeypatch.setattr(RedFlagDetector, "_semantic_detect", _empty_semantic)

    merged = _run(detector.detect(
        "I see blood in urine", {"session_id": "s1", "language": "fr-FR"}
    ))
    assert len(merged) == 1
    assert merged[0]["confidence"] == "rule_hit"


# ── AlertService.create 寫 audit log on uncovered_locale ──


class _FakeDB:
    """極簡 AsyncSession：追蹤 add + flush;不支援 execute。"""

    def __init__(self) -> None:
        self.added: list[Any] = []
        self.flushes = 0

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        self.flushes += 1

    async def execute(self, _stmt):
        # session doctor_id 查詢,回空以跳過推播邏輯
        result = MagicMock()
        result.scalar_one_or_none = MagicMock(return_value=None)
        return result


def test_alert_service_create_persists_confidence_and_canonical_id(monkeypatch):
    """AlertService.create 須把 confidence + canonical_id 寫進 model(rule_hit 路徑)。"""
    db = _FakeDB()
    data = {
        "session_id": uuid.uuid4(),
        "conversation_id": uuid.uuid4(),
        "alert_type": AlertType.RULE_BASED,
        "severity": AlertSeverity.HIGH,
        "title": "肉眼血尿",
        "description": "",
        "trigger_reason": "kw:血尿",
        "canonical_id": "gross_hematuria",
        "confidence": "rule_hit",
        "language": "zh-TW",
    }
    alert = _run(AlertService.create(db, data))
    # find RedFlagAlert in db.added
    from app.models.red_flag_alert import RedFlagAlert
    added_alerts = [o for o in db.added if isinstance(o, RedFlagAlert)]
    assert len(added_alerts) == 1
    saved = added_alerts[0]
    assert saved.canonical_id == "gross_hematuria"
    assert saved.confidence == RedFlagConfidence.RULE_HIT
    assert saved.language == "zh-TW"


def test_alert_service_create_writes_audit_log_on_uncovered_locale(monkeypatch):
    """confidence=uncovered_locale 時,必須寫 audit log(action=CREATE, resource_type=red_flag_alert)。"""
    db = _FakeDB()

    # 拒絕真寫 audit log 的 DB 依賴,改監聽 AuditLogService.log
    audit_calls: list[dict[str, Any]] = []

    async def _fake_audit_log(
        db, user_id, action, resource_type, resource_id=None, details=None,
        ip_address=None, user_agent=None,
    ):
        audit_calls.append(
            {
                "action": action,
                "resource_type": resource_type,
                "resource_id": resource_id,
                "details": details,
            }
        )
        return MagicMock()

    from app.services import audit_log_service as als_module
    monkeypatch.setattr(als_module.AuditLogService, "log", _fake_audit_log)

    data = {
        "session_id": uuid.uuid4(),
        "conversation_id": uuid.uuid4(),
        "alert_type": AlertType.SEMANTIC,
        "severity": AlertSeverity.HIGH,
        "title": "Gross Hematuria",
        "description": "",
        "trigger_reason": "semantic",
        "canonical_id": "gross_hematuria",
        "confidence": "uncovered_locale",
        "language": "fr-FR",
    }
    _run(AlertService.create(db, data))

    assert len(audit_calls) == 1, "uncovered_locale 必須觸發一筆 audit log"
    assert audit_calls[0]["resource_type"] == "red_flag_alert"
    assert audit_calls[0]["details"]["reason"] == "uncovered_locale_escalation"
    assert audit_calls[0]["details"]["canonical_id"] == "gross_hematuria"
    assert audit_calls[0]["details"]["language"] == "fr-FR"


def test_alert_service_create_no_audit_log_on_rule_hit(monkeypatch):
    """rule_hit 時不應寫 uncovered_locale audit log(避免 audit 噪音)。"""
    db = _FakeDB()

    audit_calls: list[dict[str, Any]] = []

    async def _fake_audit_log(
        db, user_id, action, resource_type, resource_id=None, details=None,
        ip_address=None, user_agent=None,
    ):
        audit_calls.append({"resource_type": resource_type})
        return MagicMock()

    from app.services import audit_log_service as als_module
    monkeypatch.setattr(als_module.AuditLogService, "log", _fake_audit_log)

    data = {
        "session_id": uuid.uuid4(),
        "conversation_id": uuid.uuid4(),
        "alert_type": AlertType.RULE_BASED,
        "severity": AlertSeverity.HIGH,
        "title": "肉眼血尿",
        "description": "",
        "trigger_reason": "kw",
        "canonical_id": "gross_hematuria",
        "confidence": "rule_hit",
        "language": "zh-TW",
    }
    _run(AlertService.create(db, data))
    assert audit_calls == []


# ── Prometheus metric 寫入守護(TODO-O4) ────────────────


def test_detector_writes_rule_layer_coverage_metric(monkeypatch):
    """detect() 每筆 merged alert 都會呼叫 record_red_flag_rule_layer_coverage 一次。"""
    detector = _make_detector([], monkeypatch)

    calls: list[tuple[str | None, str]] = []

    def _fake_metric(language=None, confidence="rule_hit"):
        calls.append((language, confidence))

    monkeypatch.setattr(
        rfd_module, "record_red_flag_rule_layer_coverage", _fake_metric
    )

    semantic_alert = {
        "canonical_id": "gross_hematuria",
        "severity": "high",
        "title": "Gross Hematuria",
        "description": "",
        "trigger_reason": "x",
        "alert_type": "semantic",
        "confidence": "semantic_only",
        "suggested_actions": [],
        "matched_rule_id": None,
    }

    async def _fake_semantic(self, text, ctx, language=None):
        return [semantic_alert.copy()]

    monkeypatch.setattr(RedFlagDetector, "_semantic_detect", _fake_semantic)

    merged = _run(detector.detect(
        "patient reports blood in urine",
        {"session_id": "s1", "language": "en-US"},
    ))
    assert len(merged) == 1
    assert calls == [("en-US", "semantic_only")]
