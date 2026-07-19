"""
病患管理服務
- CRUD 操作
- Cursor-based 分頁
- 病患場次查詢
"""

from datetime import date, datetime, timedelta
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.authz import get_user_role as _get_user_role
from app.core.exceptions import ForbiddenException, NotFoundException
from app.models.enums import Gender, SessionStatus, UserRole
from app.models.patient import Patient
from app.models.session import Session
from app.utils.datetime_utils import parse_iso
from app.utils.datetime_utils import utc_now

# 「進行中」場次：尚未進入終態（completed / aborted / cancelled）的狀態。
_ACTIVE_SESSION_STATUSES = (SessionStatus.WAITING, SessionStatus.IN_PROGRESS)

# list_patients 允許排序的欄位白名單（避免任意欄位 / SQL injection 風險）。
_PATIENT_SORT_COLUMNS = {
    "created_at": Patient.created_at,
    "updated_at": Patient.updated_at,
    "name": Patient.name,
    "date_of_birth": Patient.date_of_birth,
}


def _authorize_patient_access(patient: Patient, current_user: Any) -> None:
    """
    校驗 current_user 是否能存取此 patient。無權限則 raise ForbiddenException。

    Ownership: 病患透過 patient.user_id 連結到建立 / 負責的醫師。
    角色規則:
      - admin         → 無限制
      - doctor        → 只能存取 patient.user_id == self 的病患
      - 其餘/未知角色 → 拒絕
    """
    if current_user is None:
        raise ForbiddenException("errors.patient_access_no_principal")

    role = _get_user_role(current_user)
    user_id = getattr(current_user, "id", None)

    if role == UserRole.ADMIN:
        return

    if role == UserRole.DOCTOR:
        if patient.user_id == user_id:
            return
        raise ForbiddenException(
            "errors.patient_forbidden_other_doctor",
            details={"patient_id": str(patient.id)},
        )

    # patient / 未知角色 — 保守拒絕（病患資料僅供醫師 / 管理員存取）
    raise ForbiddenException(
        "errors.patient_forbidden_role",
        details={"patient_id": str(patient.id), "role": str(role)},
    )


def _coerce_gender(value: Any) -> Optional[Gender]:
    """將 gender 篩選值（str / Gender / None）轉成 Gender；無效值回 None（即不過濾）。"""
    if value is None:
        return None
    if isinstance(value, Gender):
        return value
    try:
        return Gender(value)
    except ValueError:
        return None


def _dob_bounds_for_age_range(
    age_from: Optional[int],
    age_to: Optional[int],
    today: Optional[date] = None,
) -> tuple[Optional[date], Optional[date]]:
    """
    將「年齡範圍」換算成 date_of_birth 的上下界（含端點）。

    年齡 a 對應的最早出生日為 today - (a+1) 年 + 1 天，最晚為 today - a 年。
    - age_from（最小年齡）→ date_of_birth 上界（出生日須 <= today - age_from 年）
    - age_to（最大年齡）  → date_of_birth 下界（出生日須 >  today - (age_to+1) 年）

    Returns:
        (dob_min, dob_max)，任一為 None 代表該方向不設限。
    """
    if today is None:
        today = utc_now().date()

    dob_max: Optional[date] = None
    dob_min: Optional[date] = None

    if age_from is not None:
        # 至少 age_from 歲 → 出生日不晚於 (today 減 age_from 年)
        dob_max = _subtract_years(today, age_from)
    if age_to is not None:
        # 至多 age_to 歲 → 出生日須晚於 (today 減 (age_to + 1) 年)，即下界為其後一天
        dob_min = _subtract_years(today, age_to + 1) + timedelta(days=1)

    return dob_min, dob_max


def _subtract_years(d: date, years: int) -> date:
    """從日期減去整數年；遇 2/29 等非法日期時退到 2/28（避免 ValueError）。"""
    try:
        return d.replace(year=d.year - years)
    except ValueError:
        # 2/29 → 非閏年無此日，退回 2/28
        return d.replace(year=d.year - years, day=28)


