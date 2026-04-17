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

import redis.asyncio as aioredis
from fastapi import Depends, Header, Query
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.redis_client import get_redis as get_cache_redis
from app.core.config import settings
from app.core.database import async_session_factory
from app.core.exceptions import ForbiddenException, UnauthorizedException
from app.core.security import verify_access_token
from app.models.user import User

# JWT 黑名單 Redis key 前綴（與 services.auth_service.BLACKLIST_KEY_PREFIX 一致）
BLACKLIST_KEY_PREFIX = "gu:token_blacklist:"

# ── Redis 單例 ─────────────────────────────────────────
_redis_client: Optional[aioredis.Redis] = None


async def init_redis() -> aioredis.Redis:
    """初始化 Redis 連線"""
    global _redis_client
    _redis_client = aioredis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
    )
    return _redis_client


async def close_redis() -> None:
    """關閉 Redis 連線"""
    global _redis_client
    if _redis_client:
        await _redis_client.close()
        _redis_client = None


async def get_redis() -> aioredis.Redis:
    """取得 Redis 客戶端（依賴注入用）"""
    if _redis_client is None:
        raise RuntimeError("Redis client not initialized. Call init_redis() first.")
    return _redis_client


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
    authorization: str = Header(..., alias="Authorization"),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    從 Bearer token 取得目前登入使用者。
    驗證流程：解析 token → 查詢使用者 → 確認帳號啟用。
    """
    if not authorization.startswith("Bearer "):
        raise UnauthorizedException(message="Invalid authorization header format")

    token = authorization[7:]  # 去掉 "Bearer " 前綴

    try:
        payload = verify_access_token(token)
    except JWTError:
        raise UnauthorizedException(message="Token 無效或已過期")

    user_id = payload.get("sub")
    if not user_id:
        raise UnauthorizedException(message="Token payload 缺少 sub")

    # 黑名單檢查：logout 過的 access token 即使未過期也要拒絕
    jti = payload.get("jti")
    if jti:
        redis = await get_cache_redis()
        if await redis.exists(f"{BLACKLIST_KEY_PREFIX}{jti}"):
            raise UnauthorizedException(message="Token 已失效")

    result = await db.execute(select(User).where(User.id == UUID(user_id)))
    user = result.scalar_one_or_none()

    if user is None:
        raise UnauthorizedException(message="使用者不存在")

    if not user.is_active:
        raise ForbiddenException(message="帳號已停用")

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
                message=f"需要角色: {', '.join(roles)}",
                details={"required_roles": list(roles), "current_role": current_user.role.value},
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
