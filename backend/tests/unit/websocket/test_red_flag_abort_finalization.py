"""critical 紅旗中止的三條路徑必須做同一組收尾（`_finalize_red_flag_abort`）。

守護的不變式（真跑 + 靜態追蹤抓到的兩個缺陷）：

1. **遲到紅旗 drain 也要生成 SOAP**（HIGH）。`_drain_late_red_flags` 以前只把
   `sessions.status` 改成 aborted_red_flag、設 `_terminated`，不派 SOAP、不通知
   病患端、不廣播 dashboard。後果：偵測慢於 3.5s gate 且該輪含 critical 時，
   場次停在 aborted_red_flag 卻**沒有任何 soap_reports 列**——主迴圈 finally 不生，
   病患下一則訊息撞 `_terminated` 守衛直接 return 也不生——醫師端永遠等不到報告。
2. **硬上限 inline drain 的 session_status 要帶 `extra`**（MEDIUM）。
   `connection_manager` 只在有 extra 時才把 status 併進 payload，前端
   `on('session_status')` 依 `payload.status` 決定要不要導離對話頁；漏了病患會卡在
   對話頁並無限重連（與 PR #49 修過的 end_session 同一類 bug，只是另一條分支）。

drain 是背景 task，`run_text_turn` 的 `asyncio.run` 會在 `_handle_text_message`
返回時把它一起取消，所以這裡自備 driver：跑完主 turn 後繼續把剩餘 task 抽乾。
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import app.websocket.conversation_handler as ch
from tests.unit.websocket.conftest import (
    DEFAULT_SESSION_ID,
    FakeRedis,
    StubDB,
    StubDetector,
    StubLLMEngine,
    StubSupervisor,
    StubTTS,
    _CaptureManager,
    make_alert,
    make_settings,
    run_text_turn,
)

SID = DEFAULT_SESSION_ID


def _ctx() -> dict[str, Any]:
    """K=0 主訴：避免 §3b 風險因子 cap 加成干擾回合數判斷。"""
    return {
        "session_id": SID,
        "user_id": "user-1",
        "chief_complaint": "睪丸疼痛",
        "chief_complaint_display": "睪丸疼痛",
        "patient_info": {"name": "測試病患"},
        "language": "zh-TW",
    }


def run_turn_draining(
    monkeypatch,
    *,
    detector: StubDetector,
    settings=None,
    session_context: dict[str, Any] | None = None,
    text: str = "我右邊睪丸突然劇痛",
) -> SimpleNamespace:
    """跑一輪 `_handle_text_message`，然後把背景 task（含遲到紅旗 drain）抽乾。"""
    cap = _CaptureManager()
    monkeypatch.setattr(ch, "manager", cap)
    monkeypatch.setattr(ch, "_RED_FLAG_WAIT_TIMEOUT", 0.01)

    settings = settings or make_settings(MAX_PATIENT_TURNS_HARD_CAP=10)
    session_context = session_context if session_context is not None else _ctx()
    redis = FakeRedis()
    db = StubDB()
    drain_db = StubDB()

    from app.services.alert_service import AlertService
    from app.services.conversation_service import ConversationService

    monkeypatch.setattr(
        ConversationService,
        "create",
        AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4())),
    )
    monkeypatch.setattr(
        AlertService, "create", AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4()))
    )

    update_status = AsyncMock(return_value=True)
    monkeypatch.setattr(ch, "_update_session_status", update_status)
    soap_spy = AsyncMock(return_value=None)
    monkeypatch.setattr(ch, "_generate_soap_report_async", soap_spy)
    queue_stats_spy = AsyncMock(return_value=None)
    monkeypatch.setattr(ch, "_broadcast_dashboard_queue_and_stats", queue_stats_spy)
    monkeypatch.setattr(ch, "_save_conversation_history", AsyncMock(return_value=None))
    monkeypatch.setattr(ch, "_cap_conversation_history", AsyncMock(return_value=None))

    import app.core.database as core_db

    @asynccontextmanager
    async def _fake_get_db_session():
        yield drain_db

    monkeypatch.setattr(core_db, "get_db_session", _fake_get_db_session)

    async def _main() -> bool:
        result = await ch._handle_text_message(
            session_id=SID,
            text=text,
            llm_engine=StubLLMEngine([["好的。"]]),
            tts_pipeline=StubTTS(),
            red_flag_detector=detector,
            supervisor_engine=StubSupervisor(),
            system_prompt="test-system-prompt",
            conversation_history=[],
            session_context=session_context,
            redis=redis,
            db=db,
            settings=settings,
        )
        # 讓 drain / SOAP / supervisor 等背景 task 跑到底（最多 ~2s）
        current = asyncio.current_task()
        for _ in range(200):
            pending = [t for t in asyncio.all_tasks() if t is not current and not t.done()]
            if not pending:
                break
            await asyncio.wait(pending, timeout=0.01)
        return result

    result = asyncio.run(_main())
    return SimpleNamespace(
        result=result,
        cap=cap,
        db=db,
        drain_db=drain_db,
        update_status=update_status,
        soap_spy=soap_spy,
        queue_stats_spy=queue_stats_spy,
        session_context=session_context,
    )


def _abort_status_calls(update_status) -> list[Any]:
    return [c for c in update_status.call_args_list if c.args[3] == "aborted_red_flag"]


def _patient_abort_events(cap: _CaptureManager) -> list[dict[str, Any]]:
    return [
        c
        for c in cap.localized_calls
        if c["code"] == "events.session.aborted_red_flag"
    ]


# ── #2：遲到紅旗 drain 的四件事 ──────────────────────────
def _late_critical_detector() -> StubDetector:
    """0.1s 才回 critical：晚於 gate（harness 設 0.01s）→ 走背景 drain。"""
    return StubDetector(
        alerts=[
            make_alert(
                severity="critical", canonical_id="testicular_torsion", title="睪丸扭轉"
            )
        ],
        delay=0.1,
    )


def test_drain_late_critical_generates_soap(monkeypatch):
    """核心回歸：遲到 critical 也必須派 SOAP，否則場次 aborted 卻無報告。"""
    res = run_turn_draining(monkeypatch, detector=_late_critical_detector())
    assert res.result is False  # 本輪不結束（drain 在飛）
    assert _abort_status_calls(res.update_status), "drain 沒把場次轉成 aborted_red_flag"
    assert res.soap_spy.called, (
        "遲到 critical 紅旗中止了場次卻沒派 SOAP —— 醫師端永遠拿不到報告"
    )


def test_drain_late_critical_notifies_patient_with_terminal_status(monkeypatch):
    res = run_turn_draining(monkeypatch, detector=_late_critical_detector())
    events = _patient_abort_events(res.cap)
    assert events, "drain 沒送病患端 session_status，病患會卡在對話頁"
    assert events[0]["extra"].get("status") == "aborted_red_flag", (
        f"session_status 缺終態 status（extra={events[0]['extra']}）"
    )


def test_drain_late_critical_broadcasts_dashboard_and_queue(monkeypatch):
    res = run_turn_draining(monkeypatch, detector=_late_critical_detector())
    dash = [
        c
        for c in res.cap.localized_dashboard_calls
        if c["msg_type"] == "session_status_changed"
    ]
    assert dash, "drain 沒廣播 dashboard session_status_changed"
    assert dash[0]["extra"]["status"] == "aborted_red_flag"
    assert dash[0]["extra"]["sessionId"] == SID
    assert res.queue_stats_spy.called, "drain 沒推播 queue/stats"


def test_drain_uses_its_own_db_session_for_status(monkeypatch):
    """WS 的 db 在 drain 執行時可能已被 get_db 關閉，狀態轉移必須走 drain 自有 session。"""
    res = run_turn_draining(monkeypatch, detector=_late_critical_detector())
    abort_calls = _abort_status_calls(res.update_status)
    assert abort_calls
    assert abort_calls[0].args[0] is res.drain_db
    # queue/stats 同樣不可用已關閉的 WS db
    assert res.queue_stats_spy.call_args.args[0] is res.drain_db


def test_drain_marks_terminated_and_carries_reason(monkeypatch):
    """既有行為不可回歸：`_terminated` 旗標 + red_flag_reason 帶在地化 title。"""
    res = run_turn_draining(monkeypatch, detector=_late_critical_detector())
    assert res.session_context.get("_terminated") == "aborted_red_flag"
    assert _abort_status_calls(res.update_status)[0].kwargs.get(
        "red_flag_reason"
    ) == "睪丸扭轉"


def test_drain_without_critical_does_not_abort_or_generate_soap(monkeypatch):
    """反向：遲到的只有 medium → 不 abort、不派 SOAP（否則會誤中止正常場次）。"""
    res = run_turn_draining(
        monkeypatch,
        detector=StubDetector(
            alerts=[make_alert(severity="medium", canonical_id="mild_lut_symptom")],
            delay=0.1,
        ),
    )
    assert not _abort_status_calls(res.update_status)
    assert not res.soap_spy.called
    assert res.session_context.get("_terminated") is None


# ── #3：硬上限 inline drain 的 session_status extra ─────────
def test_hard_cap_inline_late_critical_carries_terminal_status(monkeypatch):
    """硬上限收尾前 inline 解析出 late-critical 的那條分支以前漏了 extra。"""
    res = run_text_turn(
        monkeypatch,
        settings=make_settings(
            MAX_PATIENT_TURNS_HARD_CAP=1,
            MIN_PATIENT_TURNS_BEFORE_AUTO_END=1,
            HARD_CAP_DRAIN_AWAIT_SECONDS=0.2,
            MAX_HARD_CAP_DRAIN_DEFERS=2,
        ),
        session_context=_ctx(),
        detector=StubDetector(
            alerts=[
                make_alert(
                    severity="critical",
                    canonical_id="testicular_torsion",
                    title="睪丸扭轉",
                )
            ],
            delay=0.05,
        ),
    )
    assert res.result is True
    events = _patient_abort_events(res.cap)
    assert events, "inline drain 沒送病患端 session_status"
    assert events[0]["extra"].get("status") == "aborted_red_flag", (
        "硬上限 inline drain 的 session_status 沒帶 status —— "
        f"病患端認不出終態、卡在對話頁（extra={events[0]['extra']}）"
    )


# ── 主 abort 分支（對照組，行為不可回歸） ──────────────────
def test_main_abort_branch_still_does_all_five(monkeypatch):
    res = run_text_turn(
        monkeypatch,
        session_context=_ctx(),
        detector=StubDetector(
            alerts=[
                make_alert(
                    severity="critical",
                    canonical_id="testicular_torsion",
                    title="睪丸扭轉",
                )
            ]
        ),
    )
    events = _patient_abort_events(res.cap)
    assert events and events[0]["extra"].get("status") == "aborted_red_flag"
    assert res.soap_spy.called
    assert res.session_context.get("_terminated") == "aborted_red_flag"
    assert [
        c
        for c in res.cap.localized_dashboard_calls
        if c["msg_type"] == "session_status_changed"
    ]
    assert _abort_status_calls(res.update_status)[0].args[0] is res.db
