"""
WebSocket 認證 handshake。

設計：
- `authenticate_websocket(ws)` 先 `accept()`，然後：
    1. 若 query param `?token=` 有值 → 立刻驗證（舊行為兼容，會列警告 log）
    2. 否則等第一則 JSON 訊息，schema: `{"type": "auth", "token": "<jwt>"}`
       超過 `HANDSHAKE_TIMEOUT_SECONDS` 未收到即視為失敗
- 失敗統一 `close(code=4001, reason=...)` 並回傳 None；成功回傳 JWT payload dict
- 已 accept 的 WebSocket，後續 manager.connect_* 必須傳 `already_accepted=True`

擇日完全淘汰 query-param 模式時：只需把步驟 1 刪掉、檢查 log 數量歸零即可。
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import WebSocket
from jose import JWTError

from app.core.security import verify_access_token

logger = logging.getLogger(__name__)


HANDSHAKE_TIMEOUT_SECONDS = 5.0
_AUTH_MESSAGE_TYPES = ("auth", "authenticate")


async def authenticate_websocket(
    websocket: WebSocket,
    context: str = "ws",
) -> dict[str, Any] | None:
    """
    對 WebSocket 進行認證。

    Returns:
        成功：JWT payload（`verify_access_token` 回傳的 dict）
        失敗：None；呼叫端 **不可** 再對 websocket 做任何事（已被 close）
    """
    await websocket.accept()

    # ── 舊行為兼容：?token= ──────────────────────────────
    legacy_token = websocket.query_params.get("token")
    if legacy_token:
        logger.warning(
            "%s 使用 legacy query-param token（將於未來版本移除，請改用 auth handshake message）",
            context,
        )
        return await _verify_and_close_on_fail(websocket, legacy_token, context)

    # ── Handshake 訊息模式 ───────────────────────────────
    try:
        raw = await asyncio.wait_for(
            websocket.receive_text(),
            timeout=HANDSHAKE_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.warning("%s 等候 auth handshake 超時（%ss）", context, HANDSHAKE_TIMEOUT_SECONDS)
        await websocket.close(code=4001, reason="未在時限內送出認證訊息")
        return None
    except Exception as exc:
        logger.warning("%s handshake receive 失敗：%s", context, str(exc))
        await websocket.close(code=4001, reason="handshake 讀取失敗")
        return None

    try:
        message = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        await websocket.close(code=4001, reason="handshake 訊息非合法 JSON")
        return None

    if not isinstance(message, dict):
        await websocket.close(code=4001, reason="handshake 訊息格式錯誤")
        return None

    msg_type = message.get("type")
    if msg_type not in _AUTH_MESSAGE_TYPES:
        await websocket.close(
            code=4001,
            reason=f"期待 type=auth，收到 type={msg_type}",
        )
        return None

    token = message.get("token")
    if not isinstance(token, str) or not token:
        await websocket.close(code=4001, reason="缺少 token 欄位")
        return None

    return await _verify_and_close_on_fail(websocket, token, context)


async def _verify_and_close_on_fail(
    websocket: WebSocket,
    token: str,
    context: str,
) -> dict[str, Any] | None:
    try:
        payload = verify_access_token(token)
    except JWTError as exc:
        logger.warning("%s Token 驗證失敗：%s", context, str(exc))
        await websocket.close(code=4001, reason="Token 無效或已過期")
        return None
    return payload
