"""
Redis 非同步連線客戶端
- 使用 redis.asyncio 建立連線
"""

from typing import Optional

import redis.asyncio as aioredis

from app.core.config import settings

# ── 全域連線池 ────────────────────────────────────────────
_redis_pool: Optional[aioredis.Redis] = None


async def init_redis() -> aioredis.Redis:
    """初始化 Redis 連線池（cache DB，P3 #29）"""
    global _redis_pool
    _redis_pool = aioredis.from_url(
        settings.REDIS_URL_CACHE,
        encoding="utf-8",
        decode_responses=True,
        max_connections=20,
    )
    return _redis_pool


async def close_redis() -> None:
    """關閉 Redis 連線池（應用程式關閉時呼叫）"""
    global _redis_pool
    if _redis_pool:
        await _redis_pool.close()
        _redis_pool = None


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
