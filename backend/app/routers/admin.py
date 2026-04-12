"""
系統管理路由 — 使用者管理、系統健康檢查
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db, require_role
from app.core.exceptions import AppException
from app.schemas.admin import (
    CreateUserRequest,
    SystemHealthResponse,
    ToggleActiveResponse,
    UpdateUserRequest,
    UserDetail,
    UserListResponse,
)
from app.services.admin_service import AdminService

router = APIRouter(
    prefix="/api/v1/admin",
    tags=["系統管理"],
    dependencies=[Depends(require_role("admin"))],
)

admin_service = AdminService()


# ── 使用者管理 ──────────────────────────────────────────

@router.get(
    "/users",
    response_model=UserListResponse,
    status_code=status.HTTP_200_OK,
    summary="取得使用者列表",
)
async def list_users(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
    cursor: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    role: str | None = None,
    is_active: bool | None = None,
    search: str | None = None,
) -> UserListResponse:
    """取得系統中所有使用者的列表，支援依角色、啟用狀態篩選及關鍵字搜尋。"""
    return await admin_service.list_users(
        db,
        cursor=cursor,
        limit=limit,
        role=role,
        is_active=is_active,
        search=search,
    )


@router.post(
    "/users",
    response_model=UserDetail,
    status_code=status.HTTP_201_CREATED,
    summary="建立使用者",
)
async def create_user(
    payload: CreateUserRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> UserDetail:
    """由管理員建立新使用者帳號（支援所有角色）。"""
    return await admin_service.create_user(
        db,
        data=payload,
        created_by=current_user.id,
    )


@router.put(
    "/users/{user_id}",
    response_model=UserDetail,
    status_code=status.HTTP_200_OK,
    summary="更新使用者",
)
async def update_user(
    user_id: UUID,
    payload: UpdateUserRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> UserDetail:
    """更新指定使用者的資料。僅限管理員。"""
    return await admin_service.update_user(
        db,
        user_id=user_id,
        data=payload,
        updated_by=current_user.id,
    )


@router.put(
    "/users/{user_id}/toggle-active",
    response_model=ToggleActiveResponse,
    status_code=status.HTTP_200_OK,
    summary="啟用/停用使用者",
)
async def toggle_user_active(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> ToggleActiveResponse:
    """切換指定使用者的啟用/停用狀態。不可對自己操作。"""
    return await admin_service.toggle_active(
        db,
        user_id=user_id,
        toggled_by=current_user.id,
    )


# ── 系統管理 ────────────────────────────────────────────

@router.get(
    "/system/health",
    response_model=SystemHealthResponse,
    status_code=status.HTTP_200_OK,
    summary="系統健康檢查",
)
async def system_health(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> SystemHealthResponse:
    """取得系統各元件（資料庫、Redis、AI 服務、STT/TTS）的詳細健康狀態。"""
    return await admin_service.system_health_check(db)
