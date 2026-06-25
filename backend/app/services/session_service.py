"""
問診場次服務
- 場次 CRUD
- 狀態轉移驗證
- 醫師指派
"""

import logging
from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import (
    ConflictException,
    ForbiddenException,
    InvalidStatusTransitionException,
    NotFoundException,
    SessionNotFoundException,
    ValidationException,
)
from app.models.conversation import Conversation
from app.models.enums import AuditAction, SessionStatus, UserRole
from app.core.config import settings
from app.models.patient import Patient
from app.models.session import Session
from app.models.user import User
from app.utils.datetime_utils import utc_now
from app.utils.language import resolve_language

logger = logging.getLogger(__name__)


async def _broadcast_session_created(db: AsyncSession, session: Session) -> None:
    """H-8：場次建立後向儀表板推播 session_created + 最新 queue/stats。

    在同一 FastAPI 進程內透過 in-memory ConnectionManager 廣播；無 dashboard
    連線時 ``broadcast_queue_and_stats`` 會自行 short-circuit（不查 DB），
    故對單元測試無副作用。本函式吞掉所有例外，絕不影響場次建立主流程。

    注意：report_generated 的真正完成點在 Celery worker（另一進程），目前
    無 Redis pub/sub 橋接，故不在此處比照接線，詳見 report_service 的 TODO。
    """
    try:
        from app.cache.redis_client import get_redis
        from app.websocket.connection_manager import manager
        from app.websocket.dashboard_handler import broadcast_queue_and_stats

        if manager.dashboard_connection_count == 0:
            return  # 無儀表板連線，免去後續查詢與廣播

        patient = getattr(session, "patient", None)
        patient_name = getattr(patient, "name", "") if patient else ""
        await manager.broadcast_session_created(
            session_id=str(session.id),
            patient_name=patient_name or "",
            chief_complaint=getattr(session, "chief_complaint_text", "") or "",
            status=(
                session.status.value
                if hasattr(session.status, "value")
                else str(session.status)
            ),
        )
        # 順帶刷新 queue/stats（沿用 conversation_handler 既有的全域廣播語意）
        redis = await get_redis()
        await broadcast_queue_and_stats(db, redis)
    except Exception as exc:  # pragma: no cover - 推播失敗非致命
        logger.warning(
            "場次建立後推播儀表板事件失敗（非致命） | session=%s, error=%s",
            getattr(session, "id", None),
            str(exc),
        )


def _get_user_role(current_user: Any) -> Optional[UserRole]:
    """從 current_user 取出 role，容忍 string 或 enum 兩種來源。"""
    if current_user is None:
        return None
    raw = getattr(current_user, "role", None)
    if raw is None:
        return None
    if isinstance(raw, UserRole):
        return raw
    try:
        return UserRole(raw)
    except ValueError:
        return None


async def _authorize_session_access(
    db: AsyncSession,
    session: Session,
    current_user: Any,
) -> None:
    """
    校驗 current_user 是否能存取此 session。無權限則 raise ForbiddenException,
    不存在 current_user 則 raise UnauthorizedException 語意(此處視為 Forbidden)。

    角色規則:
      - admin         → 無限制
      - doctor        → 擁有 doctor_id == self OR doctor_id 為空(未指派) 的場次
      - patient       → 只能看自己名下 patient 的場次(Session.patient.user_id == self.id)
      - 其餘/未知角色 → 拒絕
    """
    if current_user is None:
        raise ForbiddenException("errors.session_access_no_principal")

    role = _get_user_role(current_user)
    user_id = getattr(current_user, "id", None)

    if role == UserRole.ADMIN:
        return

    if role == UserRole.DOCTOR:
        if session.doctor_id is None or session.doctor_id == user_id:
            return
        raise ForbiddenException(
            "errors.session_forbidden_other_doctor",
            details={"session_id": str(session.id)},
        )

    if role == UserRole.PATIENT:
        # 取出 patient.user_id。避免 lazy-load 錯誤,用明確 query 核對。
        result = await db.execute(
            select(Patient.user_id).where(Patient.id == session.patient_id)
        )
        owner_user_id = result.scalar_one_or_none()
        if owner_user_id is not None and owner_user_id == user_id:
            return
        raise ForbiddenException(
            "errors.session_forbidden_patient",
            details={"session_id": str(session.id)},
        )

    # 未知角色 — 保守拒絕
    raise ForbiddenException(
        "errors.session_unknown_role_access",
        details={"session_id": str(session.id), "role": str(role)},
    )


