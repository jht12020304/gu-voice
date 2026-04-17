"""
認證服務
- 登入 / 註冊 / 登出
- JWT Token 管理（RS256 access + refresh）
- 密碼變更 / 重設
- 使用者個人資料
"""

import logging
import secrets
import time
from typing import Any, Optional
from uuid import UUID

from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import (
    AccountDisabledException,
    EmailAlreadyExistsException,
    InvalidCredentialsException,
    NotFoundException,
    UnauthorizedException,
    ValidationException,
)
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    verify_access_token,
    verify_password,
    verify_refresh_token,
)
from app.models.enums import UserRole
from app.models.user import User
from app.utils.datetime_utils import utc_now

logger = logging.getLogger(__name__)

# JWT 黑名單 Redis key 前綴（與 dependencies.get_current_user 檢查端共用）
BLACKLIST_KEY_PREFIX = "gu:token_blacklist:"


class AuthService:
    """認證相關業務邏輯"""

    @staticmethod
    async def login(db: AsyncSession, email: str, password: str) -> dict[str, Any]:
        """
        使用者登入

        Args:
            db: 資料庫 session
            email: 電子信箱
            password: 明文密碼

        Returns:
            包含 access_token、refresh_token 與使用者資訊的字典

        Raises:
            InvalidCredentialsException: 帳號或密碼錯誤
            AccountDisabledException: 帳號已停用
        """
        result = await db.execute(
            select(User).where(User.email == email)
        )
        user = result.scalar_one_or_none()

        if user is None or not verify_password(password, user.password_hash):
            raise InvalidCredentialsException()

        if not user.is_active:
            raise AccountDisabledException()

        # 更新最後登入時間
        user.last_login_at = utc_now()
        await db.flush()

        # 建立 JWT token 對
        access_token = create_access_token(str(user.id), user.role.value)
        refresh_token = create_refresh_token(str(user.id), user.role.value)

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            "user": {
                "id": str(user.id),
                "email": user.email,
                "name": user.name,
                "role": user.role.value,
            },
        }

    @staticmethod
    async def register(db: AsyncSession, data: Any, current_user: Any = None) -> dict[str, Any]:
        """
        使用者註冊

        Args:
            db: 資料庫 session
            data: 註冊資料（RegisterRequest Pydantic model）
            current_user: 目前登入的使用者（可選，用於管理員建立帳號）

        Returns:
            包含 access_token、refresh_token 與使用者資訊的字典

        Raises:
            EmailAlreadyExistsException: Email 已被註冊
        """
        # 檢查 email 是否已存在
        result = await db.execute(
            select(User).where(User.email == data.email)
        )
        if result.scalar_one_or_none() is not None:
            raise EmailAlreadyExistsException()

        # 建立使用者
        now = utc_now()
        user = User(
            email=data.email,
            password_hash=hash_password(data.password),
            name=data.name,
            role=data.role,
            phone=data.phone,
            department=data.department,
            license_number=data.license_number,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        db.add(user)
        await db.flush()

        # 建立 JWT token 對（與登入回應格式一致）
        access_token = create_access_token(str(user.id), user.role.value)
        refresh_token = create_refresh_token(str(user.id), user.role.value)

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            "user": {
                "id": str(user.id),
                "email": user.email,
                "name": user.name,
                "role": user.role.value,
            },
        }

    @staticmethod
    async def refresh_token(db: AsyncSession, refresh_token: str) -> dict[str, Any]:
        """
        刷新 Token

        Args:
            db: 資料庫 session
            refresh_token: 現有的 refresh token

        Returns:
            新的 access_token 與 refresh_token

        Raises:
            UnauthorizedException: token 無效或已過期
        """
        try:
            payload = verify_refresh_token(refresh_token)
        except JWTError:
            raise UnauthorizedException("Refresh token 無效或已過期")

        user_id = payload.get("sub")
        if not user_id:
            raise UnauthorizedException("Token payload 不完整")

        # 確認使用者仍然存在且啟用
        result = await db.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()

        if user is None:
            raise UnauthorizedException("使用者不存在")
        if not user.is_active:
            raise AccountDisabledException()

        # 建立新的 token 對
        new_access = create_access_token(str(user.id), user.role.value)
        new_refresh = create_refresh_token(str(user.id), user.role.value)

        return {
            "access_token": new_access,
            "refresh_token": new_refresh,
            "token_type": "bearer",
        }

    @staticmethod
    async def logout(
        db: AsyncSession,
        user_id: UUID,
        access_token: str,
        refresh_token: Optional[str] = None,
    ) -> None:
        """
        登出 — 將 access / refresh token 加入 Redis 黑名單

        策略：
          - access token 一律黑名單（剩餘效期 = exp - now）
          - 有帶 refresh token 才黑名單它；沒帶就只記 warning
            （撤銷該使用者所有 refresh token 需 refresh token 登記表，
             見 TODO P1-#11）

        已過期或解不開的 token 直接跳過（沒有意義黑名單一個本來就失效的 token）。
        """
        from app.cache.redis_client import get_redis

        redis = await get_redis()
        now = int(time.time())

        async def _blacklist(payload: dict[str, Any]) -> None:
            jti = payload.get("jti")
            exp = payload.get("exp")
            if not jti or not exp:
                return
            ttl = max(int(exp) - now, 1)
            await redis.setex(f"{BLACKLIST_KEY_PREFIX}{jti}", ttl, "1")

        try:
            await _blacklist(verify_access_token(access_token))
        except JWTError:
            logger.debug("logout: access token 已失效，跳過黑名單 user=%s", user_id)

        if refresh_token:
            try:
                await _blacklist(verify_refresh_token(refresh_token))
            except JWTError:
                logger.debug("logout: refresh token 已失效，跳過黑名單 user=%s", user_id)
        else:
            logger.warning(
                "logout user=%s 未提供 refresh_token；目前僅黑名單 access token，"
                "撤銷該使用者所有 refresh token 需 TODO P1-#11 實作",
                user_id,
            )

    @staticmethod
    async def change_password(
        db: AsyncSession,
        user_id: UUID,
        current_password: str,
        new_password: str,
    ) -> None:
        """
        變更密碼

        Raises:
            NotFoundException: 使用者不存在
            InvalidCredentialsException: 目前密碼不正確
        """
        result = await db.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()
        if user is None:
            raise NotFoundException("使用者不存在")

        if not verify_password(current_password, user.password_hash):
            raise InvalidCredentialsException("目前密碼不正確")

        user.password_hash = hash_password(new_password)
        user.updated_at = utc_now()
        await db.flush()

    @staticmethod
    async def forgot_password(db: AsyncSession, email: str) -> dict[str, str]:
        """
        忘記密碼 — 產生重設 token

        Note:
            目前為 placeholder，實際應整合 email 發送服務

        Returns:
            包含 reset_token 的字典（開發用途，正式環境不回傳）
        """
        result = await db.execute(
            select(User).where(User.email == email)
        )
        user = result.scalar_one_or_none()

        # 無論使用者是否存在，都回傳成功（避免洩漏帳號存在與否）
        if user is None:
            return {"message": "若此信箱已註冊，將會收到重設密碼信件"}

        # 產生重設 token（64 字元隨機字串）
        reset_token = secrets.token_urlsafe(48)

        # TODO: 將 reset_token 儲存至 Redis（TTL 30 分鐘）並發送 email
        # 暫時將 token 存放在使用者記錄（需新增欄位）或 Redis
        from app.cache.redis_client import get_redis

        redis = await get_redis()
        key = f"gu:password_reset:{reset_token}"
        await redis.setex(key, 1800, str(user.id))  # 30 分鐘有效

        # Placeholder: 日後整合 email 服務
        return {
            "message": "若此信箱已註冊，將會收到重設密碼信件",
            # 開發模式下回傳 token 方便測試
            "_debug_reset_token": reset_token if settings.APP_ENV == "development" else None,
        }

    @staticmethod
    async def reset_password(db: AsyncSession, token: str, new_password: str) -> None:
        """
        重設密碼

        Args:
            token: 重設 token
            new_password: 新密碼

        Raises:
            UnauthorizedException: token 無效或已過期
        """
        from app.cache.redis_client import get_redis

        redis = await get_redis()
        key = f"gu:password_reset:{token}"
        user_id = await redis.get(key)

        if user_id is None:
            raise UnauthorizedException("重設密碼連結已過期或無效")

        result = await db.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()
        if user is None:
            raise NotFoundException("使用者不存在")

        user.password_hash = hash_password(new_password)
        user.updated_at = utc_now()
        await db.flush()

        # 使用後刪除 token
        await redis.delete(key)

    @staticmethod
    async def get_user_profile(db: AsyncSession, user_id: UUID) -> dict[str, Any]:
        """
        取得使用者個人資料

        Raises:
            NotFoundException: 使用者不存在
        """
        result = await db.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()
        if user is None:
            raise NotFoundException("使用者不存在")

        return {
            "id": str(user.id),
            "email": user.email,
            "name": user.name,
            "role": user.role.value,
            "phone": user.phone,
            "department": user.department,
            "license_number": user.license_number,
            "is_active": user.is_active,
            "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
            "created_at": user.created_at.isoformat() if user.created_at else None,
        }

    @staticmethod
    async def update_profile(
        db: AsyncSession,
        user_id: UUID,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        """
        更新使用者個人資料

        Args:
            data: 可更新欄位（name, phone, department）

        Raises:
            NotFoundException: 使用者不存在
        """
        result = await db.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()
        if user is None:
            raise NotFoundException("使用者不存在")

        # 僅更新允許的欄位
        updatable_fields = {"name", "phone", "department"}
        for field, value in data.items():
            if field in updatable_fields and value is not None:
                setattr(user, field, value)

        user.updated_at = utc_now()
        await db.flush()

        return await AuthService.get_user_profile(db, user_id)
