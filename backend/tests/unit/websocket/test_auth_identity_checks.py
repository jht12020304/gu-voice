"""守護 WS 認證的簽章後身分檢查（對齊 REST get_current_user）：

- 黑名單命中 → close(4001) 拒絕（key 格式對齊 app/core/dependencies.py）
- User 不存在 / is_active=False → close(4001) 拒絕
- Redis 掛 → fail-open 放行（logger.warning，與全系統一致）
- DB 掛 → fail-closed 拒絕（close 1011）
- payload["role"] 以 DB 為準覆蓋 token claim（降權後舊 token 不得提權）

沿用 test_auth_handshake.py 的 FakeWebSocket + asyncio.run + monkeypatch 慣例；
不碰真 Redis / 真 DB。
"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

from app.core.dependencies import BLACKLIST_KEY_PREFIX
from app.core.security import create_access_token, verify_access_token
from app.websocket import auth as ws_auth
from tests.unit.websocket.test_auth_handshake import _FakeWebSocket

_UID = "33333333-3333-4333-8333-333333333333"


def _run(coro):
    return asyncio.run(coro)


def _token(role: str = "patient", subject: str = _UID) -> str:
    return create_access_token(subject=subject, role=role)


def _ws_for(token: str) -> _FakeWebSocket:
    return _FakeWebSocket(incoming=[json.dumps({"type": "auth", "token": token})])


def _make_user(role: str = "patient", is_active: bool = True) -> SimpleNamespace:
    return SimpleNamespace(is_active=is_active, role=SimpleNamespace(value=role))


class FakeBlacklistRedis:
    """黑名單 Redis stub：可設命中集合；fail=True 時 raise（fail-open 測試）。"""

    def __init__(
        self, blacklisted: set[str] | None = None, fail: bool = False
    ) -> None:
        self.blacklisted = blacklisted or set()
        self.fail = fail
        self.queried: list[str] = []

    async def exists(self, key: str) -> int:
        if self.fail:
            raise ConnectionError("redis down (injected)")
        self.queried.append(key)
        return 1 if key in self.blacklisted else 0


def _patch_backend(
    monkeypatch,
    *,
    user: Any = None,
    redis: FakeBlacklistRedis | None = None,
    db_error: Exception | None = None,
) -> FakeBlacklistRedis:
    """把 auth 模組的黑名單 Redis 與 User DB 查詢換成 stub。"""
    redis = redis if redis is not None else FakeBlacklistRedis()

    async def _fake_get_redis():
        return redis

    class _FakeResult:
        def scalar_one_or_none(self):
            return user

    class _FakeDB:
        async def execute(self, stmt):
            if db_error is not None:
                raise db_error
            return _FakeResult()

    @asynccontextmanager
    async def _fake_get_db_session():
        yield _FakeDB()

    monkeypatch.setattr(ws_auth, "get_cache_redis", _fake_get_redis)
    monkeypatch.setattr(ws_auth, "get_db_session", _fake_get_db_session)
    return redis


# ──────────────────────────────────────────────────────────
# 黑名單
# ──────────────────────────────────────────────────────────

def test_blacklisted_token_closes_4001(monkeypatch):
    """logout 過的 token（jti 在黑名單）即使簽章有效也要拒絕。"""
    token = _token()
    jti = verify_access_token(token)["jti"]
    redis = FakeBlacklistRedis(blacklisted={f"{BLACKLIST_KEY_PREFIX}{jti}"})
    _patch_backend(monkeypatch, user=_make_user(), redis=redis)

    ws = _ws_for(token)
    payload = _run(ws_auth.authenticate_websocket(ws, context="test"))

    assert payload is None
    assert ws.closed_with is not None
    assert ws.closed_with[0] == 4001


def test_blacklist_key_format_matches_dependencies(monkeypatch):
    """查詢 key 必須是 dependencies.py 的 BLACKLIST_KEY_PREFIX + jti。"""
    token = _token()
    jti = verify_access_token(token)["jti"]
    redis = _patch_backend(monkeypatch, user=_make_user())

    ws = _ws_for(token)
    payload = _run(ws_auth.authenticate_websocket(ws, context="test"))

    assert payload is not None
    assert redis.queried == [f"{BLACKLIST_KEY_PREFIX}{jti}"]


def test_redis_failure_fails_open(monkeypatch):
    """Redis 掛 → 黑名單查不到就放行（fail-open，與全系統一致）。"""
    _patch_backend(
        monkeypatch, user=_make_user(), redis=FakeBlacklistRedis(fail=True)
    )

    ws = _ws_for(_token())
    payload = _run(ws_auth.authenticate_websocket(ws, context="test"))

    assert payload is not None
    assert payload.get("sub") == _UID
    assert ws.closed_with is None


# ──────────────────────────────────────────────────────────
# User 載入 / is_active
# ──────────────────────────────────────────────────────────

def test_inactive_user_closes_4001(monkeypatch):
    """停權（is_active=False）後 token 未過期也要拒絕。"""
    _patch_backend(monkeypatch, user=_make_user(is_active=False))

    ws = _ws_for(_token())
    payload = _run(ws_auth.authenticate_websocket(ws, context="test"))

    assert payload is None
    assert ws.closed_with is not None
    assert ws.closed_with[0] == 4001


def test_unknown_user_closes_4001(monkeypatch):
    """sub 對應不到 User（已刪除）→ 拒絕。"""
    _patch_backend(monkeypatch, user=None)

    ws = _ws_for(_token())
    payload = _run(ws_auth.authenticate_websocket(ws, context="test"))

    assert payload is None
    assert ws.closed_with is not None
    assert ws.closed_with[0] == 4001


def test_non_uuid_sub_closes_4001(monkeypatch):
    """sub 非合法 UUID → 視為無效 token 拒絕（不碰 DB）。"""
    _patch_backend(monkeypatch, user=_make_user())

    ws = _ws_for(_token(subject="not-a-uuid"))
    payload = _run(ws_auth.authenticate_websocket(ws, context="test"))

    assert payload is None
    assert ws.closed_with is not None
    assert ws.closed_with[0] == 4001


def test_db_failure_fails_closed(monkeypatch):
    """DB 掛 → 拒絕（fail-closed；服務本來就不可用）。"""
    _patch_backend(
        monkeypatch, user=_make_user(), db_error=ConnectionError("db down (injected)")
    )

    ws = _ws_for(_token())
    payload = _run(ws_auth.authenticate_websocket(ws, context="test"))

    assert payload is None
    assert ws.closed_with is not None
    assert ws.closed_with[0] == 1011


# ──────────────────────────────────────────────────────────
# role 以 DB 為準
# ──────────────────────────────────────────────────────────

def test_role_overridden_by_db_truth(monkeypatch):
    """降權後舊 token 帶舊 role claim：payload role 必須換成 DB 目前的 role。

    dashboard_handler 讀 payload.get("role") 做 doctor/admin 閘門，
    覆蓋後即自動吃到 DB 真相。
    """
    _patch_backend(monkeypatch, user=_make_user(role="patient"))

    ws = _ws_for(_token(role="doctor"))  # token 還聲稱是 doctor
    payload = _run(ws_auth.authenticate_websocket(ws, context="test"))

    assert payload is not None
    assert payload.get("role") == "patient"  # DB 為準
    assert ws.closed_with is None


def test_legacy_query_param_also_gets_identity_checks(monkeypatch):
    """legacy ?token= 路徑同樣要走黑名單／is_active 檢查（同一 helper）。"""
    _patch_backend(monkeypatch, user=_make_user(is_active=False))

    ws = _FakeWebSocket(query_token=_token())
    payload = _run(ws_auth.authenticate_websocket(ws, context="legacy"))

    assert payload is None
    assert ws.closed_with is not None
    assert ws.closed_with[0] == 4001
