"""Real SQL acceptance: scoped counts, local midnight, pagination and bounded queries."""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import json
from sqlalchemy import event, text
from app.models.session import Session
from app.models.soap_report import SOAPReport
from app.models.notification import Notification
from app.models.enums import SessionStatus, ReportStatus, ReviewStatus, NotificationType
from app.services.dashboard_service import DashboardService
from app.services.report_service import ReportService
from app.services.notification_service import NotificationService
from app.websocket.dashboard_handler import broadcast_queue_and_stats
from tests.integration.conftest import requires_db, run_with_session
from tests.integration.test_authz_scoping_pg import _seed_two_tenants, _cleanup, _doctor

pytestmark = requires_db


@pytest.mark.parametrize("row_count", [1001, 10001])
def test_large_calendar_reports_notifications_and_broadcast(monkeypatch, tmp_path, row_count):
    async def body(db):
        a, b, cc = await _seed_two_tenants(db)
        start = datetime(2026, 10, 1, tzinfo=timezone(timedelta(hours=8)))
        statements = []
        def record(_conn, _cursor, statement, _params, _context, _many):
            statements.append(statement)
        event.listen(db.bind.sync_engine, 'before_cursor_execute', record)
        try:
            rows = [Session(id=uuid4(), patient_id=a.patient.id, doctor_id=a.user.id,
                            chief_complaint_id=cc.id, status=SessionStatus.COMPLETED,
                            created_at=start + timedelta(seconds=i), duration_seconds=60)
                    for i in range(row_count)]
            db.add_all(rows)
            await db.flush()
            db.add_all([SOAPReport(session_id=row.id, status=ReportStatus.GENERATED,
                                  review_status=ReviewStatus.PENDING if i < 120 else ReviewStatus.APPROVED,
                                  created_at=start)
                        for i, row in enumerate(rows[:150])])
            db.add_all([Notification(user_id=a.user.id, type=NotificationType.SYSTEM,
                                     title='synthetic', is_read=i % 2 == 0)
                        for i in range(row_count)])
            await db.flush()
            boundaries = [start + timedelta(days=i) for i in range(32)]
            statements.clear()
            calendar = await DashboardService.get_calendar_summary(db, _doctor(a.user.id), boundaries)
            assert len(statements) == 1
            assert dict(calendar[0])['total'] == row_count
            assert dict(calendar[0])['busy_seconds'] == row_count * 60
            assert dict(calendar[0])['day_index'] == 0  # UTC is still September 30.
            other = await DashboardService.get_calendar_summary(db, _doctor(b.user.id), boundaries)
            assert not any(row['total'] >= row_count for row in other)
            reports = await ReportService.list_reports(db, current_user=_doctor(a.user.id),
                date_from=start.isoformat(), date_to=start.isoformat(), review_status='pending', limit=20)
            assert len(reports['data']) == 20
            assert reports['pagination']['total_count'] == 120
            assert reports['review_counts'] == {'pending': 120, 'approved': 30}
            statements.clear()
            notifications = await NotificationService.list_notifications(db, a.user.id, limit=20, is_read=False)
            assert len(statements) == 2  # page + both counts, independent of row count
            assert notifications['pagination']['total_count'] == row_count // 2
            assert notifications['unread_count'] == row_count // 2
            assert len(notifications['data']) == 20
            await db.execute(text('ANALYZE notifications'))
            plan = (await db.execute(text('EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) SELECT id FROM notifications WHERE user_id = :user ORDER BY created_at DESC, id DESC LIMIT 20'), {'user': a.user.id})).scalar()
            (tmp_path / f'notification-plan-{row_count}.json').write_text(json.dumps(plan, indent=2))
            assert 'ix_notifications_user_created_id' in json.dumps(plan)
            # Query count and no unused queue details in the broadcast path.
            from app.websocket import dashboard_handler as handler
            monkeypatch.setattr(handler.manager, 'broadcast_queue_updated', AsyncMock())
            monkeypatch.setattr(handler.manager, 'broadcast_stats_updated', AsyncMock())
            statements.clear()
            await broadcast_queue_and_stats(db, AsyncMock())
            assert len(statements) == 2
            handler.manager.broadcast_queue_updated.assert_awaited_once()
            assert handler.manager.broadcast_queue_updated.call_args.kwargs['queue'] == []
            summary = await DashboardService.get_monthly_summary(db, current_user=_doctor(a.user.id), month='2026-10')
            assert summary.total_sessions >= 1  # original tenant fixture in this month
            assert all('intake_data' not in sql for sql in statements)
        finally:
            db.expunge_all()  # Keep committed seed IDs available for cleanup after rollback.
            await db.rollback()  # synthetic bulk rows were deliberately never committed
            event.remove(db.bind.sync_engine, 'before_cursor_execute', record)
            await _cleanup(db, a, b, cc)
    run_with_session(body)


def test_calendar_http_contract_dst_duration_and_deleted_rows():
    """Exercise actual response validation and authorization, including a 23-hour day."""
    from zoneinfo import ZoneInfo
    from httpx import AsyncClient, ASGITransport
    from app.main import app
    from app.core.dependencies import get_db, get_current_user
    from app.models.enums import UserRole
    from types import SimpleNamespace

    async def body(db):
        a, b, cc = await _seed_two_tenants(db)
        zone = ZoneInfo('America/New_York')
        start = datetime(2026, 3, 8, tzinfo=zone)
        boundaries = [start, datetime(2026, 3, 9, tzinfo=zone), datetime(2026, 3, 10, tzinfo=zone)]
        rows = [Session(patient_id=a.patient.id, doctor_id=a.user.id, chief_complaint_id=cc.id,
                        status=SessionStatus.COMPLETED, created_at=start,
                        started_at=start, completed_at=start + timedelta(seconds=10.9),
                        duration_seconds=-1, is_deleted=deleted) for deleted in (False, True)]
        db.add_all(rows)
        await db.flush()
        old = dict(app.dependency_overrides)
        async def database(): yield db
        app.dependency_overrides[get_db] = database
        app.dependency_overrides[get_current_user] = lambda: _doctor(a.user.id)
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
                params = [('day_starts', day.isoformat()) for day in boundaries]
                response = await client.get('/api/v1/dashboard/calendar', params=params)
                assert response.status_code == 200, response.text
                assert response.json()[0]['total'] == 1
                assert response.json()[0]['busy_seconds'] == 10  # floor fractional seconds, fall back from invalid duration
                app.dependency_overrides[get_current_user] = lambda: _doctor(b.user.id)
                assert (await client.get('/api/v1/dashboard/calendar', params=params)).json() == []
                app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=a.user.id, role=UserRole.PATIENT)
                assert (await client.get('/api/v1/dashboard/calendar', params=params)).status_code == 403
                app.dependency_overrides[get_current_user] = lambda: _doctor(a.user.id)
                assert (await client.get('/api/v1/dashboard/calendar', params={'day_starts': '2026-10-01'})).status_code == 422
        finally:
            app.dependency_overrides.clear()
            app.dependency_overrides.update(old)
            db.expunge_all()
            await db.rollback()
            await _cleanup(db, a, b, cc)
    run_with_session(body)
