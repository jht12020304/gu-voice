"""
稽核日誌路由 — 日誌查詢
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db, require_role
from app.core.exceptions import AppException
from app.schemas.audit_log import (
    AuditLogDetail,
    AuditLogListResponse,
)
from app.services.audit_log_service import AuditLogService

router = APIRouter(
    prefix="/api/v1/audit-logs",
    tags=["稽核日誌"],
    dependencies=[Depends(require_role("admin"))],
)

audit_log_service = AuditLogService()


@router.get(
    "",
    response_model=AuditLogListResponse,
    status_code=status.HTTP_200_OK,
    summary="取得稽核日誌列表",
)
async def list_audit_logs(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
    cursor: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    user_id: UUID | None = None,
    action: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    ip_address: str | None = None,
) -> AuditLogListResponse:
    """
    取得系統稽核日誌，記錄所有使用者操作。僅限管理員存取。
    支援依操作者、操作類型、資源類型、日期範圍、IP 位址篩選。
    """
    return await audit_log_service.list_audit_logs(
        db,
        cursor=cursor,
        limit=limit,
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        date_from=date_from,
        date_to=date_to,
        ip_address=ip_address,
    )


@router.get(
    "/{log_id}",
    response_model=AuditLogDetail,
    status_code=status.HTTP_200_OK,
    summary="取得稽核日誌詳情",
)
async def get_audit_log(
    log_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> AuditLogDetail:
    """取得指定稽核日誌的完整詳細資料。僅限管理員。"""
    return await audit_log_service.get_audit_log(db, log_id=log_id)
