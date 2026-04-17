"""
Redis 非同步連線客戶端
- 使用 redis.asyncio 建立連線
- 自動前綴 gu: 管理 key namespace
- 提供 get / set / delete / exists 輔助方法
"""

from typing import Any, Optional

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


# ── 帶前綴的輔助方法 ──────────────────────────────────────
def _prefixed_key(key: str) -> str:
    """自動加上 gu: 前綴（若 key 尚未包含前綴）"""
    prefix = settings.REDIS_KEY_PREFIX
    if key.startswith(prefix):
        return key
    return f"{prefix}{key}"


async def cache_get(key: str) -> Optional[str]:
    """讀取快取值"""
    r = await get_redis()
    return await r.get(_prefixed_key(key))


async def cache_set(
    key: str,
    value: Any,
    ttl: Optional[int] = None,
) -> bool:
    """
    寫入快取值

    Args:
        key: 快取鍵（不含前綴）
        value: 快取值（字串或可轉換為字串的值）
        ttl: 過期秒數，None 表示不過期
    """
    r = await get_redis()
    if ttl:
        return await r.setex(_prefixed_key(key), ttl, str(value))
    return await r.set(_prefixed_key(key), str(value))


async def cache_delete(key: str) -> int:
    """刪除快取鍵"""
    r = await get_redis()
    return await r.delete(_prefixed_key(key))


async def cache_exists(key: str) -> bool:
    """檢查快取鍵是否存在"""
    r = await get_redis()
    return bool(await r.exists(_prefixed_key(key)))
