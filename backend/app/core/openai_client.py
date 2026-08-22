"""
OpenAI 客戶端：統一 singleton + timeout + tenacity retry + tiktoken 預算控制。

設計目標：
- 所有 pipeline 共用同一個 AsyncOpenAI 實體，避免每個 pipeline 各自建 HTTP client 池
- 短暫失敗（429 / timeout / 連線錯）以 tenacity 指數退避重試
- 送出前用 tiktoken 估算 token 總量，超過 context window 時從歷史頭部截斷（保留 system）
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Optional, TypeVar

import tiktoken
from openai import APIConnectionError, APITimeoutError, AsyncOpenAI, RateLimitError
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T")

# 各模型 context window（tokens）。未列名稱走保守 128k。
_MODEL_CONTEXT_LIMIT: dict[str, int] = {
    "gpt-4o": 128_000,
    "gpt-4o-mini": 128_000,
    "gpt-4.1": 128_000,
    "gpt-4.1-mini": 128_000,
    "o1": 200_000,
    "o1-mini": 128_000,
    "o3": 200_000,
    "o3-mini": 200_000,
    "gpt-5": 200_000,
}

DEFAULT_TIMEOUT_SECONDS = 60.0

_client: Optional[AsyncOpenAI] = None


def get_openai_client() -> AsyncOpenAI:
    """Singleton AsyncOpenAI（timeout=60s）。首次呼叫時 lazy 建立。"""
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=settings.OPENAI_API_KEY,
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )
    return _client


async def reset_openai_client() -> None:
    """關閉並清除 singleton。主要給測試、app shutdown 使用。"""
    global _client
    if _client is not None:
        try:
            await _client.close()
        except Exception:  # noqa: BLE001
            pass
        _client = None


def _retryable_errors() -> tuple[type[Exception], ...]:
    return (APITimeoutError, RateLimitError, APIConnectionError)


async def call_with_retry(
    coro_factory: Callable[[], Awaitable[T]],
    *,
    attempts: int = 3,
    wait_min: float = 1.0,
    wait_max: float = 10.0,
) -> T:
    """
    執行可能短暫失敗的 OpenAI 呼叫。429 / timeout / connection error 指數退避重試。

    Usage:
        resp = await call_with_retry(
            lambda: client.chat.completions.create(model=..., messages=...)
        )

    注意：streaming 呼叫（stream=True）只能在 `create()` 本身失敗時重試，
    一旦 stream 開始就不應該重試，否則輸出會重複。
    """
    retrying = AsyncRetrying(
        stop=stop_after_attempt(attempts),
        wait=wait_exponential(multiplier=1, min=wait_min, max=wait_max),
        retry=retry_if_exception_type(_retryable_errors()),
        reraise=True,
    )
    async for attempt in retrying:
        with attempt:
            return await coro_factory()
    # unreachable, reraise=True 會在最後一次失敗時拋出例外
    raise RuntimeError("call_with_retry: unreachable")


def model_context_limit(model: str) -> int:
    """查模型 context window 上限，未知名走 128k。"""
    for prefix, limit in _MODEL_CONTEXT_LIMIT.items():
        if model.startswith(prefix):
            return limit
    return 128_000


def _encoding_for(model: str) -> tiktoken.Encoding:
    try:
        return tiktoken.encoding_for_model(model)
    except KeyError:
        return tiktoken.get_encoding("cl100k_base")


def count_tokens(messages: list[dict[str, Any]], model: str) -> int:
    """粗估 chat messages 總 token 數。每則 +4 framing tokens、priming +2。"""
    enc = _encoding_for(model)
    total = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total += len(enc.encode(content))
        total += 4
    total += 2
    return total


def budget_messages(
    messages: list[dict[str, Any]],
    model: str,
    max_output_tokens: int,
    reserve: int = 256,
) -> list[dict[str, Any]]:
    """
    若訊息總 token 超過 `context_limit - max_output_tokens - reserve`，
    保留第一則 system prompt、從頭部開始丟舊訊息，直到符合 budget。

    回傳新 list，不動到原始輸入。
    """
    budget = model_context_limit(model) - max_output_tokens - reserve
    if budget <= 0:
        logger.warning("budget_messages: budget<=0 model=%s max_output=%d", model, max_output_tokens)
        return list(messages)

    if count_tokens(messages, model) <= budget:
        return list(messages)

    has_system_head = bool(messages) and messages[0].get("role") == "system"
    head = [messages[0]] if has_system_head else []
    tail = list(messages[1:]) if has_system_head else list(messages)

    while tail and count_tokens(head + tail, model) > budget:
        tail.pop(0)

    truncated = head + tail
    logger.info(
        "budget_messages truncated %d -> %d | model=%s budget=%d",
        len(messages), len(truncated), model, budget,
    )
    return truncated

# ── 模型能力判斷（2026-08-22）─────────────────────────────────────────────
# 取樣參數的相容性是「模型家族」的屬性，不是 config 約定的屬性。歷史上每條管線
# 各自靠 OPENAI_REASONING_EFFORT_*=="none" 這個字串約定決定送 temperature 還是
# reasoning_effort，結果 SOAP／紅旗根本沒有這個分支（無條件送 temperature），
# 一換 gpt-5.6 就整條 400。集中在這裡，五個呼叫點共用。
#
# 實測（2026-08-22，gpt-5.6-luna / terra）：
#   - temperature=0.7 → 400「Only the default (1) value is supported」
#   - reasoning_effort="none" → 200，reasoning_tokens=0（合法 API 值＝關閉 CoT）
#   - reasoning_effort="minimal" → 400（gpt-5.6 不支援，別照 gpt-5 初代文件抄）
def is_reasoning_model(model: str) -> bool:
    """gpt-5 系列與 o 系列：拒收非預設 temperature、接受 reasoning_effort。"""
    m = (model or "").lower()
    return m.startswith(("gpt-5", "o1", "o3", "o4"))


def sampling_kwargs(model: str, *, effort: str | None, temperature: float) -> dict:
    """回傳該模型接受的取樣參數。

    reasoning 家族 → {"reasoning_effort": effort 或 "none"}（"none" 是合法 API 值，
    代表關 CoT、走最快路徑）；傳統家族（gpt-4o / gpt-4.1）→ {"temperature": ...}。
    config 的 OPENAI_REASONING_EFFORT_* 語意隨之簡化：它就是 reasoning 家族的
    effort 值，模型不是 reasoning 家族時被忽略。
    """
    if is_reasoning_model(model):
        return {"reasoning_effort": effort or "none"}
    return {"temperature": temperature}


def cache_kwargs(session_id: str | None) -> dict:
    """回傳 prompt caching 路由參數（2026-08-22，接在每輪熱路徑上）。

    問診每一輪都重送「session 專屬 system prompt + 累積對話」，但所有場次的
    system prompt **開頭**是同一段靜態模板——OpenAI 預設以 prompt 前綴 hash 路由
    快取，全部場次會擠到同一批快取分片。`prompt_cache_key` 讓路由改按場次分散，
    提升並發下的 cache 命中率（Luna cached input 為原價 1/10；2026-08-22 實測
    gpt-5.6-luna 第二呼叫 2474/2497 tokens 命中）。

    SDK 1.58.1 沒有型別化的 prompt_cache_key 參數，經 extra_body 傳遞（實測可用）。
    session_id 缺失時回空 dict（照常自動快取，只是不帶路由 key）。
    ⚠️ 只該用在「同一前綴會重複出現」的呼叫（對話/supervisor/紅旗語意層每輪），
    一次性呼叫（SOAP、summarizer）加了沒意義。
    """
    if not session_id or session_id == "unknown":
        return {}
    return {"extra_body": {"prompt_cache_key": f"sess-{session_id}"}}

