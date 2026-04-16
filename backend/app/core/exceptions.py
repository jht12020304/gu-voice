"""
自定義例外類別 + FastAPI 例外處理器註冊
"""

from enum import Enum
from typing import Any, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


# ── 錯誤碼列舉 ─────────────────────────────────────────
class ErrorCode(str, Enum):
    """API 錯誤碼對照表"""
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    CONFLICT = "CONFLICT"
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    ACCOUNT_DISABLED = "ACCOUNT_DISABLED"
    EMAIL_ALREADY_EXISTS = "EMAIL_ALREADY_EXISTS"
    SESSION_NOT_FOUND = "SESSION_NOT_FOUND"
    SESSION_NOT_ACTIVE = "SESSION_NOT_ACTIVE"
    INVALID_STATUS_TRANSITION = "INVALID_STATUS_TRANSITION"
    REPORT_NOT_READY = "REPORT_NOT_READY"
    REPORT_ALREADY_EXISTS = "REPORT_ALREADY_EXISTS"
    ALERT_ALREADY_ACKNOWLEDGED = "ALERT_ALREADY_ACKNOWLEDGED"
    AI_SERVICE_UNAVAILABLE = "AI_SERVICE_UNAVAILABLE"
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


# 錯誤碼 → HTTP 狀態碼 映射
_ERROR_STATUS_MAP: dict[ErrorCode, int] = {
    ErrorCode.UNAUTHORIZED: 401,
    ErrorCode.FORBIDDEN: 403,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.VALIDATION_ERROR: 422,
    ErrorCode.CONFLICT: 409,
    ErrorCode.INVALID_CREDENTIALS: 401,
    ErrorCode.ACCOUNT_DISABLED: 403,
    ErrorCode.EMAIL_ALREADY_EXISTS: 409,
    ErrorCode.SESSION_NOT_FOUND: 404,
    ErrorCode.SESSION_NOT_ACTIVE: 409,
    ErrorCode.INVALID_STATUS_TRANSITION: 409,
    ErrorCode.REPORT_NOT_READY: 409,
    ErrorCode.REPORT_ALREADY_EXISTS: 409,
    ErrorCode.ALERT_ALREADY_ACKNOWLEDGED: 409,
    ErrorCode.AI_SERVICE_UNAVAILABLE: 503,
    ErrorCode.RATE_LIMIT_EXCEEDED: 429,
    ErrorCode.INTERNAL_ERROR: 500,
}


# ── 基礎例外 ───────────────────────────────────────────
class AppException(Exception):
    """應用程式例外基底類別"""

    def __init__(
        self,
        error_code: ErrorCode,
        message: str,
        details: Optional[dict[str, Any]] = None,
        status_code: Optional[int] = None,
    ) -> None:
        self.error_code = error_code
        self.message = message
        self.details = details
        self.status_code = status_code or _ERROR_STATUS_MAP.get(error_code, 500)
        super().__init__(message)


# ── 具體例外 ───────────────────────────────────────────
class UnauthorizedException(AppException):
    def __init__(self, message: str = "未認證或 Token 已過期", details: Optional[dict[str, Any]] = None):
        super().__init__(ErrorCode.UNAUTHORIZED, message, details)


class ForbiddenException(AppException):
    def __init__(self, message: str = "權限不足", details: Optional[dict[str, Any]] = None):
        super().__init__(ErrorCode.FORBIDDEN, message, details)


class NotFoundException(AppException):
    def __init__(self, message: str = "資源不存在", details: Optional[dict[str, Any]] = None):
        super().__init__(ErrorCode.NOT_FOUND, message, details)


class ValidationException(AppException):
    def __init__(self, message: str = "請求參數驗證失敗", details: Optional[dict[str, Any]] = None):
        super().__init__(ErrorCode.VALIDATION_ERROR, message, details)


class ConflictException(AppException):
    def __init__(self, message: str = "資源衝突", details: Optional[dict[str, Any]] = None):
        super().__init__(ErrorCode.CONFLICT, message, details)


