"""
i18n 錯誤訊息解譯測試 — 驗證 register_exception_handlers 註冊的 handler 會

1. 偵測 `AppException.message` 是否為 `errors.*` key，並依請求語言翻譯。
2. 支援 Accept-Language header / user.preferred_language 的 fallback 鏈。
3. `message_kwargs` 會被 format 進訊息。
4. 非 key 的原始字串會原樣回傳（回溯相容）。
5. 未知 key 回 `[missing:...]` 不 crash。

採 FastAPI TestClient + 臨時 app 做 integration-style 測試。
"""
from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.exceptions import (
    AppException,
    ErrorCode,
    ForbiddenException,
    InvalidStatusTransitionException,
    NotFoundException,
    RateLimitExceededException,
    register_exception_handlers,
)


def _build_app(exc_factory) -> FastAPI:
    """建立只含 /boom 的極簡 app，丟指定 exception。"""
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom")
    def boom() -> None:
        raise exc_factory()

    return app


def _get_message(client: TestClient, accept_language: str | None = None) -> dict[str, Any]:
    headers: dict[str, str] = {}
    if accept_language is not None:
        headers["Accept-Language"] = accept_language
    resp = client.get("/boom", headers=headers)
    return resp.json()["error"]


# ── 基本翻譯 ────────────────────────────────────────────
def test_zh_tw_translates_known_key():
    app = _build_app(lambda: NotFoundException("errors.session_not_found"))
    with TestClient(app, raise_server_exceptions=False) as client:
        err = _get_message(client, "zh-TW")
    assert err["message"] == "場次不存在"
    assert err["code"] == ErrorCode.NOT_FOUND.value


def test_en_us_translates_known_key():
    app = _build_app(lambda: NotFoundException("errors.session_not_found"))
    with TestClient(app, raise_server_exceptions=False) as client:
        err = _get_message(client, "en-US")
    assert err["message"] == "Session not found"


def test_fallback_to_default_when_no_accept_language():
    app = _build_app(lambda: NotFoundException("errors.report_not_found"))
    with TestClient(app, raise_server_exceptions=False) as client:
        err = _get_message(client, None)
    # DEFAULT_LANGUAGE = zh-TW
    assert err["message"] == "報告不存在"


def test_two_letter_language_family_expands():
    """瀏覽器常送 'en' 或 'zh' 兩字碼 → 應擴展為已支援的完整 locale。"""
    app = _build_app(lambda: NotFoundException("errors.alert_not_found"))
    with TestClient(app, raise_server_exceptions=False) as client:
        err = _get_message(client, "en")
    assert err["message"] == "Alert not found"


def test_unsupported_language_falls_back_to_default():
    app = _build_app(lambda: NotFoundException("errors.patient_not_found"))
    with TestClient(app, raise_server_exceptions=False) as client:
        err = _get_message(client, "fr-FR")
    # fr-FR 不在 SUPPORTED_LANGUAGES → 走 DEFAULT_LANGUAGE (zh-TW)
    assert err["message"] == "病患不存在"


# ── message_kwargs 格式化 ───────────────────────────────
def test_message_kwargs_are_applied_to_template():
    def factory():
        return InvalidStatusTransitionException(
            "errors.status_transition_not_allowed",
            details={"current": "waiting", "target": "completed"},
            message_kwargs={"current": "waiting", "target": "completed"},
        )

    app = _build_app(factory)
    with TestClient(app, raise_server_exceptions=False) as client:
        err_zh = _get_message(client, "zh-TW")
        err_en = _get_message(client, "en-US")
    assert err_zh["message"] == "無法從 waiting 轉移至 completed"
    assert err_en["message"] == "Cannot transition from waiting to completed"


