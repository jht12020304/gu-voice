"""主訴相關 Pydantic Schema"""

from datetime import datetime
from typing import Optional
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


class ComplaintUpdate(BaseModel):
    """更新主訴（部分更新）"""
    name: Optional[str] = Field(None, max_length=100)
    name_en: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = None
    category: Optional[str] = Field(None, max_length=100)
    is_default: Optional[bool] = None
    is_active: Optional[bool] = None
    display_order: Optional[int] = None


class ComplaintResponse(BaseModel):
    """主訴回應"""
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
