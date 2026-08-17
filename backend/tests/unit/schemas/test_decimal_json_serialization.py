"""
跨端契約回歸測試：response schema 裡的 Decimal 欄位，JSON 輸出必須是 number（float），
不能是 pydantic v2 預設的字串。

背景：pydantic v2 對 `Decimal` 的預設 JSON 序列化是字串（0.80 → "0.80"）。
Flutter 端 flutter_app/lib/data/models/soap_report.dart 用
`(json['aiConfidenceScore'] as num?)` / `(json['sttConfidence'] as num?)` 硬轉型，
遇到 String 直接 TypeError，整份 model 解析失敗且被上層 catch 吞掉 →
reports 列表整批空白、session detail 誤判「尚未生成報告」、SOAP 頁顯示「尚未生成」。
（React 端靠 JS 隱式轉型僥倖能動，所以這個破口長期沒被前端擋下來。）

修法在 app/schemas/common.py 的 `JsonFloatDecimal`。這支測試鎖住兩件事：
1. JSON 輸出（model_dump(mode="json") / model_dump_json）是 float
2. Python 端（model_dump()）仍是 Decimal——DB 寫入的 numeric 路徑不受影響
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from app.models.enums import (
    ConversationRole,
    ReportRevisionReason,
    ReportStatus,
    ReviewStatus,
)
from app.schemas.conversation import ConversationResponse
from app.schemas.report import SOAPReportResponse, SOAPReportRevisionResponse


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _report(score: Decimal | None) -> SOAPReportResponse:
    return SOAPReportResponse(
        id=uuid4(),
        session_id=uuid4(),
        status=ReportStatus.GENERATED,
        review_status=ReviewStatus.PENDING,
        summary="摘要",
        ai_confidence_score=score,
        created_at=_now(),
        updated_at=_now(),
    )


def _revision(score: Decimal | None) -> SOAPReportRevisionResponse:
    return SOAPReportRevisionResponse(
        id=uuid4(),
        report_id=uuid4(),
        revision_no=1,
        reason=ReportRevisionReason.INITIAL,
        language="zh-TW",
        ai_confidence_score=score,
        created_at=_now(),
    )


def _conversation(duration: Decimal | None, confidence: Decimal | None) -> ConversationResponse:
    return ConversationResponse(
        id=uuid4(),
        session_id=uuid4(),
        sequence_number=1,
        role=ConversationRole.PATIENT,
        content_text="我最近小便有血",
        audio_duration_seconds=duration,
        stt_confidence=confidence,
        red_flag_detected=False,
        created_at=_now(),
    )


# ── SOAP 報告 ──────────────────────────────────────────
def test_report_ai_confidence_score_is_float_in_json():
    dumped = _report(Decimal("0.80")).model_dump(mode="json")
    assert isinstance(dumped["ai_confidence_score"], float), (
        f"ai_confidence_score 應為 float，實際是 {type(dumped['ai_confidence_score'])}："
        f"{dumped['ai_confidence_score']!r}"
    )
    assert not isinstance(dumped["ai_confidence_score"], str)
    assert dumped["ai_confidence_score"] == pytest.approx(0.80)


def test_report_ai_confidence_score_is_number_in_json_string():
    """真正送到前端的那串 JSON：不能有引號包住分數。"""
    raw = _report(Decimal("0.80")).model_dump_json()
    assert '"ai_confidence_score":"0.80"' not in raw
    assert isinstance(json.loads(raw)["ai_confidence_score"], float)


def test_report_revision_ai_confidence_score_is_float_in_json():
    dumped = _revision(Decimal("0.93")).model_dump(mode="json")
    assert isinstance(dumped["ai_confidence_score"], float)
    assert dumped["ai_confidence_score"] == pytest.approx(0.93)


def test_report_ai_confidence_score_none_stays_none():
    assert _report(None).model_dump(mode="json")["ai_confidence_score"] is None
    assert _revision(None).model_dump(mode="json")["ai_confidence_score"] is None


# ── 對話紀錄 ───────────────────────────────────────────
def test_conversation_decimal_fields_are_float_in_json():
    dumped = _conversation(Decimal("12.50"), Decimal("0.95")).model_dump(mode="json")
    for field in ("audio_duration_seconds", "stt_confidence"):
        assert isinstance(dumped[field], float), (
            f"{field} 應為 float，實際是 {type(dumped[field])}：{dumped[field]!r}"
        )
        assert not isinstance(dumped[field], str)
    assert dumped["audio_duration_seconds"] == pytest.approx(12.5)
    assert dumped["stt_confidence"] == pytest.approx(0.95)


def test_conversation_decimal_fields_none_stays_none():
    dumped = _conversation(None, None).model_dump(mode="json")
    assert dumped["audio_duration_seconds"] is None
    assert dumped["stt_confidence"] is None


# ── Python 端不變（DB 寫入路徑） ─────────────────────────
def test_python_mode_keeps_decimal():
    """只有 JSON 輸出改變；Python 端仍是 Decimal，入庫 numeric 精度不受影響。"""
    assert _report(Decimal("0.80")).model_dump()["ai_confidence_score"] == Decimal("0.80")
    assert isinstance(_report(Decimal("0.80")).model_dump()["ai_confidence_score"], Decimal)
    conv = _conversation(Decimal("12.50"), Decimal("0.95")).model_dump()
    assert isinstance(conv["audio_duration_seconds"], Decimal)
    assert isinstance(conv["stt_confidence"], Decimal)


# ── OpenAPI 契約 ───────────────────────────────────────
@pytest.mark.parametrize(
    "model,field",
    [
        (SOAPReportResponse, "ai_confidence_score"),
        (SOAPReportRevisionResponse, "ai_confidence_score"),
        (ConversationResponse, "audio_duration_seconds"),
        (ConversationResponse, "stt_confidence"),
    ],
)
def test_serialization_schema_declares_number(model, field):
    """OpenAPI（serialization 模式）要宣告 number，客戶端 codegen 才不會產出 String。"""
    prop = model.model_json_schema(mode="serialization")["properties"][field]
    types = {sub.get("type") for sub in prop.get("anyOf", [prop])}
    assert "number" in types, f"{model.__name__}.{field} 的序列化 schema 不是 number：{prop}"
    assert "string" not in types, f"{model.__name__}.{field} 的序列化 schema 仍宣告 string：{prop}"
