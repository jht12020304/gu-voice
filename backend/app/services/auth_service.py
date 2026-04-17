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

# Refresh token rotation 登記表 key 前綴
# 每發一張 refresh token，就寫一筆 gu:refresh:{user_id}:{jti} = "1"，TTL = token exp
# refresh 時必須先 atomic 刪除舊 jti；刪不到就視為 replay，撤銷該 user 所有 refresh token
REFRESH_TOKEN_KEY_PREFIX = "gu:refresh:"

# 密碼重設 token key 前綴與 TTL（P3 #31）
# gu:reset:{token} = user_id；TTL 30 分鐘
RESET_TOKEN_KEY_PREFIX = "gu:reset:"
RESET_TOKEN_TTL_SECONDS = 1800

# 忘記密碼端點統一回傳訊息（不暴露帳號是否存在）
FORGOT_PASSWORD_GENERIC_MESSAGE = "若此電子郵件已註冊，密碼重設連結已寄出"


def _refresh_key(user_id: Any, jti: str) -> str:
    return f"{REFRESH_TOKEN_KEY_PREFIX}{user_id}:{jti}"


async def _register_refresh_token(redis: Any, user_id: Any, refresh_token: str) -> None:
    """Decode 並在 Redis 登記 refresh jti（TTL = exp - now）。"""
    try:
        payload = verify_refresh_token(refresh_token)
    except JWTError:
        return
    jti = payload.get("jti")
    exp = payload.get("exp")
    if not jti or not exp:
        return
    ttl = max(int(exp) - int(time.time()), 1)
    await redis.setex(_refresh_key(user_id, jti), ttl, "1")


async def _consume_refresh_jti(redis: Any, user_id: Any, jti: str) -> bool:
    """原子刪除一筆 refresh jti。True 代表本來就存在、成功消耗。"""
    deleted = await redis.delete(_refresh_key(user_id, jti))
    return bool(deleted)


async def _revoke_all_refresh_tokens(redis: Any, user_id: Any) -> int:
    """掃除該 user 所有 refresh token 登記。回傳刪除筆數。"""
    pattern = f"{REFRESH_TOKEN_KEY_PREFIX}{user_id}:*"
    count = 0
    async for key in redis.scan_iter(match=pattern):
        count += int(await redis.delete(key))
    return count


