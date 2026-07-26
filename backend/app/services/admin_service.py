"""
系統管理服務 — 使用者管理、系統健康檢查
"""

from __future__ import annotations
import asyncio
import logging
import os
from uuid import UUID
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.exceptions import (
    EmailAlreadyExistsException,
    ForbiddenException,
    NotFoundException,
)
from app.core.security import generate_temp_password, hash_password
from app.models.enums import AuditAction
from app.models.user import User
from app.schemas.admin import (
    CreateUserRequest,
    ResetPasswordResponse,
    SystemHealthResponse,
    ToggleActiveResponse,
    UpdateUserRequest,
    UserDetail,
    UserListResponse,
)
from app.schemas.common import CursorPagination
from app.services.audit_log_service import AuditLogService
from app.utils.datetime_utils import utc_now

logger = logging.getLogger(__name__)

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
        """管理員建立使用者帳號。

        - 驗證 email 唯一
        - 以 bcrypt 雜湊密碼（沿用 auth_service 的 `hash_password`）
        - 以指定角色建立 User，commit 後回傳
        - 寫入 audit log（CREATE / user）
        """
        existing = await db.execute(
            select(User).where(User.email == data.email)
        )
        if existing.scalar_one_or_none() is not None:
            raise EmailAlreadyExistsException()

        now = utc_now()
        user = User(
            email=data.email,
            password_hash=hash_password(data.password),
            name=data.name,
            role=data.role,
            phone=data.phone,
            department=data.department,
            license_number=data.license_number,
            is_active=data.is_active,
            created_at=now,
            updated_at=now,
        )
        db.add(user)
        await db.flush()

        # AuditLogService.log 內部會 flush；commit 由 get_db 依賴在請求結束時
        # 統一處理（沿用 auth_service 慣例）。
        await AuditLogService.log(
            db,
            user_id=created_by,
            action=AuditAction.CREATE,
            resource_type="user",
            resource_id=str(user.id),
            details={"email": user.email, "role": user.role.value},
        )

        return UserDetail.model_validate(user)

    async def update_user(
        self,
        db: AsyncSession,
        user_id: UUID,
        data: UpdateUserRequest,
        updated_by: UUID,
    ) -> UserDetail:
        """管理員更新使用者欄位（name / email / role / phone / department /
        license_number / is_active），persist 後寫入 audit log。

        - 僅更新 payload 中有提供（非 None）的欄位
        - email 變更時驗證唯一性
        """
        result = await db.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()
        if user is None:
            raise NotFoundException("errors.user_not_found")

        # 只取 client 實際送出的欄位（exclude_unset 區分「沒帶」與「帶 None」）
        updates = data.model_dump(exclude_unset=True)

        # email 變更需驗證唯一（排除自己）
        new_email = updates.get("email")
        if new_email is not None and new_email != user.email:
            dup = await db.execute(
                select(User).where(User.email == new_email, User.id != user_id)
            )
            if dup.scalar_one_or_none() is not None:
                raise EmailAlreadyExistsException()

        updatable_fields = {
            "name",
            "email",
            "role",
            "phone",
            "department",
            "license_number",
            "is_active",
        }
        changed: list[str] = []
        for field, value in updates.items():
            if field in updatable_fields and value is not None:
                setattr(user, field, value)
                changed.append(field)

        user.updated_at = utc_now()
        await db.flush()

        await AuditLogService.log(
            db,
            user_id=updated_by,
            action=AuditAction.UPDATE,
            resource_type="user",
            resource_id=str(user.id),
            details={"fields": changed},
        )

        return UserDetail.model_validate(user)

    async def toggle_active(
        self,
        db: AsyncSession,
        user_id: UUID,
        toggled_by: UUID,
    ) -> ToggleActiveResponse:
        """切換使用者啟用狀態。

        - 禁止管理員停用 / 切換自己（ADMIN-9 self-deactivation guard）
        - 真實 flip `User.is_active`，persist 後回傳實際新狀態
        - 寫入 audit log（UPDATE / user）
        """
        if user_id == toggled_by:
            # 防止管理員停用自己鎖死後台（ADMIN-9）。
            # errors.cannot_toggle_self 已登錄於 i18n_messages，交由
            # i18n_error_handler 依 Accept-Language 解譯。
            raise ForbiddenException("errors.cannot_toggle_self")

        result = await db.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()
        if user is None:
            raise NotFoundException("errors.user_not_found")

        user.is_active = not user.is_active
        user.updated_at = utc_now()
        await db.flush()

        new_state = user.is_active

        await AuditLogService.log(
            db,
            user_id=toggled_by,
            action=AuditAction.UPDATE,
            resource_type="user",
            resource_id=str(user.id),
            details={"is_active": new_state},
        )

        return ToggleActiveResponse(
            id=user_id,
            is_active=new_state,
            message="使用者已啟用" if new_state else "使用者已停用",
        )

    async def reset_user_password(
        self,
        db: AsyncSession,
        user_id: UUID,
        reset_by: UUID,
    ) -> ResetPasswordResponse:
        """管理員代為重設使用者密碼，回傳一次性臨時密碼。

        存在的理由（H1）：生產沒有設定 email transport，`/auth/forgot-password`
        的信永遠寄不出去，前端因此顯示「請告知現場醫護或系統管理員」——但管理員
        原本沒有任何重設他人密碼的能力，那句話等於空話。院內 kiosk 情境下病患人
        就在現場，當面由醫護重設本來就比 email 直接。

        - 臨時密碼用 `secrets` 生成，**只在這次回應裡出現一次**，不寫 log、不存明文
        - 產生的密碼保證通過 `RegisterRequest` 的強度規則（大小寫 + 數字 + ≥8）
        - **撤銷該使用者所有 refresh token**：重設密碼常見情境就是帳號可能已外洩，
          舊 session 必須一起失效，否則攻擊者手上的 refresh token 還能續命 7 天
        - 禁止對自己用（管理員改自己密碼走 `/auth/change-password`，那條要驗舊密碼）
        - 寫 audit log；**details 不含密碼**
        """
        if user_id == reset_by:
            # 對自己重設會繞過「須驗舊密碼」的保護 → 導回 change-password
            raise ForbiddenException("errors.cannot_reset_own_password")

        result = await db.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()
        if user is None:
            raise NotFoundException("errors.user_not_found")

        temp_password = generate_temp_password()
        user.password_hash = hash_password(temp_password)
        user.updated_at = utc_now()
        await db.flush()

        # 舊 session 一起失效（Redis 掛掉不該讓重設失敗——密碼已經換掉了）
        revoked = 0
        try:
            from app.cache.redis_client import get_redis
            from app.services.auth_service import _revoke_all_refresh_tokens

            redis = await get_redis()
            revoked = await _revoke_all_refresh_tokens(redis, str(user_id))
        except Exception:  # noqa: BLE001
            logger.exception(
                "reset_user_password: 撤銷 refresh token 失敗（密碼已重設）| user=%s",
                user_id,
            )

        await AuditLogService.log(
            db,
            user_id=reset_by,
            action=AuditAction.UPDATE,
            resource_type="user",
            resource_id=str(user.id),
            details={"password_reset": True, "refresh_tokens_revoked": revoked},
        )

        return ResetPasswordResponse(
            id=user_id,
            email=user.email,
            temp_password=temp_password,
        )

    async def system_health_check(self, db: AsyncSession) -> SystemHealthResponse:
        """系統健康檢查 — 對各依賴實際發一次探測。

        - DB：`SELECT 1`
        - Redis：`PING`
        - OpenAI：`models.list()`（最輕量的可達性檢查）

        每項各 2 秒逾時；任一非 "ok" 時，整體 `status` 標記為 "degraded"。
        失敗時各欄位回 `fail: <err>` 方便排錯，沿用 deep health check 慣例。
        """
        database = await _probe_db(db)
        redis = await _probe_redis()
        openai = await _probe_openai()

        overall = "ok" if all(v == "ok" for v in (database, redis, openai)) else "degraded"

        return SystemHealthResponse(
            status=overall,
            database=database,
            redis=redis,
            openai=openai,
            version=os.getenv("APP_VERSION", _APP_VERSION_FALLBACK),
            timestamp=utc_now(),
        )


