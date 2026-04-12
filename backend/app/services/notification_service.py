"""
通知服務
- 通知 CRUD / 已讀標記
- FCM 裝置管理
- 推播發送
- 未讀計數（Redis 快取）
"""

import json
import logging
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException
from app.models.enums import DevicePlatform, NotificationType
from app.models.fcm_device import FCMDevice
from app.models.notification import Notification
from app.utils.datetime_utils import utc_now

logger = logging.getLogger(__name__)

# 未讀計數快取 TTL
UNREAD_CACHE_TTL = 300


class NotificationService:
    """通知業務邏輯"""

    @staticmethod
    async def create(
        db: AsyncSession,
        user_id: UUID,
        type: NotificationType,
        title: str,
        body: Optional[str] = None,
        data: Optional[dict[str, Any]] = None,
    ) -> Notification:
        """
        建立通知

        Args:
            user_id: 通知目標使用者
            type: 通知類型
            title: 通知標題
            body: 通知內容
            data: 附加資料（Deep Link 等）
        """
        notification = Notification(
            user_id=user_id,
            type=type,
            title=title,
            body=body,
            data=data,
            is_read=False,
            created_at=utc_now(),
        )
        db.add(notification)
        await db.flush()

        # 清除未讀計數快取
        await _invalidate_unread_cache(user_id)

        return notification

    @staticmethod
    async def get_list(
        db: AsyncSession,
        user_id: UUID,
        cursor: Optional[str] = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """
        取得使用者通知列表（Cursor-based 分頁）
        """
        limit = min(limit, 100)

        query = (
            select(Notification)
            .where(Notification.user_id == user_id)
            .order_by(Notification.created_at.desc(), Notification.id.desc())
        )

        if cursor:
            result = await db.execute(
                select(Notification).where(Notification.id == cursor)
            )
            cursor_record = result.scalar_one_or_none()
            if cursor_record:
                query = query.where(
                    (Notification.created_at < cursor_record.created_at)
                    | (
                        (Notification.created_at == cursor_record.created_at)
                        & (Notification.id < cursor_record.id)
                    )
                )

        result = await db.execute(query.limit(limit + 1))
        notifications = result.scalars().all()

        has_more = len(notifications) > limit
        if has_more:
            notifications = notifications[:limit]

        count_result = await db.execute(
            select(func.count())
            .select_from(Notification)
            .where(Notification.user_id == user_id)
        )
        total_count = count_result.scalar() or 0

        return {
            "data": notifications,
            "pagination": {
                "next_cursor": str(notifications[-1].id) if has_more and notifications else None,
                "has_more": has_more,
                "limit": limit,
                "total_count": total_count,
            },
        }

    @staticmethod
    async def mark_read(
        db: AsyncSession,
        notification_id: UUID,
        user_id: UUID,
    ) -> Notification:
        """
        標記通知為已讀

        Raises:
            NotFoundException: 通知不存在
        """
        result = await db.execute(
            select(Notification)
            .where(Notification.id == notification_id)
            .where(Notification.user_id == user_id)
        )
        notification = result.scalar_one_or_none()
        if notification is None:
            raise NotFoundException("通知不存在")

        if not notification.is_read:
            notification.is_read = True
            notification.read_at = utc_now()
            await db.flush()

            # 清除未讀計數快取
            await _invalidate_unread_cache(user_id)

        return notification

    @staticmethod
    async def mark_all_read(db: AsyncSession, user_id: UUID) -> int:
        """
        標記所有通知為已讀

        Returns:
            更新的通知數量
        """
        now = utc_now()
        result = await db.execute(
            update(Notification)
            .where(Notification.user_id == user_id)
            .where(Notification.is_read.is_(False))
            .values(is_read=True, read_at=now)
        )
        await db.flush()

        # 清除未讀計數快取
        await _invalidate_unread_cache(user_id)

        return result.rowcount

    @staticmethod
    async def get_unread_count(
        db: AsyncSession,
        redis,
        user_id: UUID,
    ) -> int:
        """
        取得未讀通知數量（優先從 Redis 快取讀取）

        Args:
            db: 資料庫 session
            redis: Redis 連線實例
            user_id: 使用者 ID
        """
        cache_key = f"gu:notifications:unread:{user_id}"

        # 嘗試讀取快取
        try:
            cached = await redis.get(cache_key)
            if cached is not None:
                return int(cached)
        except Exception:
            pass

        # 查詢資料庫
        result = await db.execute(
            select(func.count())
            .select_from(Notification)
            .where(Notification.user_id == user_id)
            .where(Notification.is_read.is_(False))
        )
        count = result.scalar() or 0

        # 寫入快取
        try:
            await redis.setex(cache_key, UNREAD_CACHE_TTL, str(count))
        except Exception:
            pass

        return count

    # ── FCM 裝置管理 ──────────────────────────────────────

    @staticmethod
    async def register_fcm_token(
        db: AsyncSession,
        user_id: UUID,
        token: str,
        platform: DevicePlatform,
        device_name: Optional[str] = None,
    ) -> FCMDevice:
        """
        註冊 FCM 推播 token

        若 token 已存在則更新，否則新建
        """
        now = utc_now()

        # 檢查 token 是否已存在
        result = await db.execute(
            select(FCMDevice).where(FCMDevice.device_token == token)
        )
        device = result.scalar_one_or_none()

        if device:
            # 更新現有裝置
            device.user_id = user_id
            device.platform = platform
            device.device_name = device_name or device.device_name
            device.is_active = True
            device.updated_at = now
        else:
            # 建立新裝置
            device = FCMDevice(
                user_id=user_id,
                device_token=token,
                platform=platform,
                device_name=device_name,
                is_active=True,
                created_at=now,
                updated_at=now,
            )
            db.add(device)

        await db.flush()
        return device

    @staticmethod
    async def remove_fcm_token(db: AsyncSession, token: str) -> None:
        """
        移除 FCM token（標記為非活躍）
        """
        result = await db.execute(
            select(FCMDevice).where(FCMDevice.device_token == token)
        )
        device = result.scalar_one_or_none()
        if device:
            device.is_active = False
            device.updated_at = utc_now()
            await db.flush()

    @staticmethod
    async def send_push_notification(
        user_id: UUID,
        title: str,
        body: str,
        data: Optional[dict[str, Any]] = None,
    ) -> None:
        """
        發送推播通知（透過 Celery 任務）

        Args:
            user_id: 目標使用者
            title: 通知標題
            body: 通知內容
            data: 附加資料
        """
        from app.tasks.notification_retry import send_push_notification_task

        send_push_notification_task.delay(
            user_id=str(user_id),
            title=title,
            body=body,
            data=data or {},
        )


# ── 輔助函式 ─────────────────────────────────────────────
async def _invalidate_unread_cache(user_id: UUID) -> None:
    """清除未讀計數快取"""
    try:
        from app.cache.redis_client import get_redis

        redis = await get_redis()
        cache_key = f"gu:notifications:unread:{user_id}"
        await redis.delete(cache_key)
    except Exception:
        pass