class PatientService:
    """病患相關業務邏輯"""

    @staticmethod
    async def create(
        db: AsyncSession,
        data: dict[str, Any],
        created_by_id: UUID,
    ) -> Patient:
        """
        建立病患

        Args:
            db: 資料庫 session
            data: 病患資料
            created_by_id: 建立者（醫師）ID，對應 patient.user_id

        Returns:
            新建的 Patient 物件
        """
        now = utc_now()
        patient = Patient(
            user_id=created_by_id,
            medical_record_number=data["medical_record_number"],
            name=data["name"],
            gender=data["gender"],
            date_of_birth=data["date_of_birth"],
            phone=data.get("phone"),
            emergency_contact=data.get("emergency_contact"),
            medical_history=data.get("medical_history"),
            allergies=data.get("allergies"),
            current_medications=data.get("current_medications"),
            created_at=now,
            updated_at=now,
        )
        db.add(patient)
        await db.flush()
        return patient

    @staticmethod
    def _apply_patient_filters(
        query: Any,
        *,
        search: Optional[str] = None,
        doctor_id: Optional[UUID] = None,
        created_from: Optional[datetime] = None,
        created_to: Optional[datetime] = None,
        gender: Optional[Gender] = None,
        dob_min: Optional[date] = None,
        dob_max: Optional[date] = None,
        has_active_session: Optional[bool] = None,
    ) -> Any:
        """將病患列表的所有篩選條件套到 query（SELECT 與 COUNT 共用，確保兩者一致）。"""
        # 搜尋篩選（姓名或病歷號碼）
        if search:
            search_pattern = f"%{search}%"
            query = query.where(
                (Patient.name.ilike(search_pattern))
                | (Patient.medical_record_number.ilike(search_pattern))
            )

        # 醫師篩選
        if doctor_id:
            query = query.where(Patient.user_id == doctor_id)

        # 建立日期篩選
        if created_from:
            query = query.where(Patient.created_at >= created_from)
        if created_to:
            query = query.where(Patient.created_at <= created_to)

        # 性別等值過濾
        if gender is not None:
            query = query.where(Patient.gender == gender)

        # 年齡範圍 → date_of_birth 範圍
        if dob_min is not None:
            query = query.where(Patient.date_of_birth >= dob_min)
        if dob_max is not None:
            query = query.where(Patient.date_of_birth <= dob_max)

        # 是否有進行中（未終態）的 session
        if has_active_session is not None:
            active_subq = (
                select(Session.id)
                .where(Session.patient_id == Patient.id)
                .where(Session.status.in_(_ACTIVE_SESSION_STATUSES))
            )
            if has_active_session:
                query = query.where(active_subq.exists())
            else:
                query = query.where(~active_subq.exists())

        return query

    @staticmethod
    async def get_list(
        db: AsyncSession,
        cursor: Optional[str] = None,
        limit: int = 20,
        search: Optional[str] = None,
        doctor_id: Optional[UUID] = None,
        created_from: Optional[datetime] = None,
        created_to: Optional[datetime] = None,
        gender: Optional[Gender] = None,
        age_from: Optional[int] = None,
        age_to: Optional[int] = None,
        has_active_session: Optional[bool] = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> dict[str, Any]:
        """
        取得病患列表（Cursor-based 分頁）

        Args:
            cursor: 分頁游標（上一頁最後一筆的 ID）
            limit: 每頁筆數（預設 20，最大 100）
            search: 模糊搜尋（姓名或病歷號碼）
            doctor_id: 篩選特定醫師建立的病患
            gender: 性別等值過濾
            age_from / age_to: 年齡範圍（以 date_of_birth 換算，含端點）
            has_active_session: 是否有進行中（未終態）session
            sort_by: 排序欄位（白名單：created_at / updated_at / name / date_of_birth）
            sort_order: 排序方向（asc / desc，預設 desc）

        Returns:
            包含 data、pagination 的字典
        """
        limit = min(limit, 100)

        # 排序欄位 / 方向白名單化（非法值退回預設，避免 SQL injection 與例外）
        sort_column = _PATIENT_SORT_COLUMNS.get(sort_by, Patient.created_at)
        descending = str(sort_order).lower() != "asc"
        # 主排序 + id 作為穩定 tiebreaker（cursor 比較需與排序一致）
        if descending:
            order_clause = (sort_column.desc(), Patient.id.desc())
        else:
            order_clause = (sort_column.asc(), Patient.id.asc())

        # 年齡範圍換算為 date_of_birth 上下界
        dob_min, dob_max = _dob_bounds_for_age_range(age_from, age_to)
        gender_value = _coerce_gender(gender)

        filter_kwargs = dict(
            search=search,
            doctor_id=doctor_id,
            created_from=created_from,
            created_to=created_to,
            gender=gender_value,
            dob_min=dob_min,
            dob_max=dob_max,
            has_active_session=has_active_session,
        )

        # 軟刪除的病患不應出現在任何讀取結果
        query = select(Patient).where(Patient.is_deleted.is_(False))
        query = PatientService._apply_patient_filters(query, **filter_kwargs)
        query = query.order_by(*order_clause)

        # Cursor 分頁：取得游標之後的資料（比較鍵須與當前排序欄位一致）
        if cursor:
            result = await db.execute(
                select(Patient).where(Patient.id == cursor)
            )
            cursor_record = result.scalar_one_or_none()
            if cursor_record:
                cursor_value = getattr(cursor_record, sort_column.key)
                if descending:
                    query = query.where(
                        (sort_column < cursor_value)
                        | (
                            (sort_column == cursor_value)
                            & (Patient.id < cursor_record.id)
                        )
                    )
                else:
                    query = query.where(
                        (sort_column > cursor_value)
                        | (
                            (sort_column == cursor_value)
                            & (Patient.id > cursor_record.id)
                        )
                    )

        # 多取一筆用於判斷是否有下一頁
        result = await db.execute(query.limit(limit + 1))
        patients = result.scalars().all()

        has_more = len(patients) > limit
        if has_more:
            patients = patients[:limit]

        # 近似總筆數（套用相同篩選）
        count_query = (
            select(func.count())
            .select_from(Patient)
            .where(Patient.is_deleted.is_(False))
        )
        count_query = PatientService._apply_patient_filters(count_query, **filter_kwargs)
        total_result = await db.execute(count_query)
        total_count = total_result.scalar() or 0

        return {
            "data": patients,
            "pagination": {
                "next_cursor": str(patients[-1].id) if has_more and patients else None,
                "has_more": has_more,
                "limit": limit,
                "total_count": total_count,
            },
        }

    @staticmethod
    async def get_by_id(
        db: AsyncSession,
        patient_id: UUID,
        include_deleted: bool = False,
    ) -> Patient:
        """
        根據 ID 取得病患

        Args:
            include_deleted: 是否包含已軟刪除的病患（軟刪除流程內部用，預設排除）

        Raises:
            NotFoundException: 病患不存在
        """
        query = select(Patient).where(Patient.id == patient_id)
        if not include_deleted:
            query = query.where(Patient.is_deleted.is_(False))
        result = await db.execute(query)
        patient = result.scalar_one_or_none()
        if patient is None:
            raise NotFoundException("errors.patient_not_found")
        return patient

    @staticmethod
    async def update(
        db: AsyncSession,
        patient_id: UUID,
        data: dict[str, Any],
    ) -> Patient:
        """
        更新病患資料

        Args:
            data: 可更新欄位

        Raises:
            NotFoundException: 病患不存在
        """
        patient = await PatientService.get_by_id(db, patient_id)

        updatable_fields = {
            "name", "gender", "date_of_birth", "phone",
            "emergency_contact", "medical_history",
            "allergies", "current_medications",
        }

        for field, value in data.items():
            if field in updatable_fields and value is not None:
                setattr(patient, field, value)

        patient.updated_at = utc_now()
        await db.flush()
        return patient

    @staticmethod
    async def soft_delete(db: AsyncSession, patient_id: UUID) -> Patient:
        """
        軟刪除病患（標記 is_deleted=True，保留醫療記錄與 session FK）

        醫療病患資料不可硬刪 — 保留審計軌跡與既有 session 關聯。
        Idempotent：重複刪除同一病患不會報錯，已刪除者直接回傳。

        Raises:
            NotFoundException: 病患不存在

        Returns:
            被軟刪除的 Patient 物件
        """
        # include_deleted=True 讓重複刪除維持冪等（已刪除者仍可查到並直接回傳）
        patient = await PatientService.get_by_id(
            db, patient_id, include_deleted=True
        )
        if not patient.is_deleted:
            patient.is_deleted = True
            patient.deleted_at = utc_now()
            patient.updated_at = utc_now()
            await db.flush()
        return patient

    @staticmethod
    async def get_sessions(
        db: AsyncSession,
        patient_id: UUID,
        cursor: Optional[str] = None,
        limit: int = 20,
        current_user: Any = None,
        status: Any = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
    ) -> dict[str, Any]:
        """
        取得病患的問診場次列表

        Args:
            status: 場次狀態過濾（str / SessionStatus；無效值則略過不過濾）
            date_from / date_to: 以 created_at 篩選的起訖時間（含端點）

        Returns:
            包含 data、pagination 的字典
        """
        limit = min(limit, 100)

        # 確認病患存在（軟刪除者視為不存在）並校驗存取權限
        patient = await PatientService.get_by_id(db, patient_id)
        _authorize_patient_access(patient, current_user)

        status_value: Optional[SessionStatus] = None
        if status is not None:
            if isinstance(status, SessionStatus):
                status_value = status
            else:
                try:
                    status_value = SessionStatus(status)
                except ValueError:
                    status_value = None

        def _apply_session_filters(q: Any) -> Any:
            if status_value is not None:
                q = q.where(Session.status == status_value)
            if date_from is not None:
                q = q.where(Session.created_at >= date_from)
            if date_to is not None:
                q = q.where(Session.created_at <= date_to)
            return q

        query = (
            select(Session)
            .options(selectinload(Session.patient))
            .where(Session.patient_id == patient_id)
            .order_by(Session.created_at.desc(), Session.id.desc())
        )
        query = _apply_session_filters(query)

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

        # 總筆數（套用相同篩選）
        count_query = (
            select(func.count())
            .select_from(Session)
            .where(Session.patient_id == patient_id)
        )
        count_query = _apply_session_filters(count_query)
        count_result = await db.execute(count_query)
        total_count = count_result.scalar() or 0

        return {
            "data": sessions,
            "pagination": {
                "next_cursor": str(sessions[-1].id) if has_more and sessions else None,
                "has_more": has_more,
                "limit": limit,
                "total_count": total_count,
            },
        }

    # ── Aliases for router compatibility ─────────────────
    async def create_patient(self, db, data, created_by):
        return await self.create(db, data=data.model_dump() if hasattr(data, 'model_dump') else data, created_by_id=created_by)

    async def list_patients(self, db, current_user=None, cursor=None, limit=20, search=None,
                            created_from=None, created_to=None,
                            gender=None, age_from=None, age_to=None,
                            has_active_session=None, sort_by='created_at', sort_order='desc'):
        # 醫師僅能看自己名下病患（doctor_id 即 patient.user_id），admin 全部
        role = _get_user_role(current_user)
        doctor_id = None
        if role == UserRole.DOCTOR:
            doctor_id = getattr(current_user, "id", None)
        return await self.get_list(
            db,
            cursor=cursor,
            limit=limit,
            search=search,
            doctor_id=doctor_id,
            created_from=parse_iso(created_from),
            created_to=parse_iso(created_to),
            gender=gender,
            age_from=age_from,
            age_to=age_to,
            has_active_session=has_active_session,
            sort_by=sort_by,
            sort_order=sort_order,
        )

    async def get_patient(self, db, patient_id, current_user=None):
        patient = await self.get_by_id(db, patient_id)
        _authorize_patient_access(patient, current_user)
        return patient

    async def update_patient(self, db, patient_id, data, current_user=None):
        patient = await self.get_by_id(db, patient_id)
        _authorize_patient_access(patient, current_user)
        return await self.update(db, patient_id, data.model_dump(exclude_unset=True) if hasattr(data, 'model_dump') else data)

    async def soft_delete_patient(self, db, patient_id, deleted_by=None, current_user=None):
        """Router-facing 軟刪除。設定 is_deleted=True、deleted_at=now()，
        並 commit。Idempotent；病患不存在則 raise NotFoundException。
        醫療記錄（session 等）一律保留，不做硬刪除。

        Note:
            current_user 為相容性參數；目前 router 傳 deleted_by。當有
            current_user 時，沿用 get/update 的 ownership 規則校驗。
        """
        if current_user is not None:
            # include_deleted=True 維持冪等：已軟刪除者仍可通過 ownership 校驗
            patient = await self.get_by_id(db, patient_id, include_deleted=True)
            _authorize_patient_access(patient, current_user)
        patient = await self.soft_delete(db, patient_id)
        await db.commit()
        return patient

    async def list_patient_sessions(self, db, patient_id, cursor=None, limit=20, current_user=None):
        return await self.get_sessions(
            db, patient_id=patient_id, cursor=cursor, limit=limit, current_user=current_user
        )

    async def get_patient_sessions(
        self,
        db,
        patient_id,
        current_user=None,
        cursor=None,
        limit=20,
        status=None,
        date_from=None,
        date_to=None,
    ):
        """Router-facing alias。將 status / date_from / date_to 過濾轉交 get_sessions。

        date_from / date_to 以 ISO-8601 字串接收，透過 parse_iso 解析（非法輸入會
        拋 ValidationException，回 422 而非裸 500）；status 直接傳入由 get_sessions
        嘗試轉成 SessionStatus，無效值則略過不過濾。
        """
        return await self.get_sessions(
            db,
            patient_id=patient_id,
            cursor=cursor,
            limit=limit,
            current_user=current_user,
            status=status,
            date_from=parse_iso(date_from) if isinstance(date_from, str) else date_from,
            date_to=parse_iso(date_to) if isinstance(date_to, str) else date_to,
        )
