"""
JWT 認證 + 密碼雜湊工具
- RS256 非對稱加密
- Access Token (15 分鐘) + Refresh Token (7 天)
"""

import asyncio
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import jwt
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


# ── 給 async 路徑用的包裝 ──────────────────────────────
# bcrypt(cost 12) 在 Railway 容器上是 ~200-400ms 不可中斷的 CPU。直接在 `async def`
# 裡呼叫會把整個 event loop 釘住那麼久——那期間**所有**併發使用者都停擺：問診 WS 的
# 音訊 chunk 不會被送出、STT 上傳卡住、dashboard 事件延後。一次登入拖慢全院，
# 症狀是「app 偶爾就是會頓一下」，而且完全查不到是誰造成的。
#
# 同步版本刻意保留：CLI 腳本、測試 fixture 與 `admin_service`（測試有 monkeypatch
# 成同步 lambda）都還在用它，而那些路徑不在 event loop 上。
async def hash_password_async(password: str) -> str:
    """在 worker thread 上做雜湊，不佔用 event loop"""
    return await asyncio.to_thread(hash_password, password)


async def verify_password_async(plain_password: str, hashed_password: str) -> bool:
    """在 worker thread 上做驗證，不佔用 event loop"""
    return await asyncio.to_thread(verify_password, plain_password, hashed_password)


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
        jwt.InvalidTokenError: token 無效或已過期
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
        jwt.InvalidTokenError: token 無效、已過期或非 access 類型
    """
    payload = decode_token(token)
    if payload.get("type") != "access":
        raise jwt.InvalidTokenError("Invalid token type: expected access token")
    return payload


def verify_refresh_token(token: str) -> dict[str, Any]:
    """
    驗證 Refresh Token 並回傳 payload

    Raises:
        jwt.InvalidTokenError: token 無效、已過期或非 refresh 類型
    """
    payload = decode_token(token)
    if payload.get("type") != "refresh":
        raise jwt.InvalidTokenError("Invalid token type: expected refresh token")
    return payload


# 臨時密碼字元集：刻意排除易混淆字元（0/O/o、1/l/I），因為這串密碼要由醫護
# 口頭或手寫轉達給病患，看錯一個字就重設失敗。
_TEMP_PW_UPPER = "ABCDEFGHJKLMNPQRSTUVWXYZ"
_TEMP_PW_LOWER = "abcdefghijkmnpqrstuvwxyz"
_TEMP_PW_DIGIT = "23456789"
_TEMP_PW_LENGTH = 12


def generate_temp_password() -> str:
    """
    產生管理員代為重設用的一次性臨時密碼。

    **保證**通過 `RegisterRequest.validate_password_strength`（≥8 碼、含大寫、
    小寫、數字）——各類別先各取一個再補滿，不靠隨機碰運氣。
    使用 `secrets` 而非 `random`（這是憑證）。
    """
    alphabet = _TEMP_PW_UPPER + _TEMP_PW_LOWER + _TEMP_PW_DIGIT
    chars = [
        secrets.choice(_TEMP_PW_UPPER),
        secrets.choice(_TEMP_PW_LOWER),
        secrets.choice(_TEMP_PW_DIGIT),
    ]
    chars += [secrets.choice(alphabet) for _ in range(_TEMP_PW_LENGTH - len(chars))]
    # 洗牌，否則前三碼的類別固定可預測
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)
