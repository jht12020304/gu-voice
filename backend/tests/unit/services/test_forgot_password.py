"""
守護 P3 #31 forgot_password / reset_password：

- email 存在 → Redis 裡有 `gu:reset:{token}`；email client 被呼叫；回通用訊息
- email 不存在 → Redis 不寫；email client 不叫；仍回通用訊息（避免 enumeration）
- reset token TTL = 1800 秒
- reset_password 帶錯 token → raise UnauthorizedException
- reset_password 帶對 token → 成功，且 token 被刪掉（一次性）
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Optional
from unittest.mock import AsyncMock

import pytest

from app.cache import redis_client
from app.core.exceptions import UnauthorizedException
from app.services.auth_service import (
    FORGOT_PASSWORD_GENERIC_MESSAGE,
    RESET_TOKEN_KEY_PREFIX,
    RESET_TOKEN_TTL_SECONDS,
    AuthService,
)


def _run(coro):
    return asyncio.run(coro)


# ──────────────────────────────────────────────────────────
# Stubs
# ──────────────────────────────────────────────────────────

class _FakeRedis:
    """支援 setex / get / delete 三件組，外加 TTL 記錄以便驗證。"""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    async def setex(self, key: str, ttl: int, value: str) -> bool:
        self.store[key] = str(value)
        self.ttls[key] = int(ttl)
        return True

    async def get(self, key: str) -> Optional[str]:
        return self.store.get(key)

    async def delete(self, *keys: str) -> int:
        removed = 0
        for k in keys:
            if k in self.store:
                del self.store[k]
                self.ttls.pop(k, None)
                removed += 1
        return removed


@dataclass
class _FakeUser:
    id: uuid.UUID
    email: str
    password_hash: str = "old-hash"
    updated_at: Any = None
    role: SimpleNamespace = field(default_factory=lambda: SimpleNamespace(value="doctor"))
    is_active: bool = True


@dataclass
class _FakeScalarResult:
    value: Any

    def scalar_one_or_none(self) -> Any:
        return self.value


class _FakeDB:
    """第一次 execute 回 user（或 None），後續 flush/commit 皆為 no-op。"""

    def __init__(self, user: Any) -> None:
        self._user = user
        self.flushes = 0

    async def execute(self, stmt: Any) -> _FakeScalarResult:
        return _FakeScalarResult(self._user)

    async def flush(self) -> None:
        self.flushes += 1


@pytest.fixture(autouse=True)
def _swap_redis(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(redis_client, "_redis_pool", fake)
    yield fake
    monkeypatch.setattr(redis_client, "_redis_pool", None)


class _FakeEmailClient:
    """收集 send() 呼叫以便斷言；不做實際網路 IO。"""

    def __init__(self) -> None:
        self.send = AsyncMock()


# ──────────────────────────────────────────────────────────
# forgot_password
# ──────────────────────────────────────────────────────────

def test_forgot_password_existing_email_stores_token_and_sends_email(_swap_redis):
    user = _FakeUser(id=uuid.uuid4(), email="doc@example.com")
    db = _FakeDB(user)
    client = _FakeEmailClient()

    result = _run(
        AuthService.forgot_password(db, email=user.email, email_client=client)
    )

    assert result["message"] == FORGOT_PASSWORD_GENERIC_MESSAGE
    # 未設 SENDGRID/SMTP（測試預設）→ onsite，前端據此不謊稱已寄信
    assert result["delivery"] == "onsite"

    # Redis 應該有且只有一筆 gu:reset:{token} = user_id
    reset_keys = [k for k in _swap_redis.store if k.startswith(RESET_TOKEN_KEY_PREFIX)]
    assert len(reset_keys) == 1
    assert _swap_redis.store[reset_keys[0]] == str(user.id)

    # email 客戶端有被叫到，to 是該使用者的 email
    client.send.assert_awaited_once()
    kwargs = client.send.await_args.kwargs
    assert kwargs["to"] == user.email
    assert "重設" in kwargs["subject"] or "reset" in kwargs["subject"].lower()
    # reset URL 要含拿到的 token
    token = reset_keys[0][len(RESET_TOKEN_KEY_PREFIX):]
    assert token in kwargs["body_text"]
    assert token in kwargs["body_html"]


def test_forgot_password_unknown_email_is_silent(_swap_redis):
    db = _FakeDB(user=None)
    client = _FakeEmailClient()

    result = _run(
        AuthService.forgot_password(db, email="ghost@example.com", email_client=client)
    )

    # 回應跟「存在」情境一模一樣（含 delivery，否則就成了 enumeration 側信道）
    assert result == {
        "message": FORGOT_PASSWORD_GENERIC_MESSAGE,
        "delivery": "onsite",
    }
    # 沒寫 Redis、沒寄信
    assert not any(k.startswith(RESET_TOKEN_KEY_PREFIX) for k in _swap_redis.store)
    client.send.assert_not_awaited()


def test_forgot_password_token_ttl_is_exactly_1800(_swap_redis):
    user = _FakeUser(id=uuid.uuid4(), email="doc@example.com")
    db = _FakeDB(user)
    client = _FakeEmailClient()

    _run(AuthService.forgot_password(db, email=user.email, email_client=client))

    reset_keys = [k for k in _swap_redis.store if k.startswith(RESET_TOKEN_KEY_PREFIX)]
    assert _swap_redis.ttls[reset_keys[0]] == RESET_TOKEN_TTL_SECONDS == 1800


# ──────────────────────────────────────────────────────────
# reset_password
# ──────────────────────────────────────────────────────────

def test_reset_password_wrong_token_raises(_swap_redis):
    db = _FakeDB(user=_FakeUser(id=uuid.uuid4(), email="x@example.com"))
    with pytest.raises(UnauthorizedException):
        _run(AuthService.reset_password(db, token="not-a-real-token", new_password="NewP@ss123"))


def test_reset_password_correct_token_succeeds_and_invalidates(_swap_redis):
    user = _FakeUser(id=uuid.uuid4(), email="doc@example.com")
    db = _FakeDB(user)
    client = _FakeEmailClient()

    # 先跑 forgot_password 產生 token
    _run(AuthService.forgot_password(db, email=user.email, email_client=client))
    reset_keys = [k for k in _swap_redis.store if k.startswith(RESET_TOKEN_KEY_PREFIX)]
    token = reset_keys[0][len(RESET_TOKEN_KEY_PREFIX):]
    old_hash = user.password_hash

    _run(AuthService.reset_password(db, token=token, new_password="BrandNewP@ss1"))

    # 密碼真的換了
    assert user.password_hash != old_hash
    # token 被刪光（一次性）
    assert not any(k.startswith(RESET_TOKEN_KEY_PREFIX) for k in _swap_redis.store)

    # 同一 token 再跑一次要被拒絕
    with pytest.raises(UnauthorizedException):
        _run(AuthService.reset_password(db, token=token, new_password="Whatever1!"))


# ──────────────────────────────────────────────────────────
# delivery 旗標（生產長期未設 SENDGRID/SMTP → 信永遠不會寄出）
# ──────────────────────────────────────────────────────────

def test_is_delivery_configured_follows_settings(monkeypatch):
    """與 _build_default_client 同一組條件：兩者必須一起改。"""
    from app.core import email_client as ec

    monkeypatch.setattr(ec.settings, "SENDGRID_API_KEY", "", raising=False)
    monkeypatch.setattr(ec.settings, "SMTP_HOST", "", raising=False)
    assert ec.is_delivery_configured() is False
    assert isinstance(ec._build_default_client(), ec._LoggingEmailClient)

    monkeypatch.setattr(ec.settings, "SENDGRID_API_KEY", "SG.xxx", raising=False)
    assert ec.is_delivery_configured() is True
    assert not isinstance(ec._build_default_client(), ec._LoggingEmailClient)

    monkeypatch.setattr(ec.settings, "SENDGRID_API_KEY", "", raising=False)
    monkeypatch.setattr(ec.settings, "SMTP_HOST", "smtp.example.com", raising=False)
    assert ec.is_delivery_configured() is True


def test_forgot_password_delivery_email_when_provider_configured(_swap_redis, monkeypatch):
    from app.core import email_client as ec

    monkeypatch.setattr(ec.settings, "SENDGRID_API_KEY", "SG.xxx", raising=False)

    user = _FakeUser(id=uuid.uuid4(), email="doc@example.com")
    result = _run(
        AuthService.forgot_password(
            _FakeDB(user), email=user.email, email_client=_FakeEmailClient()
        )
    )
    assert result["delivery"] == "email"


def test_forgot_password_delivery_does_not_leak_account_existence(_swap_redis, monkeypatch):
    """delivery 只由環境設定推導 → 存在與不存在的帳號必須拿到同一個值。"""
    from app.core import email_client as ec

    for configured, expected in (("", "onsite"), ("SG.xxx", "email")):
        monkeypatch.setattr(ec.settings, "SENDGRID_API_KEY", configured, raising=False)
        monkeypatch.setattr(ec.settings, "SMTP_HOST", "", raising=False)

        existing = _run(
            AuthService.forgot_password(
                _FakeDB(_FakeUser(id=uuid.uuid4(), email="doc@example.com")),
                email="doc@example.com",
                email_client=_FakeEmailClient(),
            )
        )
        missing = _run(
            AuthService.forgot_password(
                _FakeDB(user=None),
                email="ghost@example.com",
                email_client=_FakeEmailClient(),
            )
        )
        assert existing == missing == {
            "message": FORGOT_PASSWORD_GENERIC_MESSAGE,
            "delivery": expected,
        }
