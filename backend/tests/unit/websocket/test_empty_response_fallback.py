"""A1 [D5] 空回應守衛單元測試（e2e_realopenai_audit_2026-06-28 §三）。

守護的不變式：
- LLM 正常結束但內容空 → 單次 retry（旗標 LLM_EMPTY_RESPONSE_RETRY）→ 仍空則送
  在地化 ws.ai_empty_retry_fallback，且「直接」整句 _spawn_tts_task —— 因
  _SENTENCE_BOUNDARY_CHARS 是 CJK-only，en/ko/vi 的 ASCII '?' 切不出句子，
  走切句會變成 0 個 chunk 的空泡泡（D5 根因）。
- retry 全程吞例外：任何分支都必須送出「恰好一次」ai_response_end（VAD 不卡死）。
- 不可 early-return：紅旗 gate 照走（空回應輪的病患輸入仍要被篩檢）。
"""

from __future__ import annotations

from app.utils.i18n_messages import get_message
from tests.unit.websocket.conftest import (
    StubDetector,
    make_alert,
    make_settings,
    run_text_turn,
)

_FALLBACK_ZH = get_message("ws.ai_empty_retry_fallback", "zh-TW")
_FALLBACK_EN = get_message("ws.ai_empty_retry_fallback", "en-US")


def test_empty_then_retry_succeeds_streams_retry_text(monkeypatch):
    """第 1 次 stream 空、第 2 次正常 → 送 retry 文字、恰好 1 個 ai_response_end、
    不落入 fallback。"""
    res = run_text_turn(
        monkeypatch,
        llm_programs=[[], ["您好。", "請問還有其他症狀嗎？"]],
    )
    assert res.result is False
    assert res.llm.calls == 2
    chunks = res.cap.chunk_texts()
    assert chunks == ["您好。", "請問還有其他症狀嗎？"]
    assert _FALLBACK_ZH not in chunks
    ends = res.cap.messages_of_type("ai_response_end")
    assert len(ends) == 1
    assert ends[0]["payload"]["fullText"] == "您好。請問還有其他症狀嗎？"


def test_empty_twice_sends_localized_fallback_en_ascii_question(monkeypatch):
    """兩次皆空 + en-US → 至少 1 個「非空」chunk 且內容為完整英文 fallback
    （驗 CJK-only 切句下 ASCII '?' 訊息仍整句送出，不會變空泡泡）。"""
    res = run_text_turn(
        monkeypatch,
        language="en-US",
        llm_programs=[[], []],
    )
    assert res.llm.calls == 2
    chunks = res.cap.chunk_texts()
    assert len(chunks) == 1
    assert chunks[0] == _FALLBACK_EN
    assert chunks[0].strip()  # 非空
    assert chunks[0].endswith("?")  # ASCII 問號結尾（規格鎖定）
    ends = res.cap.messages_of_type("ai_response_end")
    assert len(ends) == 1
    assert ends[0]["payload"]["fullText"] == _FALLBACK_EN
    # 逐字稿如實反映病患聽到的內容：assistant 歷史 == fallback 文字
    assert res.conversation_history[-1]["role"] == "assistant"
    assert res.conversation_history[-1]["content"] == _FALLBACK_EN


def test_retry_raises_still_sends_ai_response_end(monkeypatch):
    """第 1 次空、第 2 次 raise → 不外拋、fallback 照送、恰好 1 個 ai_response_end
    （VAD 不卡死不變式）。"""
    res = run_text_turn(
        monkeypatch,
        llm_programs=[[], RuntimeError("boom")],
    )
    assert res.result is False
    assert res.llm.calls == 2
    chunks = res.cap.chunk_texts()
    assert chunks == [_FALLBACK_ZH]
    assert len(res.cap.messages_of_type("ai_response_end")) == 1


def test_retry_disabled_flag(monkeypatch):
    """LLM_EMPTY_RESPONSE_RETRY=False → generate_response 只被呼叫 1 次、直接送 fallback。"""
    res = run_text_turn(
        monkeypatch,
        settings=make_settings(LLM_EMPTY_RESPONSE_RETRY=False),
        llm_programs=[[], ["不該被呼叫的第二次回應。"]],
    )
    assert res.llm.calls == 1
    assert res.cap.chunk_texts() == [_FALLBACK_ZH]
    assert len(res.cap.messages_of_type("ai_response_end")) == 1


def test_no_early_return_red_flag_gate_still_runs(monkeypatch):
    """兩次皆空 + 偵測器立即回 high 紅旗 → 紅旗 gate 照走（持久化被呼叫）
    且 fallback 照送（守衛不可 early-return）。"""
    res = run_text_turn(
        monkeypatch,
        llm_programs=[[], []],
        detector=StubDetector(alerts=[make_alert(severity="high")]),
    )
    assert res.alert_create.called  # 紅旗持久化照走
    assert len(res.cap.messages_of_type("red_flag_alert")) == 1
    assert res.cap.chunk_texts() == [_FALLBACK_ZH]
    assert len(res.cap.messages_of_type("ai_response_end")) == 1
