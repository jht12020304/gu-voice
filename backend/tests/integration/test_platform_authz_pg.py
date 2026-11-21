"""Platform access matrix against real SQL and in-process API routers, with synthetic identities."""
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from app.core.dependencies import get_current_user, get_db
from app.core.exceptions import register_exception_handlers
from app.core.security import hash_password
from app.models.audit_log import AuditLog
from app.models.chief_complaint import ChiefComplaint
from app.models.enums import AuditAction, Gender, NotificationType, SessionStatus, UserRole
from app.models.notification import Notification
from app.models.patient import Patient
from app.models.red_flag_rule import RedFlagRule
from app.models.session import Session
from app.models.user import User
from app.routers import admin, alerts, audit_logs, auth, notifications, research, sessions
from tests.integration.conftest import requires_db, run_with_session

pytestmark = requires_db
ROLES = [
    (UserRole.DOCTOR, None), (UserRole.ADMIN, "CLINICAL-1"),
    (UserRole.ADMIN, None), (UserRole.PATIENT, None),
    (UserRole.ADMIN, ""), (UserRole.ADMIN, "   "),
]


def account(role, license_number=None):
    return User(id=uuid4(), email=f"{uuid4()}@example.com", name="Fixture",
                role=role, license_number=license_number, department="Clinic",
                password_hash=hash_password("FixturePass9"))


def api(db, actor):
    app = FastAPI()
    for module in (admin, alerts, audit_logs, auth, notifications, research, sessions):
        app.include_router(module.router)
    register_exception_handlers(app)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: actor
    app.dependency_overrides[auth._get_optional_current_user] = lambda: actor
    return httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test/api/v1/")


@pytest.mark.parametrize("role,license_number", ROLES)
def test_account_and_rule_permissions(role, license_number, monkeypatch):
    register_token = AsyncMock()
    revoke = AsyncMock(return_value=1)
    monkeypatch.setattr("app.services.auth_service._register_refresh_token", register_token)
    monkeypatch.setattr("app.services.auth_service._revoke_all_refresh_tokens", revoke)
    monkeypatch.setattr("app.cache.redis_client.get_redis", AsyncMock())
    monkeypatch.setattr("app.core.rate_limit.enforce_register_ip_rate_limit", AsyncMock())

    async def body(db):
        actor, target = account(role, license_number), account(UserRole.ADMIN)
        db.add_all([actor, target])
        rule = RedFlagRule(name="Fixture", canonical_id=str(uuid4()), category="fixture",
                           severity="high", keywords=["fixture"], is_active=True)
        db.add(rule)
        await db.flush()
        allowed = role == UserRole.ADMIN and license_number is None
        async with api(db, actor) as client:
            # Compare persistent account/rule state and service audit writes. Production
            # middleware separately records denied requests and register attempts are rate-limited.
            create = {"email": f"{uuid4()}@example.com", "role": "admin",
                      "password": "FixturePass9", "name": "Fixture"}
            register_email = f"{uuid4()}@example.com"
            rule_body = {"name": f"rule-{uuid4()}", "category": "fixture", "keywords": ["fixture"], "severity": "high"}
            emails = [actor.email, target.email, create["email"], register_email]

            async def snapshot():
                queries = (
                    select(*User.__table__.columns).where(User.email.in_(emails)).order_by(User.id),
                    select(*RedFlagRule.__table__.columns).where(
                        (RedFlagRule.id == rule.id) | (RedFlagRule.name == rule_body["name"])
                    ).order_by(RedFlagRule.id),
                    select(AuditLog.id).where(AuditLog.user_id == actor.id).order_by(AuditLog.id),
                )
                return [(await db.execute(query)).all() for query in queries]

            before = await snapshot()
            for method, path, payload, success in [
                ("GET", "admin/users", None, 200),
                ("POST", "admin/users", create, 201),
                ("PUT", f"admin/users/{target.id}", {"role": "doctor", "license_number": "L1"}, 200),
                ("PUT", f"admin/users/{target.id}/toggle-active", None, 200),
                ("POST", f"admin/users/{target.id}/reset-password", None, 200),
                ("POST", "auth/register", {**create, "email": register_email}, 201),
                ("POST", "alerts/rules", rule_body, 201),
                ("PUT", f"alerts/rules/{rule.id}", {"name": "Updated"}, 200),
                ("DELETE", f"alerts/rules/{rule.id}", None, 200),
            ]:
                response = await client.request(method, path, json=payload)
                assert response.status_code == (success if allowed else 403), (path, response.text)
                if not allowed:
                    assert await snapshot() == before
                    register_token.assert_not_awaited()
                    revoke.assert_not_awaited()
                elif path == "auth/register":
                    assert str(register_token.await_args.args[1]) == response.json()["user"]["id"]
            if allowed:
                for blank in ("", "   "):
                    for method, path, payload in (
                        ("POST", "admin/users", create),
                        ("PUT", f"admin/users/{target.id}", {}),
                        ("POST", "auth/register", create),
                    ):
                        response = await client.request(method, path, json={**payload, "license_number": blank})
                        assert response.status_code == 422

            for payload in ({"role": "doctor"}, {"license_number": "CHANGE"}, {"is_active": False}):
                before = await snapshot()
                assert (await client.put(f"admin/users/{actor.id}", json=payload)).status_code == 403
                assert await snapshot() == before
            patient = await client.post("auth/register", json={**create, "email": f"{uuid4()}@example.com", "role": "patient"})
            assert patient.status_code == 201 and patient.json()["user"]["role"] == "patient"
            kiosk = await client.get("sessions/doctors")
            assert kiosk.status_code == 200
            assert all(set(row) == {"id", "name", "department"} for row in kiosk.json())
            change = await client.post("auth/change-password", json={"current_password": "FixturePass9", "new_password": "ChangedPass8"})
            assert change.status_code == 200

    run_with_session(body)