def _parse_date_filter(value: Optional[str], field: str) -> Optional[datetime]:
    """
    解析 date_from / date_to 查詢字串為 datetime。

    - None / 空字串 → None（不套用篩選）
    - 無法解析 → ValidationException（422），訊息使用 ISO-8601 日期格式錯誤鍵。
    """
    if value is None or value == "":
        return None
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        raise ValidationException(
            "errors.invalid_date_format",
            details={"field": field, "value": value},
        )


def _parse_cursor(cursor: Optional[str]) -> Optional[UUID]:
    """
    將 cursor 解析為 UUID。

    cursor 為「上一頁最後一筆的 id」（UUID 字串）。無法解析為合法 UUID 時
    保守視為「無 cursor」（回傳 None），避免把無效字串直接餵進 SQL，
    同時維持既有「cursor 查不到對應 record 即從頭分頁」的向後相容行為。
    """
    if not cursor:
        return None
    try:
        return UUID(str(cursor))
    except (ValueError, AttributeError, TypeError):
        return None


# ── 排序白名單 ───────────────────────────────────────────
# 僅允許白名單欄位排序，避免任意欄位字串造成 500 或資訊外洩。
# 注意：cursor 分頁的 keyset 條件以 created_at + id 為基準，故所有排序
# 都以 (主要欄位, id) 作為 tiebreaker，維持分頁穩定。
_SORTABLE_COLUMNS: dict[str, Any] = {
    "created_at": Session.created_at,
    "updated_at": Session.updated_at,
    "started_at": Session.started_at,
    "completed_at": Session.completed_at,
    "status": Session.status,
}


def _resolve_sort(sort_by: Optional[str], sort_order: Optional[str]) -> tuple[Any, bool]:
    """
    解析白名單排序欄位與方向。

    Returns:
        (column, descending)；sort_by 不在白名單退回 created_at，
        sort_order 非 asc 一律視為 desc（向後相容預設）。
    """
    column = _SORTABLE_COLUMNS.get(sort_by or "", Session.created_at)
    descending = (sort_order or "desc").lower() != "asc"
    return column, descending


def _apply_sort(query: Any, column: Any, descending: bool) -> Any:
    """套用排序，並一律附加 Session.id 作為 tiebreaker 確保分頁穩定。"""
    if descending:
        return query.order_by(column.desc(), Session.id.desc())
    return query.order_by(column.asc(), Session.id.asc())


def _apply_cursor_keyset(
    query: Any, cursor_record: Any, column: Any, descending: bool
) -> Any:
    """
    依排序方向套用 keyset 分頁條件，使 cursor 與 sort 一致。

    descending → 取「排在 cursor 之後」= column < cursor_value，tie 時 id < cursor_id。
    ascending  → column > cursor_value，tie 時 id > cursor_id。
    """
    cursor_value = getattr(cursor_record, column.key)
    cursor_id = cursor_record.id
    if descending:
        return query.where(
            (column < cursor_value)
            | ((column == cursor_value) & (Session.id < cursor_id))
        )
    return query.where(
        (column > cursor_value)
        | ((column == cursor_value) & (Session.id > cursor_id))
    )


