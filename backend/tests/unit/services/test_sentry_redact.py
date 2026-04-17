"""
Unit tests for Sentry `redact_sensitive`（TODO P1-#9）。

確保敏感欄位在事件送出前被取代成 `[Filtered]`：
- Authorization / Cookie header
- 請求 body 的 password / access_token / refresh_token
- 巢狀 dict / list 也要清洗
- 非敏感欄位不受影響
"""

from __future__ import annotations

from app.core.sentry import _FILTERED, redact_sensitive


def test_redact_strips_authorization_header():
    event = {
        "request": {
            "headers": {
                "Authorization": "Bearer secrettoken123",
                "Content-Type": "application/json",
            },
        }
    }
    out = redact_sensitive(event)
    assert out["request"]["headers"]["Authorization"] == _FILTERED
    assert out["request"]["headers"]["Content-Type"] == "application/json"


def test_redact_strips_password_and_tokens_in_body():
    event = {
        "request": {
            "data": {
                "email": "user@example.com",
                "password": "hunter2",
                "access_token": "eyJhbGciOi...",
                "refresh_token": "eyJhbGciOi...",
            }
        }
    }
    out = redact_sensitive(event)
    data = out["request"]["data"]
    assert data["email"] == "user@example.com"
    assert data["password"] == _FILTERED
    assert data["access_token"] == _FILTERED
    assert data["refresh_token"] == _FILTERED


def test_redact_recurses_into_nested_structures():
    event = {
        "extra": {
            "session": {
                "user": {"id": "u1", "jwt": "eyJ..."},
                "trail": [
                    {"api_key": "sk-...", "ok": True},
                    {"note": "normal"},
                ],
            }
        }
    }
    out = redact_sensitive(event)
    assert out["extra"]["session"]["user"]["jwt"] == _FILTERED
    assert out["extra"]["session"]["user"]["id"] == "u1"
    assert out["extra"]["session"]["trail"][0]["api_key"] == _FILTERED
    assert out["extra"]["session"]["trail"][0]["ok"] is True
    assert out["extra"]["session"]["trail"][1]["note"] == "normal"


def test_redact_preserves_non_sensitive_event_shape():
    event = {
        "message": "test error",
        "level": "error",
        "tags": {"module": "auth"},
    }
    out = redact_sensitive(event)
    assert out == event


def test_redact_handles_set_cookie_case_insensitive():
    event = {
        "request": {
            "headers": {
                "Set-Cookie": "sid=abc; Path=/",
                "X-Request-ID": "req-123",
            }
        }
    }
    out = redact_sensitive(event)
    assert out["request"]["headers"]["Set-Cookie"] == _FILTERED
    assert out["request"]["headers"]["X-Request-ID"] == "req-123"
