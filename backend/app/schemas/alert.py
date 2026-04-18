"""紅旗警示相關 Pydantic Schema"""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import AlertSeverity, AlertType, RedFlagConfidence
from app.schemas.common import CursorPagination


# ── RedFlagAlert ───────────────────────────────────────
class RedFlagAlertResponse(BaseModel):
    """
    紅旗警示回應。

    TODO-E6 / TODO-M8：
    - canonical_id：跨語言穩定 id;前端用來 dedup / 對照規則目錄。
    - confidence：rule_hit / semantic_only / uncovered_locale;前端非
      rule_hit 應顯示 banner 提醒醫師此警示由 LLM 語意層或 fail-safe 觸發。
    - title：依 Accept-Language / session.language 渲染的本地化顯示標題。
    """
    id: UUID
    session_id: UUID
    conversation_id: UUID
    alert_type: AlertType
    severity: AlertSeverity
    title: str
    description: Optional[str] = None
    trigger_reason: str
    trigger_keywords: Optional[list[str]] = None
    matched_rule_id: Optional[UUID] = None
    canonical_id: Optional[str] = None
    confidence: RedFlagConfidence = RedFlagConfidence.RULE_HIT
    llm_analysis: Optional[dict[str, Any]] = None
    suggested_actions: Optional[list[str]] = None
    acknowledged_by: Optional[UUID] = None
    acknowledged_at: Optional[datetime] = None
    acknowledge_notes: Optional[str] = None
    language: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AlertAcknowledgeRequest(BaseModel):
    """確認警示請求"""
    acknowledge_notes: Optional[str] = Field(None, description="確認備註")
    action_taken: Optional[str] = Field(None, description="已採取的行動")


class AlertListResponse(BaseModel):
    """警示列表回應"""
    data: list[RedFlagAlertResponse]
    pagination: CursorPagination


# ── RedFlagRule ────────────────────────────────────────
class RedFlagRuleCreate(BaseModel):
    """新增紅旗規則"""
    name: str = Field(..., max_length=200)
    description: Optional[str] = None
    category: str = Field(..., max_length=100)
    keywords: list[str]
    regex_pattern: Optional[str] = None
    severity: AlertSeverity
    suspected_diagnosis: Optional[str] = Field(None, max_length=200)
    suggested_action: Optional[str] = None
    is_active: bool = True


class RedFlagRuleUpdate(BaseModel):
    """更新紅旗規則（部分更新）"""
    name: Optional[str] = Field(None, max_length=200)
    description: Optional[str] = None
    category: Optional[str] = Field(None, max_length=100)
    keywords: Optional[list[str]] = None
    regex_pattern: Optional[str] = None
    severity: Optional[AlertSeverity] = None
    suspected_diagnosis: Optional[str] = Field(None, max_length=200)
    suggested_action: Optional[str] = None
    is_active: Optional[bool] = None


class RedFlagRuleResponse(BaseModel):
    """紅旗規則回應"""
    id: UUID
    name: str
    description: Optional[str] = None
    category: str
    keywords: list[str]
    regex_pattern: Optional[str] = None
    severity: AlertSeverity
    suspected_diagnosis: Optional[str] = None
    suggested_action: Optional[str] = None
    is_active: bool
    created_by: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RedFlagRuleListResponse(BaseModel):
    """紅旗規則列表回應"""
    data: list[RedFlagRuleResponse]
    pagination: CursorPagination


class AcknowledgeAlertResponse(BaseModel):
    """確認警示回應"""
    id: UUID
    acknowledged_by: UUID
    acknowledged_at: datetime
    acknowledge_notes: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


# 別名（供 router 匯入相容）
AcknowledgeAlertRequest = AlertAcknowledgeRequest
AlertDetail = RedFlagAlertResponse
RedFlagRuleDetail = RedFlagRuleResponse