class AuthService:
    """認證相關業務邏輯"""

    @staticmethod
    async def login(
        db: AsyncSession,
        email: str,
        password: str,
        client_ip: str = "",
    ) -> dict[str, Any]:
        """
        使用者登入

        Rate limit 順序（P2 #14）：
          1. IP sliding window（10/min）→ 擋刷登入端點
          2. 帳號鎖定檢查（連續 5 次失敗鎖 10 分鐘）
          3. 驗證失敗：INCR 失敗計數；達門檻自動鎖；統一回 InvalidCredentials（不洩漏鎖定）
          4. 驗證成功：清空失敗計數

        Args:
            db: 資料庫 session
            email: 電子信箱
            password: 明文密碼
            client_ip: 呼叫端 IP（router 從 X-Forwarded-For / request.client 取）

        Returns:
            包含 access_token、refresh_token 與使用者資訊的字典

        Raises:
            RateLimitExceededException: IP 頻率過高或帳號已鎖定
            InvalidCredentialsException: 帳號或密碼錯誤
            AccountDisabledException: 帳號已停用
        """
        from app.cache.redis_client import get_redis
        from app.core import rate_limit as rl

        redis = await get_redis()

        # 1. IP 層級限流
        await rl.enforce_login_ip_rate_limit(redis, client_ip)

        # 2. 帳號鎖定檢查（在比對密碼之前，避免鎖定中還在做 bcrypt）
        await rl.enforce_account_not_locked(redis, email)

        result = await db.execute(
            select(User).where(User.email == email)
        )
        user = result.scalar_one_or_none()

        if user is None or not verify_password(password, user.password_hash):
            # 3. 記錄失敗；可能觸發鎖定，但對呼叫端一律回 InvalidCredentials
            await rl.record_login_failure(redis, email)
            raise InvalidCredentialsException()

        if not user.is_active:
            raise AccountDisabledException()

        # 4. 成功 → 清失敗計數
        await rl.clear_login_failures(redis, email)

        # 更新最後登入時間
        user.last_login_at = utc_now()
        await db.flush()

        # 建立 JWT token 對
        access_token = create_access_token(str(user.id), user.role.value)
        refresh_token = create_refresh_token(str(user.id), user.role.value)

        # 登記 refresh jti 供 rotation / reuse detection（P1-#11）
        await _register_refresh_token(redis, str(user.id), refresh_token)

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

        from app.cache.redis_client import get_redis
        await _register_refresh_token(await get_redis(), str(user.id), refresh_token)

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
        old_jti = payload.get("jti")
        if not user_id or not old_jti:
            raise UnauthorizedException("Token payload 不完整")

        # Rotation + reuse detection（P1-#11）：
        # atomic 消耗舊 jti；刪不到 → 重播/被盜 → 撤銷該 user 所有 refresh token
        from app.cache.redis_client import get_redis
        redis = await get_redis()
        if not await _consume_refresh_jti(redis, user_id, old_jti):
            revoked = await _revoke_all_refresh_tokens(redis, user_id)
            logger.warning(
                "refresh token reuse detected user=%s old_jti=%s revoked_total=%d",
                user_id, old_jti, revoked,
            )
            raise UnauthorizedException("Refresh token 重複使用，請重新登入")

        # 確認使用者仍然存在且啟用
        result = await db.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()

        if user is None:
            raise UnauthorizedException("使用者不存在")
        if not user.is_active:
            raise AccountDisabledException()

        # 建立新的 token 對，並登記新 refresh jti
        new_access = create_access_token(str(user.id), user.role.value)
        new_refresh = create_refresh_token(str(user.id), user.role.value)
        await _register_refresh_token(redis, str(user.id), new_refresh)

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
                ref_payload = verify_refresh_token(refresh_token)
                await _blacklist(ref_payload)
                ref_jti = ref_payload.get("jti")
                if ref_jti:
                    # 同時移除 rotation 登記，阻斷後續 refresh 交換
                    await _consume_refresh_jti(redis, str(user_id), ref_jti)
            except JWTError:
                logger.debug("logout: refresh token 已失效，跳過黑名單 user=%s", user_id)
        else:
            # 未帶 refresh token：撤銷該 user 所有 rotation 登記，等同強制重新登入
            revoked = await _revoke_all_refresh_tokens(redis, str(user_id))
            logger.info(
                "logout user=%s 未提供 refresh_token；revoke 所有 refresh jti=%d",
                user_id, revoked,
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
    async def forgot_password(
        db: AsyncSession,
        email: str,
        email_client: Optional[Any] = None,
    ) -> dict[str, str]:
        """
        忘記密碼 — 產生重設 token 並寄出重設信（P3 #31）。

        流程：
          1. 查帳號；不存在就直接回通用訊息（避免帳號 enumeration）
          2. 產 `secrets.token_urlsafe(32)`；存 `gu:reset:{token}` → user_id，TTL 1800s
          3. 組 reset URL = `{FRONTEND_BASE_URL}/reset-password?token={token}`
          4. 呼叫 email_client 寄信（失敗不對呼叫端拋）

        Args:
            email_client: 可注入的 email 客戶端（測試用）；None 時用預設實作
        """
        from app.cache.redis_client import get_redis
        from app.core.email_client import send_email

        result = await db.execute(
            select(User).where(User.email == email)
        )
        user = result.scalar_one_or_none()

        # 不存在也要回一樣的訊息；且不可動 Redis / 不可寄信
        if user is None:
            logger.info("forgot_password: email 不存在，靜默回成功 email=%s", email)
            return {"message": FORGOT_PASSWORD_GENERIC_MESSAGE}

        reset_token = secrets.token_urlsafe(32)
        redis = await get_redis()
        await redis.setex(
            f"{RESET_TOKEN_KEY_PREFIX}{reset_token}",
            RESET_TOKEN_TTL_SECONDS,
            str(user.id),
        )

        reset_url = f"{settings.FRONTEND_BASE_URL}/reset-password?token={reset_token}"
        subject = "[GU Voice] 密碼重設連結"
        body_text = (
            f"您好，\n\n我們收到一則密碼重設請求。請於 30 分鐘內點擊以下連結完成重設：\n"
            f"{reset_url}\n\n若非您本人操作，請忽略此信。"
        )
        body_html = (
            f"<p>您好，</p><p>我們收到一則密碼重設請求。"
            f"請於 30 分鐘內點擊以下連結完成重設：</p>"
            f'<p><a href="{reset_url}">{reset_url}</a></p>'
            f"<p>若非您本人操作，請忽略此信。</p>"
        )

        await send_email(
            to=user.email,
            subject=subject,
            body_html=body_html,
            body_text=body_text,
            client=email_client,
        )

        return {"message": FORGOT_PASSWORD_GENERIC_MESSAGE}

    @staticmethod
    async def reset_password(db: AsyncSession, token: str, new_password: str) -> None:
        """
        重設密碼；成功後 invalidate token。

        Raises:
            UnauthorizedException: token 無效或已過期
            NotFoundException: token 對應的 user 已刪除
        """
        from app.cache.redis_client import get_redis

        redis = await get_redis()
        key = f"{RESET_TOKEN_KEY_PREFIX}{token}"
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

        # 一次性 token：用完立即刪除
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
