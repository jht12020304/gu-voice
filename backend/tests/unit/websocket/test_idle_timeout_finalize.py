"""閒置逾時（`_idle_watchdog`）也必須生成 SOAP。

會生成 SOAP 的路徑原本有四條：`end_session` 控制指令、HPI/硬上限自動結束、
critical 紅旗中止、硬上限前遲到 critical。**閒置逾時是漏掉的第五條**——看門狗
只做 `_update_session_status(completed)` + `websocket.close`，於是場次終態是
completed 而 `soap_reports` 永遠沒有那一列，醫師端拿不到報告。

順帶守住同一條路徑上另外兩個同族缺口（皆為 `_finalize_idle_timeout` 的職責）：
- 病患端那則 `session_status` 要帶終態 `status`（`connection_manager` 只在有
  extra 時才把 status 併進 payload），否則 WS 被 4000 關掉後前端只會無限重連。
- 儀表板要收到 `session_status_changed` + queue/stats，否則排隊清單留著一筆
  早已結束的場次。

⚠️ 不動的同族項：病患直接關瀏覽器 → 停在 in_progress → 60 分鐘後由
`app/tasks/session_timeout.py` 標 cancelled、同樣無 SOAP。那是產品決策
（未完成的場次要不要出報告），不在本次修復範圍。
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any
from unittest.mock import AsyncMock

import app.websocket.conversation_handler as ch
from tests.unit.websocket.conftest import (
    DEFAULT_SESSION_ID,
    FakeRedis,
    StubDB,
    _CaptureManager,
)

SID = DEFAULT_SESSION_ID


def _run(monkeypatch, *, transitioned: bool = True, idle_seconds: int = 600):
    cap = _CaptureManager()
    monkeypatch.setattr(ch, "manager", cap)
    update_status = AsyncMock(return_value=transitioned)
    monkeypatch.setattr(ch, "_update_session_status", update_status)
    soap_spy = AsyncMock(return_value=None)
    monkeypatch.setattr(ch, "_generate_soap_report_async", soap_spy)
    queue_stats = AsyncMock(return_value=None)
    monkeypatch.setattr(ch, "_broadcast_dashboard_queue_and_stats", queue_stats)

    db = StubDB()
    redis = FakeRedis()

    async def _main() -> bool:
        ok = await ch._finalize_idle_timeout(
            db=db, redis=redis, session_id=SID, idle_timeout_seconds=idle_seconds
        )
        # SOAP 走 _spawn_background，讓它跑完再斷言
        current = asyncio.current_task()
        for _ in range(50):
            pending = [t for t in asyncio.all_tasks() if t is not current and not t.done()]
            if not pending:
                break
            await asyncio.wait(pending, timeout=0.01)
        return ok

    ok = asyncio.run(_main())
    return ok, cap, update_status, soap_spy, queue_stats


def _idle_events(cap: _CaptureManager) -> list[dict[str, Any]]:
    return [
        c for c in cap.localized_calls if c["code"] == "events.session.idle_timeout"
    ]


# ── 核心回歸：閒置逾時要派 SOAP ────────────────────────────
def test_idle_timeout_dispatches_soap(monkeypatch):
    ok, _cap, update_status, soap_spy, _qs = _run(monkeypatch)
    assert ok is True
    assert update_status.call_args.args[3] == "completed"
    assert update_status.call_args.args[4] == "in_progress"
    assert soap_spy.called, (
        "閒置逾時把場次標成 completed 卻沒派 SOAP —— soap_reports 永遠不會有這一列"
    )
    assert soap_spy.call_args.kwargs["session_id"] == SID


def test_idle_timeout_skips_soap_when_already_terminal(monkeypatch):
    """CAS 未命中（場次早已 aborted_red_flag / completed）→ 不重複派 SOAP。

    冪等雖然也由 `_generate_soap_report_async` 的存在性檢查 + UNIQUE 擋，
    但這條路徑本來就不該當自己是終結者，否則會蓋掉別條路徑的通知語意。
    """
    ok, cap, _us, soap_spy, queue_stats = _run(monkeypatch, transitioned=False)
    assert ok is False
    assert not soap_spy.called
    assert not queue_stats.called
    # 仍會先送出一則「閒置逾時」提示（讓病患知道發生什麼事），但不送終態事件
    assert len(_idle_events(cap)) == 1
    assert _idle_events(cap)[0]["extra"] == {}


# ── 同族缺口：病患端終態 + 儀表板 ──────────────────────────
def test_idle_timeout_sends_terminal_status_to_patient(monkeypatch):
    _ok, cap, _us, _soap, _qs = _run(monkeypatch)
    events = _idle_events(cap)
    terminal = [e for e in events if e["extra"].get("status")]
    assert terminal, (
        "閒置逾時沒送帶 status 的 session_status —— WS 被 4000 關掉後前端無限重連"
    )
    assert terminal[0]["extra"]["status"] == "completed"


def test_idle_timeout_message_carries_minutes(monkeypatch):
    """既有行為不可回歸：提示要帶分鐘數（600s → 10）。"""
    _ok, cap, _us, _soap, _qs = _run(monkeypatch, idle_seconds=600)
    assert _idle_events(cap)[0]["params"] == {"minutes": 10}


def test_idle_timeout_broadcasts_dashboard(monkeypatch):
    _ok, cap, _us, _soap, queue_stats = _run(monkeypatch)
    dash = [
        c
        for c in cap.localized_dashboard_calls
        if c["msg_type"] == "session_status_changed"
    ]
    assert dash, "閒置逾時沒廣播 dashboard，醫師端排隊清單留著已結束的場次"
    assert dash[0]["extra"] == {
        "sessionId": SID,
        "status": "completed",
        "previousStatus": "in_progress",
    }
    assert queue_stats.called


# ── 韌性：任何一步失敗都不可讓看門狗死掉（後面還要關 WS）────
def test_notification_failure_still_dispatches_soap(monkeypatch):
    cap = _CaptureManager()

    async def _boom(*a, **k):
        raise RuntimeError("ws gone")

    cap.send_localized_to_session = _boom  # type: ignore[method-assign]
    monkeypatch.setattr(ch, "manager", cap)
    monkeypatch.setattr(ch, "_update_session_status", AsyncMock(return_value=True))
    soap_spy = AsyncMock(return_value=None)
    monkeypatch.setattr(ch, "_generate_soap_report_async", soap_spy)
    monkeypatch.setattr(
        ch, "_broadcast_dashboard_queue_and_stats", AsyncMock(return_value=None)
    )

    async def _main() -> bool:
        ok = await ch._finalize_idle_timeout(
            db=StubDB(), redis=FakeRedis(), session_id=SID, idle_timeout_seconds=600
        )
        current = asyncio.current_task()
        for _ in range(50):
            pending = [t for t in asyncio.all_tasks() if t is not current and not t.done()]
            if not pending:
                break
            await asyncio.wait(pending, timeout=0.01)
        return ok

    assert asyncio.run(_main()) is True
    assert soap_spy.called, "病患端 WS 已斷不該擋掉 SOAP 生成"


def test_status_update_failure_returns_false_without_soap(monkeypatch):
    async def _boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(ch, "manager", _CaptureManager())
    monkeypatch.setattr(ch, "_update_session_status", _boom)
    soap_spy = AsyncMock(return_value=None)
    monkeypatch.setattr(ch, "_generate_soap_report_async", soap_spy)

    ok = asyncio.run(
        ch._finalize_idle_timeout(
            db=StubDB(), redis=FakeRedis(), session_id=SID, idle_timeout_seconds=600
        )
    )
    assert ok is False
    assert not soap_spy.called
    # 不外拋：看門狗還要繼續關 WS


# ── 接線：看門狗真的有呼叫這個 helper ─────────────────────
def test_idle_watchdog_calls_finalizer():
    """_idle_watchdog 是 conversation_websocket 的巢狀函式，抓不到 reference，
    改用原始碼比對釘住接線（否則 helper 修好了但沒人呼叫）。"""
    src = inspect.getsource(ch.conversation_websocket)
    assert "_finalize_idle_timeout(" in src, "閒置看門狗沒有呼叫 _finalize_idle_timeout"
    # 舊的 inline 兩步驟不可留著（會重複轉狀態）
    assert 'code="events.session.idle_timeout"' not in src
