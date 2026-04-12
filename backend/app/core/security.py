"""
JWT 認證 + 密碼雜湊工具
- RS256 非對稱加密
- Access Token (15 分鐘) + Refresh Token (7 天)
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

# ── 密碼雜湊 ───────────────────────────────────────────
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """將明文密碼雜湊為 bcrypt 格式"""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """驗證明文密碼是否與雜湊值匹配"""
    return pwd_context.verify(plain_password, hashed_password)


# ── JWT Token ──────────────────────────────────────────
def create_token(
    subject: str,
    role: str,
    token_type: Literal["access", "refresh"] = "access",
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """
    建立 JWT token

    Args:
        subject: 使用者 ID (UUID 字串)
        role: 使用者角色
        token_type: "access" 或 "refresh"
        extra_claims: 額外 claims
    """
    now = datetime.now(timezone.utc)

    if token_type == "access":
        expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    else:
        expire = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

    payload: dict[str, Any] = {
        "sub": subject,
        "role": role,
        "jti": str(uuid.uuid4()),
        "exp": expire,
        "iat": now,
        "type": token_type,
    }

    if extra_claims:
        payload.update(extra_claims)

    return jwt.encode(
        payload,
        settings.JWT_PRIVATE_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


def create_access_token(subject: str, role: str) -> str:
    """建立 Access Token (短效期)"""
    return create_token(subject, role, token_type="access")


def create_refresh_token(subject: str, role: str) -> str:
    """建立 Refresh Token (長效期)"""
    return create_token(subject, role, token_type="refresh")


def decode_token(token: str) -> dict[str, Any]:
    """
    解碼並驗證 JWT token

    Raises:
        JWTError: token 無效或已過期
    """
    return jwt.decode(
        token,
        settings.JWT_PUBLIC_KEY,
        algorithms=[settings.JWT_ALGORITHM],
    )


def verify_access_token(token: str) -> dict[str, Any]:
    """
    驗證 Access Token 並回傳 payload

    Raises:
        JWTError: token 無效、已過期或非 access 類型
    """
    payload = decode_token(token)
    if payload.get("type") != "access":
        raise JWTError("Invalid token type: expected access token")
    return payload


def verify_refresh_token(token: str) -> dict[str, Any]:
    """
    驗證 Refresh Token 並回傳 payload

    Raises:
        JWTError: token 無效、已過期或非 refresh 類型
    """
    payload = decode_token(token)
    if payload.get("type") != "refresh":
        raise JWTError("Invalid token type: expected refresh token")
    return payload
