"""
Unit tests for auth_service security fixes (P6-auth-backend).

純 Python stub（無真 DB / 無真 Redis），只驗兩個 production blocker 的核心邏輯：

- AUTH-3：公開註冊不得提權。`_is_admin` 是 register() 用來決定角色降級的閘門，
  未登入 / 非 admin / 未知角色一律 False → register 強制 PATIENT。
- reset_password str→UUID cast bug：forgot_password 以 str(user.id) 寫進 Redis，
  decode_responses=True 取回為 str；若直接拿 str 去比對 UUID 欄位，valid token
  也會查不到 user 而誤拋 user_not_found。修正後應正確以 UUID 找到 user 並改密碼，
  且不再因 cast 落到 NotFoundException。
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.exceptions import NotFoundException, UnauthorizedException
from app.models.enums import UserRole
from app.services.auth_service import (
    RESET_TOKEN_KEY_PREFIX,
    AuthService,
    _is_admin,
)


def _run(coro):
    """在 sync test 裡跑 coroutine，避免多裝 pytest-asyncio。"""
    return asyncio.run(coro)


# ──────────────────────────────────────────────────────
# AUTH-3：_is_admin 閘門
# ──────────────────────────────────────────────────────

def test_is_admin_none_is_false():
    # 公開（未認證）註冊 → 不是 admin → register 會降級為 PATIENT
    assert _is_admin(None) is False


def test_is_admin_patient_enum_is_false():
    user = SimpleNamespace(role=UserRole.PATIENT)
    assert _is_admin(user) is False


def test_is_admin_doctor_cannot_self_elevate():
    # 即使帶著 DOCTOR token 來註冊，也不是 admin → 不得指定角色
    user = SimpleNamespace(role=UserRole.DOCTOR)
    assert _is_admin(user) is False


def test_is_admin_admin_enum_is_true():
    user = SimpleNamespace(role=UserRole.ADMIN)
    assert _is_admin(user) is True


def test_is_admin_admin_string_is_true():
    # role 可能是字串（來自 token / ORM 反序列化）
    user = SimpleNamespace(role="admin")
    assert _is_admin(user) is True


def test_is_admin_unknown_role_is_false():
    user = SimpleNamespace(role="superuser")
    assert _is_admin(user) is False


# ──────────────────────────────────────────────────────
# reset_password：str → UUID cast 修正
# ──────────────────────────────────────────────────────

class _FakeScalarResult:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value


class _FakeDB:
    """最小 AsyncSession 替身；execute 回傳預設好的 user，flush 為 no-op。"""

    def __init__(self, user: Any) -> None:
        self._user = user
        self.last_where_value: Any = None

    async def execute(self, stmt: Any) -> _FakeScalarResult:
        # 從 select(User).where(User.id == <value>) 取出右值，驗證它已是 UUID。
        try:
            self.last_where_value = stmt.whereclause.right.value
        except AttributeError:
            self.last_where_value = None
        return _FakeScalarResult(self._user)

    async def flush(self) -> None:
        return None


class _FakeRedis:
    """decode_responses=True 的 Redis 替身：get 回 str，與正式環境一致。"""

    def __init__(self, store: dict[str, str]) -> None:
        self._store = store
        self.deleted: list[str] = []

    async def get(self, key: str) -> Any:
        return self._store.get(key)

    async def delete(self, *keys: str) -> int:
        for k in keys:
            self.deleted.append(k)
            self._store.pop(k, None)
        return len(keys)


def _patch_redis(monkeypatch, fake_redis):
    async def _fake_get_redis():
        return fake_redis

    # reset_password 內部 `from app.cache.redis_client import get_redis`
    monkeypatch.setattr("app.cache.redis_client.get_redis", _fake_get_redis)


def test_reset_password_valid_token_finds_user_and_resets(monkeypatch):
    """
    關鍵迴歸：Redis 裡存的是 str(user.id)，valid token 必須能轉成 UUID 找到 user，
    完成改密碼，而不是因 str/UUID 不符落到 user_not_found。
    """
    user_id = uuid.uuid4()
    token = "valid-reset-token"
    user = SimpleNamespace(id=user_id, password_hash="OLD", updated_at=None)

    fake_redis = _FakeRedis({f"{RESET_TOKEN_KEY_PREFIX}{token}": str(user_id)})
    _patch_redis(monkeypatch, fake_redis)
    db = _FakeDB(user)

    # 不應拋 NotFoundException
    _run(AuthService.reset_password(db, token=token, new_password="NewPass123"))

    # 密碼已換、token 一次性刪除
    assert user.password_hash != "OLD"
    assert f"{RESET_TOKEN_KEY_PREFIX}{token}" in fake_redis.deleted
    # 證明查 user 時用的是 UUID（非 str），即 cast 修正生效
    assert isinstance(db.last_where_value, uuid.UUID)
    assert db.last_where_value == user_id


def test_reset_password_unknown_token_raises_unauthorized(monkeypatch):
    fake_redis = _FakeRedis({})  # token 不存在
    _patch_redis(monkeypatch, fake_redis)
    db = _FakeDB(SimpleNamespace(id=uuid.uuid4()))

    with pytest.raises(UnauthorizedException):
        _run(AuthService.reset_password(db, token="nope", new_password="NewPass123"))


def test_reset_password_user_deleted_raises_not_found(monkeypatch):
    """token 有效但對應 user 已刪除 → NotFoundException（cast 成功後的正常分支）。"""
    user_id = uuid.uuid4()
    token = "orphan-token"
    fake_redis = _FakeRedis({f"{RESET_TOKEN_KEY_PREFIX}{token}": str(user_id)})
    _patch_redis(monkeypatch, fake_redis)
    db = _FakeDB(None)  # user 查不到

    with pytest.raises(NotFoundException):
        _run(AuthService.reset_password(db, token=token, new_password="NewPass123"))
