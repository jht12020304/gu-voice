"""真 Postgres：被 admin 軟刪除的問診場次，從**每一條**讀取路徑消失。

2026-08-23 拍板：admin 可刪除問答內容，做法是軟刪除（`sessions.is_deleted`），
醫療記錄不硬刪、誤刪救得回來。軟刪除的價值完全取決於「有沒有漏掉一條讀取路徑」
——漏一條，使用者以為刪掉的病歷內容就會從那裡漏回畫面。所以這支測試不是
「刪得掉嗎」，而是**逐條走過所有會回傳場次內容的 service 路徑**：

    session 詳情 / 清單（admin·doctor·patient 三種角色）/ 逐字稿
    SOAP 報告詳情 / 報告清單（含 admin——admin 也看不到，這不是 ownership）
    紅旗警示清單 / 單筆 / 未確認計數
    儀表板近期場次 / 近期警示 / 排隊
    病患自己的場次歷史
    研究分析母體

同一份斷言也釘住「沒被刪的那一場仍然看得到」——避免哪天有人用「全部濾掉」
的方式讓測試變綠。

Seed / cleanup 直接沿用 test_authz_scoping_pg 的兩租戶工具（同一份資料鏈，
沒必要抄第二份；那邊改了這邊自動跟著改）。
"""

from __future__ import annotations

from types import SimpleNamespace
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException, SessionNotFoundException
from app.models.audit_log import AuditLog
from app.models.enums import AuditAction, UserRole
from app.models.session import Session
from app.models.user import User
from app.services.alert_service import AlertService
from app.services.dashboard_service import DashboardService
from app.services.patient_service import PatientService
from app.services.report_service import ReportService
from app.services.research_service import ResearchService
from app.services.session_service import SessionService

from tests.integration.conftest import requires_db, run_with_session
from tests.integration.test_authz_scoping_pg import (
    _cleanup,
    _doctor,
    _seed_two_tenants,
)

pytestmark = requires_db


async def _real_admin(session: AsyncSession, tag: str) -> User:
    """建一個**真的**存在於 users 表的 admin。

    軟刪除會把 `deleted_by` 寫成操作者 id（FK → users.id），所以這裡不能用
    `SimpleNamespace` 假 id——那會撞 FK。稽核日誌的 user_id 也是同一個道理。
    """
    admin = User(
        email=f"admin-{tag}@example.test",
        password_hash="x",
        name=f"Admin {tag}",
        role=UserRole.ADMIN,
    )
    session.add(admin)
    await session.flush()
    await session.commit()
    return admin


def _patient_principal(user_id) -> SimpleNamespace:
    return SimpleNamespace(id=user_id, role=UserRole.PATIENT)


