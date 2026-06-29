"""
Unit tests for STT 幻覺 / 靜音過濾（病患回報 #1：「沒錯」被轉成「謝謝觀看」）。

覆蓋情境：
- 已知幻覺片語（中/英）正規化後比對命中 → 丟棄
- 帶標點 / 空白的幻覺片語仍命中
- 真實的簡短回答（「沒錯」「38歲」「我最近排尿會痛」）不被誤殺
- verbose_json segments 的 no_speech_prob 高 + avg_logprob 低 → 視為靜音丟棄
- 兩條件只滿足其一 → 不丟（避免誤殺小聲/簡短回答）
- segments 缺失（None / 空）時走片語路徑，不 crash
"""

from types import SimpleNamespace

import pytest

from app.pipelines.stt_pipeline import (
    STTPipeline,
    _normalize_for_match,
)


def _resp(segments=None):
    """組一個假的 verbose_json 回應物件（只含本測試用到的欄位）。"""
    return SimpleNamespace(segments=segments)


@pytest.mark.parametrize(
    "text",
    [
        "謝謝觀看",
        "謝謝觀看。",
        "謝謝大家觀看！",
        "請訂閱我的頻道",
        " Thank you for watching. ",
        "Thanks for watching",
        "ご視聴ありがとうございました",
    ],
)
def test_known_hallucination_phrases_are_dropped(text):
    assert STTPipeline._is_hallucination(text, _resp()) is True


@pytest.mark.parametrize(
    "text",
    [
        "沒錯",
        "對",
        "38歲",
        "我最近排尿會痛",
        "三天前開始的",
        "Yes that is correct",
    ],
)
def test_real_short_answers_are_preserved(text):
    assert STTPipeline._is_hallucination(text, _resp()) is False


def test_silence_dropped_when_no_speech_high_and_logprob_low():
    """整體 no_speech_prob 高且 avg_logprob 低 → 靜音兜底丟棄。"""
    segments = [
        {"no_speech_prob": 0.92, "avg_logprob": -1.8},
        {"no_speech_prob": 0.71, "avg_logprob": -1.2},
    ]
    assert STTPipeline._is_hallucination("嗯嗯嗯嗯", _resp(segments)) is True


def test_not_dropped_when_only_no_speech_high():
    """只有 no_speech 高、avg_logprob 正常 → 不丟（避免誤殺）。"""
    segments = [{"no_speech_prob": 0.9, "avg_logprob": -0.3}]
    assert STTPipeline._is_hallucination("我有點不舒服", _resp(segments)) is False


def test_not_dropped_when_only_logprob_low():
    """只有 avg_logprob 低、no_speech 正常 → 不丟。"""
    segments = [{"no_speech_prob": 0.1, "avg_logprob": -2.5}]
    assert STTPipeline._is_hallucination("我有點不舒服", _resp(segments)) is False


def test_segments_object_attribute_access():
    """segments 為物件（非 dict）時用屬性存取也要能判定靜音。"""
    segments = [SimpleNamespace(no_speech_prob=0.95, avg_logprob=-2.0)]
    assert STTPipeline._is_hallucination("……", _resp(segments)) is True


def test_missing_segments_falls_back_to_phrase_match_only():
    """segments 缺失時不 crash；非幻覺片語的正常文字應保留。"""
    assert STTPipeline._is_hallucination("我最近頻尿", _resp(None)) is False
    assert STTPipeline._is_hallucination("謝謝觀看", _resp(None)) is True


def test_normalize_strips_punctuation_and_spaces():
    assert _normalize_for_match("謝謝觀看。") == "謝謝觀看"
    assert _normalize_for_match(" Thank you for watching! ") == "thankyouforwatching"
    assert _normalize_for_match("沒錯") == "沒錯"