# ── 合法狀態轉移表 ───────────────────────────────────────
VALID_TRANSITIONS: dict[SessionStatus, list[SessionStatus]] = {
    SessionStatus.WAITING: [
        SessionStatus.IN_PROGRESS,
        SessionStatus.CANCELLED,
    ],
    SessionStatus.IN_PROGRESS: [
        SessionStatus.COMPLETED,
        SessionStatus.ABORTED_RED_FLAG,
        SessionStatus.CANCELLED,
    ],
    SessionStatus.COMPLETED: [],
    SessionStatus.ABORTED_RED_FLAG: [],
    SessionStatus.CANCELLED: [],
}


class SessionService:
    """問診場次業務邏輯"""

    @staticmethod
    async def create(db: AsyncSession, data: dict[str, Any]) -> Session:
        """
        建立問診場次（初始狀態為 waiting）

        Args:
            data: 場次資料（patient_id, chief_complaint_id, ...）

        Returns:
            新建的 Session 物件
        """
        now = utc_now()
        session = Session(
            patient_id=data["patient_id"],
            doctor_id=data.get("doctor_id"),
            chief_complaint_id=data["chief_complaint_id"],
            chief_complaint_text=data.get("chief_complaint_text"),
            status=SessionStatus.WAITING,
            red_flag=False,
            language=data.get("language") or settings.DEFAULT_LANGUAGE,
            intake_data=data.get("intake"),
            intake_completed_at=now if data.get("intake") else None,
            created_at=now,
            updated_at=now,
        )
        db.add(session)
        await db.flush()
        return session

    @staticmethod
    async def get_list(
        db: AsyncSession,
        cursor: Optional[str] = None,
        limit: int = 20,
        status: Optional[SessionStatus] = None,
        doctor_id: Optional[UUID] = None,
        patient_id: Optional[UUID] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        取得場次列表（Cursor-based 分頁 + 多條件篩選）

        Args:
            cursor: 分頁游標（UUID 或字串；非合法 UUID 視為無 cursor）
            limit: 每頁筆數
            status: 篩選狀態
            doctor_id: 篩選醫師
            patient_id: 篩選病患
            date_from: 起始日期
            date_to: 結束日期
            sort_by: 排序欄位（白名單外退回 created_at）
            sort_order: 排序方向（asc / desc，預設 desc）
        """
        limit = min(limit, 100)
        _cursor = _parse_cursor(cursor) if not isinstance(cursor, UUID) else cursor
        _sort_column, _sort_desc = _resolve_sort(sort_by, sort_order)

        query = select(Session).options(selectinload(Session.patient))
        query = _apply_sort(query, _sort_column, _sort_desc)

        # 條件篩選
        if status:
            query = query.where(Session.status == status)
        if doctor_id:
            query = query.where(Session.doctor_id == doctor_id)
        if patient_id:
            query = query.where(Session.patient_id == patient_id)
        if date_from:
            query = query.where(Session.created_at >= date_from)
        if date_to:
            query = query.where(Session.created_at <= date_to)

        # Cursor 分頁 — keyset 條件依排序方向套用
        if _cursor is not None:
            result = await db.execute(
                select(Session).where(Session.id == _cursor)
            )
            cursor_record = result.scalar_one_or_none()
            if cursor_record:
                query = _apply_cursor_keyset(
                    query, cursor_record, _sort_column, _sort_desc
                )

        result = await db.execute(query.limit(limit + 1))
        sessions = result.scalars().all()

        has_more = len(sessions) > limit
        if has_more:
            sessions = sessions[:limit]

        # 近似總筆數
        count_query = select(func.count()).select_from(Session)
        if status:
            count_query = count_query.where(Session.status == status)
        if doctor_id:
            count_query = count_query.where(Session.doctor_id == doctor_id)
        if patient_id:
            count_query = count_query.where(Session.patient_id == patient_id)
        total_result = await db.execute(count_query)
        total_count = total_result.scalar() or 0

        return {
            "data": sessions,
            "pagination": {
                "next_cursor": str(sessions[-1].id) if has_more and sessions else None,
                "has_more": has_more,
                "limit": limit,
                "total_count": total_count,
            },
        }

    @staticmethod
    async def get_by_id(db: AsyncSession, session_id: UUID) -> Session:
        """
        根據 ID 取得場次（含對話紀錄）

        Raises:
            SessionNotFoundException: 場次不存在
        """
        result = await db.execute(
            select(Session)
            .options(
                selectinload(Session.conversations),
                selectinload(Session.patient),
            )
            .where(Session.id == session_id)
        )
        session = result.scalar_one_or_none()
        if session is None:
            raise SessionNotFoundException()
        return session

    @staticmethod
    async def update_status_static(
        db: AsyncSession,
        session_id: UUID,
        new_status: SessionStatus,
        reason: Optional[str] = None,
    ) -> Session:
        """
        更新場次狀態（含狀態轉移驗證）

        Args:
            session_id: 場次 ID
            new_status: 目標狀態
            reason: 狀態變更原因（取消、紅旗等）

        Raises:
            SessionNotFoundException: 場次不存在
            InvalidStatusTransitionException: 不合法的狀態轉移
        """
        session = await SessionService.get_by_id(db, session_id)
        current_status = session.status

        # 驗證狀態轉移合法性
        allowed = VALID_TRANSITIONS.get(current_status, [])
        if new_status not in allowed:
            raise InvalidStatusTransitionException(
                "errors.status_transition_not_allowed",
                details={
                    "current_status": current_status.value,
                    "requested_status": new_status.value,
                    "allowed_transitions": [s.value for s in allowed],
                },
                message_kwargs={
                    "current": current_status.value,
                    "target": new_status.value,
                },
            )

        now = utc_now()
        session.status = new_status
        session.updated_at = now

        # 狀態特定處理
        if new_status == SessionStatus.IN_PROGRESS:
            session.started_at = now

        elif new_status in (
            SessionStatus.COMPLETED,
            SessionStatus.ABORTED_RED_FLAG,
            SessionStatus.CANCELLED,
        ):
            session.completed_at = now
            # 計算持續秒數
            if session.started_at:
                delta = now - session.started_at
                session.duration_seconds = int(delta.total_seconds())

        if new_status == SessionStatus.ABORTED_RED_FLAG:
            session.red_flag = True
            if reason:
                session.red_flag_reason = reason

        await db.flush()
        return session

    @staticmethod
    async def end_for_language_switch(
        db: AsyncSession,
        session_id: UUID,
        to_language: str,
        current_user: Any,
    ) -> Session:
        """
        M16：使用者在對話中切語言 → 結束 session 並寫 audit log。

        - 僅 waiting / in_progress 狀態可用；其他狀態 → 409 Conflict
        - to_language 必須在 SUPPORTED_LANGUAGES（schema 層已驗證）
        - 同時更新 user.preferred_language，下一場 session 預設套用
        - audit_log 紀錄 from_lang / to_lang / session_id
        """
        from app.services.audit_log_service import AuditLogService

        session = await SessionService.get_by_id(db, session_id)
        await _authorize_session_access(db, session, current_user)

        if session.status not in (SessionStatus.WAITING, SessionStatus.IN_PROGRESS):
            raise ConflictException(
                "errors.session_not_switchable",
                details={
                    "session_id": str(session.id),
                    "current_status": session.status.value,
                },
            )

        from_lang = session.language
        now = utc_now()
        # L-3：保留變更前狀態，供 SessionStatusResponse.previous_status 回傳。
        previous_status = session.status
        session.status = SessionStatus.CANCELLED
        session.completed_at = now
        session.updated_at = now
        if session.started_at:
            session.duration_seconds = int((now - session.started_at).total_seconds())

        # 更新 user preferred_language（下次登入 / 下一場新 session 會套用）
        user_id = getattr(current_user, "id", None)
        if user_id is not None:
            result = await db.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()
            if user is not None:
                user.preferred_language = to_language
                user.updated_at = now

        await AuditLogService.log(
            db,
            user_id=user_id,
            action=AuditAction.LANGUAGE_SWITCH_END_SESSION,
            resource_type="session",
            resource_id=str(session.id),
            details={
                "from_lang": from_lang,
                "to_lang": to_language,
            },
        )

        await db.flush()
        session.previous_status = previous_status
        return session

    @staticmethod
    async def get_conversations_static(
        db: AsyncSession,
        session_id: UUID,
        cursor: Optional[str] = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """
        取得場次的對話紀錄

        Returns:
            包含 data、pagination 的字典
        """
        limit = min(limit, 100)

        # 確認場次存在
        await SessionService.get_by_id(db, session_id)

        query = (
            select(Conversation)
            .where(Conversation.session_id == session_id)
            .order_by(Conversation.sequence_number.asc())
        )

        # cursor 為上一頁最後一筆 Conversation.id（UUID）；非合法 UUID 視為無 cursor。
        _cursor = _parse_cursor(cursor)
        if _cursor is not None:
            result = await db.execute(
                select(Conversation).where(Conversation.id == _cursor)
            )
            cursor_record = result.scalar_one_or_none()
            if cursor_record:
                query = query.where(
                    Conversation.sequence_number > cursor_record.sequence_number
                )

        result = await db.execute(query.limit(limit + 1))
        conversations = result.scalars().all()

        has_more = len(conversations) > limit
        if has_more:
            conversations = conversations[:limit]

        count_result = await db.execute(
            select(func.count())
            .select_from(Conversation)
            .where(Conversation.session_id == session_id)
        )
        total_count = count_result.scalar() or 0

        return {
            "data": conversations,
            "pagination": {
                "next_cursor": str(conversations[-1].id) if has_more and conversations else None,
                "has_more": has_more,
                "limit": limit,
                "total_count": total_count,
            },
        }

    @staticmethod
    async def assign_doctor_static(
        db: AsyncSession,
        session_id: UUID,
        doctor_id: UUID,
    ) -> Session:
        """
        指派醫師至場次

        Raises:
            SessionNotFoundException: 場次不存在
        """
        session = await SessionService.get_by_id(db, session_id)
        session.doctor_id = doctor_id
        session.updated_at = utc_now()
        await db.flush()
        return session

    # --- Instance method wrappers for Router compatibility ---
    async def create_session(
        self,
        db: AsyncSession,
        data: Any,
        current_user: Any = None,
        accept_language: Optional[str] = None,
    ) -> Session:
        import random
        from datetime import date
        from app.models.enums import Gender
        from app.models.patient import Patient
        from app.models.user import User

        data_dict = data.model_dump(exclude_none=True)
        patient_info = data_dict.pop("patient_info", None)
        requested_patient_id = data_dict.get("patient_id")

        # 解析語言：payload > user.preferred_language > Accept-Language > default
        data_dict["language"] = resolve_language(
            payload_language=data_dict.get("language"),
            user=current_user,
            accept_language_header=accept_language,
        )

        current_user_id = current_user.id if current_user else None

        def _generate_mrn() -> str:
            return f"P-{utc_now().year}-{random.randint(100000, 999999)}"

        patient: Optional[Any] = None

        # 1) 明確指定 patient_id → 必須屬於目前使用者才採用
        if requested_patient_id and current_user_id:
            result = await db.execute(
                select(Patient).where(
                    and_(
                        Patient.id == requested_patient_id,
                        Patient.user_id == current_user_id,
                    )
                )
            )
            patient = result.scalar_one_or_none()

        # 2) 帶 patient_info → 依 (user_id, name, dob, phone) get_or_create
        if patient is None and patient_info is not None and current_user_id is not None:
            info_name = patient_info.get("name")
            info_gender_raw = patient_info.get("gender")
            info_gender: Optional[Gender]
            if isinstance(info_gender_raw, Gender) or info_gender_raw is None:
                info_gender = info_gender_raw
            else:
                try:
                    info_gender = Gender(info_gender_raw)
                except ValueError:
                    info_gender = Gender.OTHER
            info_dob = patient_info.get("date_of_birth")
            info_phone = patient_info.get("phone")

            conditions = [
                Patient.user_id == current_user_id,
                Patient.name == info_name,
                Patient.date_of_birth == info_dob,
            ]
            # phone 可能為 None，NULL 對 NULL 也算命中
            if info_phone is None:
                conditions.append(Patient.phone.is_(None))
            else:
                conditions.append(Patient.phone == info_phone)

            existing_result = await db.execute(
                select(Patient).where(and_(*conditions))
            )
            patient = existing_result.scalar_one_or_none()

            if patient is None:
                mrn = _generate_mrn()
                patient = Patient(
                    user_id=current_user_id,
                    medical_record_number=mrn,
                    name=info_name,
                    gender=info_gender or Gender.OTHER,
                    date_of_birth=info_dob or date(1900, 1, 1),
                    phone=info_phone,
                )
                db.add(patient)
                await db.flush()

        # 3) Fallback — 回退舊行為：使用者名下第一位病患，否則自動建立 placeholder
        if patient is None and current_user_id is not None:
            fallback_result = await db.execute(
                select(Patient)
                .where(Patient.user_id == current_user_id)
                .order_by(Patient.created_at.asc())
            )
            patient = fallback_result.scalars().first()

            if patient is None:
                user_result = await db.execute(
                    select(User).where(User.id == current_user_id)
                )
                user_obj = user_result.scalar_one_or_none()
                mrn = _generate_mrn()
                patient = Patient(
                    user_id=current_user_id,
                    medical_record_number=mrn,
                    # DB 要求 NOT NULL,使用者沒填名字時以英文 "Unknown" 佔位,
                    # 避免中文「未知」外流到 en-US / ja-JP 等場次的病患清單。
                    name=user_obj.name if user_obj else "Unknown",
                    gender=Gender.OTHER,
                    date_of_birth=date(1900, 1, 1),
                )
                db.add(patient)
                await db.flush()

        if patient is None:
            raise NotFoundException("errors.session_patient_unresolved")

        data_dict["patient_id"] = patient.id

        session = await SessionService.create(db, data_dict)
        await db.commit()
        # Re-fetch with conversations eagerly loaded to avoid lazy-load error during serialization
        result = await db.execute(
            select(Session)
            .options(
                selectinload(Session.conversations),
                selectinload(Session.patient),
            )
            .where(Session.id == session.id)
        )
        created = result.scalar_one()
        # H-8：場次建立成功（已 commit）後，向儀表板推播 session_created
        # 與最新 queue/stats。helper 不可拋例外，不影響回傳。
        await _broadcast_session_created(db, created)
        return created

    async def list_sessions(
        self,
        db: AsyncSession,
        current_user: Any = None,
        cursor: Optional[str] = None,
        limit: int = 20,
        status: Optional[str] = None,
        patient_id: Optional[UUID] = None,
        doctor_id: Optional[UUID] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> dict[str, Any]:
        """
        依角色限縮可見場次。
          - admin   → 全部
          - doctor  → 自己負責 + 未指派(doctor_id IS NULL)
          - patient → 自己名下 Patient 底下的所有 session
          - 無角色  → 403
        傳入的 doctor_id / patient_id 過濾條件會與角色限制做 AND;
        禁止一般使用者靠手動傳參數跳脫自身範圍(下方會強制覆寫)。
        """
        if current_user is None:
            raise ForbiddenException("errors.session_list_no_principal")

        role = _get_user_role(current_user)
        user_id = getattr(current_user, "id", None)

        _date_from = _parse_date_filter(date_from, "date_from")
        _date_to = _parse_date_filter(date_to, "date_to")
        _cursor = _parse_cursor(cursor)

        _status: Optional[SessionStatus] = None
        if status is not None:
            try:
                _status = SessionStatus(status) if not isinstance(status, SessionStatus) else status
            except ValueError:
                _status = None  # 無效字串直接忽略,避免 500

        _patient_id = patient_id
        _doctor_id = doctor_id
        _sort_column, _sort_desc = _resolve_sort(sort_by, sort_order)

        if role == UserRole.PATIENT:
            # 以 subquery 將 patient_id 限縮為 current_user 名下所有 Patient.id
            owned_patient_ids_subq = (
                select(Patient.id).where(Patient.user_id == user_id)
            )
            # 如果呼叫端有指定 patient_id,還是要落在自己名下 → 用 get_list 不支援多 id,
            # 改在這裡手動查完整 query,以 patient_id IN subquery 強制限縮。
            query = (
                select(Session)
                .options(selectinload(Session.patient))
                .where(Session.patient_id.in_(owned_patient_ids_subq))
            )
            query = _apply_sort(query, _sort_column, _sort_desc)
            if _patient_id is not None:
                query = query.where(Session.patient_id == _patient_id)
            if _status:
                query = query.where(Session.status == _status)
            if _date_from:
                query = query.where(Session.created_at >= _date_from)
            if _date_to:
                query = query.where(Session.created_at <= _date_to)

            # Cursor 分頁 — keyset 條件依排序方向套用，與 sort 保持一致
            if _cursor is not None:
                cursor_row = await db.execute(
                    select(Session).where(Session.id == _cursor)
                )
                cursor_record = cursor_row.scalar_one_or_none()
                if cursor_record:
                    query = _apply_cursor_keyset(
                        query, cursor_record, _sort_column, _sort_desc
                    )

            effective_limit = min(limit, 100)
            result = await db.execute(query.limit(effective_limit + 1))
            sessions = result.scalars().all()
            has_more = len(sessions) > effective_limit
            if has_more:
                sessions = sessions[:effective_limit]

            count_query = (
                select(func.count())
                .select_from(Session)
                .where(Session.patient_id.in_(owned_patient_ids_subq))
            )
            if _status:
                count_query = count_query.where(Session.status == _status)
            if _patient_id is not None:
                count_query = count_query.where(Session.patient_id == _patient_id)
            total_count = (await db.execute(count_query)).scalar() or 0

            return {
                "data": sessions,
                "pagination": {
                    "next_cursor": str(sessions[-1].id) if has_more and sessions else None,
                    "has_more": has_more,
                    "limit": effective_limit,
                    "total_count": total_count,
                },
            }

        if role == UserRole.DOCTOR:
            # 醫師: 自己負責 + 未指派。呼叫端傳的 doctor_id 會被強制覆寫為 self.id,
            # 避免透過 query 參數窺探其他醫師負責的場次。
            effective_limit = min(limit, 100)
            query = (
                select(Session)
                .options(selectinload(Session.patient))
                .where(
                    (Session.doctor_id == user_id) | (Session.doctor_id.is_(None))
                )
            )
            query = _apply_sort(query, _sort_column, _sort_desc)
            if _status:
                query = query.where(Session.status == _status)
            if _patient_id is not None:
                query = query.where(Session.patient_id == _patient_id)
            if _date_from:
                query = query.where(Session.created_at >= _date_from)
            if _date_to:
                query = query.where(Session.created_at <= _date_to)

            if _cursor is not None:
                cursor_row = await db.execute(
                    select(Session).where(Session.id == _cursor)
                )
                cursor_record = cursor_row.scalar_one_or_none()
                if cursor_record:
                    query = _apply_cursor_keyset(
                        query, cursor_record, _sort_column, _sort_desc
                    )

            result = await db.execute(query.limit(effective_limit + 1))
            sessions = result.scalars().all()
            has_more = len(sessions) > effective_limit
            if has_more:
                sessions = sessions[:effective_limit]

            count_query = (
                select(func.count())
                .select_from(Session)
                .where(
                    (Session.doctor_id == user_id) | (Session.doctor_id.is_(None))
                )
            )
            if _status:
                count_query = count_query.where(Session.status == _status)
            if _patient_id is not None:
                count_query = count_query.where(Session.patient_id == _patient_id)
            total_count = (await db.execute(count_query)).scalar() or 0

            return {
                "data": sessions,
                "pagination": {
                    "next_cursor": str(sessions[-1].id) if has_more and sessions else None,
                    "has_more": has_more,
                    "limit": effective_limit,
                    "total_count": total_count,
                },
            }

        if role == UserRole.ADMIN:
            return await SessionService.get_list(
                db,
                _cursor,
                limit,
                _status,
                _doctor_id,
                _patient_id,
                _date_from,
                _date_to,
                sort_by=sort_by,
                sort_order=sort_order,
            )

        # 未知角色
        raise ForbiddenException("errors.session_unknown_role")

    async def get_session(
        self, db: AsyncSession, session_id: UUID, current_user: Any = None
    ) -> Session:
        session = await SessionService.get_by_id(db, session_id)
        await _authorize_session_access(db, session, current_user)
        return session

    # 病患不得自行觸發的紅旗 / 終止類狀態 — 僅醫師 / admin 可設定，
    # 避免病患透過 REST 端點偽造 aborted_red_flag 觸發紅旗流程。
    _PRIVILEGED_STATUSES: frozenset[SessionStatus] = frozenset(
        {SessionStatus.ABORTED_RED_FLAG}
    )

    async def update_status(
        self,
        db: AsyncSession,
        session_id: UUID,
        new_status: SessionStatus,
        reason: Optional[str] = None,
        current_user: Any = None,
    ) -> Session:
        session = await SessionService.get_by_id(db, session_id)
        await _authorize_session_access(db, session, current_user)

        # 角色限制：紅旗 / 終止類狀態僅限 doctor / admin 變更，
        # 病患不得自行把場次改成 aborted_red_flag 等紅旗狀態。
        if new_status in self._PRIVILEGED_STATUSES:
            role = _get_user_role(current_user)
            if role not in (UserRole.DOCTOR, UserRole.ADMIN):
                raise ForbiddenException(
                    "errors.session_forbidden_patient",
                    details={
                        "session_id": str(session.id),
                        "requested_status": new_status.value,
                    },
                )

        previous_status = session.status
        updated = await SessionService.update_status_static(db, session_id, new_status, reason)
        # L-3：REST 路徑回傳變更前狀態（供 SessionStatusResponse.previous_status）。
        updated.previous_status = previous_status
        return updated

    async def get_conversations(
        self,
        db: AsyncSession,
        session_id: UUID,
        current_user: Any = None,
        cursor: Optional[str] = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        session = await SessionService.get_by_id(db, session_id)
        await _authorize_session_access(db, session, current_user)
        return await SessionService.get_conversations_static(db, session_id, cursor, limit)

    async def assign_doctor(
        self, db: AsyncSession, session_id: UUID, doctor_id: UUID, current_user: Any = None
    ) -> Session:
        # Router 已透過 require_role("doctor","admin") 限制角色,
        # 這裡仍做 ownership 檢查(防止 doctor A 把其他醫師已負責的 session 搶走)。
        session = await SessionService.get_by_id(db, session_id)
        role = _get_user_role(current_user)
        if role == UserRole.ADMIN:
            # admin 可任意指派
            pass
        elif role == UserRole.DOCTOR:
            # doctor 只能把未指派的場次搶起來,或把自己名下的場次轉出給自己(no-op)
            if session.doctor_id is not None and session.doctor_id != getattr(current_user, "id", None):
                raise ForbiddenException(
                    "errors.assign_doctor_conflict",
                    details={"session_id": str(session.id)},
                )
        else:
            raise ForbiddenException("errors.assign_doctor_role_required")
        return await SessionService.assign_doctor_static(db, session_id, doctor_id)
