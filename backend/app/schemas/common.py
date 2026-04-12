"""
共用 Pydantic Schema
- 分頁、錯誤回應、成功回應等通用結構
"""

from datetime import datetime
from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


# ── 分頁 ───────────────────────────────────────────────
class CursorPagination(BaseModel):
    """游標分頁資訊"""
    next_cursor: Optional[str] = None
    has_more: bool = False
    limit: int = 20
    total_count: int = 0


class PaginatedResponse(BaseModel, Generic[T]):
    """泛型分頁回應"""
    data: list[T]
    pagination: CursorPagination


# ── 錯誤回應 ───────────────────────────────────────────
class ErrorDetail(BaseModel):
    """錯誤內容"""
    code: str
    message: str
    details: Optional[dict[str, Any]] = None
    request_id: str = ""
    timestamp: datetime = Field(default_factory=datetime.now)


class ErrorResponse(BaseModel):
    """統一錯誤回應格式"""
    error: ErrorDetail


# ── 成功回應 ───────────────────────────────────────────
class SuccessResponse(BaseModel):
    """通用成功回應"""
    success: bool = True
    message: str = "操作成功"


# ── 健康檢查 ───────────────────────────────────────────
class HealthResponse(BaseModel):
    """健康檢查回應"""
    status: str = "ok"
    version: str = "1.0.0"
    timestamp: datetime

    model_config = ConfigDict(from_attributes=True)
