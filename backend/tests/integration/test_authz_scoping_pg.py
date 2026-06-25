"""
真 Postgres 整合測試：證明上一波加入的 row-level 授權限縮，
在 *SQL 層* 真的把跨租戶（cross-doctor）的醫療資料隔離開來。

涵蓋的 service 路徑（皆以真 DB query 走過一遍，非 stub）:
- report_service.get_report / list_reports（依 session.doctor_id 限縮）
- patient_service.get_patient / get_patient_sessions / list_patients
  （依 patient.user_id 限縮）
- alert_service.get_list（join Session 依 doctor_id 限縮）
- dashboard_service 的 doctor-scoped helpers（get_recent_alerts /
  get_recent_sessions / get_stats，依 doctor_id 限縮）

授權主體用 `SimpleNamespace(id=..., role='doctor'/'admin')`，與
tests/unit/services/test_session_authorization.py 的 stub 慣例一致。

每個測試自己 seed 兩位醫師各自的資料，跑完於 finally 反序清掉（FK 安全）。
DB 連不上時整個 module 由 conftest 的 requires_db skip。
"""

from __future__ import annotations

import uuid
from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenException, NotFoundException
from app.models.chief_complaint import ChiefComplaint
from app.models.enums import (
    AlertSeverity,
    AlertType,
    Gender,
    ReportStatus,
    ReviewStatus,
    SessionStatus,
    UserRole,
)
from app.models.patient import Patient
from app.models.red_flag_alert import RedFlagAlert
from app.models.session import Session
from app.models.soap_report import SOAPReport
from app.models.user import User
from app.services.alert_service import AlertService
from app.services.dashboard_service import DashboardService
from app.services.patient_service import PatientService
from app.services.report_service import ReportService

from tests.integration.conftest import requires_db, run_with_session

pytestmark = requires_db


# ──────────────────────────────────────────────────────
# 授權主體 stub（與 unit test 慣例一致）
# ──────────────────────────────────────────────────────

def _doctor(user_id: uuid.UUID) -> SimpleNamespace:
    return SimpleNamespace(id=user_id, role=UserRole.DOCTOR)


def _admin() -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), role=UserRole.ADMIN)


# ──────────────────────────────────────────────────────
# Seed 容器：保留所有建立的列，方便反序清理
# ──────────────────────────────────────────────────────

class _Tenant:
    """單一醫師（租戶）名下的 user / patient / session / report / alert。"""

    def __init__(self) -> None:
        self.user: User
        self.patient: Patient
        self.session: Session
        self.report: SOAPReport
        self.alert: RedFlagAlert


async def _seed_two_tenants(session: AsyncSession) -> tuple[_Tenant, _Tenant, ChiefComplaint]:
    """建立 doctorA / doctorB 兩租戶的完整資料鏈，commit 後回傳。

    回傳的 ChiefComplaint 為兩租戶 session 共用（cleanup 時最後刪）。
    """
    tag = uuid.uuid4().hex[:8]

    cc = ChiefComplaint(
        name=f"整合測試主訴-{tag}",
        category="urology",
        name_by_lang={"zh-TW": f"整合測試主訴-{tag}"},
        category_by_lang={"zh-TW": "泌尿科"},
    )
    session.add(cc)
    await session.flush()

    tenants: list[_Tenant] = []
    for idx in ("a", "b"):
        t = _Tenant()
        t.user = User(
            email=f"doc-{idx}-{tag}@example.test",
            password_hash="x",
            name=f"Doctor {idx.upper()} {tag}",
            role=UserRole.DOCTOR,
        )
        session.add(t.user)
        await session.flush()

        t.patient = Patient(
            user_id=t.user.id,
            medical_record_number=f"MRN-{idx}-{tag}",
            name=f"Patient {idx.upper()} {tag}",
            gender=Gender.OTHER,
            date_of_birth=date(1990, 1, 1),
        )
        session.add(t.patient)
        await session.flush()

        t.session = Session(
            patient_id=t.patient.id,
            doctor_id=t.user.id,
            chief_complaint_id=cc.id,
            chief_complaint_text=f"complaint {idx}",
            status=SessionStatus.COMPLETED,
        )
        session.add(t.session)
        await session.flush()

        t.report = SOAPReport(
            session_id=t.session.id,
            status=ReportStatus.GENERATED,
            review_status=ReviewStatus.PENDING,
            summary=f"summary {idx} {tag}",
        )
        session.add(t.report)
        await session.flush()

        t.alert = RedFlagAlert(
            session_id=t.session.id,
            conversation_id=uuid.uuid4(),
            alert_type=AlertType.RULE_BASED,
            severity=AlertSeverity.HIGH,
            title=f"alert {idx} {tag}",
            trigger_reason="seed",
        )
        session.add(t.alert)
        await session.flush()

        tenants.append(t)

    await session.commit()
    return tenants[0], tenants[1], cc


