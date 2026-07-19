"""紅旗告警跨輪去重（A5 [D3]）。

原本內嵌在 websocket/conversation_handler.py，只依賴 Redis + alert dict，且由
tests/unit/websocket/test_red_flag_dedup.py 覆蓋。抽到此獨立模組；行為與簽名
一字不變（handler 以 re-import 保持既有引用）。

安全語意：去重「只抑制持久化+廣播」，**絕不影響 abort 判斷用的 alert list**；
任何 Redis 失效 / 身份不明一律 fail-open（寧重複不可漏急症）。
"""

import logging
from typing import Any

from redis.asyncio import Redis

logger = logging.getLogger(__name__)

# 跨輪去重的 Redis hash key 與嚴重度排序（升級判斷用）。
SESSION_EMITTED_RED_FLAGS_KEY = "gu:session:{session_id}:emitted_red_flags"
RED_FLAG_SEVERITY_RANK = {"medium": 0, "high": 1, "critical": 2}
# 去重狀態存活時間＝場次上下文生命週期（1 小時）。
_EMITTED_TTL = 3600


def alert_dedup_identity(alert: dict[str, Any]) -> str | None:
    """A5 [D3] 去重身份：優先 canonical_id（跨語言穩定），fallback lowercase title；
    都沒有回 None（不去重，fail-open）。"""
    cid = alert.get("canonical_id")
    if cid:
        return str(cid)
    title = str(alert.get("title", "")).strip().lower()
    return title or None


async def should_suppress_duplicate_alert(
    redis: Redis, session_id: str, alert: dict[str, Any]
) -> bool:
    """A5 [D3]：跨輪去重判斷（只抑制「持久化+廣播」，絕不影響 abort 判斷用的 list）。

    Redis hash session:{id}:emitted_red_flags 存 canonical_id→severity：
    - 同 canonical_id 且 severity 未升級（同級或降級）→ True（抑制）。
    - 升級（high→critical）→ False（放行，critical 照常觸發 abort）。
    - Redis 失效 / 身份不明 / severity 不明 → False（fail-open：寧重複不可漏急症）。
    """
    identity = alert_dedup_identity(alert)
    if identity is None:
        return False
    new_rank = RED_FLAG_SEVERITY_RANK.get(str(alert.get("severity", "")).lower())
    if new_rank is None:
        return False
    try:
        key = SESSION_EMITTED_RED_FLAGS_KEY.format(session_id=session_id)
        prev = await redis.hget(key, identity)
        if prev is None:
            return False
        if isinstance(prev, (bytes, bytearray)):
            prev = prev.decode("utf-8", errors="replace")
        prev_rank = RED_FLAG_SEVERITY_RANK.get(str(prev).lower())
        if prev_rank is None:
            return False
        return new_rank <= prev_rank
    except Exception as exc:
        logger.warning(
            "紅旗去重查詢失敗，fail-open 照常送出 | session=%s, error=%s",
            session_id,
            str(exc),
        )
        return False


async def record_emitted_alert(
    redis: Redis, session_id: str, alert: dict[str, Any]
) -> None:
    """A5 [D3]：record-on-success — 僅在持久化+廣播成功後呼叫；
    自身吞例外（記錄失敗頂多下一輪重複 emit，不可拋、不可阻斷主流程）。"""
    identity = alert_dedup_identity(alert)
    if identity is None:
        return
    try:
        key = SESSION_EMITTED_RED_FLAGS_KEY.format(session_id=session_id)
        await redis.hset(key, identity, str(alert.get("severity", "")).lower())
        await redis.expire(key, _EMITTED_TTL)
    except Exception as exc:
        logger.warning(
            "紅旗去重記錄失敗（下一輪可能重複 emit，可接受） | session=%s, error=%s",
            session_id,
            str(exc),
        )
