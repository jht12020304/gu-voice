"""
自定義例外類別 + FastAPI 例外處理器註冊
"""

import logging
from enum import Enum
from typing import Any, Optional

import sentry_sdk
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.utils.i18n_messages import get_message, is_message_key
from app.utils.language import resolve_language

logger = logging.getLogger(__name__)


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
    """應用程式例外基底類別

    i18n 支援：
        - 若 `message` 恰為 `MESSAGES` 登錄的 key（如 `errors.session_not_found`），
          exception handler 會自動依請求語言翻譯。
        - 若同時需要格式化參數，傳入 `message_kwargs={...}` 供 str.format 使用。
        - 若 `message` 為一般句子，則原樣回傳（回溯相容）。
    """

    def __init__(
        self,
        error_code: ErrorCode,
        message: str,
        details: Optional[dict[str, Any]] = None,
        status_code: Optional[int] = None,
        message_kwargs: Optional[dict[str, Any]] = None,
    ) -> None:
        self.error_code = error_code
        self.message = message
        self.details = details
        self.status_code = status_code or _ERROR_STATUS_MAP.get(error_code, 500)
        self.message_kwargs = message_kwargs or {}
        super().__init__(message)


# ── 具體例外 ───────────────────────────────────────────
# 各子類預設 `message` 直接使用 `errors.*` i18n key。
# `i18n_error_handler` 會在回應序列化前依請求語言翻譯。
class UnauthorizedException(AppException):
    def __init__(
        self,
        message: str = "errors.unauthorized",
        details: Optional[dict[str, Any]] = None,
        message_kwargs: Optional[dict[str, Any]] = None,
    ):
        super().__init__(ErrorCode.UNAUTHORIZED, message, details, message_kwargs=message_kwargs)


class ForbiddenException(AppException):
    def __init__(
        self,
        message: str = "errors.forbidden",
        details: Optional[dict[str, Any]] = None,
        message_kwargs: Optional[dict[str, Any]] = None,
    ):
        super().__init__(ErrorCode.FORBIDDEN, message, details, message_kwargs=message_kwargs)


class NotFoundException(AppException):
    def __init__(
        self,
        message: str = "errors.not_found",
        details: Optional[dict[str, Any]] = None,
        message_kwargs: Optional[dict[str, Any]] = None,
    ):
        super().__init__(ErrorCode.NOT_FOUND, message, details, message_kwargs=message_kwargs)


class ValidationException(AppException):
    def __init__(
        self,
        message: str = "errors.validation_failed",
        details: Optional[dict[str, Any]] = None,
        message_kwargs: Optional[dict[str, Any]] = None,
    ):
        super().__init__(ErrorCode.VALIDATION_ERROR, message, details, message_kwargs=message_kwargs)


class ConflictException(AppException):
    def __init__(
        self,
        message: str = "errors.conflict",
        details: Optional[dict[str, Any]] = None,
        message_kwargs: Optional[dict[str, Any]] = None,
    ):
        super().__init__(ErrorCode.CONFLICT, message, details, message_kwargs=message_kwargs)


class InvalidCredentialsException(AppException):
    def __init__(
        self,
        message: str = "errors.invalid_credentials",
        details: Optional[dict[str, Any]] = None,
        message_kwargs: Optional[dict[str, Any]] = None,
    ):
        super().__init__(ErrorCode.INVALID_CREDENTIALS, message, details, message_kwargs=message_kwargs)


class AccountDisabledException(AppException):
    def __init__(
        self,
        message: str = "errors.account_disabled",
        details: Optional[dict[str, Any]] = None,
        message_kwargs: Optional[dict[str, Any]] = None,
    ):
        super().__init__(ErrorCode.ACCOUNT_DISABLED, message, details, message_kwargs=message_kwargs)


class EmailAlreadyExistsException(AppException):
    def __init__(
        self,
        message: str = "errors.email_already_exists",
        details: Optional[dict[str, Any]] = None,
        message_kwargs: Optional[dict[str, Any]] = None,
    ):
        super().__init__(ErrorCode.EMAIL_ALREADY_EXISTS, message, details, message_kwargs=message_kwargs)


class SessionNotFoundException(AppException):
    def __init__(
        self,
        message: str = "errors.session_not_found",
        details: Optional[dict[str, Any]] = None,
        message_kwargs: Optional[dict[str, Any]] = None,
    ):
        super().__init__(ErrorCode.SESSION_NOT_FOUND, message, details, message_kwargs=message_kwargs)


class SessionNotActiveException(AppException):
    def __init__(
        self,
        message: str = "errors.session_not_active",
        details: Optional[dict[str, Any]] = None,
        message_kwargs: Optional[dict[str, Any]] = None,
    ):
        super().__init__(ErrorCode.SESSION_NOT_ACTIVE, message, details, message_kwargs=message_kwargs)


class InvalidStatusTransitionException(AppException):
    def __init__(
        self,
        message: str = "errors.invalid_status_transition",
        details: Optional[dict[str, Any]] = None,
        message_kwargs: Optional[dict[str, Any]] = None,
    ):
        super().__init__(ErrorCode.INVALID_STATUS_TRANSITION, message, details, message_kwargs=message_kwargs)


class ReportNotReadyException(AppException):
    def __init__(
        self,
        message: str = "errors.report_not_ready",
        details: Optional[dict[str, Any]] = None,
        message_kwargs: Optional[dict[str, Any]] = None,
    ):
        super().__init__(ErrorCode.REPORT_NOT_READY, message, details, message_kwargs=message_kwargs)


