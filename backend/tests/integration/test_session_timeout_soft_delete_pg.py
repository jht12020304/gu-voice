"""真 Postgres：被軟刪除的 in_progress 場次不得被逾時清理任務取消或廣播。

延伸 ``test_soft_deleted_session_invisible_pg.py`` 的清單：逾時任務是 Celery 那條
讀取 Session 的路徑（CLAUDE.md：「新讀取路徑要自己加進那支測試」）。
"""

from __future__ import annotations

from datetime import timedelta
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.enums import SessionStatus
from app.models.session import Session
from app.tasks import session_timeout as st
from app.utils.datetime_utils import utc_now
from tests.integration.conftest import make_engine, requires_db, run_with_session
from tests.integration.test_authz_scoping_pg import _cleanup, _seed_two_tenants

pytestmark = requires_db


def test_timeout_task_skips_soft_deleted_sessions(monkeypatch):
    events: list = []

    async def _fake_publish(event_type, payload=None):
        events.append((event_type, payload or {}))

    async def _fake_queue_stats(db, redis):
        events.append(("queue_and_stats", None))

    import app.core.database as db_mod
    import app.websocket.connection_manager as cm_mod
    import app.websocket.dashboard_handler as dh_mod

    monkeypatch.setattr(cm_mod, "publish_dashboard_event", _fake_publish)
    monkeypatch.setattr(dh_mod, "broadcast_queue_and_stats", _fake_queue_stats)

    async def body(session: AsyncSession):
        a, b, cc = await _seed_two_tenants(session)
        stale = utc_now() - timedelta(minutes=st.SESSION_TIMEOUT_MINUTES + 10)
        deleted = Session(
            id=uuid.uuid4(), patient_id=a.patient.id, doctor_id=a.user.id,
            chief_complaint_id=cc.id, status=SessionStatus.IN_PROGRESS,
            created_at=stale, updated_at=stale, is_deleted=True,
        )
        live = Session(
            id=uuid.uuid4(), patient_id=a.patient.id, doctor_id=a.user.id,
            chief_complaint_id=cc.id, status=SessionStatus.IN_PROGRESS,
            created_at=stale, updated_at=stale,
        )
        session.add_all([deleted, live])
        await session.commit()
        try:
            engine = make_engine()
            factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            monkeypatch.setattr(db_mod, "async_session_factory", factory)
            try:
                result = await st._async_check()
            finally:
                await engine.dispose()

            rows = (await session.execute(
                select(Session.id, Session.status).where(Session.id.in_([deleted.id, live.id]))
            )).all()
            status = {rid: s for rid, s in rows}
            assert status[deleted.id] == SessionStatus.IN_PROGRESS, "軟刪除場次被逾時任務取消"
            assert status[live.id] == SessionStatus.CANCELLED, "未刪除的逾時場次應被取消"
            broadcast_ids = {
                str(p.get("session_id")) for t, p in events if t == "session_status_changed"
            }
            assert str(deleted.id) not in broadcast_ids, "軟刪除場次被廣播回儀表板"
            assert result.get("timed_out") == 1
        finally:
            await session.execute(
                Session.__table__.delete().where(Session.id.in_([deleted.id, live.id]))
            )
            await session.commit()
            await _cleanup(session, a, b, cc)

    run_with_session(body)
