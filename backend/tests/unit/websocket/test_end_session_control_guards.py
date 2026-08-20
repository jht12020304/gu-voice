"""EM-4：`control: end_session` 必須與其他終態路徑用同一組守衛。

稽核發現這條路徑（`conversation_websocket` 主迴圈內）是所有終態路徑裡最寬鬆的一條：

1. **不查 `_terminated`**：紅旗中止／自動結束已收尾的場次，再收到一則 end_session
   （病患連點、或前端在收到終態事件之前就把指令送出）會再跑一整套 —— 重複
   dashboard `session_status_changed`、重複推 queue/stats、重複派 SOAP。
2. **不尊重 CAS 回傳**：`_update_session_status` 回 False（場次早已是
   aborted_red_flag / cancelled）時照樣對病患端送 completed、對 dashboard 廣播
   completed —— 醫師端排隊清單上一場紅旗中止的場次會顯示成「正常完成」，
   分流訊號被抹掉。
3. **從不設 `_terminated`**：收尾後若還有背景 late-critical drain 在飛，它看不到
   旗標，會再跑一套 abort 收尾。

不變式 #18 的既有保護（病患端 `session_status` 要帶 `extra.status`）由
`test_end_session_status_extra.py`（AST）守著，本檔案另外用行為再確認一次。
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from tests.unit.websocket.conftest import (
    DEFAULT_SESSION_ID,
    run_control_action,
)

SID = DEFAULT_SESSION_ID
_END = {"type": "control", "payload": {"action": "end_session"}}


def _completed_status_calls(update_status) -> list[Any]:
    return [c for c in update_status.call_args_list if c.args[3] == "completed"]


def _patient_terminal_events(cap) -> list[dict[str, Any]]:
    return [c for c in cap.localized_calls if c["code"] == "events.session.ended_by_user"]


def _completed_dashboard_events(cap) -> list[dict[str, Any]]:
    """只取「宣稱 completed」的 session_status_changed。

    連線建立時也會廣播一則 `session_status_changed`（code=ws_connected、
    status=in_progress），不能一起算進來。
    """
    return [
        c
        for c in cap.localized_dashboard_calls
        if c["msg_type"] == "session_status_changed"
        and c["extra"].get("status") == "completed"
    ]


# ── 正常路徑：六件事該做的都做 ─────────────────────────────
def test_end_session_happy_path_does_the_full_fanout(monkeypatch):
    res = run_control_action(monkeypatch, messages=[_END])

    assert _completed_status_calls(res.update_status), "沒有把場次轉成 completed"

    events = _patient_terminal_events(res.cap)
    assert events, "沒送病患端 session_status"
    # 不變式 #18：沒有 extra.status 病患畫面會停在對話頁
    assert events[0]["extra"].get("status") == "completed"

    dash = _completed_dashboard_events(res.cap)
    assert dash, "沒廣播 dashboard session_status_changed（completed）"
    assert dash[0]["extra"]["previousStatus"] == "in_progress"
    # 連線建立時已推過一次；end_session 必須再推一次（排隊數字變了）
    assert res.queue_stats_spy.call_count >= 2, "沒推播 queue/stats"
    assert res.soap_spy.called, "沒派 SOAP"
    assert res.session_context.get("_terminated") == "completed", (
        "收尾後沒設 `_terminated`，背景 drain 會插隊再跑一套 abort 收尾"
    )


# ── 守衛 1：`_terminated` 已設 → 完全不重跑 ────────────────
def test_end_session_after_red_flag_abort_is_a_noop(monkeypatch):
    """紅旗中止已收尾的場次再收到 end_session：不轉狀態、不送、不廣播、不派 SOAP。"""
    res = run_control_action(
        monkeypatch,
        messages=[_END],
        session_context_seed={"_terminated": "aborted_red_flag"},
    )

    assert not _completed_status_calls(res.update_status), (
        "已終止的場次又被 end_session 轉了一次 completed"
    )
    assert not _patient_terminal_events(res.cap)
    assert not _completed_dashboard_events(res.cap), (
        "重複的 dashboard session_status_changed"
    )
    assert not res.soap_spy.called, "重複派 SOAP"
    # 旗標不可被覆寫成 completed（會把紅旗中止的終態語意抹掉）
    assert res.session_context.get("_terminated") == "aborted_red_flag"


# ── 守衛 2：CAS 未命中 → 不送 completed、不廣播、不派 SOAP ──
def test_end_session_cas_miss_does_not_announce_completed(monkeypatch):
    """場次早已是終態（別的行程／路徑轉走）→ CAS miss，不可對外宣稱 completed。"""
    res = run_control_action(
        monkeypatch,
        messages=[_END],
        update_status=AsyncMock(return_value=False),
    )

    assert _completed_status_calls(res.update_status), "應該有嘗試轉移"
    assert not _patient_terminal_events(res.cap), (
        "CAS 未命中還對病患端送 completed —— 場次可能其實是 aborted_red_flag"
    )
    assert not _completed_dashboard_events(res.cap), (
        "CAS 未命中還對 dashboard 廣播 completed，醫師端會看到假的『正常完成』"
    )
    assert not res.soap_spy.called
    assert res.session_context.get("_terminated") is None, (
        "轉移失敗卻把本連線標成 completed"
    )


# ── EM-2 附帶驗證：REST 標終態後，WS 端的守衛涵蓋到哪裡 ────
# REST（另一個行程）把場次標成終態時，`session_context["_terminated"]` 這個行程
# 內旗標設不了。此處確認**連線層**的守衛確實擋得住「已終態場次的新連線」，
# 這是 REST 路徑唯一能倚賴的 WS 端防線（限制記載於
# `session_service._after_status_transition` docstring 第 3 點）。
@pytest.mark.parametrize(
    "terminal_status", ["completed", "aborted_red_flag", "cancelled"]
)
def test_ws_refuses_to_open_on_terminal_session(monkeypatch, terminal_status):
    res = run_control_action(
        monkeypatch,
        messages=[_END],
        session_status=terminal_status,
    )

    assert (4009, "errors.ws.session_wrong_status") in res.ws.closed_with, (
        f"場次已是 {terminal_status}，WS 仍允許連線 —— 病患會對一場已結束的"
        f"問診繼續講話（closed_with={res.ws.closed_with}）"
    )
    assert res.cap.connected == [], "已終態場次不該進到 connect_session"
    assert not _completed_status_calls(res.update_status), (
        "已終態場次的連線不該再嘗試任何狀態轉移"
    )
    assert not res.soap_spy.called
