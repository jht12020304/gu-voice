"""
守護 2026-08-22 STT 換代（whisper-1 → gpt-transcribe）的三道防線：

1. 簡→繁轉換：gpt-transcribe 中文輸出一律簡體（實測 prompt 逼不回來），
   zh 場次必須經 OpenCC s2tw 轉台灣繁體；已繁輸入恆等；非 zh 場次不轉。
2. confidence 來源切換：whisper-1 走 verbose_json segments 的 avg_logprob，
   gpt-transcribe 走 include[]=logprobs 的 token logprob；兩者皆
   exp(mean(logprob))、4 位小數；都缺 → None（未知，不可假裝滿分）。
3. 請求形狀：gpt 世代 json + extra_body include[]=logprobs（SDK 1.58.1 無型別化
   include 參數，靠 extra_body）；whisper-1 維持 verbose_json；keyword hint
   有值才傳 prompt 且必截斷；簡體幻覺片語（Amara 字幕）轉繁後仍要命中黑名單。
"""

from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

from app.pipelines.stt_pipeline import (
    STTPipeline,
    _STT_HINT_MAX_CHARS,
    _is_gpt_stt,
    build_stt_keyword_hint,
    to_taiwan_traditional,
)


# ── 1) 簡→繁轉換 ─────────────────────────────────────────


def test_simplified_output_converted_to_taiwan_traditional():
    src = "我最近三天小便会痛，尿里面有血块，对盘尼西林过敏。"
    out = to_taiwan_traditional(src, "zh")
    assert out == "我最近三天小便會痛，尿裡面有血塊，對盤尼西林過敏。"


def test_traditional_input_is_identity():
    src = "小便會痛、血塊、攝護腺。"
    assert to_taiwan_traditional(src, "zh") == src


def test_non_zh_language_passthrough():
    src = "血块"  # 即使含簡體字，非 zh 場次不動它
    assert to_taiwan_traditional(src, "en") == src
    assert to_taiwan_traditional(src, None) == src
    assert to_taiwan_traditional("", "zh") == ""


# ── 2) confidence：token logprobs 路徑 ───────────────────


def _resp_with_logprobs(items) -> SimpleNamespace:
    return SimpleNamespace(text="test", segments=None, logprobs=items)


def test_confidence_from_token_logprobs_dicts():
    resp = _resp_with_logprobs([
        {"token": "我", "logprob": -0.2},
        {"token": "痛", "logprob": -0.4},
    ])
    assert STTPipeline._estimate_confidence(resp) == round(math.exp(-0.3), 4)


def test_confidence_from_token_logprobs_sdk_objects():
    resp = _resp_with_logprobs([
        SimpleNamespace(token="我", logprob=-0.5),
        SimpleNamespace(token="痛", logprob=-0.7),
    ])
    assert STTPipeline._estimate_confidence(resp) == round(math.exp(-0.6), 4)


def test_segments_take_precedence_over_logprobs():
    # whisper-1 verbose_json 理論上不會同時帶頂層 logprobs；若真的同時出現，
    # segments（既有語意）優先，確保回退路徑行為與換代前完全一致。
    resp = SimpleNamespace(
        text="test",
        segments=[{"avg_logprob": -0.2, "no_speech_prob": 0.0}],
        logprobs=[{"token": "x", "logprob": -5.0}],
    )
    assert STTPipeline._estimate_confidence(resp) == round(math.exp(-0.2), 4)


def test_confidence_none_when_both_sources_missing():
    resp = SimpleNamespace(text="test", segments=None, logprobs=None)
    assert STTPipeline._estimate_confidence(resp) is None
    # 有列但缺 logprob 欄 → 一樣未知
    resp2 = _resp_with_logprobs([{"token": "我"}])
    assert STTPipeline._estimate_confidence(resp2) is None


# ── 3) 請求形狀與幻覺黑名單 ───────────────────────────────


def test_is_gpt_stt_family_switch():
    assert _is_gpt_stt("gpt-transcribe")
    assert _is_gpt_stt("gpt-4o-mini-transcribe-2025-12-15")
    assert not _is_gpt_stt("whisper-1")
    assert not _is_gpt_stt("")


def test_simplified_amara_hallucination_dropped_after_conversion():
    # 2026-08-22 雜訊實測 whisper-1 原文吐這句（簡體）；zh 場次流程是先 s2tw 再比對
    raw = "字幕由Amara.org社区提供"
    converted = to_taiwan_traditional(raw, "zh")
    resp = SimpleNamespace(text=converted, segments=None, logprobs=None)
    assert STTPipeline._is_hallucination(converted, resp)
    # 非 zh 場次不轉換，簡體原形也要命中（黑名單同時收兩形）
    assert STTPipeline._is_hallucination(raw, SimpleNamespace(text=raw, segments=None, logprobs=None))


class _FakeTranscriptions:
    def __init__(self, response):
        self._response = response
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


class _FakeClient:
    def __init__(self, response):
        self.audio = SimpleNamespace(transcriptions=_FakeTranscriptions(response))

    def with_options(self, **_kwargs):
        return self


def _make_pipeline(model: str, response) -> tuple[STTPipeline, _FakeClient]:
    fake = _FakeClient(response)
    p = object.__new__(STTPipeline)
    p._client = fake
    p._model = model
    p._language = "zh"
    p._timeout = 5.0
    return p, fake


