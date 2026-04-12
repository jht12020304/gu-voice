"""
系統管理服務 — 使用者管理、系統健康檢查
"""

from __future__ import annotations
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from app.schemas.admin import (
    CreateUserRequest,
    SystemHealthResponse,
    ToggleActiveResponse,
    UpdateUserRequest,
    UserDetail,
    UserListResponse,
)
from app.core.exceptions import AppException

class AdminService:
    async def list_users(
        self,
        db: AsyncSession,
        cursor: str | None = None,
        limit: int = 20,
        role: str | None = None,
        is_active: bool | None = None,
        search: str | None = None,
    ) -> UserListResponse:
        # Mock implementation
        from app.schemas.common import CursorPagination
        return UserListResponse(data=[], pagination=CursorPagination(total_count=0, limit=limit, has_more=False, next_cursor=None))

    async def create_user(
        self,
        db: AsyncSession,
        data: CreateUserRequest,
        created_by: UUID,
    ) -> UserDetail:
        # Mock implementation
        raise AppException("Not implemented in stub", 501)

    async def update_user(
        self,
        db: AsyncSession,
        user_id: UUID,
        data: UpdateUserRequest,
        updated_by: UUID,
    ) -> UserDetail:
        # Mock implementation
        raise AppException("Not implemented in stub", 501)

    async def toggle_active(
        self,
        db: AsyncSession,
        user_id: UUID,
        toggled_by: UUID,
    ) -> ToggleActiveResponse:
        # Mock implementation
        return ToggleActiveResponse(user_id=user_id, is_active=False)

    async def system_health_check(self, db: AsyncSession) -> SystemHealthResponse:
        # Mock implementation
        from app.schemas.admin import HealthStatus
        status = HealthStatus(status="healthy", message="All systems operational (Stub)")
        return SystemHealthResponse(
            database=status,
            redis=status,
            ai_service=status,
            stt_service=status,
            tts_service=status,
            timestamp="2026-04-12T14:20:00Z"
        )