def test_soft_deleted_session_disappears_from_every_read_path():
    async def body(session: AsyncSession):
        a, b, cc = await _seed_two_tenants(session)
        tag = uuid.uuid4().hex[:8]
        admin = await _real_admin(session, tag)
        svc = SessionService()
        patient_svc = PatientService()
        try:
            # a 的病患是 a.user 名下的（seed 把 patient.user_id 設成醫師 user id），
            # 病患視角就用那個 user 當主體。
            patient_principal = _patient_principal(a.patient.user_id)

            # ── 刪之前：a.session 在各路徑都看得到（避免下面的斷言假通過）──
            before = await svc.get_session(
                session, a.session.id, current_user=admin
            )
            assert before.id == a.session.id
            analytics_before = await ResearchService().get_analytics(session)

            # ── 刪 ──────────────────────────────────────────
            deleted = await svc.soft_delete_session(
                session, a.session.id, current_user=admin
            )
            assert deleted.is_deleted is True
            assert deleted.deleted_at is not None
            assert deleted.deleted_by == admin.id

            # ── 1. 場次詳情：admin 與負責醫師都當它不存在 ──────
            for principal in (admin, _doctor(a.user.id)):
                with pytest.raises(SessionNotFoundException):
                    await svc.get_session(
                        session, a.session.id, current_user=principal
                    )

            # ── 2. 場次清單：三種角色都看不到，b 的那場仍在 ────
            for principal in (admin, _doctor(a.user.id), patient_principal):
                listed = await svc.list_sessions(
                    session, current_user=principal, limit=100
                )
                ids = {s.id for s in listed["data"]}
                assert a.session.id not in ids, f"{principal.role} 的場次清單仍看得到已刪場次"
            admin_ids = {
                s.id
                for s in (await svc.list_sessions(session, current_user=admin, limit=100))["data"]
            }
            assert b.session.id in admin_ids, "沒被刪的場次不該跟著消失"

            # ── 3. 逐字稿 ──────────────────────────────────
            with pytest.raises(SessionNotFoundException):
                await svc.get_conversations(
                    session, a.session.id, current_user=admin
                )

            # ── 4. SOAP 報告：詳情與清單（admin 也一樣）────────
            for principal in (admin, _doctor(a.user.id)):
                with pytest.raises(NotFoundException):
                    await ReportService.get_report(
                        session, a.report.id, current_user=principal
                    )
            reports = await ReportService.list_reports(
                session, current_user=admin, limit=100
            )
            report_ids = {r.id for r in reports["data"]}
            assert a.report.id not in report_ids
            assert b.report.id in report_ids

            # ── 5. 紅旗警示：清單 / 單筆 / 未確認計數 ──────────
            alerts = await AlertService.get_list(
                session, current_user=admin, limit=100
            )
            alert_ids = {al.id for al in alerts["data"]}
            assert a.alert.id not in alert_ids
            assert b.alert.id in alert_ids
            with pytest.raises(NotFoundException):
                await AlertService.get_by_id(
                    session, a.alert.id, current_user=admin
                )

            # ── 6. 儀表板：近期場次 / 近期警示 / 排隊 ──────────
            recent_sessions = await DashboardService.get_recent_sessions(
                session, current_user=admin, limit=100
            )
            assert a.session.id not in {i.session_id for i in recent_sessions.data}
            recent_alerts = await DashboardService.get_recent_alerts(
                session, current_user=admin, limit=100
            )
            assert a.alert.id not in {i.alert_id for i in recent_alerts.data}

            # ── 7. 病患自己的場次歷史 ─────────────────────────
            history = await patient_svc.get_patient_sessions(
                session, a.patient.id, current_user=_doctor(a.user.id)
            )
            assert a.session.id not in {s.id for s in history["data"]}

            # ── 8. 研究分析母體少一場（統計不該再算它）──────────
            analytics_after = await ResearchService().get_analytics(session)
            assert (
                analytics_after.cohort.total_sessions
                == analytics_before.cohort.total_sessions - 1
            )

            # ── 9. 稽核日誌留下「誰刪了哪一場」──────────────────
            log = (
                await session.execute(
                    select(AuditLog).where(
                        AuditLog.resource_type == "session",
                        AuditLog.resource_id == str(a.session.id),
                        AuditLog.action == AuditAction.DELETE,
                    )
                )
            ).scalars().all()
            assert len(log) == 1, "軟刪除必須留下且只留下一筆稽核日誌"
            assert log[0].user_id == admin.id
            assert log[0].details["patient_id"] == str(a.patient.id)

            # ── 10. 冪等：再刪一次不炸、不重複寫稽核 ─────────────
            again = await svc.soft_delete_session(
                session, a.session.id, current_user=admin
            )
            assert again.is_deleted is True
            log_again = (
                await session.execute(
                    select(AuditLog).where(
                        AuditLog.resource_type == "session",
                        AuditLog.resource_id == str(a.session.id),
                        AuditLog.action == AuditAction.DELETE,
                    )
                )
            ).scalars().all()
            assert len(log_again) == 1, "重複刪除不該再寫一筆稽核"

            # ── 11. 資料還在（軟刪除的意義）：row 與子表都沒被硬刪 ──
            row = (
                await session.execute(
                    select(Session).where(Session.id == a.session.id)
                )
            ).scalar_one_or_none()
            assert row is not None, "軟刪除不得真的刪掉 row"
        finally:
            await session.execute(
                AuditLog.__table__.delete().where(
                    AuditLog.resource_id == str(a.session.id)
                )
            )
            await session.commit()
            await _cleanup(session, a, b, cc)
            await session.execute(
                User.__table__.delete().where(User.id == admin.id)
            )
            await session.commit()

    run_with_session(body)
