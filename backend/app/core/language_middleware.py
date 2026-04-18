"""
LanguageMiddleware — 把每個請求的使用語言寫到 `request.state.language`。

解析順序（走 `resolve_language`）：

    1. URL query `?lng=<bcp-47>`（前端 `/:lng/*` SSR 請求時會透傳）
    2. X-Language request header（前端 fetch 客製化 header，最直接可靠）
    3. Accept-Language header（瀏覽器預設）
    4. user.preferred_language（authenticated route — middleware 跑時 state.current_user
       可能還沒填，所以真正 per-user 解析仍在 router 層補）
    5. settings.DEFAULT_LANGUAGE

Middleware 只做 header / query 解析；`user.preferred_language` 的最終 resolve
仍交給 router 層（`get_current_user` 之後才有）。這裡保證：**任何 handler 都
能直接讀 `request.state.language`，不需重新解析**，避免每個 router 重複樣板。

Response 端會寫回 `Content-Language` header，給前端 / CDN / SEO 工具使用。
"""

from __future__ import annotations

import logging
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.utils.language import resolve_language

logger = logging.getLogger(__name__)


class LanguageMiddleware(BaseHTTPMiddleware):
    """把解析後的語言寫到 `request.state.language` + Response Content-Language header。"""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        language = _resolve_from_request(request)
        request.state.language = language

        response = await call_next(request)
        # 讓 CDN / 前端可以依 response header 判斷實際回傳的語言
        response.headers.setdefault("Content-Language", language)
        return response


def _resolve_from_request(request: Request) -> str:
    """讀 query / header 解析語言；user 未知時視為匿名（router 層會再補）。"""
    payload_lang: Optional[str] = request.query_params.get("lng") or request.headers.get(
        "X-Language"
    )
    accept_lang = request.headers.get("accept-language")
    return resolve_language(
        payload_language=payload_lang,
        user=None,
        accept_language_header=accept_lang,
    )


def get_request_language(request: Request) -> str:
    """Router 層 helper：優先讀 middleware 塞的 state.language，
    未設（例如 WebSocket 未經 HTTP middleware）時即時解析一次。"""
    lang = getattr(request.state, "language", None)
    if lang:
        return lang
    return _resolve_from_request(request)
