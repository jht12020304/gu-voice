"""
通知管理路由 — 通知列表、已讀標記、FCM Token 管理
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

import redis.asyncio as aioredis

from app.core.authz import get_clinician_scope_id
from app.core.dependencies import get_current_user, get_db, get_redis, require_role
from app.schemas.notification import (
    DeviceRecoveryRequest,
    DeviceUnbindRequest,
    FCMTokenCreate,
    FCMTokenResponse,
    MarkAllReadResponse,
    MarkReadResponse,
    NotificationListResponse,
    NotificationPreferenceResponse,
    NotificationPreferenceUpdate,
    UnreadCountResponse,
)
from app.services.notification_service import NotificationService

router = APIRouter(prefix="/api/v1/notifications", tags=["通知"])

notification_service = NotificationService()


@router.get(
    "",
    response_model=NotificationListResponse,
    status_code=status.HTTP_200_OK,
    summary="取得通知列表",
)
async def list_notifications(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
    cursor: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    is_read: bool | None = None,
    type_filter: str | None = Query(None, alias="type"),
) -> NotificationListResponse:
    """取得目前使用者的通知列表，支援依已讀狀態與通知類型篩選。"""
    return await notification_service.list_notifications(
        db,
        user_id=current_user.id,
        cursor=cursor,
        limit=limit,
        is_read=is_read,
        notification_type=type_filter,
    )


@router.put(
    "/read-all",
    response_model=MarkAllReadResponse,
    status_code=status.HTTP_200_OK,
    summary="全部標記為已讀",
)
async def mark_all_read(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> MarkAllReadResponse:
    """將目前使用者的所有未讀通知標記為已讀。"""
    return await notification_service.mark_all_read(
        db,
        user_id=current_user.id,
    )


@router.get(
    "/unread-count",
    response_model=UnreadCountResponse,
    status_code=status.HTTP_200_OK,
    summary="取得未讀通知數量",
)
async def get_unread_count(
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
    current_user=Depends(get_current_user),
) -> UnreadCountResponse:
    """取得目前使用者的未讀通知數量。"""
    count = await notification_service.get_unread_count(
        db,
        redis,
        user_id=current_user.id,
    )
    return UnreadCountResponse(count=count)


@router.get(
    "/preferences",
    response_model=NotificationPreferenceResponse,
    status_code=status.HTTP_200_OK,
    summary="取得通知偏好",
)
async def get_notification_preferences(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> NotificationPreferenceResponse:
    """取得目前使用者的通知偏好（GDPR opt-out）；若不存在則建立預設全開設定。"""
    return await notification_service.get_or_create_preferences(
        db,
        user_id=current_user.id,
    )


@router.put(
    "/preferences",
    response_model=NotificationPreferenceResponse,
    status_code=status.HTTP_200_OK,
    summary="更新通知偏好",
)
async def update_notification_preferences(
    payload: NotificationPreferenceUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> NotificationPreferenceResponse:
    """更新目前使用者的通知偏好。red_flag 為病安關鍵，無法被關閉。"""
    return await notification_service.update_preferences(
        db,
        user_id=current_user.id,
        update=payload,
    )


@router.post(
    "/fcm-token",
    response_model=FCMTokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="註冊 FCM 裝置 Token",
)
async def register_fcm_token(
    payload: FCMTokenCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> FCMTokenResponse:
    """註冊或更新 Firebase Cloud Messaging (FCM) 裝置 Token，用於推播通知。"""
    device = await notification_service.register_fcm_token(
        db,
        user_id=current_user.id,
        token=payload.device_token,
        apns_token=payload.apns_token,
        platform=payload.platform,
        device_name=payload.device_name,
        binding_id=payload.binding_id,
    )
    if device is None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Device binding was removed")
    return device


@router.delete(
    "/fcm-token/{token}",
    status_code=status.HTTP_200_OK,
    summary="移除 FCM 裝置 Token",
)
async def remove_fcm_token(
    token: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> None:
    """移除指定的 FCM 裝置 Token（例如使用者登出或卸載 App 時）。"""
    await notification_service.remove_fcm_token(
        db,
        user_id=current_user.id,
        token=token,
    )


@router.post(
    "/devices/unbind",
    status_code=status.HTTP_200_OK,
    summary="移除此帳號在指定 Apple 裝置上的推播註冊",
)
async def unbind_device(
    payload: DeviceUnbindRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> None:
    if payload.recovery_id is not None:
        if not await notification_service.device_recovery_confirmed(db, current_user.id, payload.recovery_id):
            raise HTTPException(status.HTTP_409_CONFLICT, detail="Device recovery is pending")
        return
    await notification_service.unbind_device(
        db, user_id=current_user.id, tokens=payload.device_tokens, apns_token=payload.apns_token,
        binding_id=payload.binding_id,
    )


@router.post("/devices/recover", status_code=status.HTTP_200_OK, summary="解除已核對的 Apple 裝置綁定")
async def recover_device(
    payload: DeviceRecoveryRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_role("admin")),
) -> None:
    if get_clinician_scope_id(current_user) is not None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="System administrator required")
    if not await notification_service.recover_device(
        db, current_user.id, payload.user_id, payload.registration_id, payload.recovery_id
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Device registration not found")


@router.put(
    "/{notification_id}/read",
    response_model=MarkReadResponse,
    status_code=status.HTTP_200_OK,
    summary="標記通知為已讀",
)
async def mark_read(
    notification_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> MarkReadResponse:
    """將指定通知標記為已讀。僅可操作自己的通知。"""
    return await notification_service.mark_read(
        db,
        notification_id=notification_id,
        user_id=current_user.id,
    )
