"""問診場次相關 Pydantic Schema"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import SessionStatus
from app.schemas.common import CursorPagination
from app.schemas.conversation import ConversationResponse


class SessionCreate(BaseModel):
    """建立場次"""
    patient_id: UUID
    chief_complaint_id: UUID
    chief_complaint_text: Optional[str] = Field(None, max_length=200)
    language: str = Field("zh-TW", max_length=10)


class SessionUpdateStatus(BaseModel):
    """更新場次狀態"""
    status: SessionStatus
    reason: Optional[str] = None


class SessionResponse(BaseModel):
    """場次回應"""
    id: UUID
    patient_id: UUID
    doctor_id: Optional[UUID] = None
    chief_complaint_id: UUID
    chief_complaint_text: Optional[str] = None
    status: SessionStatus
    red_flag: bool
    red_flag_reason: Optional[str] = None
    language: str
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SessionDetailResponse(SessionResponse):
    """場次詳細回應（含對話紀錄）"""
    conversations: list[ConversationResponse] = []


class SessionListResponse(BaseModel):
    """場次列表回應"""
    data: list[SessionResponse]
    pagination: CursorPagination


class SessionAssignRequest(BaseModel):
    """指派醫師"""
    doctor_id: UUID


class SessionStatusResponse(BaseModel):
    """狀態更新回應"""
    id: UUID
    status: SessionStatus
    previous_status: Optional[SessionStatus] = None
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ConversationListResponse(BaseModel):
    """對話紀錄列表回應"""
    data: list[ConversationResponse]
    pagination: CursorPagination


# 別名（供 router 匯入相容）
SessionDetail = SessionDetailResponse
SessionStatusUpdate = SessionUpdateStatus
