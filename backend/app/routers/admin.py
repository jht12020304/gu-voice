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
    ResetPasswordResponse,
    ToggleActiveResponse,
    UpdateUserRequest,
    UserDetail,
    UserListResponse,
)
from app.services.admin_service import AdminService

router = APIRouter(
    prefix="/api/v1/admin",
    tags=["系統管理"],
    # 2026-08-22 使用者拍板「醫師＝管理員」：本診所的醫師就是管理者，admin 四頁
    # （使用者管理／主訴模板／系統健康／稽核日誌）對醫師開放。角色本身不合併——
    # 病患端的 RoleGuard、報告 scope 等仍分 doctor/admin 判斷，只有這個 router 收兩者。
    dependencies=[Depends(require_role("admin", "doctor"))],
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


@router.post(
    "/users/{user_id}/reset-password",
    response_model=ResetPasswordResponse,
    status_code=status.HTTP_200_OK,
    summary="管理員代為重設使用者密碼",
)
async def reset_user_password(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> ResetPasswordResponse:
    """管理員代為重設密碼，回傳一次性臨時密碼；同時撤銷該使用者所有 refresh token。

    存在的理由（TODO H1）：生產未設 email transport，`/auth/forgot-password` 的信
    寄不出去，前端因此引導使用者「告知現場醫護或系統管理員」——這條端點就是讓那句話
    成真。院內 kiosk 情境下病患人在現場，當面重設比 email 直接。

    ⚠️ 回應含**明文臨時密碼且只出現一次**（伺服器只存 hash、不寫 log）。
    不可對自己操作（改自己密碼走 `/auth/change-password`，那條要驗舊密碼）。
    """
    return await admin_service.reset_user_password(
        db,
        user_id=user_id,
        reset_by=current_user.id,
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