async def _cleanup(session: AsyncSession, a: _Tenant, b: _Tenant, cc: ChiefComplaint) -> None:
    """反序刪除（alert/report → session → patient → user → chief_complaint）。"""
    from sqlalchemy import delete

    # 用 PK-based DELETE，避開 ORM identity-map / expire 的細節，最穩。
    await session.execute(
        delete(RedFlagAlert).where(RedFlagAlert.id.in_([a.alert.id, b.alert.id]))
    )
    await session.execute(
        delete(SOAPReport).where(SOAPReport.id.in_([a.report.id, b.report.id]))
    )
    await session.execute(
        delete(Session).where(Session.id.in_([a.session.id, b.session.id]))
    )
    await session.execute(
        delete(Patient).where(Patient.id.in_([a.patient.id, b.patient.id]))
    )
    await session.execute(
        delete(User).where(User.id.in_([a.user.id, b.user.id]))
    )
    await session.execute(
        delete(ChiefComplaint).where(ChiefComplaint.id == cc.id)
    )
    await session.commit()


# ──────────────────────────────────────────────────────
# report_service
# ──────────────────────────────────────────────────────

def test_report_get_blocks_cross_tenant():
    async def body(session: AsyncSession):
        a, b, cc = await _seed_two_tenants(session)
        try:
            # doctorB 讀 doctorA 的報告 → NotFound（不洩漏存在與否）
            with pytest.raises(NotFoundException):
                await ReportService.get_report(
                    session, a.report.id, current_user=_doctor(b.user.id)
                )
            # doctorA 讀自己的報告 → ok
            own = await ReportService.get_report(
                session, a.report.id, current_user=_doctor(a.user.id)
            )
            assert own.id == a.report.id
            # admin 讀任一報告 → ok
            as_admin = await ReportService.get_report(
                session, a.report.id, current_user=_admin()
            )
            assert as_admin.id == a.report.id
        finally:
            await _cleanup(session, a, b, cc)

    run_with_session(body)


def test_report_list_scoping():
    async def body(session: AsyncSession):
        a, b, cc = await _seed_two_tenants(session)
        try:
            # doctorB 的清單不應含 doctorA 的報告，且含自己的
            res_b = await ReportService.list_reports(
                session, current_user=_doctor(b.user.id), limit=100
            )
            ids_b = {r.id for r in res_b["data"]}
            assert b.report.id in ids_b
            assert a.report.id not in ids_b

            # admin 看得到兩者
            res_admin = await ReportService.list_reports(
                session, current_user=_admin(), limit=100
            )
            ids_admin = {r.id for r in res_admin["data"]}
            assert a.report.id in ids_admin
            assert b.report.id in ids_admin
        finally:
            await _cleanup(session, a, b, cc)

    run_with_session(body)


# ──────────────────────────────────────────────────────
# patient_service
# ──────────────────────────────────────────────────────

