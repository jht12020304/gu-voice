"""
CSRF 防護 — double-submit cookie 模式（M-22）

設計
----
refresh token 改放 httpOnly cookie 後，瀏覽器會在跨站請求自動帶上該 cookie，
單純依賴 cookie 的端點（/auth/refresh、/auth/logout）因此暴露於 CSRF。

採 double-submit cookie：
  1. 登入 / refresh 成功時，除了 httpOnly 的 refresh cookie，另設一個「非 httpOnly」的
     CSRF token cookie（前端 JS 可讀）。
  2. 前端對需要保護的端點，把 CSRF cookie 值回填到 `X-CSRF-Token` header。
  3. 後端比對 header 與 cookie 是否相符（常數時間比對）。攻擊者無法跨站讀取受害者
     cookie，故無法在偽造請求中放上正確 header → 不符即拒絕。

只在「依賴 cookie 認證」的狀態變更端點要求 CSRF；login 本身不需要（尚未有 session
cookie，且以帳密驗證）。
"""

from __future__ import annotations

import secrets

from fastapi import Request, Response

from app.core.config import settings
from app.core.exceptions import ForbiddenException


def generate_csrf_token() -> str:
    """產生密碼學安全的隨機 CSRF token。"""
    return secrets.token_urlsafe(32)


def set_csrf_cookie(response: Response, token: str) -> None:
    """設定非 httpOnly 的 CSRF cookie（前端 JS 需可讀以回填 header）。

    與 refresh cookie 共用 Secure / SameSite 設定，但 path 放寬到根目錄，
    讓前端在任何頁面都能讀到並回填 header。
    """
    response.set_cookie(
        key=settings.CSRF_COOKIE_NAME,
        value=token,
        httponly=False,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        path="/",
    )


def clear_csrf_cookie(response: Response) -> None:
    """清除 CSRF cookie（登出時呼叫）。"""
    response.delete_cookie(
        key=settings.CSRF_COOKIE_NAME,
        path="/",
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
    )


def validate_csrf(request: Request) -> None:
    """double-submit 比對：要求 header 與 cookie 同時存在且相符。

    任何缺漏 / 不符一律拋 ForbiddenException（403），訊息走既有 i18n key。
    使用 `secrets.compare_digest` 做常數時間比對，避免 timing side-channel。
    """
    cookie_token = request.cookies.get(settings.CSRF_COOKIE_NAME)
    header_token = request.headers.get(settings.CSRF_HEADER_NAME)

    if not cookie_token or not header_token:
        raise ForbiddenException("errors.forbidden")
    if not secrets.compare_digest(cookie_token, header_token):
        raise ForbiddenException("errors.forbidden")
