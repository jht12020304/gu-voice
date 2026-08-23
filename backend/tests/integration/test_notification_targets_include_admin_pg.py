"""真 Postgres：未指派場次的通知 fan-out 要含 admin，不是只有 doctor。

2026-08-23：刪除問診的權限綁在 admin 角色上，所以「把一位醫師升成 admin」變成
日常操作。`_doctor_targets` 原本只 SELECT `role == doctor`，那個升級會讓當事人
從此收不到任何未指派場次的推播——**而且完全無聲**（沒有錯誤、沒有 log，只是
手機再也不響）。這支測試把「doctor + admin 都是收件人、停用者不是」釘死。

用真 DB 而不是 stub：既有的紅旗 fan-out 單元測試都用假 db（查詢回什麼由 stub
決定），角色過濾條件本身在那裡是測不到的——這條缺陷正好落在 stub 的盲區。
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import UserRole
from app.models.user import User
from app.services.notification_service import NotificationService

from tests.integration.conftest import requires_db, run_with_session

pytestmark = requires_db


def test_unassigned_session_fanout_includes_admins_and_skips_inactive():
    async def body(session: AsyncSession):
        tag = uuid.uuid4().hex[:8]
        doctor = User(
            email=f"fanout-doc-{tag}@example.test",
            password_hash="x",
            name=f"Doctor {tag}",
            role=UserRole.DOCTOR,
        )
        admin = User(
            email=f"fanout-admin-{tag}@example.test",
            password_hash="x",
            name=f"Admin {tag}",
            role=UserRole.ADMIN,
        )
        retired = User(
            email=f"fanout-retired-{tag}@example.test",
            password_hash="x",
            name=f"Retired {tag}",
            role=UserRole.DOCTOR,
            is_active=False,
        )
        patient_user = User(
            email=f"fanout-patient-{tag}@example.test",
            password_hash="x",
            name=f"Patient {tag}",
            role=UserRole.PATIENT,
        )
        session.add_all([doctor, admin, retired, patient_user])
        await session.commit()
        try:
            targets = await NotificationService._doctor_targets(
                session, None, str(uuid.uuid4())
            )
            assert doctor.id in targets, "在職醫師沒收到未指派場次的通知"
            assert admin.id in targets, (
                "admin 沒被列為收件人——升成 admin 的醫師會無聲地收不到推播"
            )
            assert retired.id not in targets, "停用帳號不該收到通知"
            assert patient_user.id not in targets, "病患不該收到醫師端通知"

            # 有指派醫師時只發給他（既有語意不變）
            assigned = await NotificationService._doctor_targets(
                session, doctor.id, str(uuid.uuid4())
            )
            assert assigned == [doctor.id]
        finally:
            await session.execute(
                User.__table__.delete().where(
                    User.id.in_([doctor.id, admin.id, retired.id, patient_user.id])
                )
            )
            await session.commit()

    run_with_session(body)
