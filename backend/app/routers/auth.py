"""
認證路由 — 登入、註冊、Token 管理、個人資料
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, Response, status
from fastapi.responses import JSONResponse
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.csrf import (
    clear_csrf_cookie,
    generate_csrf_token,
    set_csrf_cookie,
    validate_csrf,
)
from app.core.dependencies import get_current_user, get_db
from app.core.exceptions import AppException, UnauthorizedException
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
from app.utils.i18n_messages import get_message
from app.utils.language import resolve_language

router = APIRouter(prefix="/api/v1/auth", tags=["認證"])

auth_service = AuthService()


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    """把 refresh token 寫進 httpOnly + Secure + SameSite cookie（M-22）。

    path 限縮到 `settings.REFRESH_COOKIE_PATH`（/api/v1/auth），讓瀏覽器只在
    auth 端點送出此 cookie，縮小暴露面。Secure / SameSite 由 config 控制。
    """
    response.set_cookie(
        key=settings.REFRESH_COOKIE_NAME,
        value=refresh_token,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        path=settings.REFRESH_COOKIE_PATH,
    )


def _clear_refresh_cookie(response: Response) -> None:
    """清除 refresh token cookie（登出時呼叫）。"""
    response.delete_cookie(
        key=settings.REFRESH_COOKIE_NAME,
        path=settings.REFRESH_COOKIE_PATH,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
    )


def _auth_json_response(result: dict, status_code: int = status.HTTP_200_OK) -> JSONResponse:
    """登入 / refresh 成功 → 構造 JSONResponse 並設好 refresh + CSRF cookie。

    refresh token 改放 httpOnly cookie，回應 body 不再回傳 refresh_token（達成
    「前端無法讀取 refresh token」的安全目的）。同時設一個 double-submit 用的
    CSRF cookie（非 httpOnly），供前端回填 X-CSRF-Token header。

    直接回 JSONResponse（而非走 response_model）是因為 LoginResponse /
    RefreshResponse 將 refresh_token 標為必填，省略它無法通過 response_model
    驗證；改由此處明確控制 body 與 Set-Cookie。
    """
    refresh_token = result.pop("refresh_token", None)
    response = JSONResponse(content=result, status_code=status_code)
    if refresh_token:
        _set_refresh_cookie(response, refresh_token)
    set_csrf_cookie(response, generate_csrf_token())
    return response


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
) -> JSONResponse:
    """以電子郵件與密碼登入，取得 JWT Token 組合。

    M-22：refresh token 改以 httpOnly + Secure cookie 下發（回應 body 不含
    refresh_token），同時設 double-submit 用的 CSRF cookie。

    Rate limit 由 `AuthService.login` 負責：
    - 每 IP 每分鐘 10 次
    - 帳號連續失敗 5 次鎖 10 分鐘
    """
    client_ip = _extract_client_ip(request)
    result = await auth_service.login(
        db,
        email=payload.email,
        password=payload.password,
        client_ip=client_ip,
    )
    return _auth_json_response(result)


def _extract_client_ip(request: Request) -> str:
    """取出 client IP。

    委派 `app.core.net.get_client_ip`（預設不信任 X-Forwarded-For），
    集中代理信任策略，避免無條件信任 XFF 首段被偽造（M-7）。
    """
    from app.core.net import get_client_ip

    return get_client_ip(request)


@router.post(
    "/register",
    response_model=LoginResponse,
    status_code=status.HTTP_201_CREATED,
    summary="註冊",
)
async def register(
    payload: RegisterRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(_get_optional_current_user),
) -> JSONResponse:
    """
    註冊新使用者帳號。
    病患可自行註冊；醫師與管理員帳號需由管理員建立。

    Rate limit：每 IP per-IP sliding window（見 settings.REGISTER_IP_*），
    擋自助註冊濫用；超限拋 RateLimitExceededException（429）。
    """
    from app.cache.redis_client import get_redis
    from app.core import rate_limit as rl
    from app.core.net import get_client_ip

    redis = await get_redis()
    await rl.enforce_register_ip_rate_limit(redis, get_client_ip(request))

    # M-22：註冊同樣以 httpOnly cookie 下發 refresh token + CSRF cookie，
    # 與 login 一致；否則新註冊使用者無 refresh cookie，前端首次 refresh 會失敗。
    result = await auth_service.register(db, data=payload, current_user=current_user)
    return _auth_json_response(result, status_code=status.HTTP_201_CREATED)


async def _parse_optional_refresh_request(request: Request) -> RefreshRequest | None:
    """嘗試從 JSON body 解析 RefreshRequest；body 缺漏 / 非法時回 None。

    M-22 後 refresh token 主要來自 cookie，body 變為可選（相容舊客戶端）。
    因 RefreshRequest.refresh_token 為必填，這裡寬鬆解析而非以 FastAPI body
    依賴強制要求。
    """
    try:
        raw = await request.json()
    except Exception:  # noqa: BLE001 — 無 body / 非 JSON 都視為未帶
        return None
    if not isinstance(raw, dict):
        return None
    token = raw.get("refresh_token")
    if not token:
        return None
    return RefreshRequest(refresh_token=token)


@router.post(
    "/refresh",
    response_model=RefreshResponse,
    status_code=status.HTTP_200_OK,
    summary="更新 Token",
)
async def refresh_token(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """以 Refresh Token 換發新的 Access Token 與 Refresh Token。

    M-22：
    - refresh token 優先從 httpOnly cookie 讀取；cookie 缺漏時退而讀 body（相容）。
    - 採 double-submit CSRF：要求 X-CSRF-Token header 與 csrf cookie 相符，否則 403。
    - 換發成功後以 Set-Cookie 旋轉 refresh + CSRF cookie，body 不含 refresh_token。

    Rate limit：每 IP per-IP sliding window（見 settings.REFRESH_IP_*），
    擋對 refresh 端點的暴力 / 濫用；超限拋 RateLimitExceededException（429）。
    """
    from app.cache.redis_client import get_redis
    from app.core import rate_limit as rl
    from app.core.net import get_client_ip

    # CSRF 防護：cookie-based 端點必須驗 double-submit token
    validate_csrf(request)

    redis = await get_redis()
    await rl.enforce_refresh_ip_rate_limit(redis, get_client_ip(request))

    # cookie 優先，缺漏退回 body（相容）
    token = request.cookies.get(settings.REFRESH_COOKIE_NAME)
    if not token:
        body = await _parse_optional_refresh_request(request)
        token = body.refresh_token if body else None
    if not token:
        raise UnauthorizedException("errors.refresh_token_invalid")

    result = await auth_service.refresh_token(db, refresh_token=token)
    return _auth_json_response(result)


@router.post(
    "/logout",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
    summary="登出",
)
async def logout(
    payload: LogoutRequest,
    request: Request,
    response: Response,
    authorization: str = Header(..., alias="Authorization"),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> MessageResponse:
    """登出並黑名單 Access / Refresh Token。

    M-22：
    - 採 double-submit CSRF：要求 X-CSRF-Token header 與 csrf cookie 相符，否則 403。
    - refresh token 優先從 httpOnly cookie 讀取；cookie 缺漏時退而讀 body（相容）。
    - 一律清除 refresh + CSRF cookie。
    """
    # CSRF 防護：cookie-based 端點必須驗 double-submit token
    validate_csrf(request)

    # get_current_user 已驗證格式，此處直接去掉 "Bearer " 前綴即可
    access_token = authorization[7:] if authorization.startswith("Bearer ") else authorization
    refresh_token = request.cookies.get(settings.REFRESH_COOKIE_NAME) or payload.refresh_token
    await auth_service.logout(
        db,
        user_id=current_user.id,
        access_token=access_token,
        refresh_token=refresh_token,
    )
    # 清除 refresh / CSRF cookie，等同瀏覽器端登出
    _clear_refresh_cookie(response)
    clear_csrf_cookie(response)
    lang = resolve_language(
        user=current_user,
        accept_language_header=request.headers.get("accept-language"),
    )
    return MessageResponse(message=get_message("messages.logout_success", lang))


@router.post(
    "/change-password",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
    summary="變更密碼",
)
async def change_password(
    payload: ChangePasswordRequest,
    request: Request,
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
    lang = resolve_language(
        user=current_user,
        accept_language_header=request.headers.get("accept-language"),
    )
    return MessageResponse(message=get_message("messages.password_changed", lang))


@router.post(
    "/forgot-password",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
    summary="忘記密碼",
)
async def forgot_password(
    payload: ForgotPasswordRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    """發送密碼重設連結至使用者的電子郵件。無論信箱是否存在，皆回傳相同訊息。

    Rate limit：每 IP 每 15 分鐘 5 次（settings.PASSWORD_RESET_IP_*），
    擋帳號 enumeration 與寄信濫用；超限拋 RateLimitExceededException（429）。
    """
    from app.cache.redis_client import get_redis
    from app.core import rate_limit as rl

    redis = await get_redis()
    await rl.enforce_password_reset_ip_rate_limit(redis, _extract_client_ip(request))

    await auth_service.forgot_password(db, email=payload.email)
    lang = resolve_language(
        accept_language_header=request.headers.get("accept-language"),
    )
    return MessageResponse(message=get_message("messages.password_reset_link_sent", lang))


@router.post(
    "/reset-password",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
    summary="重設密碼",
)
async def reset_password(
    payload: ResetPasswordRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    """使用重設 Token 設定新密碼。

    Rate limit：與 /forgot-password 共用 per-IP policy（每 IP 每 15 分鐘 5 次），
    擋對重設 token 的暴力嘗試；超限拋 RateLimitExceededException（429）。
    """
    from app.cache.redis_client import get_redis
    from app.core import rate_limit as rl

    redis = await get_redis()
    await rl.enforce_password_reset_ip_rate_limit(redis, _extract_client_ip(request))

    await auth_service.reset_password(
        db,
        token=payload.token,
        new_password=payload.new_password,
    )
    lang = resolve_language(
        accept_language_header=request.headers.get("accept-language"),
    )
    return MessageResponse(message=get_message("messages.password_reset_success", lang))


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
