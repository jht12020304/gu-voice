"""
認證路由 — 登入、註冊、Token 管理、個人資料
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, status
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db
from app.core.exceptions import AppException
from app.core.security import verify_access_token
from app.schemas.auth import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    LoginResponse,
    LogoutRequest,
    MessageResponse,
    RefreshRequest,
    RefreshResponse,
    RegisterRequest,
    ResetPasswordRequest,
    TokenResponse,
    UpdateProfileRequest,
    UserResponse,
)
from app.services.auth_service import AuthService

router = APIRouter(prefix="/api/v1/auth", tags=["認證"])

auth_service = AuthService()


async def _get_optional_current_user(
    authorization: str | None = Header(None, alias="Authorization"),
    db: AsyncSession = Depends(get_db),
):
    """
    嘗試解析 Bearer Token；若未提供或無效則回傳 None。
    用於「病患可匿名註冊、管理員需驗證」的場景。
    """
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization[7:]
    try:
        payload = verify_access_token(token)
    except JWTError:
        return None
    from app.models.user import User
    from sqlalchemy import select
    from uuid import UUID as _UUID

    user_id = payload.get("sub")
    if not user_id:
        return None
    result = await db.execute(select(User).where(User.id == _UUID(user_id)))
    return result.scalar_one_or_none()


@router.post(
    "/login",
    response_model=LoginResponse,
    status_code=status.HTTP_200_OK,
    summary="登入",
)
async def login(
    request: Request,
    payload: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> LoginResponse:
    """以電子郵件與密碼登入，取得 JWT Token 組合。

    Rate limit 由 `AuthService.login` 負責：
    - 每 IP 每分鐘 10 次
    - 帳號連續失敗 5 次鎖 10 分鐘
    """
    client_ip = _extract_client_ip(request)
    return await auth_service.login(
        db,
        email=payload.email,
        password=payload.password,
        client_ip=client_ip,
    )


def _extract_client_ip(request: Request) -> str:
    """取出最靠近的 client IP。
    - 優先 X-Forwarded-For 第一段（Railway/Cloudflare 代理層），fallback 到 client.host。
    """
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else ""


@router.post(
    "/register",
    response_model=LoginResponse,
    status_code=status.HTTP_201_CREATED,
    summary="註冊",
)
async def register(
    payload: RegisterRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(_get_optional_current_user),
) -> LoginResponse:
    """
    註冊新使用者帳號。
    病患可自行註冊；醫師與管理員帳號需由管理員建立。
    """
    return await auth_service.register(db, data=payload, current_user=current_user)


@router.post(
    "/refresh",
    response_model=RefreshResponse,
    status_code=status.HTTP_200_OK,
    summary="更新 Token",
)
async def refresh_token(
    payload: RefreshRequest,
    db: AsyncSession = Depends(get_db),
) -> RefreshResponse:
    """以 Refresh Token 換發新的 Access Token 與 Refresh Token。"""
    return await auth_service.refresh_token(db, refresh_token=payload.refresh_token)


@router.post(
    "/logout",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
    summary="登出",
)
async def logout(
    payload: LogoutRequest,
    authorization: str = Header(..., alias="Authorization"),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> MessageResponse:
    """登出並黑名單 Access / Refresh Token。"""
    # get_current_user 已驗證格式，此處直接去掉 "Bearer " 前綴即可
    access_token = authorization[7:] if authorization.startswith("Bearer ") else authorization
    await auth_service.logout(
        db,
        user_id=current_user.id,
        access_token=access_token,
        refresh_token=payload.refresh_token,
    )
    return MessageResponse(message="登出成功")


@router.post(
    "/change-password",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
    summary="變更密碼",
)
async def change_password(
    payload: ChangePasswordRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> MessageResponse:
    """變更目前使用者的密碼，需提供目前密碼驗證。"""
    await auth_service.change_password(
        db,
        user_id=current_user.id,
        current_password=payload.current_password,
        new_password=payload.new_password,
    )
    return MessageResponse(message="密碼變更成功")


@router.post(
    "/forgot-password",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
    summary="忘記密碼",
)
async def forgot_password(
    payload: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    """發送密碼重設連結至使用者的電子郵件。無論信箱是否存在，皆回傳相同訊息。"""
    await auth_service.forgot_password(db, email=payload.email)
    return MessageResponse(message="若此電子郵件已註冊，密碼重設連結已寄出")


@router.post(
    "/reset-password",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
    summary="重設密碼",
)
async def reset_password(
    payload: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    """使用重設 Token 設定新密碼。"""
    await auth_service.reset_password(
        db,
        token=payload.token,
        new_password=payload.new_password,
    )
    return MessageResponse(message="密碼重設成功，請使用新密碼登入")


@router.get(
    "/me",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="取得目前使用者資訊",
)
async def get_me(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> UserResponse:
    """取得目前已認證使用者的完整資料。"""
    return await auth_service.get_user_profile(db, user_id=current_user.id)


@router.put(
    "/me",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="更新目前使用者資訊",
)
async def update_me(
    payload: UpdateProfileRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> UserResponse:
    """更新目前已認證使用者的個人資料。變更密碼時需提供目前密碼。"""
    return await auth_service.update_profile(
        db,
        user_id=current_user.id,
        data=payload.model_dump(exclude_unset=True),
    )
