"""
儀表板服務
- 統計數據（含 Redis 快取）
- 等候佇列
- 近期警示 / 場次
"""

import json
import logging
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.redis_client import get_redis
from app.models.enums import (
    AlertSeverity,
    ReportStatus,
    ReviewStatus,
    SessionStatus,
)
from app.models.red_flag_alert import RedFlagAlert
from app.models.session import Session
from app.models.soap_report import SOAPReport
from app.utils.datetime_utils import utc_now

logger = logging.getLogger(__name__)

# 儀表板統計快取 TTL（秒）
STATS_CACHE_TTL = 300


class DashboardService:
    """儀表板業務邏輯"""

    @staticmethod
    async def get_stats(
        db: AsyncSession,
        doctor_id: Optional[UUID] = None,
        **kwargs,
    ) -> dict[str, Any]:
        """
        取得儀表板統計資料（含 Redis 快取）

        Stats:
            - sessions_today: 今日場次數
            - completed: 已完成場次數
            - red_flags: 今日紅旗警示數
            - pending_reviews: 待審閱報告數

        Args:
            doctor_id: 醫師 ID（篩選）
        """
        cache_key = f"gu:dashboard:stats:{doctor_id or 'all'}"

        # 嘗試從 Redis 讀取快取
        try:
            redis = await get_redis()
            cached = await redis.get(cache_key)
            if cached:
                return json.loads(cached)
        except Exception:
            logger.warning("Redis 讀取失敗，直接查詢資料庫")

        # 計算今日範圍（UTC）
        now = utc_now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        # 今日場次數
        sessions_query = (
            select(func.count())
            .select_from(Session)
            .where(Session.created_at >= today_start)
        )
        if doctor_id:
            sessions_query = sessions_query.where(Session.doctor_id == doctor_id)
        sessions_today = (await db.execute(sessions_query)).scalar() or 0

        # 今日已完成
        completed_query = (
            select(func.count())
            .select_from(Session)
            .where(Session.created_at >= today_start)
            .where(Session.status == SessionStatus.COMPLETED)
        )
        if doctor_id:
            completed_query = completed_query.where(Session.doctor_id == doctor_id)
        completed = (await db.execute(completed_query)).scalar() or 0

        # 今日紅旗
        red_flags_query = (
            select(func.count())
            .select_from(RedFlagAlert)
            .where(RedFlagAlert.created_at >= today_start)
        )
        if doctor_id:
            # 透過 session 關聯篩選醫師
            red_flags_query = red_flags_query.where(
                RedFlagAlert.session_id.in_(
                    select(Session.id).where(Session.doctor_id == doctor_id)
                )
            )
        red_flags = (await db.execute(red_flags_query)).scalar() or 0

        # 待審閱報告
        pending_query = (
            select(func.count())
            .select_from(SOAPReport)
            .where(SOAPReport.review_status == ReviewStatus.PENDING)
            .where(SOAPReport.status == ReportStatus.GENERATED)
        )
        pending_reviews = (await db.execute(pending_query)).scalar() or 0

        stats = {
            "sessions_today": sessions_today,
            "completed": completed,
            "red_flags": red_flags,
            "pending_reviews": pending_reviews,
        }

        # 寫入 Redis 快取
        try:
            redis = await get_redis()
            await redis.setex(
                cache_key,
                STATS_CACHE_TTL,
                json.dumps(stats),
            )
        except Exception:
            logger.warning("Redis 寫入失敗")

        return stats

    @staticmethod
    async def get_queue(db: AsyncSession, **kwargs) -> list[Session]:
        """
        取得等候佇列（waiting + in_progress 場次，依建立時間排序）

        Returns:
            場次列表
        """
        result = await db.execute(
            select(Session)
            .where(
                Session.status.in_([
                    SessionStatus.WAITING,
                    SessionStatus.IN_PROGRESS,
                ])
            )
            .order_by(Session.created_at.asc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_recent_alerts(
        db: AsyncSession,
        doctor_id: Optional[UUID] = None,
        limit: int = 10,
        **kwargs,
    ) -> list[RedFlagAlert]:
        """
        取得近期紅旗警示

        Args:
            doctor_id: 篩選醫師
            limit: 回傳筆數
        """
        query = select(RedFlagAlert).order_by(RedFlagAlert.created_at.desc())

        if doctor_id:
            query = query.where(
                RedFlagAlert.session_id.in_(
                    select(Session.id).where(Session.doctor_id == doctor_id)
                )
            )

        result = await db.execute(query.limit(limit))
        return list(result.scalars().all())

    @staticmethod
    async def get_recent_sessions(
        db: AsyncSession,
        doctor_id: Optional[UUID] = None,
        limit: int = 10,
        **kwargs,
    ) -> list[Session]:
        """
        取得近期場次

        Args:
            doctor_id: 篩選醫師
            limit: 回傳筆數
        """
        query = select(Session).order_by(Session.created_at.desc())

        if doctor_id:
            query = query.where(Session.doctor_id == doctor_id)

        result = await db.execute(query.limit(limit))
        return list(result.scalars().all())
