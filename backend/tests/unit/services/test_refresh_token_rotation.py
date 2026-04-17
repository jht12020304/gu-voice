"""
Unit tests for refresh token rotation + reuse detection（TODO P1-#11）。

守護：
- 合法 refresh → 舊 jti 消耗、新 jti 登記、回傳新 token 對
- 重複使用同一張 refresh → 偵測到 replay，撤銷該 user 所有 refresh 登記並拒絕
- logout 帶 refresh token → rotation 登記也要刪
- logout 未帶 refresh token → 撤銷該 user 所有 refresh 登記

純 Python stub：不起 FastAPI、不碰真 Redis 或 DB。
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Optional

import pytest

from app.cache import redis_client
from app.core.exceptions import UnauthorizedException
from app.models.enums import UserRole
from app.services import auth_service as auth_service_mod
from app.services.auth_service import (
    AuthService,
    REFRESH_TOKEN_KEY_PREFIX,
    _refresh_key,
)


def _run(coro):
    return asyncio.run(coro)


# ──────────────────────────────────────────────────────
# Stubs
# ──────────────────────────────────────────────────────

class _FakeRedis:
    """In-memory Redis 替身，實作 setex / delete / scan_iter 四件組。"""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def setex(self, key: str, ttl: int, value: str) -> bool:
        self.store[key] = value
        return True

    async def delete(self, *keys: str) -> int:
        removed = 0
        for k in keys:
            if k in self.store:
                del self.store[k]
                removed += 1
        return removed

    async def exists(self, key: str) -> int:
        return 1 if key in self.store else 0

    async def scan_iter(self, match: Optional[str] = None):
        import fnmatch
        for key in list(self.store.keys()):
            if match is None or fnmatch.fnmatchcase(key, match):
                yield key


@dataclass
class _FakeUser:
    id: uuid.UUID
    role: SimpleNamespace = field(default_factory=lambda: SimpleNamespace(value="patient"))
    is_active: bool = True


@dataclass
class _FakeScalarResult:
    value: Any

    def scalar_one_or_none(self) -> Any:
        return self.value


class _FakeDB:
    def __init__(self, user: Any) -> None:
        self._user = user

    async def execute(self, stmt: Any) -> _FakeScalarResult:
        return _FakeScalarResult(self._user)


@pytest.fixture(autouse=True)
def _swap_redis(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(redis_client, "_redis_pool", fake)
    yield fake
    monkeypatch.setattr(redis_client, "_redis_pool", None)


# ──────────────────────────────────────────────────────
# Helpers: 產生一張登記過的 refresh token
# ──────────────────────────────────────────────────────

def _issue_registered_refresh(redis: _FakeRedis, user_id: uuid.UUID) -> tuple[str, str]:
    """回傳 (token, jti)，並在 Redis 登記完成。"""
    from app.core.security import create_refresh_token, verify_refresh_token
    token = create_refresh_token(str(user_id), "patient")
    _run(auth_service_mod._register_refresh_token(redis, str(user_id), token))
    jti = verify_refresh_token(token)["jti"]
    return token, jti


# ──────────────────────────────────────────────────────
# Tests: refresh_token rotation
# ──────────────────────────────────────────────────────

def test_refresh_rotates_jti_and_registers_new_one(_swap_redis):
    user_id = uuid.uuid4()
    token, old_jti = _issue_registered_refresh(_swap_redis, user_id)
    assert _refresh_key(user_id, old_jti) in _swap_redis.store

    db = _FakeDB(_FakeUser(id=user_id))
    result = _run(AuthService.refresh_token(db, refresh_token=token))

    # 舊 jti 被消耗
    assert _refresh_key(user_id, old_jti) not in _swap_redis.store
    # 新 jti 已登記
    from app.core.security import verify_refresh_token
    new_jti = verify_refresh_token(result["refresh_token"])["jti"]
    assert _refresh_key(user_id, new_jti) in _swap_redis.store
    assert new_jti != old_jti


def test_replayed_refresh_triggers_reuse_detection(_swap_redis):
    """同一張 refresh token 用兩次：第二次應被拒絕且撤銷該 user 所有 refresh 登記。"""
    user_id = uuid.uuid4()
    token, _ = _issue_registered_refresh(_swap_redis, user_id)
    # 也發第二張尚未使用的 refresh，模擬 user 正常持有的其他 session
    _other_token, other_jti = _issue_registered_refresh(_swap_redis, user_id)

    db = _FakeDB(_FakeUser(id=user_id))

    # 第一次 refresh → 成功
    _run(AuthService.refresh_token(db, refresh_token=token))

    # 第二次用同一張舊 token → reuse 偵測
    with pytest.raises(UnauthorizedException) as exc:
        _run(AuthService.refresh_token(db, refresh_token=token))
    assert exc.value.message == "errors.refresh_token_reused"

    # 該 user 所有 refresh 登記都應被清掉（包含第一次 rotate 出來的新 jti 與 _other_token 的 jti）
    remaining = [k for k in _swap_redis.store if k.startswith(f"{REFRESH_TOKEN_KEY_PREFIX}{user_id}:")]
    assert remaining == [], f"still have refresh keys: {remaining}"
    assert other_jti  # sanity


def test_refresh_unknown_jti_is_rejected(_swap_redis):
    """JWT 合法但 jti 從未登記（例如舊版/外部偽造）→ 視為 reuse。"""
    from app.core.security import create_refresh_token
    user_id = uuid.uuid4()
    token = create_refresh_token(str(user_id), "patient")  # 注意：沒 _register
    db = _FakeDB(_FakeUser(id=user_id))

    with pytest.raises(UnauthorizedException):
        _run(AuthService.refresh_token(db, refresh_token=token))


# ──────────────────────────────────────────────────────
# Tests: logout 清 rotation 登記
# ──────────────────────────────────────────────────────

def test_logout_with_refresh_token_clears_its_registry(_swap_redis):
    from app.core.security import create_access_token
    user_id = uuid.uuid4()
    refresh, refresh_jti = _issue_registered_refresh(_swap_redis, user_id)
    access = create_access_token(str(user_id), "patient")

    _run(AuthService.logout(
        db=None, user_id=user_id, access_token=access, refresh_token=refresh
    ))
    assert _refresh_key(user_id, refresh_jti) not in _swap_redis.store


def test_logout_without_refresh_revokes_all_user_refresh_keys(_swap_redis):
    from app.core.security import create_access_token
    user_id = uuid.uuid4()
    _issue_registered_refresh(_swap_redis, user_id)
    _issue_registered_refresh(_swap_redis, user_id)
    access = create_access_token(str(user_id), "patient")

    _run(AuthService.logout(
        db=None, user_id=user_id, access_token=access, refresh_token=None
    ))
    remaining = [k for k in _swap_redis.store if k.startswith(f"{REFRESH_TOKEN_KEY_PREFIX}{user_id}:")]
    assert remaining == []
