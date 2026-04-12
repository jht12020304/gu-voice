"""
資料表分區自動管理
- 自動建立下一個月份的分區（conversations、audit_logs）
- 透過 Celery Beat 每月 25 日凌晨 3 點執行
"""

import logging
from datetime import date, timedelta

from app.tasks import celery_app

logger = logging.getLogger(__name__)

# 需要分區的資料表
PARTITIONED_TABLES = ["conversations", "audit_logs"]


@celery_app.task(
    name="app.tasks.partition_manager.ensure_monthly_partitions",
    bind=True,
    max_retries=2,
    default_retry_delay=60,
    acks_late=True,
)
def ensure_monthly_partitions(self) -> dict:
    """
    確保下個月份的分區存在（Celery 定期任務）

    Returns:
        建立結果統計
    """
    import asyncio

    try:
        result = asyncio.get_event_loop().run_until_complete(_async_ensure())
        return result
    except Exception:
        result = asyncio.run(_async_ensure())
        return result


async def _async_ensure() -> dict:
    """非同步分區建立核心邏輯"""
    from sqlalchemy import text

    from app.core.database import async_session_factory

    today = date.today()

    # 計算下個月的起迄日期
    if today.month == 12:
        next_month_start = date(today.year + 1, 1, 1)
        next_month_end = date(today.year + 1, 2, 1)
    else:
        next_month_start = date(today.year, today.month + 1, 1)
        if today.month + 1 == 12:
            next_month_end = date(today.year + 1, 1, 1)
        else:
            next_month_end = date(today.year, today.month + 2, 1)

    partition_suffix = next_month_start.strftime("%Y_%m")
    created: list[str] = []
    skipped: list[str] = []

    async with async_session_factory() as db:
        for table_name in PARTITIONED_TABLES:
            partition_name = f"{table_name}_{partition_suffix}"

            # 檢查分區是否已存在
            check_sql = text(
                "SELECT 1 FROM pg_class WHERE relname = :partition_name"
            )
            result = await db.execute(check_sql, {"partition_name": partition_name})
            exists = result.scalar_one_or_none()

            if exists:
                logger.info("分區 %s 已存在，跳過", partition_name)
                skipped.append(partition_name)
                continue

            # 建立分區
            create_sql = text(
                f"CREATE TABLE IF NOT EXISTS {partition_name} "
                f"PARTITION OF {table_name} "
                f"FOR VALUES FROM ('{next_month_start.isoformat()}') "
                f"TO ('{next_month_end.isoformat()}')"
            )

            try:
                await db.execute(create_sql)
                await db.commit()
                logger.info("成功建立分區: %s", partition_name)
                created.append(partition_name)
            except Exception as exc:
                logger.error("建立分區 %s 失敗: %s", partition_name, exc)
                await db.rollback()

    return {
        "created": created,
        "skipped": skipped,
        "next_month": partition_suffix,
    }
