"""問診場次相關 Pydantic Schema"""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import SessionStatus
from app.schemas.common import CursorPagination
from app.schemas.conversation import ConversationResponse


class SessionIntakeAllergyItem(BaseModel):
    """本次問診 intake - 過敏史"""

    allergen: str = Field(..., min_length=1, max_length=100)
    reaction: Optional[str] = Field(None, max_length=200)
    severity: Optional[str] = Field(None, max_length=50)
    had_hospitalization: bool = False


class SessionIntakeMedicationItem(BaseModel):
    """本次問診 intake - 目前用藥"""

    name: str = Field(..., min_length=1, max_length=100)
    frequency: Optional[str] = Field(None, max_length=100)


class SessionIntakeMedicalHistoryItem(BaseModel):
    """本次問診 intake - 過去病史"""

    condition: str = Field(..., min_length=1, max_length=100)
    years_ago: Optional[str] = Field(None, max_length=50)
    still_has: bool = True


class SessionIntakeFamilyHistoryItem(BaseModel):
    """本次問診 intake - 家族病史"""

    relation: str = Field(..., min_length=1, max_length=50)
    condition: str = Field(..., min_length=1, max_length=100)


class SessionIntake(BaseModel):
    """本次問診 intake snapshot"""

    no_known_allergies: bool = False
    allergies: list[SessionIntakeAllergyItem] = Field(default_factory=list)
    no_current_medications: bool = False
    current_medications: list[SessionIntakeMedicationItem] = Field(default_factory=list)
    no_past_medical_history: bool = False
    medical_history: list[SessionIntakeMedicalHistoryItem] = Field(default_factory=list)
    family_history: list[SessionIntakeFamilyHistoryItem] = Field(default_factory=list)


class SessionCreate(BaseModel):
    """建立場次"""

    patient_id: UUID
    chief_complaint_id: UUID
    chief_complaint_text: Optional[str] = Field(None, max_length=200)
    language: str = Field("zh-TW", max_length=10)
    intake: Optional[SessionIntake] = None


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
    intake: Optional[SessionIntake] = Field(default=None, validation_alias="intake_data")
    intake_completed_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


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
