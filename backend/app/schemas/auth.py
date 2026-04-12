"""認證相關 Pydantic Schema"""

import re
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models.enums import UserRole


# ── 登入 ───────────────────────────────────────────────
class LoginRequest(BaseModel):
    """登入請求"""
    email: EmailStr
    password: str = Field(..., min_length=1)


class UserInfo(BaseModel):
    """登入回應中的使用者資訊"""
    id: UUID
    email: str
    name: str
    role: UserRole

    model_config = ConfigDict(from_attributes=True)


class LoginResponse(BaseModel):
    """登入回應"""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Access token 有效秒數")
    user: UserInfo


# ── 註冊 ───────────────────────────────────────────────
class RegisterRequest(BaseModel):
    """註冊請求"""
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    name: str = Field(..., min_length=1, max_length=100)
    role: UserRole = UserRole.PATIENT
    phone: Optional[str] = Field(None, max_length=20)
    department: Optional[str] = Field(None, max_length=100)
    license_number: Optional[str] = Field(None, max_length=50)

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        """密碼強度驗證：至少 8 碼，含大小寫字母與數字"""
        if not re.search(r"[A-Z]", v):
            raise ValueError("密碼需包含至少一個大寫字母")
        if not re.search(r"[a-z]", v):
            raise ValueError("密碼需包含至少一個小寫字母")
        if not re.search(r"\d", v):
            raise ValueError("密碼需包含至少一個數字")
        return v

    @field_validator("license_number")
    @classmethod
    def validate_license_for_doctor(cls, v: Optional[str], info: object) -> Optional[str]:
        """醫師角色必須提供執照號碼"""
        data = info.data if hasattr(info, "data") else {}  # type: ignore[union-attr]
        if data.get("role") == UserRole.DOCTOR and not v:
            raise ValueError("醫師角色必須提供 license_number")
        return v


# ── Token 刷新 ──────────────────────────────────────────
class RefreshTokenRequest(BaseModel):
    """Token 刷新請求"""
    refresh_token: str


class RefreshTokenResponse(BaseModel):
    """Token 刷新回應"""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


# ── 密碼變更 ───────────────────────────────────────────
class ChangePasswordRequest(BaseModel):
    """變更密碼請求"""
    current_password: str
    new_password: str = Field(..., min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, v: str) -> str:
        if not re.search(r"[A-Z]", v):
            raise ValueError("密碼需包含至少一個大寫字母")
        if not re.search(r"[a-z]", v):
            raise ValueError("密碼需包含至少一個小寫字母")
        if not re.search(r"\d", v):
            raise ValueError("密碼需包含至少一個數字")
        return v


# ── 忘記密碼 ───────────────────────────────────────────
class ForgotPasswordRequest(BaseModel):
    """忘記密碼請求（寄送重設信）"""
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    """重設密碼請求"""
    token: str
    new_password: str = Field(..., min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, v: str) -> str:
        if not re.search(r"[A-Z]", v):
            raise ValueError("密碼需包含至少一個大寫字母")
        if not re.search(r"[a-z]", v):
            raise ValueError("密碼需包含至少一個小寫字母")
        if not re.search(r"\d", v):
            raise ValueError("密碼需包含至少一個數字")
        return v


# ── 登出 ───────────────────────────────────────────────
class LogoutRequest(BaseModel):
    """登出請求"""
    refresh_token: Optional[str] = None


# ── 通用訊息回應 ───────────────────────────────────────
class MessageResponse(BaseModel):
    """通用訊息回應"""
    message: str


# ── 別名（供 router 匯入相容） ──────────────────────────
RefreshRequest = RefreshTokenRequest
RefreshResponse = RefreshTokenResponse
TokenResponse = LoginResponse
UserResponse = UserInfo

class UpdateProfileRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    phone: Optional[str] = Field(None, max_length=20)
