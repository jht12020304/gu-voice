"""E8-1 單元測試：場次已終止（aborted_red_flag / completed）後拒收後續訊息。

e2e_realopenai_findings（2026-06-28）實測：critical abort 後 server 對已中止
場次續答 3 輪、每輪重發 abort 事件並照跑 LLM。根因是 `_handle_text_message`
的 critical-abort 區塊沒有讓呼叫端結束主迴圈，導致「下一輪」訊息仍原樣重跑
紅旗/LLM/auto-conclude。

守護的不變式：
- `_handle_text_message` / `_handle_audio_chunk` 開頭一律先檢查
  `session_context["_terminated"]`；一旦設了值，後續任何一輪都必須：
    - 不建對話歷史、不打 ConversationService/AlertService、不呼叫 LLM/紅旗偵測、
      不再呼叫 `_update_session_status`（不重發 abort/completed 事件洪流）。
    - 仍送出恰好一組 ai_response_start/chunk/end（VAD 不卡死不變式），
      文字內容為對應終態的在地化提示。
    - 回傳 True，讓呼叫端結束主迴圈。
- 音訊入口在進 STT（Whisper）之前就攔下，不浪費轉錄額度。
- 旗標本身由既有的三個終態出口設下（immediate critical abort / 硬上限 inline
  late-critical abort / 正常 HPI 收尾 completed），且背景 `_drain_late_red_flags`
  在「本輪已結束之後」才解析出遲到 critical 時也會設。
"""

from __future__ import annotations

import asyncio

import app.websocket.conversation_handler as ch
from app.utils.i18n_messages import get_message
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


def _shared_session_context(language: str = "zh-TW") -> dict:
    return {
        "session_id": SID,
        "user_id": "user-1",
        "chief_complaint": "血尿",
        "chief_complaint_display": "血尿",
        "patient_info": {"name": "測試病患"},
        "language": language,
    }


# ── _handle_text_message：critical abort 這輪設旗標，下一輪被攔下 ──────────
def test_second_turn_blocked_after_immediate_critical_abort(monkeypatch):
    session_context = _shared_session_context()
    history: list = []
    redis = FakeRedis()

    res1 = run_text_turn(
        monkeypatch,
        redis=redis,
        session_context=session_context,
        conversation_history=history,
        detector=StubDetector(
            alerts=[make_alert(severity="critical", canonical_id="testicular_torsion", title="睪丸扭轉")]
        ),
    )
    # 本輪（觸發 abort 的那輪）本身仍照跑完整流程，只是事後被標記終態。
    assert session_context["_terminated"] == "aborted_red_flag"
    assert res1.update_status.called

    res2 = run_text_turn(
        monkeypatch,
        redis=redis,
        session_context=session_context,
        conversation_history=history,
        detector=StubDetector(alerts=[make_alert(severity="critical")]),
    )
    # 守衛生效：不再重新跑紅旗/LLM，也不再打 _update_session_status。
    assert res2.result is True
    assert res2.llm.calls == 0
    assert not res2.conv_create.called
    assert not res2.alert_create.called
    assert not res2.update_status.called
    # 不再重發 abort session_status / dashboard 事件。
    assert res2.cap.localized_calls == []
    assert res2.cap.localized_dashboard_calls == []
    # 仍送出恰好一組 ai_response_start/chunk/end（VAD 不卡死）。
    assert len(res2.cap.messages_of_type("ai_response_start")) == 1
    assert len(res2.cap.messages_of_type("ai_response_chunk")) == 1
    assert len(res2.cap.messages_of_type("ai_response_end")) == 1
    expected_text = get_message("ws.session_terminated_aborted_notice", "zh-TW")
    assert res2.cap.chunk_texts() == [expected_text]
    end_payload = res2.cap.messages_of_type("ai_response_end")[0]["payload"]
    assert end_payload["fullText"] == expected_text
    # 病患訊息內容完全沒被寫進對話歷史（history 只有第 1 輪的內容）。
    assert len(history) == 2  # 第 1 輪：patient + assistant


def test_second_turn_blocked_after_normal_completion(monkeypatch):
    """正常 HPI 收尾（非紅旗）也要設旗標，下一輪一樣被攔下並回覆對應語氣。"""
    session_context = _shared_session_context(language="en-US")
    # 用 K=0 主訴（一般主訴軟門檻下限 = MIN），避免預設「血尿」的 §3b 風險因子 cap/floor
    # 加成擋掉「單輪即軟門檻收尾」的測試意圖；本測試驗正常 HPI 收尾、與風險因子無關。
    session_context["chief_complaint"] = "頻尿"
    session_context["chief_complaint_display"] = "Frequent urination"
    history: list = []
    redis = FakeRedis()
    settings = make_settings(
        MIN_PATIENT_TURNS_BEFORE_AUTO_END=1,
        MAX_PATIENT_TURNS_HARD_CAP=10,
    )
    # 讓 Supervisor guidance 顯示 HPI 已達門檻，觸發軟門檻收尾。
    redis.hashes[f"gu:session:{SID}:context"] = {}
    redis.kv[f"gu:session:{SID}:supervisor_guidance"] = (
        '{"hpi_completion_percentage": 90, "fallback": false}'
    )

    res1 = run_text_turn(
        monkeypatch,
        redis=redis,
        settings=settings,
        session_context=session_context,
        conversation_history=history,
        language="en-US",
        detector=StubDetector(alerts=[]),
    )
    assert res1.result is True
    assert session_context["_terminated"] == "completed"

    res2 = run_text_turn(
        monkeypatch,
        redis=redis,
        settings=settings,
        session_context=session_context,
        conversation_history=history,
        language="en-US",
        detector=StubDetector(alerts=[]),
    )
    assert res2.result is True
    assert res2.llm.calls == 0
    assert not res2.update_status.called
    expected_text = get_message("ws.session_terminated_completed_notice", "en-US")
    assert res2.cap.chunk_texts() == [expected_text]


