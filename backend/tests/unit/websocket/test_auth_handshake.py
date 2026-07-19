"""
守護 P2 #15 WebSocket auth handshake：

- 舊行為兼容：?token= 仍可工作（會 log warning）
- Handshake 訊息模式：`{type:"auth", token:...}` 驗證通過
- 失敗情境：timeout / 非 JSON / type 錯誤 / 缺 token / Token 過期 都 close(4001)
- accept() 只呼叫一次（避免 RuntimeError）

用 FakeWebSocket 模擬 Starlette WebSocket 介面；不起真 HTTP。
簽章驗過後的身分檢查（黑名單 / User 載入 / role 覆蓋）由 autouse fixture
stub 成「不在黑名單、使用者存在且啟用」的快樂路徑；
拒絕情境的專屬測試見 test_auth_identity_checks.py。
"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.security import create_access_token
from app.websocket import auth as ws_auth

# 簽章後身分檢查需要 UUID sub（非 UUID 會被拒絕，與生產 token 一致）
_UID_1 = "11111111-1111-4111-8111-111111111111"
_UID_2 = "22222222-2222-4222-8222-222222222222"


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _identity_backend(monkeypatch):
    """Stub 掉黑名單 Redis 與 User DB 查詢（單元測試不碰真基礎設施）。

    預設快樂路徑：黑名單皆未命中、使用者存在且啟用、role=token claim 同值
    （"patient"），讓既有 handshake 測試的斷言不受 role 覆蓋影響。
    """
    user = SimpleNamespace(is_active=True, role=SimpleNamespace(value="patient"))

    class _FakeRedis:
        async def exists(self, key: str) -> int:
            return 0

    async def _fake_get_redis():
        return _FakeRedis()

    class _FakeResult:
        def scalar_one_or_none(self):
            return user

    class _FakeDB:
        async def execute(self, stmt):
            return _FakeResult()

    @asynccontextmanager
    async def _fake_get_db_session():
        yield _FakeDB()

    monkeypatch.setattr(ws_auth, "get_cache_redis", _fake_get_redis)
    monkeypatch.setattr(ws_auth, "get_db_session", _fake_get_db_session)


class _FakeWebSocket:
    """覆蓋本檔用到的 Starlette WebSocket API."""

    def __init__(
        self,
        query_token: str | None = None,
        incoming: list[str] | None = None,
        delay_before_first_message: float = 0.0,
    ) -> None:
        self.query_params = {"token": query_token} if query_token else {}
        self._incoming: list[str] = list(incoming or [])
        self._delay = delay_before_first_message
        self.accepted_count = 0
        self.closed_with: tuple[int, str] | None = None

    async def accept(self) -> None:
        self.accepted_count += 1

    async def receive_text(self) -> str:
        if self._delay:
            # 故意睡比 HANDSHAKE_TIMEOUT 久（讓 wait_for 先 TimeoutError）
            await asyncio.sleep(self._delay)
        if not self._incoming:
            # 永遠等不到資料
            await asyncio.sleep(3600)
        return self._incoming.pop(0)

    async def close(self, code: int = 1000, reason: str = "") -> None:
        if self.closed_with is None:
            self.closed_with = (code, reason)


# ──────────────────────────────────────────────────────────
# 成功路徑
# ──────────────────────────────────────────────────────────

def test_handshake_message_authenticates_and_returns_payload():
    token = create_access_token(subject=_UID_1, role="patient")
    msg = json.dumps({"type": "auth", "token": token})
    ws = _FakeWebSocket(incoming=[msg])

    payload = _run(ws_auth.authenticate_websocket(ws, context="test"))

    assert payload is not None
    assert payload.get("sub") == _UID_1
    assert payload.get("role") == "patient"
    assert ws.accepted_count == 1
    assert ws.closed_with is None


def test_legacy_query_param_still_works():
    token = create_access_token(subject=_UID_2, role="doctor")
    ws = _FakeWebSocket(query_token=token)

    payload = _run(ws_auth.authenticate_websocket(ws, context="legacy"))

    assert payload is not None
    assert payload.get("sub") == _UID_2
    assert ws.accepted_count == 1
    assert ws.closed_with is None


def test_accept_is_called_exactly_once():
    """不管走哪條路徑 accept() 都只能一次（連兩次會 Starlette RuntimeError）。"""
    token = create_access_token(subject=_UID_1, role="patient")
    ws = _FakeWebSocket(incoming=[json.dumps({"type": "auth", "token": token})])
    _run(ws_auth.authenticate_websocket(ws, context="test"))
    assert ws.accepted_count == 1


def test_authenticate_alias_type_also_works():
    """type='authenticate' 也接受（防呆，舊前端版本可能叫這個名字）。"""
    token = create_access_token(subject=_UID_1, role="patient")
    msg = json.dumps({"type": "authenticate", "token": token})
    ws = _FakeWebSocket(incoming=[msg])
    payload = _run(ws_auth.authenticate_websocket(ws, context="test"))
    assert payload is not None


# ──────────────────────────────────────────────────────────
# 失敗路徑 — 都必須 close(4001)，accept 仍應為 1
# ──────────────────────────────────────────────────────────

def test_invalid_jwt_closes_4001():
    ws = _FakeWebSocket(incoming=[json.dumps({"type": "auth", "token": "not-a-jwt"})])
    payload = _run(ws_auth.authenticate_websocket(ws, context="test"))
    assert payload is None
    assert ws.closed_with is not None
    assert ws.closed_with[0] == 4001


def test_invalid_query_token_closes_4001():
    ws = _FakeWebSocket(query_token="not-a-jwt")
    payload = _run(ws_auth.authenticate_websocket(ws, context="test"))
    assert payload is None
    assert ws.closed_with is not None
    assert ws.closed_with[0] == 4001


def test_handshake_timeout_closes_4001(monkeypatch):
    # 把 timeout 調成極小，不必真的等 5 秒
    monkeypatch.setattr(ws_auth, "HANDSHAKE_TIMEOUT_SECONDS", 0.05)
    ws = _FakeWebSocket(incoming=[])  # 永不送訊息
    payload = _run(ws_auth.authenticate_websocket(ws, context="test"))
    assert payload is None
    assert ws.closed_with is not None
    assert ws.closed_with[0] == 4001
    # TODO-E2: close reason 改送 canonical i18n code（前端負責翻譯）
    assert ws.closed_with[1] == "errors.ws.handshake_timeout"


def test_non_json_message_closes_4001():
    ws = _FakeWebSocket(incoming=["this is not json"])
    payload = _run(ws_auth.authenticate_websocket(ws, context="test"))
    assert payload is None
    assert ws.closed_with is not None
    assert ws.closed_with[0] == 4001


def test_wrong_type_closes_4001():
    token = create_access_token(subject="u", role="patient")
    msg = json.dumps({"type": "ping", "token": token})
    ws = _FakeWebSocket(incoming=[msg])
    payload = _run(ws_auth.authenticate_websocket(ws, context="test"))
    assert payload is None
    assert ws.closed_with is not None
    assert ws.closed_with[0] == 4001


def test_missing_token_field_closes_4001():
    ws = _FakeWebSocket(incoming=[json.dumps({"type": "auth"})])
    payload = _run(ws_auth.authenticate_websocket(ws, context="test"))
    assert payload is None
    assert ws.closed_with is not None
    assert ws.closed_with[0] == 4001


def test_empty_token_field_closes_4001():
    ws = _FakeWebSocket(incoming=[json.dumps({"type": "auth", "token": ""})])
    payload = _run(ws_auth.authenticate_websocket(ws, context="test"))
    assert payload is None
    assert ws.closed_with is not None
    assert ws.closed_with[0] == 4001


def test_non_dict_json_closes_4001():
    ws = _FakeWebSocket(incoming=[json.dumps(["auth", "token"])])
    payload = _run(ws_auth.authenticate_websocket(ws, context="test"))
    assert payload is None
    assert ws.closed_with is not None
    assert ws.closed_with[0] == 4001
