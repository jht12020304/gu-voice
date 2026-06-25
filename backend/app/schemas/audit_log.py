"""
稽核日誌 Pydantic Schema
獨立檔案供 audit_logs router 匯入使用
"""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

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

    @field_validator("ip_address", mode="before")
    @classmethod
    def _coerce_ip_to_str(cls, v: Any) -> Optional[str]:
        # ip_address 欄位為 PostgreSQL INET，asyncpg 會還原成 IPv4Address/IPv6Address
        # 物件，與宣告的 str 型別不符導致序列化 500。統一轉成字串。
        return str(v) if v is not None else None


class AuditLogListResponse(BaseModel):
    """稽核日誌列表回應"""
    data: list[AuditLogDetail]
    pagination: CursorPagination
