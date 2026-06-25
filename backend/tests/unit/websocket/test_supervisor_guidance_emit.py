"""
Unit tests for Supervisor 指導 WS 推播 helpers（CONV-2 / CONV-3）。

守護把 Supervisor 指導與降級狀態浮現到病患場次 WebSocket 的兩個 emit helper：
- _emit_supervisor_guidance（CONV-2）：有可用指導時送 'supervisor_guidance' 結構化事件，
  fallback 佔位 / 空指導 / 非 dict 時不送。
- _emit_supervisor_degraded（CONV-3）：Supervisor 逾時 / 退回 fallback 時送
  'supervisor_degraded' 低嚴重度 canonical 事件。

測試採純 Python stub（無真 DB、無真 WS），以 monkeypatch 把 conversation_handler
模組層的 `manager` 換成捕捉器，驗推播的 type 與 payload 形狀。沿用
tests/unit/services/test_session_authorization.py 的 asyncio.run 模式。
"""

from __future__ import annotations

import asyncio
from typing import Any

import app.websocket.conversation_handler as ch


def _run(coro):
    """在 sync test 裡跑 coroutine，避免多裝 pytest-asyncio。"""
    return asyncio.run(coro)


class _CaptureManager:
    """最小的 connection manager 替身，捕捉所有推播訊息。"""

    def __init__(self) -> None:
        self.session_messages: list[dict[str, Any]] = []
        self.localized_calls: list[dict[str, Any]] = []

    async def send_to_session(self, session_id: str, message: dict[str, Any]) -> bool:
        self.session_messages.append({"session_id": session_id, "message": message})
        return True

    async def send_localized_to_session(
        self,
        session_id: str,
        msg_type: str,
        code: str,
        params: dict[str, Any] | None = None,
        severity: str = "info",
    ) -> bool:
        self.localized_calls.append(
            {
                "session_id": session_id,
                "msg_type": msg_type,
                "code": code,
                "params": params or {},
                "severity": severity,
            }
        )
        return True


def _patch_manager(monkeypatch) -> _CaptureManager:
    cap = _CaptureManager()
    monkeypatch.setattr(ch, "manager", cap)
    return cap


# ── CONV-2：_emit_supervisor_guidance ────────────────────

def test_emit_guidance_sends_structured_event(monkeypatch):
    cap = _patch_manager(monkeypatch)
    guidance = {
        "next_focus": "請問疼痛是持續性還是間歇性？",
        "missing_hpi": ["severity", "associated_symptoms"],
        "hpi_completion_percentage": 40,
    }
    _run(ch._emit_supervisor_guidance("sess-1", guidance))

    assert len(cap.session_messages) == 1
    msg = cap.session_messages[0]["message"]
    assert msg["type"] == "supervisor_guidance"
    payload = msg["payload"]
    assert payload["nextFocus"] == "請問疼痛是持續性還是間歇性？"
    assert payload["missingHpi"] == ["severity", "associated_symptoms"]
    assert payload["hpiCompletionPercentage"] == 40


def test_emit_guidance_skips_fallback_placeholder(monkeypatch):
    cap = _patch_manager(monkeypatch)
    fallback = {
        "next_focus": "supervisor unavailable, continuing with default guidance",
        "missing_hpi": [],
        "hpi_completion_percentage": 0,
        "fallback": True,
    }
    _run(ch._emit_supervisor_guidance("sess-1", fallback))
    assert cap.session_messages == []


def test_emit_guidance_skips_when_none_or_empty(monkeypatch):
    cap = _patch_manager(monkeypatch)
    _run(ch._emit_supervisor_guidance("sess-1", None))
    _run(ch._emit_supervisor_guidance("sess-1", {}))
    _run(ch._emit_supervisor_guidance("sess-1", "not-a-dict"))  # type: ignore[arg-type]
    assert cap.session_messages == []


def test_emit_guidance_sends_when_only_completion_present(monkeypatch):
    cap = _patch_manager(monkeypatch)
    # hpi_completion_percentage=0（非 None）視為可呈現內容，仍送。
    _run(ch._emit_supervisor_guidance("sess-1", {"hpi_completion_percentage": 0}))
    assert len(cap.session_messages) == 1
    payload = cap.session_messages[0]["message"]["payload"]
    assert payload["hpiCompletionPercentage"] == 0
    assert payload["nextFocus"] == ""
    assert payload["missingHpi"] == []


def test_emit_guidance_never_raises_on_manager_error(monkeypatch):
    class _BoomManager(_CaptureManager):
        async def send_to_session(self, session_id, message):  # type: ignore[override]
            raise RuntimeError("ws gone")

    monkeypatch.setattr(ch, "manager", _BoomManager())
    # 不可拋例外（不得阻塞主 turn 流程）。
    _run(ch._emit_supervisor_guidance("sess-1", {"next_focus": "x"}))


# ── CONV-3：_emit_supervisor_degraded ────────────────────

def test_emit_degraded_sends_localized_warning(monkeypatch):
    cap = _patch_manager(monkeypatch)
    _run(ch._emit_supervisor_degraded("sess-1"))

    assert len(cap.localized_calls) == 1
    call = cap.localized_calls[0]
    assert call["msg_type"] == "supervisor_degraded"
    assert call["code"] == "events.supervisor.degraded"
    assert call["severity"] == "warning"
    assert call["params"] == {}


def test_emit_degraded_never_raises_on_manager_error(monkeypatch):
    class _BoomManager(_CaptureManager):
        async def send_localized_to_session(self, *a, **k):  # type: ignore[override]
            raise RuntimeError("ws gone")

    monkeypatch.setattr(ch, "manager", _BoomManager())
    _run(ch._emit_supervisor_degraded("sess-1"))
