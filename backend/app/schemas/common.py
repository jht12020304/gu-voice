"""
共用 Pydantic Schema
- 分頁、錯誤回應、成功回應等通用結構
"""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Generic, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

T = TypeVar("T")


# ── 數值型別 ───────────────────────────────────────────
# Decimal 欄位輸出 JSON 一律序列化為 float，否則 pydantic v2 預設輸出字串
# （例如 0.80 → "0.80"）會炸掉 Flutter 端的 `as num?` 解析：
# flutter_app/lib/data/models/soap_report.dart 的
# `(json['aiConfidenceScore'] as num?)` / `(json['sttConfidence'] as num?)`
# 遇到 String 直接丟 TypeError，整份 model 解析失敗且被上層 catch 吞掉，
# reports 列表變空、session detail 誤判「尚未生成報告」。
# （React 端靠 JS 隱式轉型僥倖能動，所以這個契約破口一直沒被前端擋下來。）
# 只影響「回應序列化」：欄位在 Python 端仍是 Decimal，寫入 DB 的 numeric 路徑不變。
# 任何新的 response schema 只要有小數欄位，一律用這個型別，不要裸寫 Decimal。
JsonFloatDecimal = Annotated[
    Decimal,
    PlainSerializer(float, return_type=float, when_used="json"),
]


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
