"""
Redis 非同步連線客戶端
- 使用 redis.asyncio 建立連線
"""

import asyncio
from typing import Optional

import redis.asyncio as aioredis

from app.core.config import settings

# ── 全域連線池 ────────────────────────────────────────────
_redis_pool: Optional[aioredis.Redis] = None
# 建池時的 event loop：連線一旦在某個 loop 上建立就只能在那個 loop 用。
# Celery 的 run_async 每個 task 開新 loop，所以池只對建它的 loop 有效。
_pool_loop: Optional[asyncio.AbstractEventLoop] = None


async def init_redis() -> aioredis.Redis:
    """初始化 Redis 連線池（cache DB，P3 #29）"""
    global _redis_pool, _pool_loop
    _redis_pool = aioredis.from_url(
        settings.REDIS_URL_CACHE,
        encoding="utf-8",
        decode_responses=True,
        max_connections=20,
    )
    _pool_loop = asyncio.get_running_loop()
    return _redis_pool


async def close_redis() -> None:
    """關閉 Redis 連線池（應用程式關閉時呼叫）"""
    global _redis_pool, _pool_loop
    if _redis_pool:
        await _redis_pool.aclose()
        _redis_pool = None
        _pool_loop = None


def pool_for_current_loop() -> Optional[aioredis.Redis]:
    """若目前 loop 就是建池的 loop，回傳共用池；否則 None（呼叫端自備短命連線）。

    給 `publish_dashboard_event` 這類「API 行程每則事件都要 publish」的路徑用：
    在 API 行程重用池（省掉每則事件 3–4 個 round trip 的 connect/AUTH/QUIT），
    在 Celery（每個 task 新 loop）仍走原本的短命 client，避免跨 loop 共用連線。
    """
    if _redis_pool is None or _pool_loop is None:
        return None
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return None
    return _redis_pool if loop is _pool_loop else None


async def get_redis() -> aioredis.Redis:
    """
    取得 Redis 連線實例（FastAPI 依賴注入用）

    Returns:
        aioredis.Redis: 已連線的 Redis 客戶端
    """
    global _redis_pool
    if _redis_pool is None:
        await init_redis()
    return _redis_pool  # type: ignore[return-value]
