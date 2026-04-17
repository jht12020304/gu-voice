"""
audit_logs 分區保留管理。

- 每月 1 日凌晨 04:00 跑 `cleanup_old_audit_partitions`
  （避開 partition_manager.ensure_monthly_partitions 的 25 日 03:00）
- 掃 `audit_logs_YYYY_MM` 分區；解析後綴；> `RETENTION_YEARS` 年以前的：
    1. `ALTER TABLE audit_logs DETACH PARTITION ...`
    2. `DROP TABLE ...`
  兩步走以符合 HIPAA/GDPR 等合規的「硬刪除且可稽核」要求。
- 只處理名稱精準符合 `audit_logs_YYYY_MM` 的分區，不動母表、不動今年的任何分區。

設計權衡：
- 為什麼不用 `DROP PARTITION`？Postgres 直接 DROP 子分區會 cascade；先 DETACH 讓母表在任何瞬間都不受影響、
  刪除操作可分兩階段（排程 + 手動覆核）。這裡自動化連刪是為了維運成本；若公司政策要求人工核可，
  只要把 drop 步驟拿掉，保留 detach 即可得到「脫分區但保留實體表」的 grace period。
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from app.tasks import celery_app

logger = logging.getLogger(__name__)

# 7 年 — 符合醫療稽核常見保留期
RETENTION_YEARS = 7
_PARTITION_PREFIX = "audit_logs_"


@celery_app.task(
    name="app.tasks.audit_retention.cleanup_old_audit_partitions",
    bind=True,
    max_retries=2,
    default_retry_delay=120,
    acks_late=True,
)
def cleanup_old_audit_partitions(self) -> dict[str, Any]:
    """掃描並清掉 > `RETENTION_YEARS` 年的 audit_logs 分區。"""
    import asyncio

    try:
        return asyncio.get_event_loop().run_until_complete(_async_cleanup())
    except Exception:
        return asyncio.run(_async_cleanup())


async def _async_cleanup() -> dict[str, Any]:
    from sqlalchemy import text

    from app.core.database import async_session_factory

    cutoff = _cutoff_yyyymm(date.today())
    logger.info("audit_logs retention cleanup started | cutoff=%s", cutoff)

    detached: list[str] = []
    dropped: list[str] = []
    skipped: list[str] = []
    errors: list[dict[str, str]] = []

    async with async_session_factory() as db:
        # 枚舉所有 audit_logs_YYYY_MM 子分區
        result = await db.execute(
            text(
                """
                SELECT child.relname AS name
                FROM pg_inherits
                JOIN pg_class parent ON parent.oid = pg_inherits.inhparent
                JOIN pg_class child  ON child.oid  = pg_inherits.inhrelid
                WHERE parent.relname = 'audit_logs'
                  AND child.relname LIKE 'audit_logs\\_%' ESCAPE '\\'
                """
            )
        )
        all_partitions = [row[0] for row in result.fetchall()]

    for name in all_partitions:
        suffix_yyyymm = _parse_suffix(name)
        if suffix_yyyymm is None:
            skipped.append(name)
            continue
        if suffix_yyyymm >= cutoff:
            skipped.append(name)
            continue

        # 真的要刪：DETACH → DROP
        try:
            async with async_session_factory() as db:
                await db.execute(
                    text(f"ALTER TABLE audit_logs DETACH PARTITION {name}")
                )
                await db.commit()
            detached.append(name)
        except Exception as exc:
            logger.exception("detach partition failed | partition=%s", name)
            errors.append({"partition": name, "stage": "detach", "error": str(exc)})
            continue

        try:
            async with async_session_factory() as db:
                await db.execute(text(f"DROP TABLE IF EXISTS {name}"))
                await db.commit()
            dropped.append(name)
            logger.info("audit_logs partition dropped | partition=%s", name)
        except Exception as exc:
            logger.exception("drop partition failed | partition=%s", name)
            errors.append({"partition": name, "stage": "drop", "error": str(exc)})

    result_summary = {
        "cutoff_yyyymm": cutoff,
        "retention_years": RETENTION_YEARS,
        "detached": detached,
        "dropped": dropped,
        "skipped_count": len(skipped),
        "errors": errors,
    }
    logger.info(
        "audit_logs retention cleanup done | detached=%d dropped=%d skipped=%d errors=%d",
        len(detached), len(dropped), len(skipped), len(errors),
    )
    return result_summary


def _cutoff_yyyymm(today: date) -> int:
    """
    回傳邊界 YYYYMM：小於此值的分區要刪。

    例：2026-04 且 RETENTION_YEARS=7 → cutoff 2019-04 → 201904
    分區 201903 ← 刪；201904 ← 保留（剛好滿 7 年）
    """
    return (today.year - RETENTION_YEARS) * 100 + today.month


def _parse_suffix(partition_name: str) -> int | None:
    """
    從 `audit_logs_2019_03` 解出 201903；不符合格式回 None。
    """
    if not partition_name.startswith(_PARTITION_PREFIX):
        return None
    suffix = partition_name[len(_PARTITION_PREFIX):]
    parts = suffix.split("_")
    if len(parts) != 2:
        return None
    try:
        year = int(parts[0])
        month = int(parts[1])
    except ValueError:
        return None
    if not (2000 <= year <= 2999 and 1 <= month <= 12):
        return None
    return year * 100 + month
