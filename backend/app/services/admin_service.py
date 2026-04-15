"""
系統管理服務 — 使用者管理、系統健康檢查
"""

from __future__ import annotations
from uuid import UUID
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.user import User
from app.schemas.admin import (
    CreateUserRequest,
    SystemHealthResponse,
    ToggleActiveResponse,
    UpdateUserRequest,
    UserDetail,
    UserListResponse,
)
from app.schemas.common import CursorPagination
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
        query = select(User).order_by(User.created_at.desc(), User.id.desc())
        count_query = select(func.count()).select_from(User)

        if role:
            from app.models.enums import UserRole
            try:
                role_enum = UserRole(role)
                query = query.where(User.role == role_enum)
                count_query = count_query.where(User.role == role_enum)
            except ValueError:
                pass

        if is_active is not None:
            query = query.where(User.is_active == is_active)
            count_query = count_query.where(User.is_active == is_active)

        if search:
            pattern = f"%{search}%"
            condition = or_(User.name.ilike(pattern), User.email.ilike(pattern))
            query = query.where(condition)
            count_query = count_query.where(condition)

        if cursor:
            try:
                cursor_result = await db.execute(
                    select(User).where(User.id == UUID(cursor))
                )
                cursor_record = cursor_result.scalar_one_or_none()
                if cursor_record:
                    query = query.where(
                        (User.created_at < cursor_record.created_at)
                        | (
                            (User.created_at == cursor_record.created_at)
                            & (User.id < cursor_record.id)
                        )
                    )
            except ValueError:
                pass

        total_result = await db.execute(count_query)
        total_count = total_result.scalar() or 0

        result = await db.execute(query.limit(limit + 1))
        users = list(result.scalars().all())

        has_more = len(users) > limit
        if has_more:
            users = users[:limit]

        next_cursor = str(users[-1].id) if has_more and users else None

        return UserListResponse(
            data=[UserDetail.model_validate(u) for u in users],
            pagination=CursorPagination(
                total_count=total_count,
                limit=limit,
                has_more=has_more,
                next_cursor=next_cursor,
            ),
        )

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
        # Stub 實作 — 回傳 schema 定義的預設 "ok" 字串與目前時間戳,
        # 讓 /api/v1/admin/system/health 不會 500。
        # TODO: 未來接真實的 db `SELECT 1` / redis `PING` / OpenAI client 驗證。
        from datetime import datetime, timezone
        return SystemHealthResponse(timestamp=datetime.now(timezone.utc))
