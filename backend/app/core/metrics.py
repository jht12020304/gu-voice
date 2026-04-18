"""
Prometheus metrics 註冊 + 埋點輔助（TODO-O2）。

目的
────
i18n 上線後要能從 `/metrics` 同時觀察：
  1. 各語言 session 建立量 — 量測 rollout 覆蓋範圍
  2. 各語言 × 雙層 (rule / semantic) 紅旗命中數 — 驗證 red-flag precision 不被語言退化
  3. 未支援語言請求量 — 評估要不要擴 SUPPORTED_LANGUAGES
  4. STT / TTS 延遲分佈 — catch 不同語言 model 的延遲退化
  5. Forced fallback（kill switch / rollout bucket 踢出）次數 — 確認 kill switch 觸發頻率

所有 Counter / Histogram 的命名遵循 Prometheus 慣例（snake_case + `_total` / `_seconds`）。
Histogram buckets 針對 OpenAI Whisper / TTS 的實測分佈設計，覆蓋 50ms～30s。

使用方式
────────
各呼叫端只動 `metrics.XXX.labels(...).inc()` / `.observe(...)`，不要 import
prometheus_client 本身，讓 metric 定義集中可 review。
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Iterator

from prometheus_client import Counter, Histogram

# ── 共用 bucket 規格 ──────────────────────────────────
# STT / TTS OpenAI 延遲在 200ms～10s 間最密集，預留 30s 以捕捉超時尾巴
_LATENCY_BUCKETS_SECONDS = (
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.0,
    5.0,
    10.0,
    20.0,
    30.0,
)


# ── 1) Session 建立數 ─────────────────────────────────
SESSIONS_TOTAL: Counter = Counter(
    "urovoice_sessions_total",
    "Total number of patient sessions created, labelled by resolved language.",
    ["language"],
)


# ── 2) 紅旗命中數（雙層） ─────────────────────────────
# layer 固定兩個值：rule / semantic（combined 拆回兩層各 +1，
# 方便分開算 precision；後續合併統計用 sum(layer="rule")+sum(layer="semantic") 即可）
RED_FLAG_TRIGGERS: Counter = Counter(
    "urovoice_red_flag_triggers_total",
    "Red flag alert triggers by language and detection layer (rule|semantic).",
    ["language", "layer"],
)


# ── 3) 未支援語言請求 ─────────────────────────────────
UNSUPPORTED_LANG_REQUESTS: Counter = Counter(
    "urovoice_unsupported_language_requests_total",
    "Requests that asked for a language not in SUPPORTED_LANGUAGES; "
    "label `requested` is the normalised BCP-47 code (or 'unknown').",
    ["requested"],
)


# ── 4) STT / TTS 延遲 ────────────────────────────────
STT_LATENCY: Histogram = Histogram(
    "urovoice_stt_latency_seconds",
    "Speech-to-text end-to-end latency (OpenAI Whisper call) in seconds.",
    ["language"],
    buckets=_LATENCY_BUCKETS_SECONDS,
)

TTS_LATENCY: Histogram = Histogram(
    "urovoice_tts_latency_seconds",
    "Text-to-speech end-to-end latency (OpenAI TTS call) in seconds.",
    ["language"],
    buckets=_LATENCY_BUCKETS_SECONDS,
)


# ── 5) Forced fallback（kill switch / rollout gate 觸發） ─
# 例：使用者要求 en-US 但該語言在 MULTILANG_DISABLED_LANGUAGES → 退 zh-TW，
# label from="en-US", to="zh-TW"
FORCED_FALLBACK: Counter = Counter(
    "urovoice_forced_fallback_total",
    "Times a requested language was overridden by kill switch / rollout gate.",
    ["from", "to"],
)


# ── 6) 紅旗 rule-layer coverage SLO（TODO-O4） ───────────
# Ratio metric 用「兩個 Counter + PromQL 計算」而非 Gauge;
# Grafana 端用 rule_hit / (rule_hit + semantic_only) 即可得 rolling window coverage。
# labels:
#   language    — BCP-47 session 語言(限 SUPPORTED_LANGUAGES,避免 cardinality 爆炸)
#   confidence  — rule_hit / semantic_only / uncovered_locale(TODO-M8 同源)
RED_FLAG_RULE_LAYER_COVERAGE: Counter = Counter(
    "urovoice_red_flag_rule_layer_coverage_total",
    (
        "Red flag detection hits by language and confidence level "
        "(rule_hit | semantic_only | uncovered_locale). Coverage ratio = "
        "rule_hit / (rule_hit + semantic_only) per language; Grafana alert "
        "fires when a locale's ratio < 0.5 * zh-TW with n>=30 in 1h."
    ),
    ["language", "confidence"],
)


# ── 埋點輔助 ─────────────────────────────────────────
def record_session_created(language: str) -> None:
    """Session 建立成功後呼叫一次。language 必填（由 resolve_language 保證非空）。"""
    SESSIONS_TOTAL.labels(language=language or "unknown").inc()


def record_red_flag_triggers(
    language: str | None,
    rule_count: int,
    semantic_count: int,
) -> None:
    """
    給 detector.detect() 在回傳前呼叫。count 為該層命中的 alert 數，0 代表沒命中。

    `combined` alert（兩層都命中）不重複算：detector 端把 rule / semantic list
    各自計數傳入即可，不要用 merge 後的 list。
    """
    lang = language or "unknown"
    if rule_count > 0:
        RED_FLAG_TRIGGERS.labels(language=lang, layer="rule").inc(rule_count)
    if semantic_count > 0:
        RED_FLAG_TRIGGERS.labels(language=lang, layer="semantic").inc(semantic_count)


def record_unsupported_language(requested: str | None) -> None:
    """resolve_language 遇到 payload / header 不在 SUPPORTED_LANGUAGES 時呼叫。"""
    UNSUPPORTED_LANG_REQUESTS.labels(requested=requested or "unknown").inc()


def record_forced_fallback(from_lang: str | None, to_lang: str) -> None:
    """kill switch / rollout bucket / disabled list 觸發時，記 requested → actual 的位移。"""
    FORCED_FALLBACK.labels(**{"from": from_lang or "unknown", "to": to_lang}).inc()


def record_red_flag_rule_layer_coverage(
    language: str | None, confidence: str
) -> None:
    """
    記錄一筆紅旗偵測的 (language, confidence) 覆蓋度樣本（TODO-O4）。

    由 RedFlagDetector 在每次偵測（不論 rule-based / semantic-only /
    uncovered_locale）回傳前呼叫一次。metric 失敗不應 crash 主流程。

    Args:
        language: BCP-47 語言碼；None → "unknown"
        confidence: rule_hit / semantic_only / uncovered_locale
    """
    try:
        RED_FLAG_RULE_LAYER_COVERAGE.labels(
            language=language or "unknown",
            confidence=confidence,
        ).inc()
    except Exception:  # pragma: no cover — metric failure is never fatal
        import logging
        logging.getLogger(__name__).debug(
            "record_red_flag_rule_layer_coverage failed (silently ignored)",
            exc_info=True,
        )


@contextmanager
def observe_stt_latency(language: str | None) -> Iterator[None]:
    """包住 STT 呼叫，結束時 observe。異常不會吞，但延遲仍會記錄（便於算 timeout 分佈）。"""
    start = time.perf_counter()
    try:
        yield
    finally:
        STT_LATENCY.labels(language=language or "unknown").observe(
            time.perf_counter() - start
        )


@contextmanager
def observe_tts_latency(language: str | None) -> Iterator[None]:
    start = time.perf_counter()
    try:
        yield
    finally:
        TTS_LATENCY.labels(language=language or "unknown").observe(
            time.perf_counter() - start
        )


# 讓外部可 import 整組名稱，供測試斷言 metric registration 成功
__all__ = [
    "SESSIONS_TOTAL",
    "RED_FLAG_TRIGGERS",
    "RED_FLAG_RULE_LAYER_COVERAGE",
    "UNSUPPORTED_LANG_REQUESTS",
    "STT_LATENCY",
    "TTS_LATENCY",
    "FORCED_FALLBACK",
    "record_session_created",
    "record_red_flag_triggers",
    "record_red_flag_rule_layer_coverage",
    "record_unsupported_language",
    "record_forced_fallback",
    "observe_stt_latency",
    "observe_tts_latency",
]