# 應用版本：優先讀 APP_VERSION 環境變數，否則沿用 main.py 既有的版本字串
_APP_VERSION_FALLBACK = "1.0.0"


# ── 健康檢查探測（沿用 main.py deep health check 慣例）───────
_HEALTH_PROBE_TIMEOUT_SECONDS = 2.0


async def _probe_db(db: AsyncSession) -> str:
    """對 DB 跑 SELECT 1；成功回 "ok"，失敗回 "fail: <err>"。"""
    from sqlalchemy import text

    try:
        async def _run() -> None:
            await db.execute(text("SELECT 1"))

        await asyncio.wait_for(_run(), timeout=_HEALTH_PROBE_TIMEOUT_SECONDS)
        return "ok"
    except asyncio.TimeoutError:
        return f"fail: timeout >{_HEALTH_PROBE_TIMEOUT_SECONDS}s"
    except Exception as exc:  # noqa: BLE001 — 要回報給呼叫端
        return f"fail: {exc}"


async def _probe_redis() -> str:
    """對 Redis 跑 PING；成功回 "ok"，失敗回 "fail: <err>"。"""
    try:
        from app.cache.redis_client import get_redis

        redis = await get_redis()
        await asyncio.wait_for(redis.ping(), timeout=_HEALTH_PROBE_TIMEOUT_SECONDS)
        return "ok"
    except asyncio.TimeoutError:
        return f"fail: timeout >{_HEALTH_PROBE_TIMEOUT_SECONDS}s"
    except Exception as exc:  # noqa: BLE001
        return f"fail: {exc}"


async def _probe_openai() -> str:
    """對 OpenAI 跑最輕量的可達性檢查（models.list）；成功回 "ok"。"""
    try:
        from app.core.openai_client import get_openai_client

        client = get_openai_client()
        await asyncio.wait_for(
            client.models.list(), timeout=_HEALTH_PROBE_TIMEOUT_SECONDS
        )
        return "ok"
    except asyncio.TimeoutError:
        return f"fail: timeout >{_HEALTH_PROBE_TIMEOUT_SECONDS}s"
    except Exception as exc:  # noqa: BLE001
        return f"fail: {exc}"
