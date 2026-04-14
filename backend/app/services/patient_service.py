"""
病患管理服務
- CRUD 操作
- Cursor-based 分頁
- 病患場次查詢
"""

from typing import Any, Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import NotFoundException
from app.models.patient import Patient
from app.models.session import Session
from app.utils.datetime_utils import utc_now


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
    async def get_list(
        db: AsyncSession,
        cursor: Optional[str] = None,
        limit: int = 20,
        search: Optional[str] = None,
        doctor_id: Optional[UUID] = None,
    ) -> dict[str, Any]:
        """
        取得病患列表（Cursor-based 分頁）

        Args:
            cursor: 分頁游標（上一頁最後一筆的 ID）
            limit: 每頁筆數（預設 20，最大 100）
            search: 模糊搜尋（姓名或病歷號碼）
            doctor_id: 篩選特定醫師建立的病患

        Returns:
            包含 data、pagination 的字典
        """
        limit = min(limit, 100)

        query = select(Patient).order_by(Patient.created_at.desc(), Patient.id.desc())

        # 搜尋篩選
        if search:
            search_pattern = f"%{search}%"
            query = query.where(
                (Patient.name.ilike(search_pattern))
                | (Patient.medical_record_number.ilike(search_pattern))
            )

        # 醫師篩選
        if doctor_id:
            query = query.where(Patient.user_id == doctor_id)

        # Cursor 分頁：取得游標之後的資料
        if cursor:
            result = await db.execute(
                select(Patient).where(Patient.id == cursor)
            )
            cursor_record = result.scalar_one_or_none()
            if cursor_record:
                query = query.where(
                    (Patient.created_at < cursor_record.created_at)
                    | (
                        (Patient.created_at == cursor_record.created_at)
                        & (Patient.id < cursor_record.id)
                    )
                )

        # 多取一筆用於判斷是否有下一頁
        result = await db.execute(query.limit(limit + 1))
        patients = result.scalars().all()

        has_more = len(patients) > limit
        if has_more:
            patients = patients[:limit]

        # 近似總筆數
        count_query = select(func.count()).select_from(Patient)
        if search:
            search_pattern = f"%{search}%"
            count_query = count_query.where(
                (Patient.name.ilike(search_pattern))
                | (Patient.medical_record_number.ilike(search_pattern))
            )
        if doctor_id:
            count_query = count_query.where(Patient.user_id == doctor_id)
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
    async def get_by_id(db: AsyncSession, patient_id: UUID) -> Patient:
        """
        根據 ID 取得病患

        Raises:
            NotFoundException: 病患不存在
        """
        result = await db.execute(
            select(Patient).where(Patient.id == patient_id)
        )
        patient = result.scalar_one_or_none()
        if patient is None:
            raise NotFoundException("病患不存在")
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
    async def delete(db: AsyncSession, patient_id: UUID) -> None:
        """
        刪除病患（軟刪除 — 移除記錄）

        Note:
            目前為實際刪除。若需軟刪除，可新增 is_deleted 欄位。

        Raises:
            NotFoundException: 病患不存在
        """
        patient = await PatientService.get_by_id(db, patient_id)
        await db.delete(patient)
        await db.flush()

    @staticmethod
    async def get_sessions(
        db: AsyncSession,
        patient_id: UUID,
        cursor: Optional[str] = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """
        取得病患的問診場次列表

        Returns:
            包含 data、pagination 的字典
        """
        limit = min(limit, 100)

        # 確認病患存在
        await PatientService.get_by_id(db, patient_id)

        query = (
            select(Session)
            .options(selectinload(Session.patient))
            .where(Session.patient_id == patient_id)
            .order_by(Session.created_at.desc(), Session.id.desc())
        )

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

        # 總筆數
        count_result = await db.execute(
            select(func.count())
            .select_from(Session)
            .where(Session.patient_id == patient_id)
        )
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

    async def list_patients(self, db, cursor=None, limit=20, search=None,
                            gender=None, age_from=None, age_to=None,
                            has_active_session=None, sort_by='created_at', sort_order='desc'):
        return await self.get_list(db, cursor=cursor, limit=limit, search=search)

    async def get_patient(self, db, patient_id, current_user=None):
        return await self.get_by_id(db, patient_id)

    async def update_patient(self, db, patient_id, data, current_user=None):
        return await self.update(db, patient_id, data.model_dump(exclude_unset=True) if hasattr(data, 'model_dump') else data)

    async def delete_patient(self, db, patient_id, current_user=None):
        return await self.delete(db, patient_id)

    async def list_patient_sessions(self, db, patient_id, cursor=None, limit=20):
        return await self.get_sessions(db, patient_id=patient_id, cursor=cursor, limit=limit)

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
        """Router-facing alias. Extra filters (status/date_from/date_to) are
        accepted for API compatibility but not yet applied — the frontend
        detail page doesn't pass them today."""
        return await self.get_sessions(
            db, patient_id=patient_id, cursor=cursor, limit=limit
        )
