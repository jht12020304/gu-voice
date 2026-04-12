"""
對話上下文快取管理
- 儲存 / 讀取 LLM 對話歷史（gu:session:{id}:context）
- 儲存 / 讀取場次狀態快照（gu:session:{id}:state）
"""

import json
from typing import Any, Optional

from app.cache.redis_client import get_redis

# ── TTL 常數 ──────────────────────────────────────────────
CONTEXT_TTL = 3600    # 對話上下文 1 小時
STATE_TTL = 1800      # 場次狀態 30 分鐘


# ── 對話上下文 ────────────────────────────────────────────
async def save_context(session_id: str, messages: list[dict[str, Any]]) -> None:
    """
    儲存 LLM 對話歷史至 Redis

    Args:
        session_id: 場次 ID
        messages: LLM message 格式的對話歷史列表
                  [{"role": "...", "content": "..."}, ...]
    """
    r = await get_redis()
    key = f"gu:session:{session_id}:context"
    await r.setex(key, CONTEXT_TTL, json.dumps(messages, ensure_ascii=False))


async def get_context(session_id: str) -> Optional[list[dict[str, Any]]]:
    """
    讀取 LLM 對話歷史

    Returns:
        對話歷史列表，若不存在則回傳 None
    """
    r = await get_redis()
    key = f"gu:session:{session_id}:context"
    raw = await r.get(key)
    if raw is None:
        return None
    return json.loads(raw)


async def clear_context(session_id: str) -> None:
    """清除對話上下文"""
    r = await get_redis()
    key = f"gu:session:{session_id}:context"
    await r.delete(key)


# ── 場次狀態快照 ──────────────────────────────────────────
async def save_session_state(session_id: str, state: dict[str, Any]) -> None:
    """
    儲存場次即時狀態至 Redis

    Args:
        session_id: 場次 ID
        state: 狀態字典（包含 status、current_question、turn_count 等）
    """
    r = await get_redis()
    key = f"gu:session:{session_id}:state"
    await r.setex(key, STATE_TTL, json.dumps(state, ensure_ascii=False))


async def get_session_state(session_id: str) -> Optional[dict[str, Any]]:
    """
    讀取場次即時狀態

    Returns:
        狀態字典，若不存在則回傳 None
    """
    r = await get_redis()
    key = f"gu:session:{session_id}:state"
    raw = await r.get(key)
    if raw is None:
        return None
    return json.loads(raw)
