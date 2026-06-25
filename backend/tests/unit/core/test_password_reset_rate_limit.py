"""
守護 forgot-password / reset-password 端點的 per-IP rate limit（RL-auth-ratelimit）。

`enforce_password_reset_ip_rate_limit` 走與 login IP policy 相同的
SlidingWindowLimiter，但上限改讀 settings.PASSWORD_RESET_IP_LIMIT/WINDOW
（預設更保守：5 次 / 900s）。本檔驗：
- 在 limit 內全部放行
- 超過 limit 即抛 RateLimitExceededException，details.scope == "password_reset_ip"
- 不同 IP 互不影響
- 空 IP（測試 / 健康檢查）一律放行

純 in-memory FakeRedis stub；不起 FastAPI、不連真 Redis（asyncio.run pattern）。
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest

from app.core import rate_limit as rl
from app.core.config import settings
from app.core.exceptions import RateLimitExceededException


def _run(coro):
    return asyncio.run(coro)


# ──────────────────────────────────────────────────────────
# 最小 FakeRedis：覆蓋 SlidingWindowLimiter.check 用到的指令
# ──────────────────────────────────────────────────────────

class _FakePipeline:
    def __init__(self, redis: "_FakeRedis") -> None:
        self.redis = redis
        self.ops: list[tuple[str, tuple]] = []

    def zremrangebyscore(self, key: str, lo: float, hi: float):
        self.ops.append(("zremrangebyscore", (key, lo, hi)))
        return self

    def zcard(self, key: str):
        self.ops.append(("zcard", (key,)))
        return self

    def zadd(self, key: str, mapping: dict):
        self.ops.append(("zadd", (key, mapping)))
        return self

    def expire(self, key: str, seconds: int):
        self.ops.append(("expire", (key, seconds)))
        return self

    async def execute(self) -> list[Any]:
        out: list[Any] = []
        for name, args in self.ops:
            out.append(getattr(self.redis, f"_sync_{name}")(*args))
        return out


class _FakeRedis:
    def __init__(self) -> None:
        self.zsets: dict[str, list[tuple[str, float]]] = {}
        self.expires_at: dict[str, float] = {}

    def _sync_zremrangebyscore(self, key: str, lo: float, hi: float) -> int:
        z = self.zsets.get(key, [])
        before = len(z)
        self.zsets[key] = [(m, s) for (m, s) in z if not (lo <= s <= hi)]
        return before - len(self.zsets[key])

    def _sync_zcard(self, key: str) -> int:
        return len(self.zsets.get(key, []))

    def _sync_zadd(self, key: str, mapping: dict) -> int:
        z = self.zsets.setdefault(key, [])
        added = 0
        for member, score in mapping.items():
            if all(m != member for m, _ in z):
                z.append((member, float(score)))
                added += 1
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

    def pipeline(self, transaction: bool = False) -> _FakePipeline:  # noqa: ARG002
        return _FakePipeline(self)


# ──────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────

def test_password_reset_ip_allows_under_limit():
    fake = _FakeRedis()
    for i in range(settings.PASSWORD_RESET_IP_LIMIT):
        # 在上限內全部放行，不該 raise
        _run(rl.enforce_password_reset_ip_rate_limit(fake, "9.9.9.9"))


def test_password_reset_ip_blocks_beyond_limit():
    fake = _FakeRedis()
    for _ in range(settings.PASSWORD_RESET_IP_LIMIT):
        _run(rl.enforce_password_reset_ip_rate_limit(fake, "9.9.9.9"))
    with pytest.raises(RateLimitExceededException) as exc:
        _run(rl.enforce_password_reset_ip_rate_limit(fake, "9.9.9.9"))
    assert (exc.value.details or {}).get("scope") == "password_reset_ip"
    assert (exc.value.details or {}).get("retry_after", 0) > 0


def test_password_reset_ip_isolates_distinct_ips():
    fake = _FakeRedis()
    for _ in range(settings.PASSWORD_RESET_IP_LIMIT):
        _run(rl.enforce_password_reset_ip_rate_limit(fake, "1.1.1.1"))
    # 另一個 IP 不受影響
    _run(rl.enforce_password_reset_ip_rate_limit(fake, "2.2.2.2"))


def test_password_reset_ip_skips_when_ip_empty():
    fake = _FakeRedis()
    # 空 IP（測試 / 健康檢查）連呼叫多次都不該 raise
    for _ in range(settings.PASSWORD_RESET_IP_LIMIT + 10):
        _run(rl.enforce_password_reset_ip_rate_limit(fake, ""))


def test_password_reset_ip_uses_its_own_key_prefix():
    fake = _FakeRedis()
    _run(rl.enforce_password_reset_ip_rate_limit(fake, "3.3.3.3"))
    assert f"{rl.RL_PWRESET_IP_PREFIX}3.3.3.3" in fake.zsets
    # 不該污染 login IP 的 namespace
    assert f"{rl.RL_LOGIN_IP_PREFIX}3.3.3.3" not in fake.zsets