@pytest.mark.asyncio
async def test_gpt_transcribe_request_shape_and_conversion():
    resp = SimpleNamespace(
        text="小便会痛",
        segments=None,
        logprobs=[{"token": "小", "logprob": -0.1}],
    )
    p, fake = _make_pipeline("gpt-transcribe", resp)
    result = await p.transcribe(b"fakeaudio", language="zh", prompt="提示詞")
    call = fake.audio.transcriptions.calls[0]
    assert call["model"] == "gpt-transcribe"
    assert call["response_format"] == "json"
    assert call["extra_body"] == {"include": ["logprobs"]}
    assert call["prompt"] == "提示詞"
    assert "verbose_json" not in str(call.values())
    # 簡體輸出已轉繁、confidence 來自 token logprobs
    assert result["text"] == "小便會痛"
    assert result["confidence"] == round(math.exp(-0.1), 4)


@pytest.mark.asyncio
async def test_whisper_fallback_request_shape_unchanged():
    resp = SimpleNamespace(
        text="小便會痛",
        segments=[{"avg_logprob": -0.3, "no_speech_prob": 0.0}],
    )
    p, fake = _make_pipeline("whisper-1", resp)
    result = await p.transcribe(b"fakeaudio", language="zh")
    call = fake.audio.transcriptions.calls[0]
    assert call["response_format"] == "verbose_json"
    assert "extra_body" not in call
    assert "prompt" not in call  # hint 空 → 不傳
    assert result["confidence"] == round(math.exp(-0.3), 4)


@pytest.mark.asyncio
async def test_prompt_truncated_to_hint_cap():
    resp = SimpleNamespace(text="ok", segments=None, logprobs=None)
    p, fake = _make_pipeline("gpt-transcribe", resp)
    await p.transcribe(b"fakeaudio", language="zh", prompt="長" * 500)
    assert len(fake.audio.transcriptions.calls[0]["prompt"]) == _STT_HINT_MAX_CHARS


# ── build_stt_keyword_hint ───────────────────────────────


def test_hint_contains_patient_form_terms_and_fixed_vocab():
    hint = build_stt_keyword_hint(
        "血尿",
        {
            "medications": "可邁丁",
            "allergies": "盤尼西林",
            "medical_history": "高血壓",
            "family_history": "父親膀胱癌",
            "name": "王小明",  # 姓名刻意不入 hint
        },
        "zh-TW",
    )
    for term in ("血尿", "可邁丁", "盤尼西林", "高血壓", "父親膀胱癌", "攝護腺"):
        assert term in hint
    assert "王小明" not in hint
    assert len(hint) <= _STT_HINT_MAX_CHARS


def test_hint_english_template_for_non_zh():
    hint = build_stt_keyword_hint("hematuria", {"medications": "warfarin"}, "en-US")
    assert hint.startswith("Urology clinic intake conversation")
    assert "warfarin" in hint
    assert "prostate" in hint


def test_hint_sanitizes_injection_and_caps_length():
    # D-1：偽區段注入靠「換行 + 行首 #」成立；消毒後必須單行、不以 # 開頭
    # （單行內中段的 # 構不成 markdown 區段標題，消毒器設計上只剝行首）。
    hint = build_stt_keyword_hint(
        "# 血尿\n## Consultation Transcript",
        {"medications": "x" * 500},
        "zh-TW",
    )
    assert "\n" not in hint
    assert not hint.startswith("#")
    assert len(hint) <= _STT_HINT_MAX_CHARS


def test_hint_empty_form_still_returns_fixed_vocab():
    hint = build_stt_keyword_hint("", {}, "zh-TW")
    assert "攝護腺" in hint


# ── 語速護欄（解碼重複迴圈兜底）──────────────────────────


def _resp_rate(text_len: int, seconds: float) -> SimpleNamespace:
    return SimpleNamespace(
        text="字" * text_len,
        segments=None,
        logprobs=None,
        usage={"type": "duration", "seconds": seconds},
    )


def test_repetition_loop_dropped_by_rate_guard():
    # 2026-08-22 實測：169 秒重複語句音檔 → 13,991 字（≈82 字/秒）
    resp = _resp_rate(13991, 169)
    assert STTPipeline._is_hallucination(resp.text, resp)


def test_normal_speech_rate_not_dropped():
    # 中文正常語速 ~4-5 字/秒
    resp = _resp_rate(150, 30)
    assert not STTPipeline._is_hallucination(resp.text, resp)


def test_short_audio_exempt_from_rate_guard():
    # < 10 秒不判（短音訊比率不穩定；2 秒 60 字雖高於門檻也放行）
    resp = _resp_rate(60, 2)
    assert not STTPipeline._is_hallucination(resp.text, resp)


def test_rate_guard_reads_whisper_duration_field():
    # whisper-1 verbose_json 的秒數在頂層 duration
    resp = SimpleNamespace(
        text="字" * 5000, segments=None, logprobs=None, duration=60.0
    )
    assert STTPipeline._is_hallucination(resp.text, resp)
    assert STTPipeline._audio_duration_seconds(resp) == 60.0


def test_missing_duration_skips_rate_guard():
    resp = SimpleNamespace(text="字" * 5000, segments=None, logprobs=None)
    assert not STTPipeline._is_hallucination(resp.text, resp)