def test_late_drain_sets_flag_for_next_turn(monkeypatch):
    """遲到 critical 由背景 `_drain_late_red_flags` 解析出來也要設旗標。

    不能用 `run_text_turn`：它內部用 `asyncio.run()` 各跑一個獨立事件迴圈，
    函式一返回就會把尚未完成的背景 drain task 一併取消（`asyncio.run` 收尾
    會 cancel 所有殘留 task）。這裡改成單一事件迴圈：先 `await
    _handle_text_message`，再在「同一個」事件迴圈內 `await asyncio.sleep(...)`
    讓背景 drain task 真正有機會跑完，才觀察得到它對 session_context 的副作用。
    """
    import uuid as _uuid
    from contextlib import asynccontextmanager
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    import app.core.database as core_db
    from app.services.alert_service import AlertService
    from app.services.conversation_service import ConversationService

    cap = _CaptureManager()
    monkeypatch.setattr(ch, "manager", cap)
    monkeypatch.setattr(ch, "_RED_FLAG_WAIT_TIMEOUT", 0.01)

    session_context = _shared_session_context()
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
    monkeypatch.setattr(
        AlertService, "create", AsyncMock(return_value=SimpleNamespace(id=_uuid.uuid4()))
    )
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
        alerts=[make_alert(severity="critical", canonical_id="testicular_torsion")],
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

    result = asyncio.run(_body())
    assert result is False  # 本輪同步路徑走不到 abort（逾時才落地）
    assert session_context["_terminated"] == "aborted_red_flag"
    assert update_status.called


# ── _handle_audio_chunk：終態守衛在進 STT 之前就攔下 ────────────────────
class _ExplodingSTT:
    """一旦被呼叫就代表守衛沒攔下，測試應失敗。"""

    async def transcribe(self, *args, **kwargs):  # noqa: ANN001, D401
        raise AssertionError("守衛失效：已終止場次仍呼叫了 STT")

    async def close(self) -> None:
        return None


def _run_audio_chunk(session_context: dict, cap: _CaptureManager, **payload_overrides):
    payload = {"audioData": "", "isFinal": True}
    payload.update(payload_overrides)
    audio_buffer: list[bytes] = [b"leftover-chunk"]
    audio_buffer_total_bytes = [999]
    return asyncio.run(
        ch._handle_audio_chunk(
            session_id=SID,
            payload=payload,
            audio_buffer=audio_buffer,
            audio_buffer_total_bytes=audio_buffer_total_bytes,
            stt_pipeline=_ExplodingSTT(),
            llm_engine=StubLLMEngine([["不應被呼叫"]]),
            tts_pipeline=StubTTS(),
            red_flag_detector=StubDetector(alerts=[]),
            supervisor_engine=StubSupervisor(),
            system_prompt="test-system-prompt",
            conversation_history=[],
            session_context=session_context,
            redis=FakeRedis(),
            db=StubDB(),
            settings=make_settings(),
        )
    ), audio_buffer, audio_buffer_total_bytes


def test_audio_chunk_guard_skips_stt_when_already_terminated(monkeypatch):
    cap = _CaptureManager()
    monkeypatch.setattr(ch, "manager", cap)
    session_context = _shared_session_context()
    session_context["_terminated"] = "completed"

    result, audio_buffer, audio_buffer_total_bytes = _run_audio_chunk(
        session_context, cap, isFinal=False, audioData=""
    )

    assert result is True
    assert audio_buffer == []
    assert audio_buffer_total_bytes[0] == 0
    assert len(cap.messages_of_type("ai_response_start")) == 1
    assert len(cap.messages_of_type("ai_response_end")) == 1
    expected_text = get_message("ws.session_terminated_completed_notice", "zh-TW")
    assert cap.chunk_texts() == [expected_text]


def test_audio_chunk_guard_active_session_untouched(monkeypatch):
    """回歸鎖：未終止的場次不受影響——沒有旗標就完全不觸發守衛（沿用原行為）。"""
    cap = _CaptureManager()
    monkeypatch.setattr(ch, "manager", cap)
    session_context = _shared_session_context()

    # isFinal=False 且無音訊資料：既有邏輯應直接 return False（等待更多片段）。
    result = asyncio.run(
        ch._handle_audio_chunk(
            session_id=SID,
            payload={"audioData": "", "isFinal": False},
            audio_buffer=[],
            audio_buffer_total_bytes=[0],
            stt_pipeline=_ExplodingSTT(),
            llm_engine=StubLLMEngine([["不應被呼叫"]]),
            tts_pipeline=StubTTS(),
            red_flag_detector=StubDetector(alerts=[]),
            supervisor_engine=StubSupervisor(),
            system_prompt="test-system-prompt",
            conversation_history=[],
            session_context=session_context,
            redis=FakeRedis(),
            db=StubDB(),
            settings=make_settings(),
        )
    )
    assert result is False
    assert cap.messages_of_type("ai_response_start") == []
