"""E8-4 補強測試：session.red_flag_reason 的 title 重解析一致性。

背景（finding 修復前的缺口）：`_persist_and_emit_alert`（DB alerts 表 /
WS `red_flag_alert` / dashboard `new_red_flag`）在持久化/廣播前，會依
`session.language` 對「內建 catalogue」紅旗的 title 做防禦性重解析
（E8-4），但寫入 `session.red_flag_reason` 的三個計算點——

  1. 立即 critical abort（`_handle_text_message` 主體，critical_title）
  2. 遲到紅旗背景 drain（`_drain_late_red_flags`，late_critical_title）
  3. 硬上限 + 遲到紅旗有界 inline 解析（late_critical_title）

——原本都直接讀 `alert.get("title")`，繞過了同一份重解析。若上游
red_flag_detector 對某次 critical 紅旗仍漂移出語言不符的 title，DB
alerts 表 / WS 廣播會被修正，但 `session.red_flag_reason`
（doctor 端 SessionDetailPage / SOAPReportPage、patient 端
SessionCompletePage 皆會原樣渲染）卻仍是漂移前的原文，形成同一急症
事件在不同顯示面語言不一致。

本檔案針對上述三個計算點各補一個「language drift」情境測試：alert
dict 的 title 刻意帶著與 session.language 不符的語言，斷言
`session.red_flag_reason`（透過 `_update_session_status` 的
`red_flag_reason` kwarg 觀察）必須是依場次語言重新解析後的 title，
而不是 alert dict 裡漂移前的原文。
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
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


def _session_context(language: str) -> dict:
    return {
        "session_id": SID,
        "user_id": "user-1",
        "chief_complaint": "血尿",
        "chief_complaint_display": "血尿",
        "patient_info": {"name": "測試病患"},
        "language": language,
    }


# ── 1. 立即 critical abort：critical_title 必須依場次語言重解析 ──────────
def test_immediate_critical_abort_reason_uses_localized_title(monkeypatch):
    """en-US 場次收到中文 title 的 critical 紅旗：red_flag_reason 仍須是英文，
    且與同一輪 WS/alerts 表廣播的 title 一致（不可語言分岔）。"""
    alert = make_alert(
        severity="critical",
        canonical_id="gross_hematuria",
        title="肉眼血尿",  # 模擬偵測器漂移：en-US 場次卻拿到中文
    )
    res = run_text_turn(
        monkeypatch,
        session_context=_session_context("en-US"),
        detector=StubDetector(alerts=[alert]),
    )

    # 與 alerts 表 / WS 廣播用的 title 保持一致
    persisted_title = res.alert_create.call_args.args[1]["title"]
    ws_title = res.cap.messages_of_type("red_flag_alert")[0]["payload"]["title"]
    assert persisted_title == "Gross Hematuria"
    assert ws_title == "Gross Hematuria"

    abort_calls = [
        c
        for c in res.update_status.call_args_list
        if c.args[3] == "aborted_red_flag"
    ]
    assert len(abort_calls) == 1
    assert abort_calls[0].kwargs.get("red_flag_reason") == "Gross Hematuria"
    # 修復前的 regression 寫法：仍是漂移前的中文原文
    assert abort_calls[0].kwargs.get("red_flag_reason") != "肉眼血尿"


# ── 2. 遲到紅旗背景 drain：late_critical_title 必須依場次語言重解析 ────────
def test_background_drain_late_critical_reason_uses_localized_title(monkeypatch):
    """偵測器延遲回應、critical 紅旗由背景 `_drain_late_red_flags` 解析出來：
    這條路徑計算的 red_flag_reason 同樣要依場次語言重解析，不可沿用 alert
    dict 裡漂移前的原文。

    比照 test_session_terminated_guard.py::test_late_drain_sets_flag_for_next_turn
    的作法：同一事件迴圈內先 await `_handle_text_message`，再 `asyncio.sleep`
    讓背景 drain task 有機會跑完，才能觀察其對 session.red_flag_reason 的
    計算結果（`run_text_turn` 用 `asyncio.run` 各自獨立事件迴圈，函式一返回
    就會 cancel 掉尚未完成的背景 task，觀察不到 drain 的副作用）。
    """
    import uuid as _uuid

    import app.core.database as core_db
    from app.services.alert_service import AlertService
    from app.services.conversation_service import ConversationService

    cap = _CaptureManager()
    monkeypatch.setattr(ch, "manager", cap)
    monkeypatch.setattr(ch, "_RED_FLAG_WAIT_TIMEOUT", 0.01)

    session_context = _session_context("ja-JP")
    history: list = []
    redis = FakeRedis()
    settings = make_settings()
    db = StubDB()
    drain_db = StubDB()

    monkeypatch.setattr(
        ConversationService,
        "create",
        AsyncMock(return_value=SimpleNamespace(id=_uuid.uuid4())),
    )
    alert_create = AsyncMock(return_value=SimpleNamespace(id=_uuid.uuid4()))
    monkeypatch.setattr(AlertService, "create", alert_create)
    update_status = AsyncMock(return_value=True)
    monkeypatch.setattr(ch, "_update_session_status", update_status)
    monkeypatch.setattr(ch, "_generate_soap_report_async", AsyncMock(return_value=None))
    monkeypatch.setattr(ch, "_broadcast_dashboard_queue_and_stats", AsyncMock(return_value=None))
    monkeypatch.setattr(ch, "_save_conversation_history", AsyncMock(return_value=None))
    monkeypatch.setattr(ch, "_cap_conversation_history", AsyncMock(return_value=None))

    @asynccontextmanager
    async def _fake_get_db_session():
        yield drain_db

    monkeypatch.setattr(core_db, "get_db_session", _fake_get_db_session)

    detector = StubDetector(
        alerts=[
            make_alert(
                severity="critical",
                canonical_id="gross_hematuria",
                title="肉眼血尿",  # 漂移：ja-JP 場次卻拿到中文原文
            )
        ],
        delay=0.05,
    )
    llm = StubLLMEngine([["好的。"]])

    async def _body() -> bool:
        result = await ch._handle_text_message(
            session_id=SID,
            text="我最近排尿會痛",
            llm_engine=llm,
            tts_pipeline=StubTTS(),
            red_flag_detector=detector,
            supervisor_engine=StubSupervisor(),
            system_prompt="test-system-prompt",
            conversation_history=history,
            session_context=session_context,
            redis=redis,
            db=db,
            settings=settings,
        )
        # 讓背景 drain task（0.05s 後才拿到 critical）在同一個事件迴圈跑完。
        await asyncio.sleep(0.1)
        return result

    asyncio.run(_body())

    abort_calls = [
        c
        for c in update_status.call_args_list
        if c.args[3] == "aborted_red_flag"
    ]
    assert len(abort_calls) == 1
    assert abort_calls[0].kwargs.get("red_flag_reason") == "肉眼的血尿"
    assert abort_calls[0].kwargs.get("red_flag_reason") != "肉眼血尿"


# ── 3. 硬上限 + 遲到紅旗有界 inline 解析：同樣要重解析 ────────────────────
def test_hard_cap_inline_late_critical_reason_uses_localized_title(monkeypatch):
    """硬上限那輪剛好遇到遲到 critical、走有界 inline 解析（見
    test_auto_conclude.py::test_hard_cap_late_critical_inline_abort 的
    同款情境），alert title 語言漂移時 red_flag_reason 仍須重解析。"""
    settings = make_settings(
        MAX_PATIENT_TURNS_HARD_CAP=1,
        MIN_PATIENT_TURNS_BEFORE_AUTO_END=1,
        HARD_CAP_DRAIN_AWAIT_SECONDS=0.2,
        MAX_HARD_CAP_DRAIN_DEFERS=2,
    )
    res = run_text_turn(
        monkeypatch,
        settings=settings,
        session_context=_session_context("en-US"),
        detector=StubDetector(
            alerts=[
                make_alert(
                    severity="critical",
                    canonical_id="gross_hematuria",
                    title="肉眼血尿",  # 漂移：en-US 場次卻拿到中文原文
                )
            ],
            delay=0.05,
        ),
    )

    assert res.result is True
    # 硬上限這輪可能同時有背景 drain task 與 inline shield-await 都觀察到同一個
    # late_alerts（compare-and-set 讓重複呼叫冪等，比照
    # test_auto_conclude.py::test_hard_cap_late_critical_inline_abort 用 any()
    # 斷言，不假設恰好一次）。
    abort_calls = [
        c
        for c in res.update_status.call_args_list
        if c.args[3] == "aborted_red_flag"
    ]
    assert abort_calls
    assert any(
        c.kwargs.get("red_flag_reason") == "Gross Hematuria" for c in abort_calls
    )
    assert not any(
        c.kwargs.get("red_flag_reason") == "肉眼血尿" for c in abort_calls
    )
