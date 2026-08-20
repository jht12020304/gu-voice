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

        ⚠️ **這一條刻意不 fan-out**（2026-08-20 一併檢視時的決定）。
        `notify_report_ready` 對 `doctor_id IS NULL` 的場次改成通知全體在職醫師，
        因為報告是最終產物、沒人知道就等於白做。但「問診完成」與「報告就緒」
        在時間上只差幾十秒，兩條都 fan-out 會讓每位醫師對**同一場**收到兩則
        通知＋兩次推播——噪音翻倍，而第二則（報告就緒）才是可以點進去看東西的
        那一則。所以未指派場次的廣播只留 report_ready 這一條。
        本函式的呼叫端（conversation_handler）本來就只在有 doctor_id 時呼叫。
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

        title = get_message("notifications.session_complete.title", doctor_lang)
        body = get_message(
            "notifications.session_complete.body",
            doctor_lang,
            patient_name=patient_name or "",
        )
        data = {"session_id": str(session_id)}

        notification = await NotificationService.create(
            db,
            user_id=doctor_id,
            type=NotificationType.SESSION_COMPLETE,
            title=title,
            body=body,
            data=data,
        )
        # 站內通知建立成功才發推播（被類型偏好抑制時 create() 回 None，推播也一併略過）。
        # 推播走 send_push_notification 的 push_enabled 通道閘控；派送失敗不可影響站內通知。
        if notification is not None:
            await _dispatch_push_best_effort(
                db=db, user_id=doctor_id, title=title, body=body, data=data
            )
        return notification

    @staticmethod
    async def notify_report_ready(
        db: AsyncSession,
        *,
        session_id: Any,
        report_id: Any,
    ) -> list[Notification]:
        """SOAP 報告生成完成 → REPORT_READY 站內通知。

        - 場次**已指派**醫師 → 只通知該醫師（維持原行為）。
        - 場次 `doctor_id IS NULL` → **fan-out 給全體在職醫師**。

        為什麼要 fan-out（2026-08-20，比照紅旗的
        `conversation_handler._notify_doctors_red_flag`）：院內 kiosk 的場次在
        問診當下**通常還沒指派醫師**（實測 DB 內 `sessions.doctor_id` 全為 NULL）。
        舊版在這個分支直接 `return None`——報告生成完了，**一個人都不會知道**。
        紅旗路徑早就修過同一個坑，report_ready 這條漏掉了。

        與紅旗的差別：REPORT_READY **受** `report_ready_enabled` 偏好抑制
        （紅旗是病安關鍵、恆送；報告就緒不是）。所以 fan-out 時每位醫師各自
        走一次 `create()`，關掉這個類型的醫師不會收到——這是刻意的。

        回傳**實際建立**的通知清單（被偏好抑制的醫師不在內）。
        呼叫端負責 commit；本函式僅 flush。
        """
        from app.models.user import User
        from app.utils.i18n_messages import get_message

        doctor_id, patient_name = await NotificationService._resolve_session_targets(
            db, session_id
        )
        targets = await NotificationService._doctor_targets(db, doctor_id, session_id)
        if not targets:
            return []

        data = {"session_id": str(session_id), "report_id": str(report_id)}
        created: list[Notification] = []
        for target_id in targets:
            # 逐位查 preferred_language：fan-out 的規模是「在職醫師數」，
            # 通常是個位數到十幾位，N+1 在這裡不是問題，而每位醫師看到自己
            # 語言的通知比省幾個 query 重要（notify_session_complete 同樣作法）。
            doctor_lang = (
                await db.execute(
                    select(User.preferred_language).where(User.id == target_id)
                )
            ).scalar_one_or_none()
            title = get_message("notifications.report_ready.title", doctor_lang)
            body = get_message(
                "notifications.report_ready.body",
                doctor_lang,
                patient_name=patient_name or "",
            )
            notification = await NotificationService.create(
                db,
                user_id=target_id,
                type=NotificationType.REPORT_READY,
                title=title,
                body=body,
                data=data,
            )
            # 同 notify_session_complete：站內通知成功才推播，且推播失敗不可影響
            # 已生成的報告（呼叫端 report_queue 為獨立第二段交易）。
            if notification is not None:
                created.append(notification)
                await _dispatch_push_best_effort(
                    db=db, user_id=target_id, title=title, body=body, data=data
                )
        return created

    @staticmethod
    async def notify_report_failed(
        db: AsyncSession,
        *,
        session_id: Any,
        report_id: Any = None,
    ) -> list[Notification]:
        """SOAP 報告生成**失敗** → SYSTEM 站內通知（SO-2 的通知半邊）。

        目標與 `notify_report_ready` 同一套規則：有指派醫師就通知他，
        `doctor_id IS NULL` 就 fan-out 給全體在職醫師。

        為什麼是 SYSTEM 而不是 REPORT_READY：報告**沒有**就緒，用 REPORT_READY
        會讓醫師點進去看到一片空白；而且 `report_ready_enabled=False` 的醫師
        會連「生成失敗」都收不到——「我不想被報告就緒打擾」不等於
        「我不想知道報告壞了」。

        呼叫端負責 commit；本函式僅 flush。
        """
        from app.models.user import User

        doctor_id, patient_name = await NotificationService._resolve_session_targets(
            db, session_id
        )
        targets = await NotificationService._doctor_targets(db, doctor_id, session_id)
        if not targets:
            return []

        data: dict[str, Any] = {"session_id": str(session_id), "status": "failed"}
        if report_id:
            data["report_id"] = str(report_id)

        created: list[Notification] = []
        for target_id in targets:
            doctor_lang = (
                await db.execute(
                    select(User.preferred_language).where(User.id == target_id)
                )
            ).scalar_one_or_none()
            title, body = _report_failed_copy(doctor_lang, patient_name or "")
            notification = await NotificationService.create(
                db,
                user_id=target_id,
                type=NotificationType.SYSTEM,
                title=title,
                body=body,
                data=data,
            )
            if notification is not None:
                created.append(notification)
                await _dispatch_push_best_effort(
                    db=db, user_id=target_id, title=title, body=body, data=data
                )
        return created

    @staticmethod
    async def _resolve_session_targets(
        db: AsyncSession, session_id: Any
    ) -> tuple[Optional[UUID], Optional[str]]:
        """取 (場次的 doctor_id, 病患姓名)。查不到場次時回 (None, None)。"""
        from app.models.patient import Patient
        from app.models.session import Session

        try:
            session_uuid = UUID(str(session_id))
        except (ValueError, TypeError, AttributeError):
            logger.warning("session_id 不是合法 UUID，通知略過 | %r", session_id)
            return None, None

        row = (
            await db.execute(
                select(Session.doctor_id, Patient.name)
                .join(Patient, Patient.id == Session.patient_id, isouter=True)
                .where(Session.id == session_uuid)
            )
        ).first()
        if row is None:
            return None, None
        return row.doctor_id, row.name

    @staticmethod
    async def _doctor_targets(
        db: AsyncSession, doctor_id: Optional[UUID], session_id: Any
    ) -> list[UUID]:
        """通知目標：有指派醫師就是他，否則全體在職醫師（未指派佇列 fan-out）。

        與 `conversation_handler._notify_doctors_red_flag` 同一套語意，
        查詢自帶 try/except：查不到不可讓呼叫端的第二段交易連帶炸掉。
        """
        from app.models.enums import UserRole
        from app.models.user import User as _User

        if doctor_id is not None:
            return [doctor_id]
        try:
            result = await db.execute(
                select(_User.id).where(
                    _User.role == UserRole.DOCTOR,
                    _User.is_active.is_(True),
                )
            )
            targets = list(result.scalars().all())
        except Exception:  # noqa: BLE001
            logger.warning(
                "查詢在職醫師失敗，通知略過 | session=%s", session_id, exc_info=True
            )
            return []
        if not targets:
            logger.warning(
                "場次未指派醫師且查無在職醫師，通知無人可送 | session=%s", session_id
            )
        return targets

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

