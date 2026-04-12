"""
自定義中介層
- Request ID: 為每個請求附加唯一追蹤 ID
- Audit Logging: 記錄操作至 audit_logs 表
"""

import logging
import time
import uuid
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

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


class AuditLoggingMiddleware(BaseHTTPMiddleware):
    """
    稽核日誌中介層 — 記錄每個寫入操作（POST/PUT/PATCH/DELETE）的
    基本資訊至 audit_logs 表。
    讀取操作 (GET/OPTIONS/HEAD) 不記錄以避免過量日誌。
    """

    # 不記錄稽核日誌的路徑前綴
    SKIP_PATHS: set[str] = {
        "/api/v1/health",
        "/docs",
        "/redoc",
        "/openapi.json",
    }

    # 僅記錄這些 HTTP 方法
    AUDIT_METHODS: set[str] = {"POST", "PUT", "PATCH", "DELETE"}

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # 跳過不需要稽核的路徑與方法
        if request.url.path in self.SKIP_PATHS or request.method not in self.AUDIT_METHODS:
            return await call_next(request)

        start_time = time.monotonic()
        response = await call_next(request)
        duration_ms = (time.monotonic() - start_time) * 1000

        # 非同步寫入稽核日誌（背景任務避免阻塞回應）
        try:
            _log_audit_entry(request, response, duration_ms)
        except Exception:
            logger.exception("Failed to write audit log entry")

        return response


def _log_audit_entry(request: Request, response: Response, duration_ms: float) -> None:
    """將稽核資訊輸出至 logger，實際寫入資料庫由背景任務/服務層處理"""
    user_id = None
    if hasattr(request.state, "user"):
        user_id = getattr(request.state.user, "id", None)

    request_id = getattr(request.state, "request_id", "unknown")
    client_ip = request.client.host if request.client else "unknown"

    logger.info(
        "AUDIT | request_id=%s method=%s path=%s status=%s user=%s ip=%s duration=%.1fms",
        request_id,
        request.method,
        request.url.path,
        response.status_code,
        user_id,
        client_ip,
        duration_ms,
    )
