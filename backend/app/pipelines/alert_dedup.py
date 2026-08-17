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
# 去重狀態存活時間。
#
# 原本＝場次上下文生命週期（3600s / 1 小時），但兩者的失效代價完全不同：
# session context 過期只是「這場問診結束了」，去重狀態過期卻是**默默退化成不去重**
# ——同一 canonical 紅旗會再次寫進 red_flag_alerts、再廣播一次，直接灌水 research
# analytics 的紅旗計數與 dashboard 的未確認警示數（護理站看到重複警示 → 警示疲勞）。
# 一場 kiosk 問診遠短於 1 小時，但場次可能被暫停（病患離開座位、換裝置、系統重連），
# 恢復後同一 session_id 繼續問診就會踩到過期。TTL 拉到 24 小時：涵蓋任何合理的
# 「暫停後續問」情境，而一個活超過 24 小時的問診場次已不具臨床意義。
# 成本可忽略：每 session 一個 hash、欄位數＝該場觸發過的紅旗種類（個位數）。
#
# ⚠️ 這只是「更不容易掉」，不是保證：Redis 抖動 / flush / 被驅逐時 `should_suppress`
# 仍會 fail-open（刻意設計，寧重複不可漏急症，勿改成 fail-close）。真正的最後防線
# 應該是 DB 端 (session_id, canonical_id, severity) 唯一約束——見回報 needsFromOthers
# （需 alembic migration，不在本檔範圍）。
_EMITTED_TTL = 86400


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
