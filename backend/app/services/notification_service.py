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
from app.models.notification_preference import NotificationPreference
from app.schemas.notification import MarkAllReadResponse, NotificationPreferenceUpdate
from app.utils.datetime_utils import utc_now

logger = logging.getLogger(__name__)

# 未讀計數快取 TTL
UNREAD_CACHE_TTL = 300

# 通知類型 → NotificationPreference 上對應的「類型開關」欄位名。
# red_flag 為病安關鍵，刻意不列入；其抑制邏輯一律放行（恆為開）。
_TYPE_FLAG_FIELD: dict[NotificationType, str] = {
    NotificationType.SESSION_COMPLETE: "session_complete_enabled",
    NotificationType.REPORT_READY: "report_ready_enabled",
    NotificationType.SYSTEM: "system_enabled",
}


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
    ) -> Optional[Notification]:
        """
        建立通知

        依使用者通知偏好（NotificationPreference）抑制已關閉的類型；
        red_flag 為病安關鍵，一律建立。若該類型被關閉則略過、回傳 None
        作為明確的 no-op 訊號（不丟例外，維持呼叫端相容）。

        Args:
            user_id: 通知目標使用者
            type: 通知類型
            title: 通知標題
            body: 通知內容
            data: 附加資料（Deep Link 等）

        Returns:
            建立的 Notification；若被偏好設定抑制則回傳 None。
        """
        # 抑制：若該類型被使用者關閉則略過（red_flag 除外，恆送）。
        # 防禦性：查不到偏好設定（無 pref row）時預設照常發送。
        if not await NotificationService._is_type_enabled(db, user_id, type):
            logger.info(
                "通知被偏好設定抑制 user=%s type=%s", user_id, getattr(type, "value", type)
            )
            return None

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

    # ── 問診流程 domain helpers ───────────────────────────
    # WS（conversation_handler）與 Celery（report_queue）共用；標題/內文以
    # 「負責醫師的 preferred_language」解析（doctor-facing，不用場次語言）。

    @staticmethod
    async def notify_session_complete(
        db: AsyncSession,
        *,
        session_id: Any,
        doctor_id: UUID,
        patient_id: Optional[UUID] = None,
    ) -> Optional[Notification]:
        """問診完成 → SESSION_COMPLETE 站內通知給負責醫師。

        受偏好設定 session_complete_enabled 抑制（回 None）。
        呼叫端負責 commit；本函式僅 flush。
        """
        from app.models.patient import Patient
        from app.models.user import User
        from app.utils.i18n_messages import get_message

        doctor_lang = (
            await db.execute(
                select(User.preferred_language).where(User.id == doctor_id)
            )
        ).scalar_one_or_none()
        patient_name: Optional[str] = None
        if patient_id is not None:
            patient_name = (
                await db.execute(select(Patient.name).where(Patient.id == patient_id))
            ).scalar_one_or_none()

        return await NotificationService.create(
            db,
            user_id=doctor_id,
            type=NotificationType.SESSION_COMPLETE,
            title=get_message("notifications.session_complete.title", doctor_lang),
            body=get_message(
                "notifications.session_complete.body",
                doctor_lang,
                patient_name=patient_name or "",
            ),
            data={"session_id": str(session_id)},
        )

    @staticmethod
    async def notify_report_ready(
        db: AsyncSession,
        *,
        session_id: Any,
        report_id: Any,
    ) -> Optional[Notification]:
        """SOAP 報告生成完成 → REPORT_READY 站內通知給負責醫師。

        場次無負責醫師時 no-op 回 None；受偏好 report_ready_enabled 抑制。
        呼叫端負責 commit；本函式僅 flush。
        """
        from app.models.patient import Patient
        from app.models.session import Session
        from app.models.user import User
        from app.utils.i18n_messages import get_message

        row = (
            await db.execute(
                select(Session.doctor_id, Patient.name)
                .join(Patient, Patient.id == Session.patient_id, isouter=True)
                .where(Session.id == UUID(str(session_id)))
            )
        ).first()
        if row is None or row.doctor_id is None:
            return None

        doctor_lang = (
            await db.execute(
                select(User.preferred_language).where(User.id == row.doctor_id)
            )
        ).scalar_one_or_none()

        return await NotificationService.create(
            db,
            user_id=row.doctor_id,
            type=NotificationType.REPORT_READY,
            title=get_message("notifications.report_ready.title", doctor_lang),
            body=get_message(
                "notifications.report_ready.body",
                doctor_lang,
                patient_name=row.name or "",
            ),
            data={"session_id": str(session_id), "report_id": str(report_id)},
        )

    @staticmethod
    async def list_notifications(
        db: AsyncSession,
        user_id: UUID,
        cursor: Optional[str] = None,
        limit: int = 20,
        is_read: Optional[bool] = None,
        notification_type: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        取得使用者通知列表（Cursor-based 分頁）

        Args:
            is_read: 若指定，僅回傳對應已讀狀態的通知
            notification_type: 若指定，僅回傳對應類型的通知（NotificationType value）
        """
        limit = min(limit, 100)

        query = (
            select(Notification)
            .where(Notification.user_id == user_id)
            .order_by(Notification.created_at.desc(), Notification.id.desc())
        )

        # 篩選：已讀狀態
        if is_read is not None:
            query = query.where(Notification.is_read.is_(is_read))

        # 篩選：通知類型
        if notification_type is not None:
            query = query.where(Notification.type == notification_type)

        if cursor:
            # cursor 為 Notification.id（UUID）。先驗證格式，避免將非法字串
            # 直接餵給 asyncpg 觸發 DataError 裸 500；無效 cursor 視為無 cursor。
            try:
                cursor_uuid = UUID(cursor)
            except (ValueError, TypeError):
                cursor_uuid = None
            if cursor_uuid is not None:
                result = await db.execute(
                    select(Notification).where(Notification.id == cursor_uuid)
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

        # total_count 須與 list 套用相同篩選，分頁總數才一致
        count_query = (
            select(func.count())
            .select_from(Notification)
            .where(Notification.user_id == user_id)
        )
        if is_read is not None:
            count_query = count_query.where(Notification.is_read.is_(is_read))
        if notification_type is not None:
            count_query = count_query.where(Notification.type == notification_type)
        count_result = await db.execute(count_query)
        total_count = count_result.scalar() or 0

        # unread_count 不受篩選影響，永遠回傳該使用者的未讀總數
        unread_result = await db.execute(
            select(func.count())
            .select_from(Notification)
            .where(Notification.user_id == user_id)
            .where(Notification.is_read.is_(False))
        )
        unread_count = unread_result.scalar() or 0

        return {
            "data": notifications,
            "pagination": {
                "next_cursor": str(notifications[-1].id) if has_more and notifications else None,
                "has_more": has_more,
                "limit": limit,
                "total_count": total_count,
            },
            "unread_count": unread_count,
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
            raise NotFoundException("errors.notification_not_found")

        if not notification.is_read:
            notification.is_read = True
            notification.read_at = utc_now()
            await db.flush()

            # 清除未讀計數快取
            await _invalidate_unread_cache(user_id)

        return notification

    @staticmethod
    async def mark_all_read(db: AsyncSession, user_id: UUID) -> MarkAllReadResponse:
        """
        標記所有通知為已讀

        Returns:
            MarkAllReadResponse（含更新筆數）
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

        return MarkAllReadResponse(updated_count=result.rowcount or 0)

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

    # ── 通知偏好（GDPR opt-out）────────────────────────────

    @staticmethod
    async def get_or_create_preferences(
        db: AsyncSession,
        user_id: UUID,
    ) -> NotificationPreference:
        """
        取得使用者的通知偏好；若不存在則建立一筆預設全開的列。

        所有開關預設為 true（見 model server_default），故僅需建立空列即可。
        """
        result = await db.execute(
            select(NotificationPreference).where(
                NotificationPreference.user_id == user_id
            )
        )
        pref = result.scalar_one_or_none()
        if pref is None:
            pref = NotificationPreference(user_id=user_id)
            db.add(pref)
            await db.flush()
            await db.refresh(pref)
        return pref

    @staticmethod
    async def update_preferences(
        db: AsyncSession,
        user_id: UUID,
        update: NotificationPreferenceUpdate,
    ) -> NotificationPreference:
        """
        更新使用者通知偏好（僅更新有提供的欄位），並 commit。

        病安守則：red_flag 為病安關鍵，**不允許**被關閉；任何將
        ``red_flag_enabled`` 設為 False 的嘗試都會被忽略並維持為 True。
        """
        pref = await NotificationService.get_or_create_preferences(db, user_id)

        # exclude_unset：只動呼叫端真正帶上的欄位，避免把未提供欄位覆寫成預設值
        changes = update.model_dump(exclude_unset=True)

        # red_flag 病安守則：忽略任何關閉嘗試，強制維持為 True
        if "red_flag_enabled" in changes and changes["red_flag_enabled"] is False:
            logger.warning(
                "拒絕關閉 red_flag 通知（病安關鍵）user=%s", user_id
            )
            changes.pop("red_flag_enabled")

        for field, value in changes.items():
            if value is not None:
                setattr(pref, field, value)

        await db.commit()
        await db.refresh(pref)
        return pref

    @staticmethod
    async def _is_type_enabled(
        db: AsyncSession,
        user_id: UUID,
        type: NotificationType,
    ) -> bool:
        """
        判斷某通知類型對該使用者是否啟用。

        - red_flag（不在 _TYPE_FLAG_FIELD 內）：恆為 True。
        - 查無偏好列：防禦性預設為 True（照常發送）。
        """
        flag_field = _TYPE_FLAG_FIELD.get(type)
        if flag_field is None:
            # red_flag 或未知類型：一律放行
            return True

        result = await db.execute(
            select(getattr(NotificationPreference, flag_field)).where(
                NotificationPreference.user_id == user_id
            )
        )
        enabled = result.scalar_one_or_none()
        # 無 pref row → enabled is None → 預設發送
        return enabled is None or bool(enabled)

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
    async def remove_fcm_token(db: AsyncSession, user_id: UUID, token: str) -> None:
        """
        移除 FCM token（標記為非活躍）

        僅可移除屬於請求使用者自己的裝置 token；scope 加上
        ``FCMDevice.user_id == user_id``，避免越權停用他人裝置。
        """
        result = await db.execute(
            select(FCMDevice)
            .where(FCMDevice.device_token == token)
            .where(FCMDevice.user_id == user_id)
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
        db: Optional[AsyncSession] = None,
    ) -> bool:
        """
        發送推播通知（透過 Celery 任務）

        若提供 ``db``，會依使用者偏好的 ``push_enabled`` 通道開關閘控：
        關閉時略過、回傳 False。未提供 db 或查無偏好列時，防禦性預設照常發送。

        Args:
            user_id: 目標使用者
            title: 通知標題
            body: 通知內容
            data: 附加資料
            db: （選填）用於查詢 push 通道偏好的 session

        Returns:
            True 表示已派送 Celery 任務；False 表示因偏好關閉而略過。
        """
        # 通道閘控：push_enabled 關閉則略過（防禦性：無 db / 無 pref 列 → 照常發送）
        if db is not None:
            result = await db.execute(
                select(NotificationPreference.push_enabled).where(
                    NotificationPreference.user_id == user_id
                )
            )
            push_enabled = result.scalar_one_or_none()
            if push_enabled is False:
                logger.info("推播被偏好設定抑制（push 通道關閉）user=%s", user_id)
                return False

        from app.tasks.notification_retry import send_push_notification_task

        send_push_notification_task.delay(
            user_id=str(user_id),
            title=title,
            body=body,
            data=data or {},
        )
        return True


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