@pytest.mark.parametrize("role,license_number", ROLES)
def test_audit_and_research_scope(role, license_number):
    async def body(db):
        actor, other = account(role, license_number), account(UserRole.DOCTOR)
        db.add_all([actor, other])
        await db.flush()
        resource = str(uuid4())
        events = [AuditLog(user_id=uid, action=AuditAction.READ, resource_type=resource,
                           ip_address="192.0.2.1", user_agent="fixture", details={"i": i})
                  for i, uid in enumerate((actor.id, other.id, actor.id, None))]
        patient = Patient(user_id=other.id, name="Fixture", medical_record_number=resource,
                          gender=Gender.OTHER, date_of_birth=date(1980, 1, 1))
        complaint = ChiefComplaint(name=resource, category="fixture")
        db.add_all([*events, patient, complaint])
        await db.flush()
        day = date(2040, 5, 20)
        for doctor_id, status in ((actor.id, SessionStatus.COMPLETED), (other.id, SessionStatus.COMPLETED), (None, SessionStatus.CANCELLED)):
            db.add(Session(doctor_id=doctor_id, patient_id=patient.id, chief_complaint_id=complaint.id,
                           status=status, created_at=datetime(2040, 5, 20, tzinfo=timezone.utc)))
        await db.flush()
        async with api(db, actor) as client:
            query = {"resource_type": resource, "ip_address": "192.0.2.1"}
            listing = await client.get("audit-logs", params={**query, "limit": 1})
            analytics = await client.get("research/analytics", params={"date_from": day, "date_to": day})
            other_detail = await client.get(f"audit-logs/{events[1].id}")
            if role == UserRole.PATIENT or (license_number is not None and not license_number.strip()):
                assert listing.status_code == analytics.status_code == other_detail.status_code == 403
                return
            global_scope = role == UserRole.ADMIN and license_number is None
            permitted = events if global_scope else [events[0], events[2]]
            assert listing.status_code == 200
            page = listing.json()
            assert page["pagination"]["total_count"] == len(permitted)
            second = await client.get("audit-logs", params={**query, "cursor": page["pagination"]["next_cursor"]})
            assert second.json()["pagination"]["total_count"] == len(permitted)
            assert {row["id"] for row in page["data"] + second.json()["data"]} == {e.id for e in permitted}
            filtered = await client.get("audit-logs", params={**query, "user_id": str(other.id)})
            assert filtered.json()["pagination"]["total_count"] == int(global_scope)
            assert [row["id"] for row in filtered.json()["data"]] == ([events[1].id] if global_scope else [])
            assert (await client.get(f"audit-logs/{events[0].id}")).status_code == 200
            assert other_detail.status_code == (200 if global_scope else 404)
            assert (await client.get(f"audit-logs/{events[3].id}")).status_code == (200 if global_scope else 404)
            assert analytics.status_code == 200
            cohort = analytics.json()["cohort"]
            assert cohort["total_sessions"] == (3 if global_scope else 1)
            assert cohort["completed"] == (2 if global_scope else 1)
            assert cohort["completion"]["numerator"] == cohort["completed"]
            assert cohort["completion"]["denominator"] == cohort["total_sessions"]
    run_with_session(body)


def test_existing_clinical_inbox_text_is_masked_without_rewriting_rows():
    async def body(db):
        actor = account(UserRole.DOCTOR)
        actor.preferred_language = "en-US"
        db.add(actor)
        await db.flush()
        rows = []
        for kind, data in [
            (NotificationType.RED_FLAG, {"alert_id": str(uuid4())}),
            (NotificationType.SESSION_COMPLETE, {"session_id": str(uuid4())}),
            (NotificationType.REPORT_READY, {"report_id": str(uuid4())}),
            (NotificationType.SYSTEM, {"session_id": str(uuid4()), "status": "failed"}),
            (NotificationType.SYSTEM, {}),
        ]:
            row = Notification(user_id=actor.id, type=kind, data=data, title="Stored title", body="Stored detail")
            db.add(row)
            rows.append(row)
        await db.flush()
        async with api(db, actor) as client:
            result = await client.get("notifications")
            assert result.status_code == 200
            items = {item["id"]: item for item in result.json()["data"]}
            for row in rows[:-1]:
                item = items[str(row.id)]
                assert item["title"] != row.title and item["body"] != row.body
                assert item["data"] == row.data
            assert items[str(rows[-1].id)]["body"] == "Stored detail"
            for row in rows:
                await db.refresh(row)
                assert (row.title, row.body) == ("Stored title", "Stored detail")
    run_with_session(body)