# 「報告生成失敗」通知文案。
#
# ⚠️ 這裡沒有走 `app/utils/i18n_messages.py`，是**本輪的檔案邊界限制**
#（該檔由另一位執行者持有），不是設計選擇。將來合併時應搬成
# `notifications.report_failed.title` / `.body` 兩個 key，並把這個 dict 刪掉。
# 在那之前這份拷貝要與其他 notifications.* 文案的語氣保持一致。
_REPORT_FAILED_COPY: dict[str, tuple[str, str]] = {
    "zh-TW": ("報告生成失敗", "{patient_name} 的問診報告生成失敗，請重試。"),
    "en-US": (
        "Report generation failed",
        "The consultation report for {patient_name} could not be generated. Please retry.",
    ),
    "ja-JP": (
        "レポート生成に失敗しました",
        "{patient_name} さんの問診レポートを生成できませんでした。再試行してください。",
    ),
    "ko-KR": (
        "리포트 생성 실패",
        "{patient_name} 님의 문진 리포트를 생성하지 못했습니다. 다시 시도해 주세요.",
    ),
    "vi-VN": (
        "Tạo báo cáo thất bại",
        "Không thể tạo báo cáo khám cho {patient_name}. Vui lòng thử lại.",
    ),
}
_REPORT_FAILED_DEFAULT_LANG = "zh-TW"


def _report_failed_copy(language: Optional[str], patient_name: str) -> tuple[str, str]:
    """回傳 (title, body)；未支援語言退回 zh-TW（與 i18n_messages 的預設一致）。"""
    title, body = _REPORT_FAILED_COPY.get(
        language or "", _REPORT_FAILED_COPY[_REPORT_FAILED_DEFAULT_LANG]
    )
    return title, body.format(patient_name=patient_name).strip()


async def _dispatch_push_best_effort(
    *,
    db: AsyncSession,
    user_id: UUID,
    title: str,
    body: Optional[str],
    data: Optional[dict[str, Any]] = None,
) -> bool:
    """best-effort 派送推播：任何失敗都吞掉，只記 warning。

    語意對齊 report_queue 的第二段交易設計 —— 推播是站內通知/報告生成之外的
    附加動作，Celery / Redis / FCM 不可用時絕不可讓呼叫端炸掉或回滾。

    刻意**不**放進通用的 `create()`：RED_FLAG 路徑已於 alert_service 自行
    派推播，若 create() 也發會造成重複推播。

    Returns:
        True 表示已派送；False 表示被 push_enabled 偏好抑制或派送失敗。
    """
    try:
        return await NotificationService.send_push_notification(
            user_id=user_id,
            title=title,
            body=body or "",
            data=data,
            db=db,
        )
    except Exception:  # noqa: BLE001 — 推播失敗不可影響站內通知/報告
        logger.warning(
            "推播派送失敗（非致命）user=%s title=%s", user_id, title, exc_info=True
        )
        return False


async def _invalidate_unread_cache(user_id: UUID) -> None:
    """清除未讀計數快取"""
    try:
        from app.cache.redis_client import get_redis

        redis = await get_redis()
        cache_key = f"gu:notifications:unread:{user_id}"
        await redis.delete(cache_key)
    except Exception:
        pass
