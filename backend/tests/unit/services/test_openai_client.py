"""
Unit tests for `app.core.openai_client`（TODO P1-#7）。

涵蓋：
- singleton：兩次 get_openai_client() 回傳同一實體
- call_with_retry：對 RateLimitError / APITimeoutError / APIConnectionError 退避後成功
- call_with_retry：非預期例外直接 propagate，不重試
- call_with_retry：超過重試上限後最終 raise
- count_tokens / budget_messages：超量時保留 system 並從頭部丟舊訊息
"""

from __future__ import annotations

import asyncio

import httpx
import pytest
from openai import APIConnectionError, APITimeoutError, RateLimitError

from app.core import openai_client as oa
from app.core.openai_client import (
    budget_messages,
    call_with_retry,
    count_tokens,
    get_openai_client,
)


def _run(coro):
    return asyncio.run(coro)


def _timeout_error() -> APITimeoutError:
    return APITimeoutError(httpx.Request("POST", "http://example.com/v1"))


def _rate_limit_error() -> RateLimitError:
    req = httpx.Request("POST", "http://example.com/v1")
    resp = httpx.Response(status_code=429, request=req)
    return RateLimitError("rate limited", response=resp, body=None)


def _conn_error() -> APIConnectionError:
    return APIConnectionError(request=httpx.Request("POST", "http://example.com/v1"))


# ──────────────────────────────────────────────────────
# Singleton
# ──────────────────────────────────────────────────────

def test_get_openai_client_is_singleton():
    a = get_openai_client()
    b = get_openai_client()
    assert a is b


# ──────────────────────────────────────────────────────
# call_with_retry
# ──────────────────────────────────────────────────────

def test_call_with_retry_succeeds_after_transient_failures():
    attempts = {"n": 0}

    async def _call() -> str:
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise _rate_limit_error()
        return "ok"

    # wait_min 0 使測試不用真的等 1 秒
    result = _run(call_with_retry(_call, wait_min=0, wait_max=0))
    assert result == "ok"
    assert attempts["n"] == 3


def test_call_with_retry_retries_on_timeout_and_conn_errors():
    seq: list[Exception] = [_timeout_error(), _conn_error()]

    async def _call() -> str:
        if seq:
            raise seq.pop(0)
        return "done"

    result = _run(call_with_retry(_call, wait_min=0, wait_max=0))
    assert result == "done"


def test_call_with_retry_does_not_retry_on_other_errors():
    attempts = {"n": 0}

    async def _call() -> str:
        attempts["n"] += 1
        raise ValueError("不在重試白名單內")

    with pytest.raises(ValueError):
        _run(call_with_retry(_call, wait_min=0, wait_max=0))
    assert attempts["n"] == 1  # 只呼叫一次，不重試


def test_call_with_retry_raises_after_max_attempts():
    attempts = {"n": 0}

    async def _call() -> str:
        attempts["n"] += 1
        raise _rate_limit_error()

    with pytest.raises(RateLimitError):
        _run(call_with_retry(_call, attempts=3, wait_min=0, wait_max=0))
    assert attempts["n"] == 3


# ──────────────────────────────────────────────────────
# Token budget
# ──────────────────────────────────────────────────────

def test_count_tokens_is_positive():
    messages = [{"role": "system", "content": "hello"}, {"role": "user", "content": "world"}]
    assert count_tokens(messages, "gpt-4o") > 0


def test_budget_messages_noop_when_within_budget():
    messages = [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "hi"},
    ]
    out = budget_messages(messages, "gpt-4o", max_output_tokens=100)
    assert out == messages


def test_budget_messages_truncates_from_head_preserving_system(monkeypatch):
    """
    強迫 budget = 很小，確認：
    - 保留第一則 system
    - 從 index=1 開始刪舊訊息
    - 最新的訊息一定會留下來
    """
    # 先把 context_limit 設為非常小，讓預算極度緊縮
    monkeypatch.setattr(oa, "_MODEL_CONTEXT_LIMIT", {"gpt-4o": 120})

    messages = [
        {"role": "system", "content": "SYSTEM"},
        {"role": "user", "content": "A" * 200},
        {"role": "assistant", "content": "B" * 200},
        {"role": "user", "content": "latest question"},
    ]
    out = budget_messages(messages, "gpt-4o", max_output_tokens=20, reserve=20)
    assert out[0]["role"] == "system"
    assert out[-1]["content"] == "latest question"
    # 舊的長字串訊息應該被截掉
    assert len(out) < len(messages)
