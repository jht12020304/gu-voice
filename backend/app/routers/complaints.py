"""
主訴管理路由 — 主訴 CRUD、分類、排序
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db, require_role
from app.core.exceptions import AppException
from app.core.language_middleware import get_request_language
from app.schemas.complaint import (
    ComplaintCreate,
    ComplaintDetail,
    ComplaintListResponse,
    ComplaintUpdate,
    ReorderRequest,
    ReorderResponse,
)
from app.services.complaint_service import ComplaintService

router = APIRouter(prefix="/api/v1/complaints", tags=["主訴管理"])

complaint_service = ComplaintService()


@router.get(
    "",
    response_model=ComplaintListResponse,
    status_code=status.HTTP_200_OK,
    summary="取得主訴列表",
    dependencies=[Depends(require_role("doctor", "admin"))],
)
async def list_complaints(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
    cursor: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    category: str | None = None,
    is_default: bool | None = None,
    search: str | None = None,
    is_active: bool = True,
) -> ComplaintListResponse:
    """
    取得所有主訴項目，包含系統預設與自訂項目。
    支援依分類、預設/自訂、啟用狀態篩選及關鍵字搜尋。

    回應的 `name / description / category` 依 middleware 解析的語言輸出；
    同時帶 `*_by_lang` 原始 JSONB 供前端切換語言時零延遲使用。
    """
    language = get_request_language(request)
    return await complaint_service.list_complaints(
        db,
        cursor=cursor,
        limit=limit,
        category=category,
        is_default=is_default,
        search=search,
        is_active=is_active,
        language=language,
    )


@router.post(
    "",
    response_model=ComplaintDetail,
    status_code=status.HTTP_201_CREATED,
    summary="建立自訂主訴",
    dependencies=[Depends(require_role("doctor", "admin"))],
)
async def create_complaint(
    payload: ComplaintCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> ComplaintDetail:
    """建立新的自訂主訴項目。需具備醫師或管理員角色。"""
    language = get_request_language(request)
    return await complaint_service.create_complaint(
        db,
        data=payload,
        created_by=current_user.id,
        language=language,
    )


@router.put(
    "/reorder",
    response_model=ReorderResponse,
    status_code=status.HTTP_200_OK,
    summary="批次重新排序主訴",
    dependencies=[Depends(require_role("doctor", "admin"))],
)
async def reorder_complaints(
    payload: ReorderRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> ReorderResponse:
    """批次更新多個主訴的顯示排序 (display_order)。"""
    return await complaint_service.reorder_complaints(
        db,
        items=payload.items,
    )


@router.get(
    "/{complaint_id}",
    response_model=ComplaintDetail,
    status_code=status.HTTP_200_OK,
    summary="取得單一主訴",
)
async def get_complaint(
    complaint_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> ComplaintDetail:
    """依 ID 取得單一主訴的完整資訊。"""
    return await complaint_service.get_complaint(
        db,
        complaint_id=complaint_id,
        language=get_request_language(request),
    )


@router.put(
    "/{complaint_id}",
    response_model=ComplaintDetail,
    status_code=status.HTTP_200_OK,
    summary="更新主訴",
)
async def update_complaint(
    complaint_id: UUID,
    payload: ComplaintUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> ComplaintDetail:
    """
    更新指定主訴的內容。
    系統預設主訴僅限管理員修改；醫師僅可修改自訂主訴。
    """
    return await complaint_service.update_complaint(
        db,
        complaint_id=complaint_id,
        data=payload,
        current_user=current_user,
        language=get_request_language(request),
    )


@router.delete(
    "/{complaint_id}",
    status_code=status.HTTP_200_OK,
    summary="刪除主訴",
)
async def delete_complaint(
    complaint_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> None:
    """
    軟刪除指定主訴（設定 is_active 為 False）。
    系統預設主訴僅限管理員刪除；醫師僅可刪除自訂主訴。
    """
    await complaint_service.delete_complaint(
        db,
        complaint_id=complaint_id,
        current_user=current_user,
    )
