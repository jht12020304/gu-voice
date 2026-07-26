"""
共用依賴注入
- get_db: 非同步資料庫 session
- get_redis: Redis 客戶端
- get_current_user: JWT 認證
- require_role: 角色權限控制
- PaginationParams: 游標分頁參數
"""

from collections.abc import AsyncGenerator, Callable
from typing import Any, Optional
from uuid import UUID

from fastapi import Depends, Header, Query, Request
import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Redis 客戶端單一權威：app.cache.redis_client（懶初始化 _redis_pool）。
# 此處僅 re-export，讓 `Depends(get_redis)` 與既有
# `from app.core.dependencies import get_redis` 呼叫端保持不變，同時
# 保證全 backend 共用同一連線池。
from app.cache.redis_client import get_redis as get_redis
from app.core.database import async_session_factory
from app.core.exceptions import ForbiddenException, UnauthorizedException
from app.core.security import verify_access_token
from app.models.user import User

# JWT 黑名單 Redis key 前綴（與 services.auth_service.BLACKLIST_KEY_PREFIX 一致）
BLACKLIST_KEY_PREFIX = "gu:token_blacklist:"

# ── Database Session ───────────────────────────────────
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """取得非同步資料庫 session（依賴注入用，請求結束後自動關閉）"""
    session = async_session_factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


# ── JWT 認證 ───────────────────────────────────────────
async def get_current_user(
    request: Request,
    authorization: str = Header(..., alias="Authorization"),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    從 Bearer token 取得目前登入使用者。
    驗證流程：解析 token → 查詢使用者 → 確認帳號啟用。

    `request` 由 FastAPI 自動注入（不影響呼叫端 `Depends(get_current_user)` 介面）；
    成功取得 user 後寫入 `request.state.user`，供 AuditLoggingMiddleware 取 user_id。
    """
    if not authorization.startswith("Bearer "):
        raise UnauthorizedException(message="errors.invalid_auth_header")

    token = authorization[7:]  # 去掉 "Bearer " 前綴

    try:
        payload = verify_access_token(token)
    except jwt.InvalidTokenError:
        raise UnauthorizedException(message="errors.token_invalid_or_expired")

    user_id = payload.get("sub")
    if not user_id:
        raise UnauthorizedException(message="errors.token_payload_missing_sub")

    # 黑名單檢查：logout 過的 access token 即使未過期也要拒絕
    jti = payload.get("jti")
    if jti:
        redis = await get_redis()
        if await redis.exists(f"{BLACKLIST_KEY_PREFIX}{jti}"):
            raise UnauthorizedException(message="errors.token_revoked")

    result = await db.execute(select(User).where(User.id == UUID(user_id)))
    user = result.scalar_one_or_none()

    if user is None:
        raise UnauthorizedException(message="errors.user_not_found")

    if not user.is_active:
        raise ForbiddenException(message="errors.account_disabled")

    # 供 AuditLoggingMiddleware._extract_user_id 取用（middleware 在 endpoint 之後執行，
    # request.state 仍存活，故能讀到此處設定的 user）。
    request.state.user = user

    return user


# ── 角色權限控制 ───────────────────────────────────────
def require_role(*roles: str) -> Callable[..., Any]:
    """
    角色權限依賴工廠。
    用法：Depends(require_role("doctor", "admin"))
    """

    async def _role_checker(
        current_user: User = Depends(get_current_user),
    ) -> User:
        if current_user.role.value not in roles:
            raise ForbiddenException(
                message="errors.role_required",
                details={"required_roles": list(roles), "current_role": current_user.role.value},
                message_kwargs={"roles": ", ".join(roles)},
            )
        return current_user

    return _role_checker


# ── 分頁參數 ───────────────────────────────────────────
class PaginationParams:
    """游標分頁查詢參數"""

    def __init__(
        self,
        cursor: Optional[str] = Query(None, description="上一頁最後一筆的 cursor"),
        limit: int = Query(20, ge=1, le=100, description="每頁筆數，預設 20，最大 100"),
    ) -> None:
        self.cursor = cursor
        self.limit = limit
