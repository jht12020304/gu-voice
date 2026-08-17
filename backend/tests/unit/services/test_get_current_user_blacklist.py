"""
Unit tests for JWT 黑名單檢查（TODO P1-#6）。

保證登出後的 access token 立即失效：
- blacklist 命中 → `get_current_user` 回 401 (UnauthorizedException)
- blacklist 未命中 → 正常通過，回傳 User
- token 缺少 jti → 跳過 blacklist 檢查（舊 token 相容性）
- Redis 掛 → fail-open 放行（黑名單是加強機制；與 rate_limit.py、
  websocket/auth.py 同政策，見 test_auth_identity_checks.test_redis_failure_fails_open）
- DB 掛 → fail-closed，例外照常往上（不得因 Redis 的 fail-open 一併放寬）

不起 FastAPI / Redis 實體，Redis 用 in-memory stub 替換
app.cache.redis_client._redis_pool 即可攔截 `get_current_user` 內部的 lookup。
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any, Optional
from types import SimpleNamespace

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from app.cache import redis_client
from app.core import dependencies
from app.core.dependencies import BLACKLIST_KEY_PREFIX, get_current_user
from app.core.exceptions import ForbiddenException, UnauthorizedException
from app.core.security import create_access_token


def _run(coro):
    return asyncio.run(coro)


# ──────────────────────────────────────────────────────
# Stubs
# ──────────────────────────────────────────────────────

@dataclass
class _FakeScalarResult:
    value: Any

    def scalar_one_or_none(self) -> Any:
        return self.value


class _FakeDB:
    """回傳預設的 User 物件；不解析 SQL。"""

    def __init__(self, user: Any) -> None:
        self._user = user

    async def execute(self, stmt: Any) -> _FakeScalarResult:
        return _FakeScalarResult(self._user)


class _FakeRedis:
    """只實作 get_current_user 會用到的 exists / setex。"""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def exists(self, key: str) -> int:
        return 1 if key in self._store else 0

    async def setex(self, key: str, ttl: int, value: str) -> bool:
        self._store[key] = value
        return True

    async def close(self) -> None:  # pragma: no cover - 介面相容
        return None


class _BrokenRedis:
    """模擬 Redis 掛掉：任何指令都拋 redis-py 的 ConnectionError。"""

    async def exists(self, key: str) -> int:
        raise RedisConnectionError("redis down (injected)")

    async def close(self) -> None:  # pragma: no cover - 介面相容
        return None


def _make_user(user_id: uuid.UUID) -> SimpleNamespace:
    return SimpleNamespace(
        id=user_id,
        role=SimpleNamespace(value="patient"),
        is_active=True,
    )


def _make_request() -> SimpleNamespace:
    """最小 Request stub：只需 `state`，供 get_current_user 寫入 request.state.user。"""
    return SimpleNamespace(state=SimpleNamespace())


@pytest.fixture(autouse=True)
def _swap_redis(monkeypatch):
    """把 app.cache.redis_client._redis_pool 換成 in-memory stub。"""
    fake = _FakeRedis()
    monkeypatch.setattr(redis_client, "_redis_pool", fake)
    yield fake
    monkeypatch.setattr(redis_client, "_redis_pool", None)


# ──────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────

def test_blacklisted_access_token_is_rejected(_swap_redis):
    user_id = uuid.uuid4()
    token = create_access_token(str(user_id), "patient")

    # 解出 jti 並丟黑名單（模擬 logout 動作）
    from app.core.security import decode_token
    jti = decode_token(token)["jti"]
    _run(_swap_redis.setex(f"{BLACKLIST_KEY_PREFIX}{jti}", 60, "1"))

    db = _FakeDB(_make_user(user_id))
    with pytest.raises(UnauthorizedException) as exc:
        _run(get_current_user(_make_request(), authorization=f"Bearer {token}", db=db))
    assert exc.value.message == "errors.token_revoked"


def test_non_blacklisted_access_token_passes(_swap_redis):
    user_id = uuid.uuid4()
    token = create_access_token(str(user_id), "patient")

    db = _FakeDB(_make_user(user_id))
    user = _run(get_current_user(_make_request(), authorization=f"Bearer {token}", db=db))
    assert user.id == user_id


# ──────────────────────────────────────────────────────
# Redis 故障 → fail-open（P4 L9 演練：Redis 停掉時整個認證面 500）
# ──────────────────────────────────────────────────────

def test_redis_failure_fails_open(monkeypatch, caplog):
    """Redis 連線失敗 → 黑名單查不到就放行，並留下 warning log。"""
    user_id = uuid.uuid4()
    token = create_access_token(str(user_id), "patient")
    monkeypatch.setattr(redis_client, "_redis_pool", _BrokenRedis())

    db = _FakeDB(_make_user(user_id))
    with caplog.at_level(logging.WARNING, logger=dependencies.__name__):
        user = _run(
            get_current_user(_make_request(), authorization=f"Bearer {token}", db=db)
        )

    assert user.id == user_id
    assert any("fail-open" in r.message for r in caplog.records)


def test_redis_failure_still_enforces_db_identity_checks(monkeypatch):
    """fail-open 只放寬黑名單：停權帳號在 Redis 掛掉時仍要被拒（403）。"""
    user_id = uuid.uuid4()
    token = create_access_token(str(user_id), "patient")
    monkeypatch.setattr(redis_client, "_redis_pool", _BrokenRedis())

    user = _make_user(user_id)
    user.is_active = False
    with pytest.raises(ForbiddenException):
        _run(
            get_current_user(
                _make_request(), authorization=f"Bearer {token}", db=_FakeDB(user)
            )
        )


def test_db_failure_fails_closed(monkeypatch):
    """DB 掛 → 例外照常往上（fail-closed），不比照 Redis 放行。"""
    user_id = uuid.uuid4()
    token = create_access_token(str(user_id), "patient")

    class _BrokenDB:
        async def execute(self, stmt: Any) -> Any:
            raise ConnectionError("db down (injected)")

    with pytest.raises(ConnectionError):
        _run(
            get_current_user(
                _make_request(), authorization=f"Bearer {token}", db=_BrokenDB()
            )
        )
