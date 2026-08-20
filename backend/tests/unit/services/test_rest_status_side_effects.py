"""EM-2 / D-8：REST 狀態轉移的附帶效應（不變式 #20「終態六件事」）。

`PUT /sessions/{id}/status` 以前是所有終態路徑裡最空的一條——六件事只做了
「改 status」一件：**不派 SOAP、不廣播 dashboard、不建任何通知**。後果：
- 醫師端排隊清單留著一筆早已 completed 的場次（沒有 `session_status_changed`、
  沒有 queue/stats 刷新），要等下一個不相干的事件才會被動更新；
- `soap_reports` 永遠沒有那一列（違反不變式 #20「每一個終態都要有 SOAP」），
  醫師端等不到報告。

`POST /sessions/{id}/end-for-language-switch`（切語言收場次 → cancelled）同樣
一則 dashboard 事件都沒有（D-8），與 P7 的逾時 cancelled 路徑不對稱。

架構限制（病患端 WS 通知）記載在 `session_service._after_status_transition`
的 docstring 第 3 點，`test_terminal_path_six_things_matrix.py` 會檢查那段註解
還在。
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Optional

import pytest

from app.models.enums import SessionStatus, UserRole
from app.services.session_service import SessionService


def _run(coro):
    return asyncio.run(coro)


@dataclass
class _FakeSession:
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    patient_id: uuid.UUID = field(default_factory=uuid.uuid4)
    doctor_id: Optional[uuid.UUID] = None
    status: SessionStatus = SessionStatus.IN_PROGRESS
    language: str = "zh-TW"
    started_at: Any = None
    completed_at: Any = None
    updated_at: Any = None
    duration_seconds: Optional[int] = None
    previous_status: Any = None


@dataclass
class _FakeUser:
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    role: UserRole = UserRole.ADMIN
    preferred_language: Optional[str] = None
    updated_at: Any = None


class _FakeDB:
    def __init__(self, user: Any = None) -> None:
        self._user = user
        self.flushed = 0
        self.commits = 0

    async def execute(self, stmt: Any):
        return SimpleNamespace(scalar_one_or_none=lambda: self._user)

    async def flush(self) -> None:
        self.flushed += 1

    async def commit(self) -> None:
        self.commits += 1


class _CaptureManager:
    def __init__(self) -> None:
        self.localized_dashboard_calls: list[dict[str, Any]] = []

    async def broadcast_localized_dashboard(
        self, msg_type, code, params=None, severity="info", extra=None
    ) -> None:
        self.localized_dashboard_calls.append(
            {
                "msg_type": msg_type,
                "code": code,
                "severity": severity,
                "extra": extra or {},
            }
        )


@pytest.fixture
def wiring(monkeypatch):
    """把 `_after_status_transition` 會碰到的四個外部依賴全部換成 spy。

    它們都是**函式內 lazy import**，所以必須 patch 在來源模組上。
    """
    import app.cache.redis_client as redis_client
    import app.websocket.conversation_handler as ch
    import app.websocket.dashboard_handler as dash
    from app.services import audit_log_service as als
    from app.services import session_service as ss
    from app.websocket import connection_manager as cm

    cap = _CaptureManager()
    monkeypatch.setattr(cm, "manager", cap)

    soap_calls: list[str] = []

    async def _soap(*, session_id: str) -> None:
        soap_calls.append(session_id)

    monkeypatch.setattr(ch, "_generate_soap_report_async", _soap)

    queue_calls: list[Any] = []

    async def _queue(db, redis) -> None:
        queue_calls.append(db)

    monkeypatch.setattr(dash, "broadcast_queue_and_stats", _queue)

    class _FakeRedis:
        def __init__(self) -> None:
            self.hset_calls: list[tuple[str, str, Any]] = []

        async def hset(self, key, field, value):
            self.hset_calls.append((key, field, value))
            return 1

        async def expire(self, key, ttl):
            return True

    fake_redis = _FakeRedis()

    async def _get_redis():
        return fake_redis

    monkeypatch.setattr(redis_client, "get_redis", _get_redis)

    audit_calls: list[dict[str, Any]] = []

    async def _log(db, **kwargs):
        audit_calls.append(kwargs)
        return SimpleNamespace(**kwargs)

    monkeypatch.setattr(als.AuditLogService, "log", _log)

    notif_calls: list[dict[str, Any]] = []

    async def _notify_complete(db, *, session_id, doctor_id, patient_id):
        notif_calls.append({"session_id": session_id, "doctor_id": doctor_id})
        return SimpleNamespace(id=uuid.uuid4())

    from app.services import notification_service as ns

    monkeypatch.setattr(
        ns.NotificationService, "notify_session_complete", _notify_complete
    )

    async def _no_auth(db, session, current_user):
        return None

    monkeypatch.setattr(ss, "_authorize_session_access", _no_auth)

    return SimpleNamespace(
        dashboard=cap,
        soap_calls=soap_calls,
        queue_calls=queue_calls,
        redis=fake_redis,
        audit_calls=audit_calls,
        notif_calls=notif_calls,
    )


def _install_get_by_id(monkeypatch, session: _FakeSession) -> None:
    async def _fake(db, session_id):
        return session

    monkeypatch.setattr(SessionService, "get_by_id", staticmethod(_fake))


def _dashboard_events(wiring, status: str) -> list[dict[str, Any]]:
    return [
        c
        for c in wiring.dashboard.localized_dashboard_calls
        if c["msg_type"] == "session_status_changed"
        and c["extra"].get("status") == status
    ]


# ── EM-2：PUT /status → completed ──────────────────────────
def test_rest_completed_dispatches_soap(monkeypatch, wiring):
    session = _FakeSession(status=SessionStatus.IN_PROGRESS)
    _install_get_by_id(monkeypatch, session)
    db = _FakeDB()

    _run(
        SessionService().update_status(
            db,
            session_id=session.id,
            new_status=SessionStatus.COMPLETED,
            current_user=_FakeUser(),
        )
    )

    assert wiring.soap_calls == [str(session.id)], (
        "REST 把場次標成 completed 卻沒派 SOAP —— 違反不變式 #20"
        "「每一個終態都要有 SOAP」，醫師端永遠等不到報告"
    )


def test_rest_completed_broadcasts_dashboard_and_queue(monkeypatch, wiring):
    session = _FakeSession(status=SessionStatus.IN_PROGRESS)
    _install_get_by_id(monkeypatch, session)

    _run(
        SessionService().update_status(
            _FakeDB(),
            session_id=session.id,
            new_status=SessionStatus.COMPLETED,
            current_user=_FakeUser(),
        )
    )

    events = _dashboard_events(wiring, "completed")
    assert events, "REST completed 沒廣播 dashboard session_status_changed"
    assert events[0]["extra"]["sessionId"] == str(session.id)
    assert events[0]["extra"]["previousStatus"] == "in_progress"
    assert wiring.queue_calls, "REST completed 沒刷新 queue/stats"


def test_rest_completed_refreshes_redis_state_cache(monkeypatch, wiring):
    session = _FakeSession(status=SessionStatus.IN_PROGRESS)
    _install_get_by_id(monkeypatch, session)

    _run(
        SessionService().update_status(
            _FakeDB(),
            session_id=session.id,
            new_status=SessionStatus.COMPLETED,
            current_user=_FakeUser(),
        )
    )

    assert wiring.redis.hset_calls, "REST 轉移後沒更新 Redis 場次狀態快取"
    key, field, value = wiring.redis.hset_calls[0]
    # key 格式與 WS `_update_session_status` 共用同一份常數（不得各寫一份字面值）
    assert key == f"gu:session:{session.id}:state"
    assert (field, value) == ("status", "completed")


def test_rest_side_effects_run_after_commit(monkeypatch, wiring):
    """SOAP / 廣播必須在 commit 之後：Celery 在另一個連線讀場次，
    未 commit 的話它撈到的還是 in_progress。"""
    session = _FakeSession(status=SessionStatus.IN_PROGRESS)
    _install_get_by_id(monkeypatch, session)
    db = _FakeDB()

    order: list[str] = []
    real_commit = db.commit

    async def _commit():
        order.append("commit")
        await real_commit()

    db.commit = _commit  # type: ignore[method-assign]

    import app.websocket.conversation_handler as ch

    async def _soap(*, session_id: str) -> None:
        order.append("soap")

    monkeypatch.setattr(ch, "_generate_soap_report_async", _soap)

    _run(
        SessionService().update_status(
            db,
            session_id=session.id,
            new_status=SessionStatus.COMPLETED,
            current_user=_FakeUser(),
        )
    )

    assert order == ["commit", "soap"], f"附帶效應早於 commit：{order}"


def test_rest_completed_notifies_assigned_doctor(monkeypatch, wiring):
    """六件事第 5 件：已指派醫師時建 SESSION_COMPLETE 通知（與 WS 端同判準）。"""
    doctor_id = uuid.uuid4()
    session = _FakeSession(status=SessionStatus.IN_PROGRESS, doctor_id=doctor_id)
    _install_get_by_id(monkeypatch, session)

    _run(
        SessionService().update_status(
            _FakeDB(),
            session_id=session.id,
            new_status=SessionStatus.COMPLETED,
            current_user=_FakeUser(),
        )
    )
    assert wiring.notif_calls == [
        {"session_id": session.id, "doctor_id": doctor_id}
    ], "REST completed 沒建醫師通知"


def test_rest_completed_without_doctor_creates_no_notification(monkeypatch, wiring):
    """院內 kiosk 場次恆無指派醫師 → no-op（不得憑空 fan-out 給全體醫師）。"""
    session = _FakeSession(status=SessionStatus.IN_PROGRESS, doctor_id=None)
    _install_get_by_id(monkeypatch, session)

    _run(
        SessionService().update_status(
            _FakeDB(),
            session_id=session.id,
            new_status=SessionStatus.COMPLETED,
            current_user=_FakeUser(),
        )
    )
    assert wiring.notif_calls == []


# ── cancelled：對齊 P7 政策（廣播、無 SOAP）─────────────────
def test_rest_cancelled_broadcasts_but_does_not_dispatch_soap(monkeypatch, wiring):
    session = _FakeSession(status=SessionStatus.IN_PROGRESS)
    _install_get_by_id(monkeypatch, session)

    _run(
        SessionService().update_status(
            _FakeDB(),
            session_id=session.id,
            new_status=SessionStatus.CANCELLED,
            current_user=_FakeUser(),
        )
    )

    assert _dashboard_events(wiring, "cancelled"), "cancelled 沒廣播 dashboard"
    assert wiring.soap_calls == [], (
        "cancelled 派了 SOAP —— 與 P7（逾時 cancelled 無報告）的既有政策不一致；"
        "要改政策請連 tasks/session_timeout 一起改"
    )


def test_rest_aborted_red_flag_dispatches_soap(monkeypatch, wiring):
    """醫師/admin 手動標紅旗中止也是終態 → 一樣要有報告。"""
    session = _FakeSession(status=SessionStatus.IN_PROGRESS)
    _install_get_by_id(monkeypatch, session)

    _run(
        SessionService().update_status(
            _FakeDB(),
            session_id=session.id,
            new_status=SessionStatus.ABORTED_RED_FLAG,
            current_user=_FakeUser(role=UserRole.DOCTOR),
        )
    )

    assert wiring.soap_calls == [str(session.id)]
    events = _dashboard_events(wiring, "aborted_red_flag")
    assert events and events[0]["severity"] == "critical"


def test_rest_in_progress_refreshes_queue_without_status_changed(monkeypatch, wiring):
    """非終態轉移只刷 queue/stats：現有 canonical code 沒有「REST 轉 in_progress」
    的語意（`ws_connected` 是假話），刻意不送 session_status_changed。"""
    session = _FakeSession(status=SessionStatus.WAITING)
    _install_get_by_id(monkeypatch, session)

    _run(
        SessionService().update_status(
            _FakeDB(),
            session_id=session.id,
            new_status=SessionStatus.IN_PROGRESS,
            current_user=_FakeUser(),
        )
    )

    assert wiring.queue_calls, "非終態轉移也該刷新排隊數字"
    assert wiring.dashboard.localized_dashboard_calls == []
    assert wiring.soap_calls == []


# ── D-8：切語言收場次 → cancelled ───────────────────────────
def test_language_switch_broadcasts_dashboard(monkeypatch, wiring):
    user = _FakeUser(role=UserRole.PATIENT)
    session = _FakeSession(status=SessionStatus.IN_PROGRESS)
    _install_get_by_id(monkeypatch, session)

    _run(
        SessionService.end_for_language_switch(
            _FakeDB(user=user),
            session_id=session.id,
            to_language="en-US",
            current_user=user,
        )
    )

    events = _dashboard_events(wiring, "cancelled")
    assert events, (
        "切語言把場次收成 cancelled 卻沒廣播 dashboard —— "
        "醫師端排隊清單會留著一筆已結束的場次"
    )
    assert events[0]["extra"]["previousStatus"] == "in_progress"
    assert wiring.queue_calls, "沒刷新 queue/stats"
    assert wiring.soap_calls == [], "cancelled 不派 SOAP（P7 政策）"


def test_language_switch_idempotent_path_does_not_broadcast(monkeypatch, wiring):
    """場次早已是終態（本次沒轉移）→ 不可再推一則事件。"""
    user = _FakeUser(role=UserRole.PATIENT)
    session = _FakeSession(status=SessionStatus.COMPLETED)
    _install_get_by_id(monkeypatch, session)

    _run(
        SessionService.end_for_language_switch(
            _FakeDB(user=user),
            session_id=session.id,
            to_language="en-US",
            current_user=user,
        )
    )

    assert wiring.dashboard.localized_dashboard_calls == []
    assert wiring.queue_calls == []
