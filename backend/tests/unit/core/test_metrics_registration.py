"""
驗證 Prometheus metric 名稱 / label 與 /metrics 輸出（TODO-O2）。

這些 assertion 等於把 metric 的 public contract 固化 —
任何人改動 metric 名稱或 label 都會讓這組測試失敗，
提醒 reviewer 同步更新 Grafana dashboard JSON 與 alert rule。
"""

from __future__ import annotations

import pytest
from prometheus_client import REGISTRY, generate_latest

from app.core import metrics as m


@pytest.mark.parametrize(
    "attr, expected_name, expected_labels",
    [
        # prometheus-client 內部 `_name` 會把 Counter 的 `_total` suffix 自動 strip，
        # 但最終 /metrics 輸出與 promql query 仍以 `_total` 結尾；我們在 test_metrics_registered_in_default_registry
        # 以實際 generate_latest 輸出驗證 `_total` 後綴。
        ("SESSIONS_TOTAL", "urovoice_sessions", {"language"}),
        (
            "RED_FLAG_TRIGGERS",
            "urovoice_red_flag_triggers",
            {"language", "layer"},
        ),
        (
            "UNSUPPORTED_LANG_REQUESTS",
            "urovoice_unsupported_language_requests",
            {"requested"},
        ),
        ("STT_LATENCY", "urovoice_stt_latency_seconds", {"language"}),
        ("TTS_LATENCY", "urovoice_tts_latency_seconds", {"language"}),
        ("FORCED_FALLBACK", "urovoice_forced_fallback", {"from", "to"}),
    ],
)
def test_metric_name_and_labels(attr: str, expected_name: str, expected_labels: set[str]) -> None:
    """metric 的 ._name 與 ._labelnames 是 prometheus-client 的公開屬性（Counter/Histogram 都有）。"""
    metric = getattr(m, attr)
    assert metric._name == expected_name
    assert set(metric._labelnames) == expected_labels


def test_metrics_registered_in_default_registry() -> None:
    """確認 metric 確實註冊到 prometheus_client default REGISTRY，能被 /metrics endpoint 拉到。"""
    # 觸發一次 label 組合，確保該系列會出現在 /metrics 輸出（未 label 的 Counter 不會有樣本行）
    m.SESSIONS_TOTAL.labels(language="zh-TW").inc(0)
    m.RED_FLAG_TRIGGERS.labels(language="zh-TW", layer="rule").inc(0)
    m.UNSUPPORTED_LANG_REQUESTS.labels(requested="fr-FR").inc(0)
    m.FORCED_FALLBACK.labels(**{"from": "fr-FR", "to": "zh-TW"}).inc(0)
    m.STT_LATENCY.labels(language="zh-TW").observe(0.1)
    m.TTS_LATENCY.labels(language="zh-TW").observe(0.1)

    output = generate_latest(REGISTRY).decode("utf-8")
    for expected in (
        "urovoice_sessions_total",
        "urovoice_red_flag_triggers_total",
        "urovoice_unsupported_language_requests_total",
        "urovoice_stt_latency_seconds",
        "urovoice_tts_latency_seconds",
        "urovoice_forced_fallback_total",
    ):
        assert expected in output, f"metric {expected!r} 未出現在 /metrics 輸出"


def test_record_session_created_increments() -> None:
    before = m.SESSIONS_TOTAL.labels(language="en-US")._value.get()
    m.record_session_created("en-US")
    after = m.SESSIONS_TOTAL.labels(language="en-US")._value.get()
    assert after - before == 1


def test_record_red_flag_triggers_splits_layers() -> None:
    before_rule = m.RED_FLAG_TRIGGERS.labels(language="en-US", layer="rule")._value.get()
    before_sem = m.RED_FLAG_TRIGGERS.labels(language="en-US", layer="semantic")._value.get()

    m.record_red_flag_triggers(language="en-US", rule_count=2, semantic_count=3)

    assert (
        m.RED_FLAG_TRIGGERS.labels(language="en-US", layer="rule")._value.get()
        - before_rule
        == 2
    )
    assert (
        m.RED_FLAG_TRIGGERS.labels(language="en-US", layer="semantic")._value.get()
        - before_sem
        == 3
    )


def test_record_red_flag_triggers_zero_is_noop() -> None:
    """0 個命中不應該 inc（否則會讓 rate 出現 0 樣本污染）。"""
    before_rule = m.RED_FLAG_TRIGGERS.labels(language="ja-JP", layer="rule")._value.get()
    m.record_red_flag_triggers(language="ja-JP", rule_count=0, semantic_count=0)
    assert (
        m.RED_FLAG_TRIGGERS.labels(language="ja-JP", layer="rule")._value.get()
        == before_rule
    )


def test_record_unsupported_language_handles_none() -> None:
    """None 應降級為 "unknown"，不可 raise（避免壞掉 language resolution 主路徑）。"""
    m.record_unsupported_language(None)
    output = generate_latest(REGISTRY).decode("utf-8")
    assert 'requested="unknown"' in output


def test_record_forced_fallback_label_keys() -> None:
    """label key 是 Python reserved word `from`，必須用 **kwargs 傳；測試確保不 raise。"""
    m.record_forced_fallback("ko-KR", "zh-TW")
    output = generate_latest(REGISTRY).decode("utf-8")
    assert 'from="ko-KR"' in output
    assert 'to="zh-TW"' in output


def test_observe_stt_latency_records_sample() -> None:
    import time

    before_count = m.STT_LATENCY.labels(language="en-US")._sum.get()
    with m.observe_stt_latency("en-US"):
        time.sleep(0.01)
    after_count = m.STT_LATENCY.labels(language="en-US")._sum.get()
    assert after_count > before_count, "STT latency 未被記錄"


def _histogram_count(histogram, **labels):
    """Histogram 的 count 取法跨版本不穩定；用 collect() 抽 `_count` sample 最可靠。"""
    for metric in histogram.collect():
        for sample in metric.samples:
            if sample.name.endswith("_count") and sample.labels == labels:
                return sample.value
    return 0.0


def test_observe_tts_latency_records_even_on_exception() -> None:
    """TTS 呼叫失敗也要記一筆延遲 sample（用來算 timeout 尾巴分佈）。"""
    before_count = _histogram_count(m.TTS_LATENCY, language="zh-TW")
    with pytest.raises(RuntimeError):
        with m.observe_tts_latency("zh-TW"):
            raise RuntimeError("simulate TTS failure")
    after_count = _histogram_count(m.TTS_LATENCY, language="zh-TW")
    assert after_count - before_count == 1
