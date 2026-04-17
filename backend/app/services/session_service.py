"""
問診場次服務
- 場次 CRUD
- 狀態轉移驗證
- 醫師指派
"""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import (
    ForbiddenException,
    InvalidStatusTransitionException,
    NotFoundException,
    SessionNotFoundException,
)
from app.models.conversation import Conversation
from app.models.enums import SessionStatus, UserRole
from app.core.config import settings
from app.models.patient import Patient
from app.models.session import Session
from app.utils.datetime_utils import utc_now
from app.utils.language import resolve_language


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
        raise ForbiddenException("缺少認證主體，無法判定場次存取權限")

    role = _get_user_role(current_user)
    user_id = getattr(current_user, "id", None)

    if role == UserRole.ADMIN:
        return

    if role == UserRole.DOCTOR:
        if session.doctor_id is None or session.doctor_id == user_id:
            return
        raise ForbiddenException(
            "此場次已由其他醫師負責",
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
            "您沒有權限存取此場次",
            details={"session_id": str(session.id)},
        )

    # 未知角色 — 保守拒絕
    raise ForbiddenException(
        "未知角色，拒絕存取",
        details={"session_id": str(session.id), "role": str(role)},
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
    ) -> dict[str, Any]:
        """
        取得場次列表（Cursor-based 分頁 + 多條件篩選）

        Args:
            cursor: 分頁游標
            limit: 每頁筆數
            status: 篩選狀態
            doctor_id: 篩選醫師
            patient_id: 篩選病患
            date_from: 起始日期
            date_to: 結束日期
        """
        limit = min(limit, 100)

        query = (
            select(Session)
            .options(selectinload(Session.patient))
            .order_by(Session.created_at.desc(), Session.id.desc())
        )

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

        # Cursor 分頁
        if cursor:
            result = await db.execute(
                select(Session).where(Session.id == cursor)
            )
            cursor_record = result.scalar_one_or_none()
            if cursor_record:
                query = query.where(
                    (Session.created_at < cursor_record.created_at)
                    | (
                        (Session.created_at == cursor_record.created_at)
                        & (Session.id < cursor_record.id)
                    )
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
                f"無法從 {current_status.value} 轉移至 {new_status.value}",
                details={
                    "current_status": current_status.value,
                    "requested_status": new_status.value,
                    "allowed_transitions": [s.value for s in allowed],
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

        if cursor:
            result = await db.execute(
                select(Conversation).where(Conversation.id == cursor)
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
                    name=user_obj.name if user_obj else "未知",
                    gender=Gender.OTHER,
                    date_of_birth=date(1900, 1, 1),
                )
                db.add(patient)
                await db.flush()

        if patient is None:
            raise NotFoundException("無法決定場次對應的病患")

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
        return result.scalar_one()

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
        from datetime import datetime

        if current_user is None:
            raise ForbiddenException("缺少認證主體，無法列出場次")

        role = _get_user_role(current_user)
        user_id = getattr(current_user, "id", None)

        _date_from = datetime.fromisoformat(date_from) if date_from else None
        _date_to = datetime.fromisoformat(date_to) if date_to else None

        _status: Optional[SessionStatus] = None
        if status is not None:
            try:
                _status = SessionStatus(status) if not isinstance(status, SessionStatus) else status
            except ValueError:
                _status = None  # 無效字串直接忽略,避免 500

        _patient_id = patient_id
        _doctor_id = doctor_id

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
                .order_by(Session.created_at.desc(), Session.id.desc())
            )
            if _patient_id is not None:
                query = query.where(Session.patient_id == _patient_id)
            if _status:
                query = query.where(Session.status == _status)
            if _date_from:
                query = query.where(Session.created_at >= _date_from)
            if _date_to:
                query = query.where(Session.created_at <= _date_to)

            # Cursor 分頁 — 沿用 get_list 的邏輯
            if cursor:
                cursor_row = await db.execute(
                    select(Session).where(Session.id == cursor)
                )
                cursor_record = cursor_row.scalar_one_or_none()
                if cursor_record:
                    query = query.where(
                        (Session.created_at < cursor_record.created_at)
                        | (
                            (Session.created_at == cursor_record.created_at)
                            & (Session.id < cursor_record.id)
                        )
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
                .order_by(Session.created_at.desc(), Session.id.desc())
            )
            if _status:
                query = query.where(Session.status == _status)
            if _patient_id is not None:
                query = query.where(Session.patient_id == _patient_id)
            if _date_from:
                query = query.where(Session.created_at >= _date_from)
            if _date_to:
                query = query.where(Session.created_at <= _date_to)

            if cursor:
                cursor_row = await db.execute(
                    select(Session).where(Session.id == cursor)
                )
                cursor_record = cursor_row.scalar_one_or_none()
                if cursor_record:
                    query = query.where(
                        (Session.created_at < cursor_record.created_at)
                        | (
                            (Session.created_at == cursor_record.created_at)
                            & (Session.id < cursor_record.id)
                        )
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
                db, cursor, limit, _status, _doctor_id, _patient_id, _date_from, _date_to
            )

        # 未知角色
        raise ForbiddenException("未知角色，無法列出場次")

    async def get_session(
        self, db: AsyncSession, session_id: UUID, current_user: Any = None
    ) -> Session:
        session = await SessionService.get_by_id(db, session_id)
        await _authorize_session_access(db, session, current_user)
        return session

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
        return await SessionService.update_status_static(db, session_id, new_status, reason)

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
                    "此場次已由其他醫師負責，無法重新指派",
                    details={"session_id": str(session.id)},
                )
        else:
            raise ForbiddenException("僅 doctor / admin 可指派醫師")
        return await SessionService.assign_doctor_static(db, session_id, doctor_id)
