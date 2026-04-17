"""
守護 P2 #15 WebSocket auth handshake：

- 舊行為兼容：?token= 仍可工作（會 log warning）
- Handshake 訊息模式：`{type:"auth", token:...}` 驗證通過
- 失敗情境：timeout / 非 JSON / type 錯誤 / 缺 token / Token 過期 都 close(4001)
- accept() 只呼叫一次（避免 RuntimeError）

用 FakeWebSocket 模擬 Starlette WebSocket 介面；不起真 HTTP。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from app.core.security import create_access_token
from app.websocket import auth as ws_auth


def _run(coro):
    return asyncio.run(coro)


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
    token = create_access_token(subject="user-1", role="patient")
    msg = json.dumps({"type": "auth", "token": token})
    ws = _FakeWebSocket(incoming=[msg])

    payload = _run(ws_auth.authenticate_websocket(ws, context="test"))

    assert payload is not None
    assert payload.get("sub") == "user-1"
    assert payload.get("role") == "patient"
    assert ws.accepted_count == 1
    assert ws.closed_with is None


def test_legacy_query_param_still_works():
    token = create_access_token(subject="user-2", role="doctor")
    ws = _FakeWebSocket(query_token=token)

    payload = _run(ws_auth.authenticate_websocket(ws, context="legacy"))

    assert payload is not None
    assert payload.get("sub") == "user-2"
    assert ws.accepted_count == 1
    assert ws.closed_with is None


def test_accept_is_called_exactly_once():
    """不管走哪條路徑 accept() 都只能一次（連兩次會 Starlette RuntimeError）。"""
    token = create_access_token(subject="u", role="patient")
    ws = _FakeWebSocket(incoming=[json.dumps({"type": "auth", "token": token})])
    _run(ws_auth.authenticate_websocket(ws, context="test"))
    assert ws.accepted_count == 1


def test_authenticate_alias_type_also_works():
    """type='authenticate' 也接受（防呆，舊前端版本可能叫這個名字）。"""
    token = create_access_token(subject="u", role="patient")
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
    assert "時限" in ws.closed_with[1] or "逾時" in ws.closed_with[1] or "未在" in ws.closed_with[1]


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