def test_rate_limit_retry_after_localized():
    def factory():
        return RateLimitExceededException(
            "errors.login_ip_rate_limited",
            details={"retry_after": 42, "scope": "ip"},
            message_kwargs={"retry_after": 42},
        )

    app = _build_app(factory)
    with TestClient(app, raise_server_exceptions=False) as client:
        assert "42 秒" in _get_message(client, "zh-TW")["message"]
        assert "42 seconds" in _get_message(client, "en-US")["message"]


# ── 回溯相容：非 key 的字串不動 ───────────────────────
def test_non_key_message_is_passed_through():
    """舊字串（不在 MESSAGES 註冊）原樣回傳，不會變 [missing:...]。"""
    def factory():
        return ForbiddenException("arbitrary plain message")

    app = _build_app(factory)
    with TestClient(app, raise_server_exceptions=False) as client:
        err = _get_message(client, "zh-TW")
    assert err["message"] == "arbitrary plain message"


# ── 未知 key：不 crash ─────────────────────────────────
def test_unknown_key_does_not_crash():
    def factory():
        return NotFoundException("errors.does_not_exist")

    app = _build_app(factory)
    with TestClient(app, raise_server_exceptions=False) as client:
        err = _get_message(client, "en-US")
    # 不在 MESSAGES 裡 → is_message_key 回 False → 回 key 本身（原字串 passthrough）
    assert err["message"] == "errors.does_not_exist"


# ── Accept-Language 多候選挑第一個支援的 ────────────────
def test_accept_language_picks_first_supported():
    app = _build_app(lambda: NotFoundException("errors.user_not_found"))
    with TestClient(app, raise_server_exceptions=False) as client:
        err = _get_message(client, "fr-FR, en-US;q=0.8, zh-TW;q=0.5")
    assert err["message"] == "User not found"


# ── format kwargs 不足：不 crash ────────────────────────
def test_missing_kwargs_returns_template_without_crash():
    """template 有 {retry_after} 但 caller 沒傳 → get_message 會 log warning 回原 template。"""
    def factory():
        return RateLimitExceededException(
            "errors.login_ip_rate_limited",
            details={"scope": "ip"},
            # 故意不給 message_kwargs
        )

    app = _build_app(factory)
    with TestClient(app, raise_server_exceptions=False) as client:
        err = _get_message(client, "en-US")
    # 未 format → 回模板本身（含 {retry_after}）
    assert "{retry_after}" in err["message"]


# ── 非 HTTPException/AppException：走 unhandled handler 也要本地化 ──
def test_unhandled_exception_returns_localized_internal_error():
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/crash")
    def crash() -> None:
        raise RuntimeError("boom")

    with TestClient(app, raise_server_exceptions=False) as client:
        resp_zh = client.get("/crash", headers={"Accept-Language": "zh-TW"})
        resp_en = client.get("/crash", headers={"Accept-Language": "en-US"})

    assert resp_zh.status_code == 500
    assert resp_zh.json()["error"]["message"] == "內部伺服器錯誤"
    assert resp_en.json()["error"]["message"] == "Internal server error"


# ── Response schema 不變（{error: {...}}） ──────────────
def test_response_schema_unchanged():
    app = _build_app(lambda: NotFoundException("errors.session_not_found"))
    with TestClient(app, raise_server_exceptions=False) as client:
        body = client.get("/boom").json()
    # 必須保留 error 包裝以及 code/message/details/request_id/timestamp 五個欄位
    assert set(body.keys()) == {"error"}
    assert {"code", "message", "details", "request_id", "timestamp"}.issubset(
        body["error"].keys()
    )


# ── Sanity: AppException 直接 raise 帶 ErrorCode 也可本地化 ──
def test_bare_app_exception_with_key_is_localized():
    def factory():
        return AppException(
            ErrorCode.CONFLICT,
            "errors.report_already_exists",
        )

    app = _build_app(factory)
    with TestClient(app, raise_server_exceptions=False) as client:
        err_zh = _get_message(client, "zh-TW")
        err_en = _get_message(client, "en-US")
    assert err_zh["message"] == "報告已存在"
    assert err_en["message"] == "Report already exists"
