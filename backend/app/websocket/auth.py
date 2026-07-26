"""
WebSocket 認證 handshake。

設計：
- `authenticate_websocket(ws)` 先 `accept()`，然後：
    1. 若 query param `?token=` 有值 → 立刻驗證（舊行為兼容，會列警告 log）
    2. 否則等第一則 JSON 訊息，schema: `{"type": "auth", "token": "<jwt>"}`
       超過 `HANDSHAKE_TIMEOUT_SECONDS` 未收到即視為失敗
- 失敗統一 `close(code=4001, reason=...)` 並回傳 None；成功回傳 JWT payload dict
- 已 accept 的 WebSocket，後續 manager.connect_* 必須傳 `already_accepted=True`
- 簽章驗過後比照 REST 層 `get_current_user`（app/core/dependencies.py）做身分檢查：
    1. Redis 黑名單（logout 過的 token 拒絕；Redis 掛 → fail-open 放行，與全系統一致）
    2. DB 載入 User，不存在或 `is_active=False` 拒絕（DB 掛 → fail-closed 拒絕）
    3. `payload["role"]` 以 DB 為準覆蓋 token claim（防止降權後舊 token 提權）

擇日完全淘汰 query-param 模式時：只需把步驟 1 刪掉、檢查 log 數量歸零即可。
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any
from uuid import UUID

from fastapi import WebSocket
from jose import JWTError
from sqlalchemy import select

from app.cache.redis_client import get_redis as get_cache_redis
from app.core.database import get_db_session
from app.core.dependencies import BLACKLIST_KEY_PREFIX
from app.core.security import verify_access_token
from app.models.user import User

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
        await _close_with_code(websocket, 4001, "errors.ws.handshake_timeout")
        return None
    except Exception as exc:
        logger.warning("%s handshake receive 失敗：%s", context, str(exc))
        await _close_with_code(websocket, 4001, "errors.ws.handshake_read_failed")
        return None

    try:
        message = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        await _close_with_code(websocket, 4001, "errors.ws.handshake_invalid_json")
        return None

    if not isinstance(message, dict):
        await _close_with_code(websocket, 4001, "errors.ws.handshake_invalid_shape")
        return None

    msg_type = message.get("type")
    if msg_type not in _AUTH_MESSAGE_TYPES:
        await _close_with_code(websocket, 4001, "errors.ws.handshake_wrong_type")
        return None

    token = message.get("token")
    if not isinstance(token, str) or not token:
        await _close_with_code(websocket, 4001, "errors.ws.missing_token")
        return None

    return await _verify_and_close_on_fail(websocket, token, context)


async def _close_with_code(
    websocket: WebSocket, close_code: int, canonical_code: str
) -> None:
    """統一用 canonical code 當作 close frame reason（< 123 bytes，前端 i18n 渲染）。"""
    try:
        await websocket.close(code=close_code, reason=canonical_code)
    except Exception:
        pass


async def _verify_and_close_on_fail(
    websocket: WebSocket,
    token: str,
    context: str,
) -> dict[str, Any] | None:
    try:
        payload = verify_access_token(token)
    except JWTError as exc:
        logger.warning("%s Token 驗證失敗：%s", context, str(exc))
        await _close_with_code(websocket, 4001, "errors.ws.invalid_token")
        return None

    # ── 黑名單檢查（對齊 REST get_current_user；Redis 掛 → fail-open） ──
    jti = payload.get("jti")
    if jti:
        try:
            redis = await get_cache_redis()
            revoked = bool(await redis.exists(f"{BLACKLIST_KEY_PREFIX}{jti}"))
        except Exception as exc:
            logger.warning(
                "%s 黑名單檢查失敗（Redis 不可用），fail-open 放行：%s",
                context,
                str(exc),
            )
            revoked = False
        if revoked:
            logger.warning("%s Token 已撤銷（黑名單命中） | jti=%s", context, jti)
            await _close_with_code(websocket, 4001, "errors.ws.invalid_token")
            return None

    # ── 載入 User，驗證存在與 is_active（DB 掛 → fail-closed） ──
    user_id = payload.get("sub")
    try:
        user_uuid = UUID(str(user_id))
    except (TypeError, ValueError):
        logger.warning("%s Token sub 非合法 UUID | sub=%s", context, user_id)
        await _close_with_code(websocket, 4001, "errors.ws.invalid_token")
        return None

    try:
        async with get_db_session() as db:
            result = await db.execute(select(User).where(User.id == user_uuid))
            user = result.scalar_one_or_none()
    except Exception as exc:
        logger.error(
            "%s 使用者查詢失敗（DB 不可用），fail-closed 拒絕：%s", context, str(exc)
        )
        await _close_with_code(websocket, 1011, "errors.ws.internal_error")
        return None

    if user is None:
        logger.warning("%s Token sub 對應使用者不存在 | sub=%s", context, user_id)
        await _close_with_code(websocket, 4001, "errors.ws.invalid_token")
        return None

    if not user.is_active:
        logger.warning("%s 使用者帳號已停用 | sub=%s", context, user_id)
        await _close_with_code(websocket, 4001, "errors.ws.invalid_token")
        return None

    # 角色以 DB 為準覆蓋 token claim（降權後舊 token 不得沿用舊角色）
    payload["role"] = user.role.value
    return payload
