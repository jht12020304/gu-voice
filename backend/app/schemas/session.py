"""問診場次相關 Pydantic Schema"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.config import settings
from app.models.enums import Gender, SessionStatus
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


class PatientInfoPayload(BaseModel):
    """場次建立時隨附的病患資料（供後端 get_or_create）"""

    name: str = Field(..., min_length=1, max_length=100)
    gender: Gender
    date_of_birth: date = Field(..., alias="dateOfBirth")
    phone: Optional[str] = Field(None, max_length=20)

    model_config = ConfigDict(populate_by_name=True)


class SessionCreate(BaseModel):
    """建立場次"""

    patient_id: Optional[UUID] = Field(None, alias="patientId")
    chief_complaint_id: UUID = Field(..., alias="chiefComplaintId")
    chief_complaint_text: Optional[str] = Field(
        None, max_length=200, alias="chiefComplaintText"
    )
    # Optional：未指定時由 router 依 user.preferred_language → Accept-Language →
    # settings default 推算（app.utils.language.resolve_language）。
    # 若顯式指定，必須落在 settings.SUPPORTED_LANGUAGES，否則 422。
    language: Optional[str] = Field(None, max_length=10)
    intake: Optional[SessionIntake] = None
    patient_info: Optional[PatientInfoPayload] = Field(None, alias="patientInfo")

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("language")
    @classmethod
    def _validate_language(cls, v: Optional[str]) -> Optional[str]:
        """白名單驗證 + BCP-47 大小寫正規化（zh-tw → zh-TW）。"""
        if v is None or v == "":
            return None
        # 正規化（複用 utils.language._normalize 的邏輯，但避免循環 import）
        parts = v.strip().split("-")
        normalized = parts[0].lower() if len(parts) == 1 else f"{parts[0].lower()}-{parts[1].upper()}"
        if normalized not in settings.SUPPORTED_LANGUAGES:
            raise ValueError(
                f"language must be one of: {', '.join(settings.SUPPORTED_LANGUAGES)}"
            )
        return normalized


class SessionUpdateStatus(BaseModel):
    """更新場次狀態"""
    status: SessionStatus
    reason: Optional[str] = None


class SessionResponse(BaseModel):
    """場次回應"""
    id: UUID
    patient_id: UUID
    patient_name: Optional[str] = None
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

    @model_validator(mode="before")
    @classmethod
    def _populate_patient_name(cls, data: Any) -> Any:
        # 當從 ORM 物件載入時，若 patient 關聯已被 eager-load，
        # 則把 patient.name 複製到 patient_name 屬性上，
        # 讓 from_attributes=True 的 pydantic 能讀到。
        if data is None or isinstance(data, dict):
            return data
        existing = getattr(data, "patient_name", None)
        if existing:
            return data
        try:
            patient = data.__dict__.get("patient") if hasattr(data, "__dict__") else None
        except Exception:
            patient = None
        if patient is None:
            return data
        name = getattr(patient, "name", None)
        if name:
            try:
                data.patient_name = name
            except Exception:
                pass
        return data


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