class InvalidCredentialsException(AppException):
    def __init__(self, message: str = "帳號或密碼錯誤", details: Optional[dict[str, Any]] = None):
        super().__init__(ErrorCode.INVALID_CREDENTIALS, message, details)


class AccountDisabledException(AppException):
    def __init__(self, message: str = "帳號已停用", details: Optional[dict[str, Any]] = None):
        super().__init__(ErrorCode.ACCOUNT_DISABLED, message, details)


class EmailAlreadyExistsException(AppException):
    def __init__(self, message: str = "Email 已註冊", details: Optional[dict[str, Any]] = None):
        super().__init__(ErrorCode.EMAIL_ALREADY_EXISTS, message, details)


class SessionNotFoundException(AppException):
    def __init__(self, message: str = "場次不存在", details: Optional[dict[str, Any]] = None):
        super().__init__(ErrorCode.SESSION_NOT_FOUND, message, details)


class SessionNotActiveException(AppException):
    def __init__(self, message: str = "場次非活躍狀態", details: Optional[dict[str, Any]] = None):
        super().__init__(ErrorCode.SESSION_NOT_ACTIVE, message, details)


class InvalidStatusTransitionException(AppException):
    def __init__(self, message: str = "不合法的狀態轉移", details: Optional[dict[str, Any]] = None):
        super().__init__(ErrorCode.INVALID_STATUS_TRANSITION, message, details)


class ReportNotReadyException(AppException):
    def __init__(self, message: str = "報告尚未產生完成", details: Optional[dict[str, Any]] = None):
        super().__init__(ErrorCode.REPORT_NOT_READY, message, details)


class ReportAlreadyExistsException(AppException):
    def __init__(self, message: str = "報告已存在", details: Optional[dict[str, Any]] = None):
        super().__init__(ErrorCode.REPORT_ALREADY_EXISTS, message, details)


class AlertAlreadyAcknowledgedException(AppException):
    def __init__(self, message: str = "警示已確認", details: Optional[dict[str, Any]] = None):
        super().__init__(ErrorCode.ALERT_ALREADY_ACKNOWLEDGED, message, details)


class AIServiceUnavailableException(AppException):
    def __init__(self, message: str = "AI 服務不可用", details: Optional[dict[str, Any]] = None):
        super().__init__(ErrorCode.AI_SERVICE_UNAVAILABLE, message, details)


class RateLimitExceededException(AppException):
    def __init__(self, message: str = "超過速率限制", details: Optional[dict[str, Any]] = None):
        super().__init__(ErrorCode.RATE_LIMIT_EXCEEDED, message, details)


class InternalErrorException(AppException):
    def __init__(self, message: str = "內部伺服器錯誤", details: Optional[dict[str, Any]] = None):
        super().__init__(ErrorCode.INTERNAL_ERROR, message, details)


# ── 例外處理器註冊 ──────────────────────────────────────
def _cors_headers(request: Request) -> dict[str, str]:
    """從請求 Origin 產生 CORS headers，確保錯誤回應也帶有 CORS 資訊。"""
    from app.core.config import settings as _settings

    origin = request.headers.get("origin", "")
    if origin in _settings.CORS_ORIGINS:
        return {
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Credentials": "true",
            "Vary": "Origin",
        }
    return {}


def register_exception_handlers(app: FastAPI) -> None:
    """將自定義例外處理器註冊至 FastAPI app"""

    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "unknown")
        return JSONResponse(
            status_code=exc.status_code,
            headers=_cors_headers(request),
            content={
                "error": {
                    "code": exc.error_code.value,
                    "message": exc.message,
                    "details": exc.details,
                    "request_id": request_id,
                    "timestamp": __import__("datetime").datetime.now(
                        __import__("datetime").timezone.utc
                    ).isoformat(),
                },
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "unknown")
        return JSONResponse(
            status_code=500,
            headers=_cors_headers(request),
            content={
                "error": {
                    "code": ErrorCode.INTERNAL_ERROR.value,
                    "message": "內部伺服器錯誤",
                    "details": str(exc),
                    "request_id": request_id,
                    "timestamp": __import__("datetime").datetime.now(
                        __import__("datetime").timezone.utc
                    ).isoformat(),
                },
            },
        )
