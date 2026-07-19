"""
資料表分區自動管理
- 為 conversations、audit_logs 確保「當月起共 PARTITION_MONTHS_AHEAD 個月」的分區 runway
- 透過 Celery Beat 每月 25 日凌晨 3 點執行；API 啟動時也補跑一次（ensure_partitions_on_startup）
  兜底，beat 掛掉或任務跨月失敗時，任一次部署/重啟即自動補齊

為什麼不用 DEFAULT 分區兜底：
PostgreSQL 在 DEFAULT 分區已累積某月資料後，再 CREATE 該月分區會因資料
與新分區範圍重疊而失敗，得先手動搬移資料才能補建 —— 反而把「缺分區」
變成更難恢復的故障模式。用長 runway + 啟動補跑取代。
"""

import logging
from datetime import date

from app.tasks import celery_app

logger = logging.getLogger(__name__)

# 需要分區的資料表
PARTITIONED_TABLES = ["conversations", "audit_logs"]

# 從當月起要保證存在的分區月數（含當月）。
# beat 每月跑一次 + 每次部署啟動補跑，4 個月 runway 可容忍 beat 連續數月失效。
PARTITION_MONTHS_AHEAD = 4


def _add_months(month_start: date, months: int) -> date:
    """回傳 month_start（某月 1 號）往後 months 個月的 1 號。"""
    total = month_start.year * 12 + (month_start.month - 1) + months
    return date(total // 12, total % 12 + 1, 1)


def _target_month_starts(today: date, count: int = PARTITION_MONTHS_AHEAD) -> list[date]:
    """回傳從 today 所在月份起、共 count 個月的每月 1 號。"""
    first = today.replace(day=1)
    return [_add_months(first, i) for i in range(count)]


@celery_app.task(
    name="app.tasks.partition_manager.ensure_monthly_partitions",
    bind=True,
    max_retries=2,
    default_retry_delay=60,
    acks_late=True,
)
def ensure_monthly_partitions(self) -> dict:
    """
    確保當月起共 PARTITION_MONTHS_AHEAD 個月的分區存在（Celery 定期任務）

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
    """非同步分區建立核心邏輯（冪等，可重複執行）"""
    from sqlalchemy import text

    from app.core.database import async_session_factory

    month_starts = _target_month_starts(date.today())
    created: list[str] = []
    skipped: list[str] = []

    async with async_session_factory() as db:
        for month_start in month_starts:
            month_end = _add_months(month_start, 1)
            partition_suffix = month_start.strftime("%Y_%m")

            for table_name in PARTITIONED_TABLES:
                partition_name = f"{table_name}_{partition_suffix}"

                # 檢查分區是否已存在
                check_sql = text(
                    "SELECT 1 FROM pg_class WHERE relname = :partition_name"
                )
                result = await db.execute(
                    check_sql, {"partition_name": partition_name}
                )
                exists = result.scalar_one_or_none()

                if exists:
                    logger.info("分區 %s 已存在，跳過", partition_name)
                    skipped.append(partition_name)
                    continue

                # 建立分區（IF NOT EXISTS 冪等；uvicorn 多 worker 同時啟動補跑的
                # 競態由下面的 try/except 吸收，單一分區失敗不影響其他分區）
                create_sql = text(
                    f"CREATE TABLE IF NOT EXISTS {partition_name} "
                    f"PARTITION OF {table_name} "
                    f"FOR VALUES FROM ('{month_start.isoformat()}') "
                    f"TO ('{month_end.isoformat()}')"
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
        "months": [m.strftime("%Y_%m") for m in month_starts],
    }


async def ensure_partitions_on_startup() -> None:
    """
    API 啟動時補跑分區建立（兜底 Celery beat 失效）。

    任何失敗只記 log、絕不 raise —— 缺分區只影響新月份的 INSERT，
    不該阻擋整個 app 啟動；beat 排程之後仍會定期重試。
    """
    try:
        result = await _async_ensure()
        logger.info(
            "啟動分區補建完成 | created=%s skipped=%s",
            result["created"],
            result["skipped"],
        )
    except Exception as exc:  # noqa: BLE001 — 兜底失敗不可中斷啟動
        logger.error(
            "啟動時分區補建失敗（非致命，Celery beat 會定期重試）| error=%s", exc
        )