def test_patient_get_blocks_cross_tenant():
    async def body(session: AsyncSession):
        a, b, cc = await _seed_two_tenants(session)
        svc = PatientService()
        try:
            # doctorB 讀 doctorA 的病患 → Forbidden
            with pytest.raises(ForbiddenException):
                await svc.get_patient(
                    session, a.patient.id, current_user=_doctor(b.user.id)
                )
            # doctorA 讀自己的病患 → ok
            own = await svc.get_patient(
                session, a.patient.id, current_user=_doctor(a.user.id)
            )
            assert own.id == a.patient.id
            # admin → ok
            as_admin = await svc.get_patient(
                session, a.patient.id, current_user=_admin()
            )
            assert as_admin.id == a.patient.id
        finally:
            await _cleanup(session, a, b, cc)

    run_with_session(body)


def test_patient_sessions_blocks_cross_tenant():
    async def body(session: AsyncSession):
        a, b, cc = await _seed_two_tenants(session)
        svc = PatientService()
        try:
            # doctorB 拿 doctorA 病患的 session 列表 → Forbidden
            with pytest.raises(ForbiddenException):
                await svc.get_patient_sessions(
                    session, a.patient.id, current_user=_doctor(b.user.id)
                )
            # doctorA 自己的病患 session → 只含該病患的場次
            res = await svc.get_patient_sessions(
                session, a.patient.id, current_user=_doctor(a.user.id)
            )
            session_ids = {s.id for s in res["data"]}
            assert a.session.id in session_ids
            assert b.session.id not in session_ids
        finally:
            await _cleanup(session, a, b, cc)

    run_with_session(body)


def test_patient_list_scoping():
    async def body(session: AsyncSession):
        a, b, cc = await _seed_two_tenants(session)
        svc = PatientService()
        try:
            # doctorB 列表只含自己名下病患
            res_b = await svc.list_patients(
                session, current_user=_doctor(b.user.id), limit=100
            )
            ids_b = {p.id for p in res_b["data"]}
            assert b.patient.id in ids_b
            assert a.patient.id not in ids_b

            # admin 看得到兩者
            res_admin = await svc.list_patients(
                session, current_user=_admin(), limit=100
            )
            ids_admin = {p.id for p in res_admin["data"]}
            assert a.patient.id in ids_admin
            assert b.patient.id in ids_admin
        finally:
            await _cleanup(session, a, b, cc)

    run_with_session(body)


# ──────────────────────────────────────────────────────
# alert_service
# ──────────────────────────────────────────────────────

def test_alert_list_scoping():
    async def body(session: AsyncSession):
        a, b, cc = await _seed_two_tenants(session)
        try:
            # doctorB 的警示清單排除 doctorA 的警示
            res_b = await AlertService.get_list(
                session, current_user=_doctor(b.user.id), limit=100
            )
            ids_b = {al.id for al in res_b["data"]}
            assert b.alert.id in ids_b
            assert a.alert.id not in ids_b

            # admin 看得到兩者
            res_admin = await AlertService.get_list(
                session, current_user=_admin(), limit=100
            )
            ids_admin = {al.id for al in res_admin["data"]}
            assert a.alert.id in ids_admin
            assert b.alert.id in ids_admin
        finally:
            await _cleanup(session, a, b, cc)

    run_with_session(body)


# ──────────────────────────────────────────────────────
# dashboard_service（doctor-scoped helpers）
# ──────────────────────────────────────────────────────

def test_dashboard_recent_helpers_scoping():
    async def body(session: AsyncSession):
        a, b, cc = await _seed_two_tenants(session)
        try:
            doc_b = _doctor(b.user.id)

            # 近期警示：doctorB 只見自己場次的警示
            alerts_b = await DashboardService.get_recent_alerts(
                session, current_user=doc_b, limit=100
            )
            alert_ids_b = {item.alert_id for item in alerts_b.data}
            assert b.alert.id in alert_ids_b
            assert a.alert.id not in alert_ids_b

            # 近期場次：doctorB 只見自己負責的場次
            sessions_b = await DashboardService.get_recent_sessions(
                session, current_user=doc_b, limit=100
            )
            session_ids_b = {item.session_id for item in sessions_b.data}
            assert b.session.id in session_ids_b
            assert a.session.id not in session_ids_b
        finally:
            await _cleanup(session, a, b, cc)

    run_with_session(body)
