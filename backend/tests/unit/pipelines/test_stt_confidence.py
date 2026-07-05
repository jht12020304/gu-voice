"""
守護 STT 真實信心分數（session_data_inventory §11-2 修復）：

- `_estimate_confidence` 由 verbose_json segments 的 avg_logprob 估算
  exp(mean(avg_logprob))，clamp 到 [0, 1]、四捨五入 4 位
  （對齊 conversations.stt_confidence Numeric(5,4)）。
- segments 缺失 → None（未知），不可再假裝 1.0 滿分。
- dict 與 SDK 物件兩種 segment 形狀都要支援（_segment_stats 共用）。
"""

from __future__ import annotations

import math
from types import SimpleNamespace

from app.pipelines.stt_pipeline import STTPipeline


def _resp(segments) -> SimpleNamespace:
    return SimpleNamespace(text="test", segments=segments)


def test_confidence_is_exp_of_mean_avg_logprob():
    resp = _resp([
        {"avg_logprob": -0.2, "no_speech_prob": 0.01},
        {"avg_logprob": -0.4, "no_speech_prob": 0.02},
    ])
    expected = round(math.exp((-0.2 + -0.4) / 2), 4)
    assert STTPipeline._estimate_confidence(resp) == expected


def test_confidence_none_without_segments():
    assert STTPipeline._estimate_confidence(_resp([])) is None
    assert STTPipeline._estimate_confidence(_resp(None)) is None
    # segments 有列但缺 avg_logprob 欄 → 一樣未知
    assert STTPipeline._estimate_confidence(_resp([{"no_speech_prob": 0.1}])) is None


def test_confidence_clamped_to_unit_interval_and_rounded():
    # avg_logprob > 0 理論上不會發生，但防禦性 clamp 不可超過 1.0
    assert STTPipeline._estimate_confidence(_resp([{"avg_logprob": 0.5}])) == 1.0
    # 極低 logprob → 接近 0，不為負
    val = STTPipeline._estimate_confidence(_resp([{"avg_logprob": -20.0}]))
    assert val is not None and 0.0 <= val < 0.001
    # 4 位小數（Numeric(5,4) 對齊）
    val2 = STTPipeline._estimate_confidence(_resp([{"avg_logprob": -0.333333}]))
    assert val2 == round(val2, 4)


def test_segment_stats_supports_sdk_objects():
    resp = _resp([
        SimpleNamespace(avg_logprob=-0.5, no_speech_prob=0.3),
        SimpleNamespace(avg_logprob=-0.7, no_speech_prob=0.4),
    ])
    nsp, alp = STTPipeline._segment_stats(resp)
    assert nsp == [0.3, 0.4]
    assert alp == [-0.5, -0.7]
    assert STTPipeline._estimate_confidence(resp) == round(math.exp(-0.6), 4)


def test_hallucination_detection_unaffected_by_refactor():
    """幻覺判定（片語 + 靜音兜底）沿用 _segment_stats，行為不變。"""
    silent = _resp([{"avg_logprob": -1.5, "no_speech_prob": 0.9}])
    assert STTPipeline._is_hallucination("嗯", silent) is True
    normal = _resp([{"avg_logprob": -0.2, "no_speech_prob": 0.05}])
    assert STTPipeline._is_hallucination("我最近血尿", normal) is False
    assert STTPipeline._is_hallucination("謝謝觀看", normal) is True
