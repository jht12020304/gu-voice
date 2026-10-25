"""DB／Redis 健康探針：/healthz/deep（main.py）與 /admin/system/health 共用。

兩邊以前各寫一份（同樣 2 s 逾時、SELECT 1／PING、"fail: …" 協定），Railway healthcheck
與管理頁健康狀態會各自漂移；現在只有這一份。
"""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

PROBE_TIMEOUT_SECONDS = 2.0


async def probe_db(db: AsyncSession) -> str:
    """對 DB 跑 SELECT 1；成功回 "ok"，失敗回 "fail: <err>"。"""
    try:
        async def _run() -> None:
            await db.execute(text("SELECT 1"))

        await asyncio.wait_for(_run(), timeout=PROBE_TIMEOUT_SECONDS)
        return "ok"
    except asyncio.TimeoutError:
        return f"fail: timeout >{PROBE_TIMEOUT_SECONDS}s"
    except Exception as exc:  # noqa: BLE001 — 要回報給呼叫端
        return f"fail: {exc}"


async def probe_redis(redis: Any) -> str:
    """對 Redis 跑 PING；成功回 "ok"，失敗回 "fail: <err>"。"""
    try:
        await asyncio.wait_for(redis.ping(), timeout=PROBE_TIMEOUT_SECONDS)
        return "ok"
    except asyncio.TimeoutError:
        return f"fail: timeout >{PROBE_TIMEOUT_SECONDS}s"
    except Exception as exc:  # noqa: BLE001
        return f"fail: {exc}"
