"""
守護 P2 #14 rate limiter 行為：

- SlidingWindowLimiter：未超限 allowed、超限 blocked 並回合理的 retry_after
- login IP policy：10/min/IP 邊界
- login failure tracker：5 次失敗鎖 10 分鐘；成功清鎖
- LLM per-user：20/min/user 邊界
- 鎖定檢查：ttl > 0 擋；ttl=-2/-1 不擋
- Redis 故障 fail-open：RedisError（ConnectionError/TimeoutError）時放行不拋錯；
  RateLimitExceededException 是業務例外，照常拋

純 in-memory FakeRedis stub；不起 FastAPI、不連真 Redis。
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Optional

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from app.core import rate_limit as rl
from app.core.exceptions import RateLimitExceededException


def _run(coro):
    return asyncio.run(coro)


# ──────────────────────────────────────────────────────────
# FakeRedis stub：覆蓋本檔用到的 API
# ──────────────────────────────────────────────────────────

class _FakePipeline:
    """只支援本檔用到的 pipeline 指令；execute() 依序回 list."""

    def __init__(self, redis: "_FakeRedis") -> None:
        self.redis = redis
        self.ops: list[tuple[str, tuple, dict]] = []

    def zremrangebyscore(self, key: str, lo: float, hi: float):
        self.ops.append(("zremrangebyscore", (key, lo, hi), {}))
        return self

    def zcard(self, key: str):
        self.ops.append(("zcard", (key,), {}))
        return self

    def zadd(self, key: str, mapping: dict):
        self.ops.append(("zadd", (key, mapping), {}))
        return self

    def expire(self, key: str, seconds: int):
        self.ops.append(("expire", (key, seconds), {}))
        return self

    async def execute(self) -> list[Any]:
        out: list[Any] = []
        for name, args, _ in self.ops:
            method = getattr(self.redis, f"_sync_{name}")
            out.append(method(*args))
        return out


class _FakeRedis:
    def __init__(self) -> None:
        self.zsets: dict[str, list[tuple[str, float]]] = {}
        self.strings: dict[str, str] = {}
        self.ttls: dict[str, float] = {}
        self.expires_at: dict[str, float] = {}

    # ── zset ──
    def _sync_zremrangebyscore(self, key: str, lo: float, hi: float) -> int:
        z = self.zsets.get(key, [])
        before = len(z)
        z = [(m, s) for (m, s) in z if not (lo <= s <= hi)]
        self.zsets[key] = z
        return before - len(z)

    def _sync_zcard(self, key: str) -> int:
        return len(self.zsets.get(key, []))

    def _sync_zadd(self, key: str, mapping: dict) -> int:
        z = self.zsets.setdefault(key, [])
        added = 0
        for member, score in mapping.items():
            if all(m != member for m, _ in z):
                z.append((member, float(score)))
                added += 1
            else:
                z[:] = [(m, s) if m != member else (m, float(score)) for (m, s) in z]
        return added

    def _sync_expire(self, key: str, seconds: int) -> int:
        self.expires_at[key] = time.time() + seconds
        return 1

    async def zrange(self, key: str, start: int, stop: int, withscores: bool = False):
        z = sorted(self.zsets.get(key, []), key=lambda t: t[1])
        slicing = z[start:stop + 1]
        if withscores:
            return [(m, s) for (m, s) in slicing]
        return [m for (m, _) in slicing]

    # ── pipeline ──
    def pipeline(self, transaction: bool = False) -> _FakePipeline:  # noqa: ARG002
        return _FakePipeline(self)

    # ── string / INCR ──
    async def incr(self, key: str) -> int:
        self.strings[key] = str(int(self.strings.get(key, "0")) + 1)
        return int(self.strings[key])

    async def setex(self, key: str, ttl: int, value: str) -> bool:
        self.strings[key] = value
        self.ttls[key] = time.time() + ttl
        return True

    async def expire(self, key: str, seconds: int) -> bool:
        if key in self.strings:
            self.ttls[key] = time.time() + seconds
        return True

    async def ttl(self, key: str) -> int:
        if key not in self.strings:
            return -2
        expiry = self.ttls.get(key)
        if expiry is None:
            return -1
        remaining = int(expiry - time.time())
        return max(remaining, 0)

    async def delete(self, *keys: str) -> int:
        count = 0
        for k in keys:
            if k in self.strings:
                del self.strings[k]
                self.ttls.pop(k, None)
                count += 1
        return count


# ──────────────────────────────────────────────────────────
# SlidingWindowLimiter 本身
# ──────────────────────────────────────────────────────────

def test_sliding_window_allows_under_limit():
    fake = _FakeRedis()
    for i in range(5):
        ok, retry = _run(rl.SlidingWindowLimiter.check(fake, "k", limit=5, window_seconds=60))
        assert ok is True, f"iter={i} 應該允許"
        assert retry == 0


def test_sliding_window_blocks_at_limit():
    fake = _FakeRedis()
    for _ in range(5):
        _run(rl.SlidingWindowLimiter.check(fake, "k", limit=5, window_seconds=60))
    ok, retry = _run(rl.SlidingWindowLimiter.check(fake, "k", limit=5, window_seconds=60))
    assert ok is False
    assert retry > 0, "blocked 時 retry_after 要 > 0"
    assert retry <= 60, f"retry_after 不該超過 window：{retry}"


# ──────────────────────────────────────────────────────────
# login IP policy
# ──────────────────────────────────────────────────────────

def test_login_ip_policy_blocks_at_eleventh_attempt():
    fake = _FakeRedis()
    for _ in range(rl.LOGIN_IP_LIMIT):
        _run(rl.enforce_login_ip_rate_limit(fake, "1.2.3.4"))
    with pytest.raises(RateLimitExceededException) as exc:
        _run(rl.enforce_login_ip_rate_limit(fake, "1.2.3.4"))
    assert (exc.value.details or {}).get("scope") == "ip"
    assert (exc.value.details or {}).get("retry_after", 0) > 0


def test_login_ip_policy_skips_when_ip_empty():
    fake = _FakeRedis()
    # 連呼叫 100 次都不該 raise（空 IP 代表測試/健康檢查場景）
    for _ in range(100):
        _run(rl.enforce_login_ip_rate_limit(fake, ""))


# ──────────────────────────────────────────────────────────
# login failure tracker + 帳號鎖定
# ──────────────────────────────────────────────────────────

def test_record_login_failure_locks_after_threshold():
    fake = _FakeRedis()
    for i in range(rl.LOGIN_FAIL_THRESHOLD - 1):
        count = _run(rl.record_login_failure(fake, "u@example.com"))
        assert count == i + 1
    # 第 5 次：自動鎖
    count = _run(rl.record_login_failure(fake, "u@example.com"))
    assert count == rl.LOGIN_FAIL_THRESHOLD
    locked_key = f"{rl.RL_LOGIN_LOCKED_PREFIX}u@example.com"
    assert locked_key in fake.strings
    # 失敗計數應被清掉（否則第 6 次又會重新 trigger）
    assert f"{rl.RL_LOGIN_FAIL_PREFIX}u@example.com" not in fake.strings


def test_enforce_account_not_locked_raises_when_locked():
    fake = _FakeRedis()
    _run(fake.setex(f"{rl.RL_LOGIN_LOCKED_PREFIX}u@example.com", 300, "1"))
    with pytest.raises(RateLimitExceededException) as exc:
        _run(rl.enforce_account_not_locked(fake, "u@example.com"))
    assert (exc.value.details or {}).get("scope") == "account"


def test_enforce_account_not_locked_pass_when_no_lock():
    fake = _FakeRedis()
    _run(rl.enforce_account_not_locked(fake, "fresh@example.com"))  # 不該 raise


def test_clear_login_failures_removes_counter_and_lock():
    fake = _FakeRedis()
    _run(rl.record_login_failure(fake, "u@example.com"))
    _run(fake.setex(f"{rl.RL_LOGIN_LOCKED_PREFIX}u@example.com", 60, "1"))
    _run(rl.clear_login_failures(fake, "u@example.com"))
    assert f"{rl.RL_LOGIN_FAIL_PREFIX}u@example.com" not in fake.strings
    assert f"{rl.RL_LOGIN_LOCKED_PREFIX}u@example.com" not in fake.strings


def test_email_is_lowercased_for_keys():
    """大小寫混用不該逃過失敗計數/鎖定檢查。"""
    fake = _FakeRedis()
    for _ in range(rl.LOGIN_FAIL_THRESHOLD):
        _run(rl.record_login_failure(fake, "U@Example.com"))
    with pytest.raises(RateLimitExceededException):
        _run(rl.enforce_account_not_locked(fake, "u@example.com"))


# ──────────────────────────────────────────────────────────
# LLM per-user policy
# ──────────────────────────────────────────────────────────

def test_llm_per_user_policy_blocks_beyond_limit():
    fake = _FakeRedis()
    for _ in range(rl.LLM_USER_LIMIT):
        _run(rl.enforce_llm_per_user_rate_limit(fake, "user-a"))
    with pytest.raises(RateLimitExceededException) as exc:
        _run(rl.enforce_llm_per_user_rate_limit(fake, "user-a"))
    assert (exc.value.details or {}).get("scope") == "llm_user"


def test_llm_per_user_policy_isolates_users():
    fake = _FakeRedis()
    for _ in range(rl.LLM_USER_LIMIT):
        _run(rl.enforce_llm_per_user_rate_limit(fake, "user-a"))
    # user-b 不受影響
    _run(rl.enforce_llm_per_user_rate_limit(fake, "user-b"))


def test_llm_per_user_policy_skips_when_user_none():
    fake = _FakeRedis()
    for _ in range(100):
        _run(rl.enforce_llm_per_user_rate_limit(fake, None))


# ──────────────────────────────────────────────────────────
# Redis 故障 fail-open（RedisError 放行；業務例外照常拋）
# ──────────────────────────────────────────────────────────

class _DownPipeline(_FakePipeline):
    """execute() 一律 raise，模擬 Redis 連線故障。"""

    def __init__(self, redis: "_DownRedis") -> None:
        super().__init__(redis)
        self.exc = redis.exc

    async def execute(self) -> list[Any]:
        raise self.exc


class _DownRedis(_FakeRedis):
    """所有會打 Redis 的操作一律 raise 指定的 redis.exceptions 例外。"""

    def __init__(self, exc: Exception | None = None) -> None:
        super().__init__()
        self.exc = exc if exc is not None else RedisConnectionError("connection refused")

    def pipeline(self, transaction: bool = False) -> _DownPipeline:  # noqa: ARG002
        return _DownPipeline(self)

    async def zrange(self, key, start, stop, withscores=False):  # noqa: ARG002
        raise self.exc

    async def incr(self, key):  # noqa: ARG002
        raise self.exc

    async def setex(self, key, ttl, value):  # noqa: ARG002
        raise self.exc

    async def expire(self, key, seconds):  # noqa: ARG002
        raise self.exc

    async def ttl(self, key):  # noqa: ARG002
        raise self.exc

    async def delete(self, *keys):  # noqa: ARG002
        raise self.exc


def test_sliding_window_fails_open_on_connection_error():
    down = _DownRedis()
    ok, retry = _run(rl.SlidingWindowLimiter.check(down, "k", limit=5, window_seconds=60))
    assert ok is True, "Redis 掛掉時應放行（fail-open）"
    assert retry == 0


def test_sliding_window_fails_open_on_timeout_error():
    down = _DownRedis(RedisTimeoutError("timeout"))
    ok, retry = _run(rl.SlidingWindowLimiter.check(down, "k", limit=5, window_seconds=60))
    assert ok is True
    assert retry == 0


def test_enforce_policies_fail_open_when_redis_down():
    """所有走 SlidingWindowLimiter 的 enforce_* 在 Redis 故障時都不該 raise。"""
    down = _DownRedis()
    _run(rl.enforce_login_ip_rate_limit(down, "1.2.3.4"))
    _run(rl.enforce_register_ip_rate_limit(down, "1.2.3.4"))
    _run(rl.enforce_refresh_ip_rate_limit(down, "1.2.3.4"))
    _run(rl.enforce_password_reset_ip_rate_limit(down, "1.2.3.4"))
    _run(rl.enforce_llm_per_user_rate_limit(down, "user-a"))


def test_account_lockout_fails_open_when_redis_down():
    down = _DownRedis()
    _run(rl.enforce_account_not_locked(down, "u@example.com"))  # 不該 raise
    assert _run(rl.record_login_failure(down, "u@example.com")) == 0
    _run(rl.clear_login_failures(down, "u@example.com"))  # 不該 raise


def test_fail_open_logs_warning_with_key_and_exc_type(caplog):
    down = _DownRedis()
    with caplog.at_level("WARNING", logger="app.core.rate_limit"):
        _run(rl.SlidingWindowLimiter.check(down, "gu:rl:login_ip:1.2.3.4", limit=5, window_seconds=60))
    assert any(
        "fail-open" in r.message and "gu:rl:login_ip:1.2.3.4" in r.message
        and "ConnectionError" in r.message
        for r in caplog.records
    ), f"warning 應含 limiter key 與例外類型：{[r.message for r in caplog.records]}"


def test_rate_limit_exceeded_still_raised_when_redis_healthy():
    """fail-open 不可吞掉業務例外：Redis 正常、超限時 429 照常拋。"""
    fake = _FakeRedis()
    for _ in range(rl.LOGIN_IP_LIMIT):
        _run(rl.enforce_login_ip_rate_limit(fake, "9.9.9.9"))
    with pytest.raises(RateLimitExceededException):
        _run(rl.enforce_login_ip_rate_limit(fake, "9.9.9.9"))
    # 帳號鎖定同理
    _run(fake.setex(f"{rl.RL_LOGIN_LOCKED_PREFIX}x@example.com", 300, "1"))
    with pytest.raises(RateLimitExceededException):
        _run(rl.enforce_account_not_locked(fake, "x@example.com"))
