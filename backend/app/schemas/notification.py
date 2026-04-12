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
    """未讀通知計數"""
    unread_count: int = 0


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
