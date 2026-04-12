"""
稽核日誌 Pydantic Schema
獨立檔案供 audit_logs router 匯入使用
"""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.enums import AuditAction
from app.schemas.common import CursorPagination


class AuditLogDetail(BaseModel):
    """稽核日誌詳細回應"""
    id: int
    user_id: Optional[UUID] = None
    action: AuditAction
    resource_type: str
    resource_id: Optional[str] = None
    details: Optional[dict[str, Any]] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AuditLogListResponse(BaseModel):
    """稽核日誌列表回應"""
    data: list[AuditLogDetail]
    pagination: CursorPagination
