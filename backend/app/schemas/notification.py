"""通知相關 Pydantic Schema"""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import DevicePlatform, NotificationType
from app.schemas.common import CursorPagination


class NotificationResponse(BaseModel):
    """通知回應"""
    id: UUID
    user_id: UUID
    type: NotificationType
    title: str
    body: Optional[str] = None
    data: Optional[dict[str, Any]] = None
    is_read: bool
    read_at: Optional[datetime] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class NotificationListResponse(BaseModel):
    """通知列表回應"""
    data: list[NotificationResponse]
    pagination: CursorPagination
    unread_count: int = 0


class UnreadCountResponse(BaseModel):
    """未讀通知計數

    欄位名為 ``count``，與前端 ``data.count`` 讀取一致。
    """
    count: int = 0


class MarkReadResponse(BaseModel):
    """標記已讀回應"""
    id: UUID
    is_read: bool = True
    read_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MarkAllReadResponse(BaseModel):
    """全部標記已讀回應"""
    updated_count: int = 0
    message: str = "已全部標記為已讀"


class MessageResponse(BaseModel):
    """通用訊息回應"""
    message: str


class NotificationPreferenceResponse(BaseModel):
    """通知偏好回應（GDPR opt-out）"""
    user_id: UUID
    red_flag_enabled: bool
    session_complete_enabled: bool
    report_ready_enabled: bool
    system_enabled: bool
    email_enabled: bool
    push_enabled: bool

    model_config = ConfigDict(from_attributes=True)


class NotificationPreferenceUpdate(BaseModel):
    """更新通知偏好（僅更新提供的欄位）

    注意：red_flag 為病安關鍵，服務層會忽略關閉 red_flag 的請求並維持恆為開。
    """
    red_flag_enabled: Optional[bool] = None
    session_complete_enabled: Optional[bool] = None
    report_ready_enabled: Optional[bool] = None
    system_enabled: Optional[bool] = None
    email_enabled: Optional[bool] = None
    push_enabled: Optional[bool] = None


class FCMTokenCreate(BaseModel):
    """註冊 FCM 推播 Token"""
    device_token: str = Field(..., max_length=500)
    platform: DevicePlatform
    device_name: Optional[str] = Field(None, max_length=200)


class FCMTokenResponse(BaseModel):
    """FCM Token 回應"""
    id: UUID
    device_token: str
    platform: DevicePlatform
    device_name: Optional[str] = None
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
