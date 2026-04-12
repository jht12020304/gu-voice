"""
問診場次路由 — 場次 CRUD、狀態管理、對話記錄
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db, require_role
from app.core.exceptions import AppException
from app.schemas.session import (
    ConversationListResponse,
    SessionAssignRequest,
    SessionCreate,
    SessionDetail,
    SessionListResponse,
    SessionStatusUpdate,
    SessionStatusResponse,
)
from app.services.session_service import SessionService

router = APIRouter(prefix="/api/v1/sessions", tags=["問診場次"])

session_service = SessionService()


@router.post(
    "",
    response_model=SessionDetail,
    status_code=status.HTTP_201_CREATED,
    summary="建立場次",
)
async def create_session(
    payload: SessionCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> SessionDetail:
    """
    建立新的問診場次。
    病患開始語音問診前必須先建立場次。
    病患角色時 patient_id 自動填入，醫師與管理員需指定。
    """
    return await session_service.create_session(
        db,
        data=payload,
        current_user=current_user,
    )


@router.get(
    "",
    response_model=SessionListResponse,
    status_code=status.HTTP_200_OK,
    summary="取得場次列表",
)
async def list_sessions(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
    cursor: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    status_filter: str | None = Query(None, alias="status"),
    patient_id: UUID | None = None,
    doctor_id: UUID | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    sort_by: str = Query("created_at"),
    sort_order: str = Query("desc"),
) -> SessionListResponse:
    """
    取得場次列表，支援多條件篩選。
    病患僅能查看自己的場次。支援以狀態、醫師、日期範圍篩選。
    """
    return await session_service.list_sessions(
        db,
        current_user=current_user,
        cursor=cursor,
        limit=limit,
        status=status_filter,
        patient_id=patient_id,
        doctor_id=doctor_id,
        date_from=date_from,
        date_to=date_to,
        sort_by=sort_by,
        sort_order=sort_order,
    )


@router.get(
    "/{session_id}",
    response_model=SessionDetail,
    status_code=status.HTTP_200_OK,
    summary="取得場次詳情",
)
async def get_session(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> SessionDetail:
    """取得指定場次的完整詳細資料（含對話摘要）。"""
    return await session_service.get_session(
        db,
        session_id=session_id,
        current_user=current_user,
    )


@router.put(
    "/{session_id}/status",
    response_model=SessionStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="更新場次狀態",
)
async def update_session_status(
    session_id: UUID,
    payload: SessionStatusUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> SessionStatusResponse:
    """
    更新場次狀態，需遵循合法狀態轉移。
    合法轉移: waiting->in_progress, waiting->cancelled,
    in_progress->completed, in_progress->aborted_red_flag, in_progress->cancelled。
    """
    return await session_service.update_status(
        db,
        session_id=session_id,
        new_status=payload.status,
        reason=payload.reason,
        current_user=current_user,
    )


@router.get(
    "/{session_id}/conversations",
    response_model=ConversationListResponse,
    status_code=status.HTTP_200_OK,
    summary="取得場次對話記錄",
)
async def get_session_conversations(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
    cursor: str | None = None,
    limit: int = Query(50, ge=1, le=200),
) -> ConversationListResponse:
    """取得指定場次的完整對話記錄（逐字稿），支援分頁。"""
    return await session_service.get_conversations(
        db,
        session_id=session_id,
        current_user=current_user,
        cursor=cursor,
        limit=limit,
    )


@router.post(
    "/{session_id}/assign",
    response_model=SessionDetail,
    status_code=status.HTTP_200_OK,
    summary="指派醫師",
    dependencies=[Depends(require_role("doctor", "admin"))],
)
async def assign_doctor(
    session_id: UUID,
    payload: SessionAssignRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> SessionDetail:
    """將醫師指派至指定的問診場次。"""
    return await session_service.assign_doctor(
        db,
        session_id=session_id,
        doctor_id=payload.doctor_id,
        current_user=current_user,
    )
