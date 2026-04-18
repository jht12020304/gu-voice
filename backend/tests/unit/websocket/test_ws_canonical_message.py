"""
TODO-E2：WebSocket canonical code 契約測試。

- `WSMessage` schema 必須拒絕空 code / 非法 severity。
- `send_ws_message` 以標準 shape 呼叫 `ws.send_json`。
- `ConnectionManager.send_localized_to_session` 與 `broadcast_localized_dashboard`
  會包出 `{type, id, timestamp, payload: {code, params, severity}}` 的信封。
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from pydantic import ValidationError

from app.schemas.ws_message import WSMessage, send_ws_message
from app.websocket.connection_manager import ConnectionManager


class _FakeWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.closed: bool = False

    async def accept(self) -> None:
        pass

    async def send_json(self, data: dict[str, Any]) -> None:
        self.sent.append(data)

    async def close(self, *args: Any, **kwargs: Any) -> None:
        self.closed = True


# ── schema ────────────────────────────────────────────────


def test_ws_message_defaults():
    msg = WSMessage(code="errors.ws.invalid_token")
    assert msg.code == "errors.ws.invalid_token"
    assert msg.params == {}
    assert msg.severity == "info"


def test_ws_message_rejects_empty_code():
    with pytest.raises(ValidationError):
        WSMessage(code="")


def test_ws_message_rejects_bad_severity():
    with pytest.raises(ValidationError):
        WSMessage(code="x", severity="boom")  # type: ignore[arg-type]


def test_ws_message_rejects_extra_fields():
    with pytest.raises(ValidationError):
        WSMessage(code="x", message="legacy free-form text")  # type: ignore[call-arg]


# ── helper: send_ws_message ───────────────────────────────


def test_send_ws_message_shape():
    async def _run():
        ws = _FakeWebSocket()
        await send_ws_message(
            ws,  # type: ignore[arg-type]
            code="errors.ws.invalid_token",
            params={"hint": "token expired"},
            severity="error",
        )
        assert len(ws.sent) == 1
        payload = ws.sent[0]
        assert payload == {
            "code": "errors.ws.invalid_token",
            "params": {"hint": "token expired"},
            "severity": "error",
        }

    asyncio.run(_run())


def test_send_ws_message_default_severity_info():
    async def _run():
        ws = _FakeWebSocket()
        await send_ws_message(ws, code="events.session.started")  # type: ignore[arg-type]
        assert ws.sent[0]["severity"] == "info"
        assert ws.sent[0]["params"] == {}

    asyncio.run(_run())


# ── ConnectionManager canonical helpers ───────────────────


def test_manager_send_localized_to_session_wraps_envelope():
    async def _run():
        mgr = ConnectionManager()
        ws = _FakeWebSocket()
        await mgr.connect_session(ws, "sess-1", already_accepted=True)  # type: ignore[arg-type]
        ok = await mgr.send_localized_to_session(
            "sess-1",
            msg_type="session_status",
            code="events.session.idle_timeout",
            params={"minutes": 10},
            severity="warning",
        )
        assert ok is True
        assert len(ws.sent) == 1
        env = ws.sent[0]
        assert env["type"] == "session_status"
        assert set(env.keys()) == {"type", "id", "timestamp", "payload"}
        assert env["payload"] == {
            "code": "events.session.idle_timeout",
            "params": {"minutes": 10},
            "severity": "warning",
        }

    asyncio.run(_run())


def test_manager_broadcast_localized_dashboard_merges_extra():
    async def _run():
        mgr = ConnectionManager()
        ws = _FakeWebSocket()
        await mgr.connect_dashboard(ws, already_accepted=True)  # type: ignore[arg-type]
        await mgr.broadcast_localized_dashboard(
            msg_type="session_status_changed",
            code="events.session.completed_normal",
            params={},
            severity="info",
            extra={
                "sessionId": "sess-1",
                "status": "completed",
                "previousStatus": "in_progress",
                # 下方這組 key 會被保護，不允許覆蓋 canonical 欄位
                "code": "SHOULD_BE_IGNORED",
                "severity": "SHOULD_BE_IGNORED",
            },
        )
        assert len(ws.sent) == 1
        payload = ws.sent[0]["payload"]
        assert payload["code"] == "events.session.completed_normal"
        assert payload["severity"] == "info"
        assert payload["sessionId"] == "sess-1"
        assert payload["status"] == "completed"
        assert payload["previousStatus"] == "in_progress"

    asyncio.run(_run())


def test_manager_send_localized_to_session_missing_session_returns_false():
    async def _run():
        mgr = ConnectionManager()
        ok = await mgr.send_localized_to_session(
            "no-such-session",
            msg_type="error",
            code="errors.ws.internal_error",
        )
        assert ok is False

    asyncio.run(_run())
