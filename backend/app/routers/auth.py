"""
認證路由 — 登入、註冊、Token 管理、個人資料
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, Response, status
from fastapi.responses import JSONResponse
import jwt
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

    雙路徑 refresh：
    - 同站部署：refresh token 走 httpOnly + Secure cookie（M-22 原流程）。
    - 跨站部署（Vercel 前端 ↔ Railway API）：SameSite cookie 不會隨 XHR 送出，
      cookie 路徑天生不可用；body 同時回傳 refresh_token，由前端存 localStorage、
      refresh 時放 body（見 /refresh 的 CSRF 豁免理由）。
    回應 body 因此重新符合 LoginResponse / RefreshResponse 宣告；仍直接回
    JSONResponse 以便同時控制 Set-Cookie。
    """
    refresh_token = result.get("refresh_token")
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
    except jwt.InvalidTokenError:
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

    refresh token 以 httpOnly + Secure cookie 與回應 body 雙路徑下發（跨站部署
    cookie 送不出去，前端存 localStorage 走 body refresh），同時設 double-submit
    用的 CSRF cookie（僅 cookie 路徑需要）。

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

    同站部署 refresh token 來自 cookie、body 可省略；跨站部署（cookie 送不出去）
    則以 body 為唯一管道。因 RefreshRequest.refresh_token 為必填，這裡寬鬆解析
    而非以 FastAPI body 依賴強制要求。
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

    雙路徑（M-22 + 跨站部署後備）：
    - cookie 路徑（同站部署）：refresh token 從 httpOnly cookie 讀取，並要求
      double-submit CSRF（X-CSRF-Token header 與 csrf cookie 相符），否則 403。
    - body 路徑（跨站部署）：cookie 缺漏時改讀 JSON body 的 refresh_token，
      跳過 CSRF 驗證（理由見下方註解）。
    - 換發成功後以 Set-Cookie 旋轉 refresh + CSRF cookie，body 同時回傳新
      refresh_token（雙路徑下發）。rotation + reuse-detection 在
      `AuthService.refresh_token`，兩路徑共用、不放寬。

    Rate limit：每 IP per-IP sliding window（見 settings.REFRESH_IP_*），
    擋對 refresh 端點的暴力 / 濫用；超限拋 RateLimitExceededException（429）。

    F7 #2：完全無憑證（無 cookie 且 body 也無 refresh_token）的請求，快速拒絕要
    放在「消耗 rate limit 額度之前」——否則沒有任何憑證的 garbage 請求也能白白
    洗掉合法使用者的每 IP 額度（等於用零成本的 401 就能把別人擠出 refresh 端點）。
    只要「帶了憑證」（不論最終驗證是否通過），才進入下面的額度消耗，對「有憑證但
    無效」的暴力嘗試維持原本的防暴力語意不變。
    """
    from app.cache.redis_client import get_redis
    from app.core import rate_limit as rl
    from app.core.net import get_client_ip

    cookie_token = request.cookies.get(settings.REFRESH_COOKIE_NAME)
    body = None if cookie_token else await _parse_optional_refresh_request(request)

    if not cookie_token and (body is None or not body.refresh_token):
        # 無 cookie、body 也解不出 refresh_token：視為完全無憑證，直接 401，
        # 不呼叫 enforce_refresh_ip_rate_limit（不消耗額度）。
        raise UnauthorizedException("errors.refresh_token_invalid")

    redis = await get_redis()
    await rl.enforce_refresh_ip_rate_limit(redis, get_client_ip(request))

    if cookie_token:
        # cookie 路徑：refresh token 由瀏覽器自動附帶，具 CSRF 攻擊面 →
        # 必須驗 double-submit，維持 M-22 原防護，不放寬。
        validate_csrf(request)
        token = cookie_token
    else:
        # body 路徑（跨站部署後備）：token 由前端 JS 自 localStorage 讀出並顯式
        # 放入 JSON body。跨站攻擊者既無法讀取受害者的 localStorage，也無法令
        # 瀏覽器自動附帶它，偽造請求不可能持有有效 refresh token —— 與
        # Authorization: Bearer header 同級的自證憑證，無 CSRF 攻擊面，
        # 故跳過 double-submit 驗證（bearer-style token 的標準做法）。
        token = body.refresh_token if body else None
        if not token:
            # 理論上不會走到（上面的快速拒絕已排除），防禦性保留。
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

    雙路徑（M-22 + 跨站部署後備）：
    - cookie 路徑：refresh token 從 httpOnly cookie 讀取，要求 double-submit CSRF
      （X-CSRF-Token header 與 csrf cookie 相符），否則 403。
    - body 路徑（跨站部署）：cookie 缺漏時改讀 body 的 refresh_token，跳過 CSRF
      驗證（理由同 /refresh）。
    - 一律清除 refresh + CSRF cookie。
    """
    cookie_refresh = request.cookies.get(settings.REFRESH_COOKIE_NAME)
    if cookie_refresh:
        # cookie 路徑才有 CSRF 攻擊面（見 /refresh 說明）；本端點本身已由
        # Bearer access token（get_current_user）授權，無 cookie 時不驗 double-submit。
        validate_csrf(request)

    # get_current_user 已驗證格式，此處直接去掉 "Bearer " 前綴即可
    access_token = authorization[7:] if authorization.startswith("Bearer ") else authorization
    refresh_token = cookie_refresh or payload.refresh_token
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
