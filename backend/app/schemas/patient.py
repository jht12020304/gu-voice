"""病患相關 Pydantic Schema"""

from datetime import date, datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import Gender
from app.schemas.common import CursorPagination


class PatientCreate(BaseModel):
    """新增病患"""
    user_id: UUID
    medical_record_number: str = Field(..., max_length=50)
    name: str = Field(..., min_length=1, max_length=100)
    gender: Gender
    date_of_birth: date
    phone: Optional[str] = Field(None, max_length=20)
    emergency_contact: Optional[dict[str, Any]] = None
    medical_history: Optional[list[dict[str, Any]]] = None
    allergies: Optional[list[dict[str, Any]]] = None
    current_medications: Optional[list[dict[str, Any]]] = None


class PatientUpdate(BaseModel):
    """更新病患（部分更新）"""
    name: Optional[str] = Field(None, max_length=100)
    gender: Optional[Gender] = None
    date_of_birth: Optional[date] = None
    phone: Optional[str] = Field(None, max_length=20)
    emergency_contact: Optional[dict[str, Any]] = None
    medical_history: Optional[list[dict[str, Any]]] = None
    allergies: Optional[list[dict[str, Any]]] = None
    current_medications: Optional[list[dict[str, Any]]] = None


class PatientResponse(BaseModel):
    """病患回應"""
    id: UUID
    user_id: UUID
    medical_record_number: str
    name: str
    gender: Gender
    date_of_birth: date
    phone: Optional[str] = None
    emergency_contact: Optional[dict[str, Any]] = None
    medical_history: Optional[list[dict[str, Any]]] = None
    allergies: Optional[list[dict[str, Any]]] = None
    current_medications: Optional[list[dict[str, Any]]] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PatientListResponse(BaseModel):
    """病患列表回應"""
    data: list[PatientResponse]
    pagination: CursorPagination


# 別名（供 router 匯入相容）
PatientDetail = PatientResponse
