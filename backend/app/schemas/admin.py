"""管理後台相關 Pydantic Schema"""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.enums import AuditAction, UserRole
from app.schemas.common import CursorPagination


# ── 使用者管理 ─────────────────────────────────────────
class AdminUserCreate(BaseModel):
    """管理員建立使用者"""
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    name: str = Field(..., max_length=100)
    role: UserRole
    phone: Optional[str] = Field(None, max_length=20)
    department: Optional[str] = Field(None, max_length=100)
    license_number: Optional[str] = Field(None, max_length=50)
    is_active: bool = True


class AdminUserUpdate(BaseModel):
    """管理員更新使用者"""
    name: Optional[str] = Field(None, max_length=100)
    role: Optional[UserRole] = None
    phone: Optional[str] = Field(None, max_length=20)
    department: Optional[str] = Field(None, max_length=100)
    license_number: Optional[str] = Field(None, max_length=50)
    is_active: Optional[bool] = None


class AdminUserResponse(BaseModel):
    """管理員查看使用者回應"""
    id: UUID
    email: str
    name: str
    role: UserRole
    phone: Optional[str] = None
    department: Optional[str] = None
    license_number: Optional[str] = None
    is_active: bool
    last_login_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AdminUserListResponse(BaseModel):
    """使用者列表回應"""
    data: list[AdminUserResponse]
    pagination: CursorPagination


# ── 稽核日誌 ───────────────────────────────────────────
class AuditLogResponse(BaseModel):
    """稽核日誌回應"""
    id: int
    user_id: Optional[UUID] = None
    action: AuditAction
    resource_type: str
    resource_id: Optional[str] = None
    details: Optional[dict[str, Any]] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AuditLogListResponse(BaseModel):
    """稽核日誌列表回應"""
    data: list[AuditLogResponse]
    pagination: CursorPagination


class SystemHealthResponse(BaseModel):
    """系統健康狀態回應"""
    status: str = "ok"
    database: str = "ok"
    redis: str = "ok"
    version: str = "1.0.0"
    timestamp: datetime


class ToggleActiveResponse(BaseModel):
    """切換啟用狀態回應"""
    id: UUID
    is_active: bool
    message: str

    model_config = ConfigDict(from_attributes=True)


# 別名（供 router 匯入相容）
CreateUserRequest = AdminUserCreate
UpdateUserRequest = AdminUserUpdate
UserDetail = AdminUserResponse
UserListResponse = AdminUserListResponse
