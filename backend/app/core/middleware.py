"""
自定義中介層
- Request ID: 為每個請求附加唯一追蹤 ID
- Audit Logging: 記錄 sensitive 操作至 audit_logs 表
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from typing import Callable, Optional
from uuid import UUID

from sqlalchemy import text
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.models.enums import AuditAction

logger = logging.getLogger(__name__)


class RequestIdMiddleware(BaseHTTPMiddleware):
    """
    為每個 HTTP 請求注入 X-Request-ID header。
    若請求已帶有 X-Request-ID 則沿用，否則自動產生。
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        # 附加到 request.state 供下游使用
        request.state.request_id = request_id

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


# ──────────────────────────────────────────────────────────
# 安全 Headers
# ──────────────────────────────────────────────────────────

# HSTS 的選擇：max-age 一年 + preload ready（只在 HTTPS 生效，代理層非 HTTPS 時瀏覽器也不會錯誤提示）
_HSTS_VALUE = "max-age=31536000; includeSubDomains; preload"

# 預設 headers（API 用；/docs /openapi.json 另外處理）
_DEFAULT_SECURITY_HEADERS = {
    "Strict-Transport-Security": _HSTS_VALUE,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(self), geolocation=()",
}

# /docs 與 /redoc 需要 loading CDN JS（Swagger / ReDoc）；為了不把 UI 打壞，
# 這些路徑跳過嚴格 CSP / X-Frame-Options，只留最基本的 HSTS + nosniff。
_DOCS_PATHS = {"/docs", "/redoc", "/openapi.json"}
_DOCS_SECURITY_HEADERS = {
    "Strict-Transport-Security": _HSTS_VALUE,
    "X-Content-Type-Options": "nosniff",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    統一注入安全 headers。

    設計：
    - API 路徑套嚴格（`_DEFAULT_SECURITY_HEADERS`）：HSTS、nosniff、DENY frame、Referrer 限同源、
      Permissions-Policy 只允許 microphone（自家 WebRTC / getUserMedia）
    - `/docs`、`/redoc`、`/openapi.json` 走較寬鬆集合（`_DOCS_SECURITY_HEADERS`）避免打壞 Swagger UI
    - 已存在的 header（例如上游代理已設）**不覆寫**，讓 Railway / Cloudflare 的政策贏
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        response = await call_next(request)
        headers = _DOCS_SECURITY_HEADERS if request.url.path in _DOCS_PATHS else _DEFAULT_SECURITY_HEADERS
        for name, value in headers.items():
            response.headers.setdefault(name, value)
        return response


# ──────────────────────────────────────────────────────────
# 稽核路徑對應表
# ──────────────────────────────────────────────────────────
# key：(method, path_regex)；value：(action, resource_type)
# 只寫「sensitive 操作」，避免 audit_logs 洪水。
# resource_id 若路徑帶 UUID 則從 regex group 'rid' 抓出；否則留空。
_UUID_RE = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"

_AUDIT_RULES: list[tuple[str, re.Pattern[str], AuditAction, str]] = [
    # auth
    ("POST",   re.compile(r"^/api/v1/auth/login$"),                            AuditAction.LOGIN,       "user"),
    ("POST",   re.compile(r"^/api/v1/auth/logout$"),                           AuditAction.LOGOUT,      "user"),
    ("POST",   re.compile(r"^/api/v1/auth/register$"),                         AuditAction.CREATE,      "user"),
    ("POST",   re.compile(r"^/api/v1/auth/change-password$"),                  AuditAction.UPDATE,      "user"),
    ("POST",   re.compile(r"^/api/v1/auth/reset-password$"),                   AuditAction.UPDATE,      "user"),
    ("PUT",    re.compile(r"^/api/v1/auth/me$"),                               AuditAction.UPDATE,      "user"),
    # sessions
    ("POST",   re.compile(r"^/api/v1/sessions/?$"),                            AuditAction.CREATE,      "session"),
    ("PUT",    re.compile(rf"^/api/v1/sessions/(?P<rid>{_UUID_RE})/?$"),       AuditAction.UPDATE,      "session"),
    ("PATCH",  re.compile(rf"^/api/v1/sessions/(?P<rid>{_UUID_RE})/?$"),       AuditAction.UPDATE,      "session"),
    ("DELETE", re.compile(rf"^/api/v1/sessions/(?P<rid>{_UUID_RE})/?$"),       AuditAction.DELETE,      "session"),
    # SOAP 報告審閱
    ("PUT",    re.compile(rf"^/api/v1/soap-reports/(?P<rid>{_UUID_RE})/?$"),   AuditAction.REVIEW,      "soap_report"),
    ("PATCH",  re.compile(rf"^/api/v1/soap-reports/(?P<rid>{_UUID_RE})/?$"),   AuditAction.REVIEW,      "soap_report"),
    # 紅旗 ack
    ("POST",   re.compile(rf"^/api/v1/red-flag-alerts/(?P<rid>{_UUID_RE})/acknowledge/?$"), AuditAction.ACKNOWLEDGE, "red_flag_alert"),
    # 匯出
    ("POST",   re.compile(r"^/api/v1/.*/export$"),                             AuditAction.EXPORT,      "export"),
    ("GET",    re.compile(r"^/api/v1/.*/export$"),                             AuditAction.EXPORT,      "export"),
]


def _match_audit_rule(method: str, path: str) -> Optional[tuple[AuditAction, str, Optional[str]]]:
    """回傳 (action, resource_type, resource_id) 或 None 代表不記錄。"""
    for m, pattern, action, rtype in _AUDIT_RULES:
        if m != method:
            continue
        match = pattern.match(path)
        if match:
            rid: Optional[str] = match.groupdict().get("rid")
            return action, rtype, rid
    return None


class AuditLoggingMiddleware(BaseHTTPMiddleware):
    """
    稽核日誌中介層 — 只記錄 `_AUDIT_RULES` 命中的 sensitive 操作。

    設計：
    - 用 `asyncio.create_task` fire-and-forget，不阻塞 response
    - 寫入失敗只 log，不影響 API 回應（audit 失敗 ≠ 業務失敗）
    - `async_session_factory()` 自己開 session（request 的 DB session 已 close）
    - 失敗的請求（status >= 400）也記錄，details 帶 status_code 方便審計
    """

    SKIP_PATHS: set[str] = {
        "/api/v1/health",
        "/docs",
        "/redoc",
        "/openapi.json",
    }

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if request.url.path in self.SKIP_PATHS:
            return await call_next(request)

        start_time = time.monotonic()
        response = await call_next(request)
        duration_ms = (time.monotonic() - start_time) * 1000

        matched = _match_audit_rule(request.method, request.url.path)
        if matched is None:
            return response

        action, resource_type, resource_id = matched

        # 收集欄位
        user_id = _extract_user_id(request)
        client_ip = _extract_client_ip(request)
        user_agent = request.headers.get("user-agent", "")[:500]
        request_id = getattr(request.state, "request_id", None)

        details = {
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": round(duration_ms, 1),
        }
        if request_id:
            details["request_id"] = request_id

        # 先 log（本地 debug/運維觀察）
        logger.info(
            "AUDIT | action=%s resource=%s/%s user=%s ip=%s status=%d",
            action.value, resource_type, resource_id, user_id, client_ip, response.status_code,
        )

        # 非同步落表（fire-and-forget）
        asyncio.create_task(
            _persist_audit_entry(
                user_id=user_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                details=details,
                ip_address=client_ip,
                user_agent=user_agent,
            )
        )

        return response


def _extract_user_id(request: Request) -> Optional[UUID]:
    """從 request.state 取 user_id（get_current_user 會設）。"""
    user = getattr(request.state, "user", None)
    if user is None:
        return None
    uid = getattr(user, "id", None)
    if isinstance(uid, UUID):
        return uid
    if isinstance(uid, str):
        try:
            return UUID(uid)
        except ValueError:
            return None
    return None


def _extract_client_ip(request: Request) -> Optional[str]:
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    if request.client:
        return request.client.host
    return None


async def _persist_audit_entry(
    *,
    user_id: Optional[UUID],
    action: AuditAction,
    resource_type: str,
    resource_id: Optional[str],
    details: dict,
    ip_address: Optional[str],
    user_agent: Optional[str],
) -> None:
    """
    用獨立 session 插入 audit_logs。
    放到分區表上（created_at 由 DB `now()` 預設）。失敗只記 log，不 raise。
    """
    try:
        # 延後 import 避免 module 初始化期間 DB engine 還沒建好
        from app.core.database import async_session_factory

        async with async_session_factory() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO audit_logs (user_id, action, resource_type, resource_id,
                                             details, ip_address, user_agent)
                    VALUES (:user_id, :action, :resource_type, :resource_id,
                            CAST(:details AS jsonb), CAST(:ip_address AS inet), :user_agent)
                    """
                ),
                {
                    "user_id": user_id,
                    "action": action.value,
                    "resource_type": resource_type,
                    "resource_id": resource_id,
                    "details": _json_dumps(details),
                    "ip_address": ip_address,
                    "user_agent": user_agent,
                },
            )
            await session.commit()
    except Exception:
        # 不能讓 audit 失敗影響 API；只記 log
        logger.exception(
            "audit log persist failed | action=%s resource=%s/%s",
            action.value, resource_type, resource_id,
        )


def _json_dumps(obj: dict) -> str:
    import json
    return json.dumps(obj, ensure_ascii=False, default=str)
