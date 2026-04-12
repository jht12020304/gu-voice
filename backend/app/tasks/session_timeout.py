"""
場次超時檢查定期任務
- 將超過指定時間仍為 in_progress 的場次標記為 cancelled
- 預設超時時間為 60 分鐘
"""

import logging

from app.tasks import celery_app

logger = logging.getLogger(__name__)

# 場次超時閾值（分鐘）
SESSION_TIMEOUT_MINUTES = 60


@celery_app.task(
    name="app.tasks.session_timeout.check_session_timeouts",
    bind=True,
    max_retries=1,
    acks_late=True,
)
def check_session_timeouts(self) -> dict:
    """
    檢查並處理超時場次（Celery 定期任務）

    Returns:
        處理結果統計
    """
    import asyncio

    try:
        result = asyncio.get_event_loop().run_until_complete(_async_check())
        return result
    except Exception:
        result = asyncio.run(_async_check())
        return result


async def _async_check() -> dict:
    """非同步超時檢查核心邏輯"""
    from datetime import timedelta

    from sqlalchemy import select, update

    from app.core.database import async_session_factory
    from app.models.enums import SessionStatus
    from app.models.session import Session
    from app.utils.datetime_utils import utc_now

    timeout_threshold = utc_now() - timedelta(minutes=SESSION_TIMEOUT_MINUTES)

    async with async_session_factory() as db:
        # 查詢超時的 in_progress 場次
        result = await db.execute(
            select(Session)
            .where(Session.status == SessionStatus.IN_PROGRESS)
            .where(Session.updated_at < timeout_threshold)
        )
        stale_sessions = result.scalars().all()

        if not stale_sessions:
            logger.info("無超時場次需要處理")
            return {"timed_out": 0}

        timed_out_ids = []
        now = utc_now()

        for session in stale_sessions:
            session.status = SessionStatus.CANCELLED
            session.completed_at = now
            session.updated_at = now
            timed_out_ids.append(str(session.id))
            logger.info(
                "場次 %s 已超時（上次更新: %s），標記為 cancelled",
                session.id,
                session.updated_at,
            )

        await db.commit()

        logger.info("共處理 %d 個超時場次", len(timed_out_ids))
        return {
            "timed_out": len(timed_out_ids),
            "session_ids": timed_out_ids,
        }
