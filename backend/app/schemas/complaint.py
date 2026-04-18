"""主訴相關 Pydantic Schema

多語版本（Phase 3）：
- `ComplaintCreate` / `ComplaintUpdate` 接受 `*_by_lang` JSONB 欄位，
  同時沿用 legacy `name / name_en / description / category` 提供 backwards compatibility。
- `ComplaintResponse` 有兩組欄位：
  - `name / description / category`：依 `request.state.language` resolve 後的單一字串，
    前端可直接渲染
  - `name_by_lang / description_by_lang / category_by_lang`：完整多語內容，
    管理後台編輯時使用
"""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import CursorPagination


class ComplaintCreate(BaseModel):
    """新增主訴"""
    name: str = Field(..., max_length=100)
    name_en: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = None
    category: str = Field(..., max_length=100)
    is_default: bool = False
    is_active: bool = True
    display_order: int = 0
    # 多語欄位（optional — 未填時由 service 由 legacy 欄位自動 seed）
    name_by_lang: Optional[dict[str, Any]] = None
    description_by_lang: Optional[dict[str, Any]] = None
    category_by_lang: Optional[dict[str, Any]] = None


class ComplaintUpdate(BaseModel):
    """更新主訴（部分更新）"""
    name: Optional[str] = Field(None, max_length=100)
    name_en: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = None
    category: Optional[str] = Field(None, max_length=100)
    is_default: Optional[bool] = None
    is_active: Optional[bool] = None
    display_order: Optional[int] = None
    name_by_lang: Optional[dict[str, Any]] = None
    description_by_lang: Optional[dict[str, Any]] = None
    category_by_lang: Optional[dict[str, Any]] = None


class ComplaintResponse(BaseModel):
    """主訴回應

    `name / description / category` 為解析後的目標語言字串；
    `*_by_lang` 為完整多語 JSONB，管理後台使用。
    """
    id: UUID
    name: str
    name_en: Optional[str] = None
    description: Optional[str] = None
    category: str
    is_default: bool
    is_active: bool
    display_order: int
    created_by: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime
    # 多語原始資料（前端切語言時不用重打 API）
    name_by_lang: Optional[dict[str, Any]] = None
    description_by_lang: Optional[dict[str, Any]] = None
    category_by_lang: Optional[dict[str, Any]] = None

    model_config = ConfigDict(from_attributes=True)


class ComplaintListResponse(BaseModel):
    """主訴列表回應"""
    data: list[ComplaintResponse]
    pagination: CursorPagination


class ComplaintReorderRequest(BaseModel):
    """主訴重新排序請求"""
    items: list[dict[str, int | str]]
    """格式: [{"id": "uuid", "display_order": 0}, ...]"""


class ReorderResponse(BaseModel):
    """排序結果回應"""
    success: bool = True
    message: str = "排序更新完成"


# 別名（供 router 匯入相容）
ComplaintDetail = ComplaintResponse
ReorderRequest = ComplaintReorderRequest
