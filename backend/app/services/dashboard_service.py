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
from app.models.patient import Patient
from app.models.red_flag_alert import RedFlagAlert
from app.models.session import Session
from app.models.soap_report import SOAPReport
from app.schemas.dashboard import (
    QueueItemResponse,
    QueueResponse,
    RecentAlertItem,
    RecentAlertsResponse,
    RecentSessionItem,
    RecentSessionsResponse,
)
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
        """
        cache_key = f"gu:dashboard:stats:{doctor_id or 'all'}"

        # 嘗試從 Redis 讀取快取
        try:
            redis = await get_redis()
            cached = await redis.get(cache_key)
            if cached:
                data = json.loads(cached)
                if "timestamp" not in data:
                    data["timestamp"] = utc_now().isoformat()
                return data
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

        # 今日進行中
        in_progress_query = (
            select(func.count())
            .select_from(Session)
            .where(Session.status == SessionStatus.IN_PROGRESS)
        )
        if doctor_id:
            in_progress_query = in_progress_query.where(Session.doctor_id == doctor_id)
        in_progress = (await db.execute(in_progress_query)).scalar() or 0

        # 今日等待中
        waiting_query = (
            select(func.count())
            .select_from(Session)
            .where(Session.status == SessionStatus.WAITING)
        )
        if doctor_id:
            waiting_query = waiting_query.where(Session.doctor_id == doctor_id)
        waiting = (await db.execute(waiting_query)).scalar() or 0

        # 今日紅旗
        red_flags_query = (
            select(func.count())
            .select_from(RedFlagAlert)
            .where(RedFlagAlert.created_at >= today_start)
        )
        if doctor_id:
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
            "in_progress": in_progress,
            "waiting": waiting,
            "timestamp": now.isoformat(),
        }

        # 寫入 Redis 快取
        try:
            redis = await get_redis()
            await redis.setex(cache_key, STATS_CACHE_TTL, json.dumps(stats))
        except Exception:
            logger.warning("Redis 寫入失敗")

        return stats

    @staticmethod
    async def get_queue(db: AsyncSession, **kwargs) -> QueueResponse:
        """
        取得等候佇列（waiting + in_progress 場次，依建立時間排序）
        """
        result = await db.execute(
            select(Session, Patient.name.label("patient_name"))
            .join(Patient, Session.patient_id == Patient.id)
            .where(
                Session.status.in_([
                    SessionStatus.WAITING,
                    SessionStatus.IN_PROGRESS,
                ])
            )
            .order_by(Session.created_at.asc())
        )
        rows = result.all()

        now = utc_now()
        queue_items = []
        for session, patient_name in rows:
            waiting_seconds = None
            if session.status == SessionStatus.WAITING and session.created_at:
                waiting_seconds = int((now - session.created_at).total_seconds())
            queue_items.append(QueueItemResponse(
                session_id=session.id,
                patient_id=session.patient_id,
                patient_name=patient_name or "未知",
                chief_complaint=session.chief_complaint_text or "",
                status=session.status,
                has_red_flag=session.red_flag,
                created_at=session.created_at,
                started_at=session.started_at,
                waiting_seconds=waiting_seconds,
            ))

        total_waiting = sum(1 for item in queue_items if item.status == SessionStatus.WAITING)
        total_in_progress = sum(1 for item in queue_items if item.status == SessionStatus.IN_PROGRESS)

        return QueueResponse(
            total_waiting=total_waiting,
            total_in_progress=total_in_progress,
            queue=queue_items,
        )

    @staticmethod
    async def get_recent_alerts(
        db: AsyncSession,
        doctor_id: Optional[UUID] = None,
        limit: int = 10,
        **kwargs,
    ) -> RecentAlertsResponse:
        """取得近期紅旗警示"""
        query = (
            select(RedFlagAlert, Patient.name.label("patient_name"))
            .join(Session, RedFlagAlert.session_id == Session.id)
            .join(Patient, Session.patient_id == Patient.id)
            .order_by(RedFlagAlert.created_at.desc())
        )
        if doctor_id:
            query = query.where(Session.doctor_id == doctor_id)

        result = await db.execute(query.limit(limit))
        rows = result.all()

        items = [
            RecentAlertItem(
                alert_id=alert.id,
                session_id=alert.session_id,
                patient_name=patient_name or "未知",
                severity=alert.severity.value,
                title=alert.title,
                acknowledged=alert.acknowledged_by is not None,
                created_at=alert.created_at,
            )
            for alert, patient_name in rows
        ]

        return RecentAlertsResponse(data=items)

    @staticmethod
    async def get_recent_sessions(
        db: AsyncSession,
        doctor_id: Optional[UUID] = None,
        limit: int = 10,
        **kwargs,
    ) -> RecentSessionsResponse:
        """取得近期場次"""
        query = (
            select(Session, Patient.name.label("patient_name"))
            .join(Patient, Session.patient_id == Patient.id)
            .order_by(Session.created_at.desc())
        )
        if doctor_id:
            query = query.where(Session.doctor_id == doctor_id)

        result = await db.execute(query.limit(limit))
        rows = result.all()

        items = [
            RecentSessionItem(
                session_id=session.id,
                patient_name=patient_name or "未知",
                chief_complaint=session.chief_complaint_text or "",
                status=session.status,
                red_flag=session.red_flag,
                created_at=session.created_at,
                completed_at=session.completed_at,
            )
            for session, patient_name in rows
        ]

        return RecentSessionsResponse(data=items)
