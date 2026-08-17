"""
守護 P4 逾時清理任務的「終態轉移」不變式：

逾時把 in_progress 場次轉 cancelled 時，必須
- 每場成功轉移後 publish 一次 dashboard ``session_status_changed``（cancelled），
- 整批結束後刷新一次 queue/stats，
- 走 compare-and-set：DB 目前已非 in_progress 的場次不得被覆寫、也不得推播，
- 轉移前先問單一權威狀態機 ``is_valid_transition``。

回歸背景：先前實作是 SELECT 後逐一改欄位再整批 commit，零推播 —— 醫師端排隊
清單會停在舊資料直到整頁重載，且並發時會用 cancelled 蓋掉別的行程剛寫入的終態。

FakeSession 風格對齊 tests/unit/tasks/test_audio_lifecycle.py。
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

import pytest

from app.tasks import session_timeout as st
from app.utils.datetime_utils import utc_now


def _run(coro):
    return asyncio.run(coro)


# ──────────────────────────────────────────────────────────
# Fakes
# ──────────────────────────────────────────────────────────

class _FakeResult:
    def __init__(self, rows: list[Any]):
        self._rows = rows

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


class _FakeSession:
    """SELECT 回傳指定的逾時場次；UPDATE 依 ``cas_hits`` 決定 CAS 是否命中。

    Args:
        stale_rows: SELECT 結果，每列為 ``(session_id, updated_at)``。
        cas_hits: 依序對應每次 UPDATE 是否命中（True＝RETURNING 有列）。
            不足的部分預設為 True。
    """

    def __init__(
        self,
        stale_rows: list[tuple],
        cas_hits: list[bool] | None = None,
    ):
        self.stale_rows = stale_rows
        self.cas_hits = list(cas_hits or [])
        self.executed_sql: list[str] = []
        self.update_count = 0
        self.commits = 0

    async def execute(self, stmt, params: dict | None = None):
        sql = str(stmt)
        self.executed_sql.append(sql)
        if sql.lstrip().upper().startswith("UPDATE"):
            idx = self.update_count
            self.update_count += 1
            hit = self.cas_hits[idx] if idx < len(self.cas_hits) else True
            return _FakeResult([("row-id",)] if hit else [])
        return _FakeResult(self.stale_rows)

    async def commit(self):
        self.commits += 1

    async def close(self):
        pass


class _FakeSessionFactory:
    def __init__(self, session: _FakeSession):
        self.session = session

    def __call__(self):
        return self._CM(self.session)

    class _CM:
        def __init__(self, sess):
            self.sess = sess

        async def __aenter__(self):
            return self.sess

        async def __aexit__(self, *exc):
            await self.sess.close()
            return False


@pytest.fixture
def patch_factory(monkeypatch):
    def _install(session: _FakeSession) -> _FakeSessionFactory:
        factory = _FakeSessionFactory(session)
        import app.core.database as db_mod

        monkeypatch.setattr(db_mod, "async_session_factory", factory)
        return factory

    return _install


@pytest.fixture
def spy_broadcasts(monkeypatch):
    """攔截跨行程推播：dashboard 事件 publish 與 queue/stats 廣播。

    兩者都在函式內 lazy import，故 patch 各自的來源模組即可。
    ``events`` 依呼叫順序記錄，可用來斷言「先逐場、後整批」。
    """
    events: list[tuple[str, Any]] = []

    async def _fake_publish(event_type: str, payload: dict | None = None) -> None:
        events.append(("publish", (event_type, payload or {})))

    async def _fake_queue_stats(db, redis) -> None:
        events.append(("queue_and_stats", db))

    import app.websocket.connection_manager as cm_mod
    import app.websocket.dashboard_handler as dh_mod

    monkeypatch.setattr(cm_mod, "publish_dashboard_event", _fake_publish)
    monkeypatch.setattr(dh_mod, "broadcast_queue_and_stats", _fake_queue_stats)
    return events


def _publishes(events):
    return [payload for kind, payload in events if kind == "publish"]


def _stale(n: int) -> list[tuple]:
    old = utc_now() - timedelta(minutes=st.SESSION_TIMEOUT_MINUTES + 5)
    return [(f"sess-{i}", old) for i in range(n)]


# ──────────────────────────────────────────────────────────
# 測試
# ──────────────────────────────────────────────────────────

def test_timeout_threshold_default_is_60_minutes():
    """閾值誤改會讓還在問診的場次被腰斬；改動請同步 dashboard 事件文案的 minutes。"""
    assert st.SESSION_TIMEOUT_MINUTES == 60


def test_each_cancelled_session_publishes_session_status_changed(
    patch_factory, spy_broadcasts
):
    """核心修復：每場取消都要 publish 一則 session_status_changed。"""
    session = _FakeSession(_stale(2))
    patch_factory(session)

    result = _run(st._async_check())

    assert result["timed_out"] == 2
    assert result["session_ids"] == ["sess-0", "sess-1"]

    published = _publishes(spy_broadcasts)
    status_events = [p for p in published if p[0] == "session_status_changed"]
    assert len(status_events) == 2

    for (event_type, payload), sid in zip(status_events, ["sess-0", "sess-1"]):
        assert event_type == "session_status_changed"
        assert payload["sessionId"] == sid
        assert payload["status"] == "cancelled"
        assert payload["previousStatus"] == "in_progress"
        # canonical 在地化欄位（前端以 t(code, params) 渲染）
        assert payload["code"] == st._TIMEOUT_EVENT_CODE
        assert payload["params"] == {"minutes": st.SESSION_TIMEOUT_MINUTES}
        assert payload["severity"] == "warning"


def test_queue_and_stats_broadcast_once_after_batch(patch_factory, spy_broadcasts):
    """批次結束後要刷新一次 queue/stats，且排在所有逐場推播之後。"""
    session = _FakeSession(_stale(3))
    patch_factory(session)

    _run(st._async_check())

    kinds = [kind for kind, _ in spy_broadcasts]
    assert kinds.count("queue_and_stats") == 1
    assert kinds == ["publish", "publish", "publish", "queue_and_stats"]


def test_cas_miss_is_not_counted_and_not_published(patch_factory, spy_broadcasts):
    """DB 目前已非 in_progress（他處先轉終態）→ 不覆寫、不計數、不推播。"""
    session = _FakeSession(_stale(3), cas_hits=[True, False, True])
    patch_factory(session)

    result = _run(st._async_check())

    assert result["timed_out"] == 2
    assert result["skipped"] == 1
    assert result["session_ids"] == ["sess-0", "sess-2"]

    published = _publishes(spy_broadcasts)
    sids = [p[1]["sessionId"] for p in published]
    assert sids == ["sess-0", "sess-2"]
    assert "sess-1" not in sids


def test_all_cas_miss_skips_queue_stats_broadcast(patch_factory, spy_broadcasts):
    """一場都沒真的轉移就不該推 queue/stats（避免無意義的 DB 查詢與抖動）。"""
    session = _FakeSession(_stale(2), cas_hits=[False, False])
    patch_factory(session)

    result = _run(st._async_check())

    assert result["timed_out"] == 0
    assert result["skipped"] == 2
    assert spy_broadcasts == []


def test_update_uses_compare_and_set_on_in_progress(patch_factory, spy_broadcasts):
    """UPDATE 必須帶 status 條件（CAS），不可只用 id 當唯一條件。"""
    session = _FakeSession(_stale(1))
    patch_factory(session)

    _run(st._async_check())

    updates = [s for s in session.executed_sql if s.lstrip().upper().startswith("UPDATE")]
    assert len(updates) == 1
    sql = updates[0]
    assert "WHERE" in sql.upper()
    assert "sessions.status" in sql
    assert "sessions.id" in sql
    # 每場獨立 commit（推播只在 commit 成功後才發）
    assert session.commits == 1


def test_no_stale_sessions_publishes_nothing(patch_factory, spy_broadcasts):
    session = _FakeSession([])
    patch_factory(session)

    result = _run(st._async_check())

    assert result == {"timed_out": 0}
    assert spy_broadcasts == []
    assert session.commits == 0


def test_illegal_transition_table_stops_the_task(
    patch_factory, spy_broadcasts, monkeypatch
):
    """狀態機才是權威：若 in_progress→cancelled 被移出 VALID_TRANSITIONS，
    本任務必須整批停手，而不是照舊硬改 status。"""
    import app.core.session_state as ss_mod

    monkeypatch.setattr(ss_mod, "is_valid_transition", lambda *a, **k: False)

    session = _FakeSession(_stale(2))
    patch_factory(session)

    result = _run(st._async_check())

    assert result["timed_out"] == 0
    assert result["skipped_invalid_transition"] is True
    assert session.executed_sql == []  # 連 SELECT 都不該發
    assert spy_broadcasts == []


def test_in_progress_to_cancelled_is_currently_legal():
    """把上一則測試的前提釘住：目前狀態表確實允許此轉移。"""
    from app.core.session_state import is_valid_transition
    from app.models.enums import SessionStatus

    assert is_valid_transition(SessionStatus.IN_PROGRESS, SessionStatus.CANCELLED)


def test_publish_failure_does_not_break_the_batch(
    patch_factory, spy_broadcasts, monkeypatch
):
    """推播是盡力而為：Redis 掛掉不可讓已 commit 的取消回頭失敗。"""
    import app.websocket.connection_manager as cm_mod

    async def _boom(event_type: str, payload: dict | None = None) -> None:
        raise RuntimeError("redis down")

    monkeypatch.setattr(cm_mod, "publish_dashboard_event", _boom)

    session = _FakeSession(_stale(2))
    patch_factory(session)

    result = _run(st._async_check())

    assert result["timed_out"] == 2
    # queue/stats 仍會嘗試（其失敗同樣被吞掉）
    assert [kind for kind, _ in spy_broadcasts] == ["queue_and_stats"]