class ReportAlreadyExistsException(AppException):
    def __init__(
        self,
        message: str = "errors.report_already_exists",
        details: Optional[dict[str, Any]] = None,
        message_kwargs: Optional[dict[str, Any]] = None,
    ):
        super().__init__(ErrorCode.REPORT_ALREADY_EXISTS, message, details, message_kwargs=message_kwargs)


class AlertAlreadyAcknowledgedException(AppException):
    def __init__(
        self,
        message: str = "errors.alert_already_acknowledged",
        details: Optional[dict[str, Any]] = None,
        message_kwargs: Optional[dict[str, Any]] = None,
    ):
        super().__init__(ErrorCode.ALERT_ALREADY_ACKNOWLEDGED, message, details, message_kwargs=message_kwargs)


class AIServiceUnavailableException(AppException):
    def __init__(
        self,
        message: str = "errors.ai_service_unavailable",
        details: Optional[dict[str, Any]] = None,
        message_kwargs: Optional[dict[str, Any]] = None,
    ):
        super().__init__(ErrorCode.AI_SERVICE_UNAVAILABLE, message, details, message_kwargs=message_kwargs)


class RateLimitExceededException(AppException):
    def __init__(
        self,
        message: str = "errors.rate_limit_exceeded",
        details: Optional[dict[str, Any]] = None,
        message_kwargs: Optional[dict[str, Any]] = None,
    ):
        super().__init__(ErrorCode.RATE_LIMIT_EXCEEDED, message, details, message_kwargs=message_kwargs)


class InternalErrorException(AppException):
    def __init__(
        self,
        message: str = "errors.internal_error",
        details: Optional[dict[str, Any]] = None,
        message_kwargs: Optional[dict[str, Any]] = None,
    ):
        super().__init__(ErrorCode.INTERNAL_ERROR, message, details, message_kwargs=message_kwargs)


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


def _resolve_request_language(request: Request) -> str:
    """從 request 推斷使用者語言：user.preferred_language → Accept-Language → 預設。"""
    user = getattr(request.state, "current_user", None)
    header = request.headers.get("accept-language")
    return resolve_language(
        user=user,
        accept_language_header=header,
    )


def _localize_message(
    message: str,
    language: str,
    message_kwargs: Optional[dict[str, Any]] = None,
) -> str:
    """若 `message` 為 i18n key 則翻譯，否則原樣回傳（回溯相容）。"""
    if is_message_key(message):
        return get_message(message, language, **(message_kwargs or {}))
    return message


def register_exception_handlers(app: FastAPI) -> None:
    """將自定義例外處理器註冊至 FastAPI app"""

    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "unknown")
        language = _resolve_request_language(request)
        localized_message = _localize_message(exc.message, language, exc.message_kwargs)
        return JSONResponse(
            status_code=exc.status_code,
            headers=_cors_headers(request),
            content={
                "error": {
                    "code": exc.error_code.value,
                    "message": localized_message,
                    "details": exc.details,
                    "request_id": request_id,
                    "timestamp": __import__("datetime").datetime.now(
                        __import__("datetime").timezone.utc
                    ).isoformat(),
                },
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """請求驗證失敗（pydantic / FastAPI 422）統一走應用錯誤殼。

        FastAPI 預設回 `{"detail": [...]}`，與本專案統一的
        `{"error": {code, message, request_id, timestamp}}` 不一致；此 handler 將其
        映射為 VALIDATION_ERROR，並把原始 errors 放進 details.errors 方便前端定位欄位。
        """
        request_id = getattr(request.state, "request_id", "unknown")
        language = _resolve_request_language(request)
        localized_message = get_message("errors.validation_failed", language)
        # exc.errors() 可能含 ValueError 等不可序列化物件；用 jsonable_encoder 安全轉換。
        from fastapi.encoders import jsonable_encoder

        return JSONResponse(
            status_code=_ERROR_STATUS_MAP[ErrorCode.VALIDATION_ERROR],
            headers=_cors_headers(request),
            content={
                "error": {
                    "code": ErrorCode.VALIDATION_ERROR.value,
                    "message": localized_message,
                    "details": {"errors": jsonable_encoder(exc.errors())},
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
        language = _resolve_request_language(request)
        # 完整例外（含 traceback）只記在伺服器端與 Sentry，絕不回傳給 client。
        # str(exc) 可能含 DB 連線字串 / 檔案路徑 / 內部結構，外洩即資安事故。
        logger.exception(
            "unhandled exception | request_id=%s path=%s",
            request_id,
            request.url.path,
        )
        # FastApiIntegration 不會自動捕捉已被本 handler 攔下的例外，故顯式上報；
        # before_send=redact_sensitive 會在送出前過濾 PII。
        sentry_sdk.capture_exception(exc)
        return JSONResponse(
            status_code=500,
            headers=_cors_headers(request),
            content={
                "error": {
                    "code": ErrorCode.INTERNAL_ERROR.value,
                    "message": get_message("errors.internal_error", language),
                    # 對外只回 request_id，讓使用者回報時可對應伺服器 log，不洩漏內部細節。
                    "details": {"request_id": request_id},
                    "request_id": request_id,
                    "timestamp": __import__("datetime").datetime.now(
                        __import__("datetime").timezone.utc
                    ).isoformat(),
                },
            },
        )
