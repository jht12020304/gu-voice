"""
儀表板服務
- 統計數據（含 Redis 快取）
- 等候佇列
- 近期警示 / 場次
"""

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
import json
import logging
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.redis_client import get_redis
from app.core.exceptions import ValidationException
from app.models.chief_complaint import ChiefComplaint
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
    DailyTrendItem,
    MonthlySummaryResponse,
    QueueItemResponse,
    QueueResponse,
    RecentAlertItem,
    RecentAlertsResponse,
    RecentSessionItem,
    RecentSessionsResponse,
    SummaryBucketItem,
)
from app.utils.datetime_utils import utc_now

logger = logging.getLogger(__name__)

# 儀表板統計快取 TTL（秒）
STATS_CACHE_TTL = 300

STATUS_LABELS = {
    SessionStatus.WAITING.value: "等待中",
    SessionStatus.IN_PROGRESS.value: "對話中",
    SessionStatus.COMPLETED.value: "已完成",
    SessionStatus.ABORTED_RED_FLAG.value: "紅旗中止",
    SessionStatus.CANCELLED.value: "已取消",
}

ALERT_SEVERITY_LABELS = {
    AlertSeverity.CRITICAL.value: "危急",
    AlertSeverity.HIGH.value: "高度",
    AlertSeverity.MEDIUM.value: "中度",
}


def _resolve_doctor_scope(current_user: Any, doctor_id: Optional[UUID]) -> Optional[UUID]:
    """醫師角色只能看自己的資料；管理員可查看全部或指定醫師。"""
    role = getattr(getattr(current_user, "role", None), "value", None)
    if role == "doctor":
        return getattr(current_user, "id", None)
    return doctor_id


def _parse_day_range(date_value: Optional[str]) -> tuple[datetime, datetime]:
    """解析 YYYY-MM-DD，回傳 UTC 當日區間。"""
    now = utc_now()
    if not date_value:
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return day_start, day_start + timedelta(days=1)

    try:
        target = datetime.strptime(date_value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise ValidationException("errors.dashboard_date_format") from exc

    day_start = target.replace(hour=0, minute=0, second=0, microsecond=0)
    return day_start, day_start + timedelta(days=1)


def _parse_month_range(month_value: Optional[str]) -> tuple[datetime, datetime, str, str]:
    """解析 YYYY-MM，回傳 UTC 月份區間與標籤。"""
    now = utc_now()
    if month_value:
        try:
            month_start = datetime.strptime(month_value, "%Y-%m").replace(tzinfo=timezone.utc)
        except ValueError as exc:
            raise ValidationException("errors.dashboard_month_format") from exc
    else:
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    month_start = month_start.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if month_start.month == 12:
        month_end = month_start.replace(year=month_start.year + 1, month=1)
    else:
        month_end = month_start.replace(month=month_start.month + 1)

    return (
        month_start,
        month_end,
        month_start.strftime("%Y-%m"),
        f"{month_start.year} 年 {month_start.month} 月",
    )


# 佇列預設只顯示「等待中 + 進行中」場次
DEFAULT_QUEUE_STATUSES: tuple[SessionStatus, ...] = (
    SessionStatus.WAITING,
    SessionStatus.IN_PROGRESS,
)


def _parse_queue_status(status_value: Optional[str]) -> list[SessionStatus]:
    """解析逗號分隔的 status 字串為 SessionStatus 清單。

    - 空字串 / None → 預設（waiting + in_progress）。
    - 去除空白、忽略重複；保留出現順序。
    - 任一值非合法 SessionStatus → ValidationException。
    """
    if not status_value or not status_value.strip():
        return list(DEFAULT_QUEUE_STATUSES)

    parsed: list[SessionStatus] = []
    for raw in status_value.split(","):
        token = raw.strip()
        if not token:
            continue
        try:
            member = SessionStatus(token)
        except ValueError as exc:
            raise ValidationException(
                "errors.invalid_status",
                details={
                    "field": "status",
                    "value": token,
                    "allowed": [s.value for s in SessionStatus],
                },
            ) from exc
        if member not in parsed:
            parsed.append(member)

    return parsed or list(DEFAULT_QUEUE_STATUSES)


def _parse_alert_severity(severity_value: Optional[str]) -> Optional[AlertSeverity]:
    """驗證 severity 查詢參數並轉為 AlertSeverity。

    - 空字串 / None → None（不篩選）。
    - 非合法 AlertSeverity → ValidationException。
    """
    if severity_value is None:
        return None
    token = severity_value.strip()
    if not token:
        return None
    try:
        return AlertSeverity(token)
    except ValueError as exc:
        raise ValidationException(
            "errors.invalid_severity",
            details={
                "field": "severity",
                "value": token,
                "allowed": [s.value for s in AlertSeverity],
            },
        ) from exc


class DashboardService:
    """儀表板業務邏輯"""

    @staticmethod
    async def get_stats(
        db: AsyncSession,
        current_user: Any = None,
        doctor_id: Optional[UUID] = None,
        date: Optional[str] = None,
        **kwargs,
    ) -> dict[str, Any]:
        """
        取得儀表板統計資料（含 Redis 快取）
        """
        effective_doctor_id = _resolve_doctor_scope(current_user, doctor_id)
        day_start, day_end = _parse_day_range(date)
        cache_key = f"gu:dashboard:stats:{effective_doctor_id or 'all'}:{day_start.date().isoformat()}"

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

        now = utc_now()

        # 今日場次數
        sessions_query = (
            select(func.count())
            .select_from(Session)
            .where(Session.created_at >= day_start)
            .where(Session.created_at < day_end)
        )
        if effective_doctor_id:
            sessions_query = sessions_query.where(Session.doctor_id == effective_doctor_id)
        sessions_today = (await db.execute(sessions_query)).scalar() or 0

        # 今日已完成
        completed_query = (
            select(func.count())
            .select_from(Session)
            .where(Session.created_at >= day_start)
            .where(Session.created_at < day_end)
            .where(Session.status == SessionStatus.COMPLETED)
        )
        if effective_doctor_id:
            completed_query = completed_query.where(Session.doctor_id == effective_doctor_id)
        completed = (await db.execute(completed_query)).scalar() or 0

        # 進行中（即時狀態快照，刻意不受 date 區間限制，反映當下佇列）
        in_progress_query = (
            select(func.count())
            .select_from(Session)
            .where(Session.status == SessionStatus.IN_PROGRESS)
        )
        if effective_doctor_id:
            in_progress_query = in_progress_query.where(Session.doctor_id == effective_doctor_id)
        in_progress = (await db.execute(in_progress_query)).scalar() or 0

        # 等待中（即時狀態快照，刻意不受 date 區間限制，反映當下佇列）
        waiting_query = (
            select(func.count())
            .select_from(Session)
            .where(Session.status == SessionStatus.WAITING)
        )
        if effective_doctor_id:
            waiting_query = waiting_query.where(Session.doctor_id == effective_doctor_id)
        waiting = (await db.execute(waiting_query)).scalar() or 0

        # 今日紅旗
        red_flags_query = (
            select(func.count())
            .select_from(RedFlagAlert)
            .where(RedFlagAlert.created_at >= day_start)
            .where(RedFlagAlert.created_at < day_end)
        )
        if effective_doctor_id:
            red_flags_query = red_flags_query.where(
                RedFlagAlert.session_id.in_(
                    select(Session.id).where(Session.doctor_id == effective_doctor_id)
                )
            )
        red_flags = (await db.execute(red_flags_query)).scalar() or 0

        # 待審閱報告
        pending_query = (
            select(func.count())
            .select_from(SOAPReport)
            .join(Session, SOAPReport.session_id == Session.id)
            .where(SOAPReport.review_status == ReviewStatus.PENDING)
            .where(SOAPReport.status == ReportStatus.GENERATED)
        )
        if effective_doctor_id:
            pending_query = pending_query.where(Session.doctor_id == effective_doctor_id)
        pending_reviews = (await db.execute(pending_query)).scalar() or 0

        # 平均場次時長（秒）：當日「已完成」場次的 ended/started 差
        # 優先用 completed_at − started_at；缺值時退回 duration_seconds。
        duration_expr = func.coalesce(
            func.extract("epoch", Session.completed_at - Session.started_at),
            Session.duration_seconds,
        )
        duration_query = (
            select(func.avg(duration_expr))
            .select_from(Session)
            .where(Session.created_at >= day_start)
            .where(Session.created_at < day_end)
            .where(Session.status == SessionStatus.COMPLETED)
            .where(duration_expr.isnot(None))
        )
        if effective_doctor_id:
            duration_query = duration_query.where(Session.doctor_id == effective_doctor_id)
        avg_duration_raw = (await db.execute(duration_query)).scalar()
        average_duration_seconds = (
            round(float(avg_duration_raw), 1) if avg_duration_raw is not None else None
        )

        stats = {
            "sessions_today": sessions_today,
            "completed": completed,
            "red_flags": red_flags,
            "pending_reviews": pending_reviews,
            "in_progress": in_progress,
            "waiting": waiting,
            "average_duration_seconds": average_duration_seconds,
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
    async def get_queue(
        db: AsyncSession,
        current_user: Any = None,
        doctor_id: Optional[UUID] = None,
        status: Optional[str] = None,
        **kwargs,
    ) -> QueueResponse:
        """
        取得等候佇列（依建立時間排序）

        status：逗號分隔的場次狀態（如 "waiting,in_progress"），用於篩選佇列。
        未提供時預設為 waiting + in_progress。含無效狀態值時擲出 ValidationException。
        """
        effective_doctor_id = _resolve_doctor_scope(current_user, doctor_id)
        status_filters = _parse_queue_status(status)
        query = (
            select(Session, Patient.name.label("patient_name"))
            .join(Patient, Session.patient_id == Patient.id)
            .where(Session.status.in_(status_filters))
            .order_by(Session.created_at.asc())
        )
        if effective_doctor_id:
            query = query.where(Session.doctor_id == effective_doctor_id)

        result = await db.execute(query)
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
                patient_name=patient_name or "",
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
        current_user: Any = None,
        doctor_id: Optional[UUID] = None,
        severity: Optional[str] = None,
        limit: int = 10,
        **kwargs,
    ) -> RecentAlertsResponse:
        """取得近期「未確認」紅旗警示（acknowledged_by 為 NULL）"""
        effective_doctor_id = _resolve_doctor_scope(current_user, doctor_id)
        severity_filter = _parse_alert_severity(severity)
        query = (
            select(RedFlagAlert, Patient.name.label("patient_name"))
            .join(Session, RedFlagAlert.session_id == Session.id)
            .join(Patient, Session.patient_id == Patient.id)
            # 只回未確認警示，與「近期未確認警示」語意一致
            .where(RedFlagAlert.acknowledged_by.is_(None))
            .order_by(RedFlagAlert.created_at.desc())
        )
        if effective_doctor_id:
            query = query.where(Session.doctor_id == effective_doctor_id)
        if severity_filter is not None:
            query = query.where(RedFlagAlert.severity == severity_filter)

        result = await db.execute(query.limit(limit))
        rows = result.all()

        items = [
            RecentAlertItem(
                alert_id=alert.id,
                session_id=alert.session_id,
                patient_name=patient_name or "",
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
        current_user: Any = None,
        doctor_id: Optional[UUID] = None,
        limit: int = 10,
        **kwargs,
    ) -> RecentSessionsResponse:
        """取得近期場次"""
        effective_doctor_id = _resolve_doctor_scope(current_user, doctor_id)
        query = (
            select(Session, Patient.name.label("patient_name"))
            .join(Patient, Session.patient_id == Patient.id)
            .order_by(Session.created_at.desc())
        )
        if effective_doctor_id:
            query = query.where(Session.doctor_id == effective_doctor_id)

        result = await db.execute(query.limit(limit))
        rows = result.all()

        items = [
            RecentSessionItem(
                session_id=session.id,
                patient_name=patient_name or "",
                chief_complaint=session.chief_complaint_text or "",
                status=session.status,
                red_flag=session.red_flag,
                created_at=session.created_at,
                completed_at=session.completed_at,
            )
            for session, patient_name in rows
        ]

        return RecentSessionsResponse(data=items)

    @staticmethod
    async def get_monthly_summary(
        db: AsyncSession,
        current_user: Any = None,
        doctor_id: Optional[UUID] = None,
        month: Optional[str] = None,
        **kwargs,
    ) -> MonthlySummaryResponse:
        """取得指定月份的問診摘要與圖表資料。"""
        effective_doctor_id = _resolve_doctor_scope(current_user, doctor_id)
        month_start, month_end, month_key, month_label = _parse_month_range(month)

        session_query = (
            select(Session, ChiefComplaint.category)
            .join(ChiefComplaint, Session.chief_complaint_id == ChiefComplaint.id, isouter=True)
            .where(Session.created_at >= month_start)
            .where(Session.created_at < month_end)
            .order_by(Session.created_at.asc())
        )
        if effective_doctor_id:
            session_query = session_query.where(Session.doctor_id == effective_doctor_id)

        alert_query = (
            select(RedFlagAlert.severity, RedFlagAlert.created_at)
            .join(Session, RedFlagAlert.session_id == Session.id)
            .where(RedFlagAlert.created_at >= month_start)
            .where(RedFlagAlert.created_at < month_end)
        )
        if effective_doctor_id:
            alert_query = alert_query.where(Session.doctor_id == effective_doctor_id)

        pending_query = (
            select(func.count())
            .select_from(SOAPReport)
            .join(Session, SOAPReport.session_id == Session.id)
            .where(Session.created_at >= month_start)
            .where(Session.created_at < month_end)
            .where(SOAPReport.review_status == ReviewStatus.PENDING)
            .where(SOAPReport.status == ReportStatus.GENERATED)
        )
        if effective_doctor_id:
            pending_query = pending_query.where(Session.doctor_id == effective_doctor_id)

        session_rows = (await db.execute(session_query)).all()
        alert_rows = (await db.execute(alert_query)).all()
        pending_reviews = (await db.execute(pending_query)).scalar() or 0

        status_counts = {status.value: 0 for status in SessionStatus}
        severity_counts = {severity.value: 0 for severity in AlertSeverity}
        complaint_counts: dict[str, int] = defaultdict(int)
        daily_map: dict[date, dict[str, int]] = {}

        current_day = month_start.date()
        end_day = month_end.date()
        while current_day < end_day:
            daily_map[current_day] = {"sessions": 0, "completed": 0, "red_flags": 0}
            current_day += timedelta(days=1)

        completed_sessions = 0
        aborted_red_flag_sessions = 0

        for session, chief_complaint_category in session_rows:
            status_key = session.status.value
            status_counts[status_key] += 1

            created_day = session.created_at.date()
            if created_day in daily_map:
                daily_map[created_day]["sessions"] += 1

            if session.status == SessionStatus.COMPLETED:
                completed_sessions += 1
                if created_day in daily_map:
                    daily_map[created_day]["completed"] += 1

            if session.status == SessionStatus.ABORTED_RED_FLAG:
                aborted_red_flag_sessions += 1

            complaint_label = (
                chief_complaint_category
                or (session.chief_complaint_text or "").strip()
                or "未分類"
            )
            complaint_counts[complaint_label] += 1

        for severity, created_at in alert_rows:
            severity_key = severity.value if hasattr(severity, "value") else str(severity)
            if severity_key in severity_counts:
                severity_counts[severity_key] += 1

            created_day = created_at.date()
            if created_day in daily_map:
                daily_map[created_day]["red_flags"] += 1

        total_sessions = len(session_rows)
        total_red_flag_alerts = len(alert_rows)
        completion_rate = round(
            (completed_sessions / total_sessions) * 100, 1
        ) if total_sessions else 0.0

        sorted_complaints = sorted(
            complaint_counts.items(),
            key=lambda item: item[1],
            reverse=True,
        )
        top_complaints = sorted_complaints[:5]
        remaining_count = sum(count for _, count in sorted_complaints[5:])
        chief_complaint_distribution = [
            SummaryBucketItem(key=label, label=label, count=count)
            for label, count in top_complaints
        ]
        if remaining_count:
            chief_complaint_distribution.append(
                SummaryBucketItem(key="other", label="其他", count=remaining_count)
            )

        status_distribution = [
            SummaryBucketItem(
                key=status_key,
                label=STATUS_LABELS[status_key],
                count=status_counts[status_key],
            )
            for status_key in [
                SessionStatus.COMPLETED.value,
                SessionStatus.IN_PROGRESS.value,
                SessionStatus.WAITING.value,
                SessionStatus.ABORTED_RED_FLAG.value,
                SessionStatus.CANCELLED.value,
            ]
        ]

        alert_severity_distribution = [
            SummaryBucketItem(
                key=severity_key,
                label=ALERT_SEVERITY_LABELS[severity_key],
                count=severity_counts[severity_key],
            )
            for severity_key in [
                AlertSeverity.CRITICAL.value,
                AlertSeverity.HIGH.value,
                AlertSeverity.MEDIUM.value,
            ]
        ]

        daily_trend = [
            DailyTrendItem(
                date=day,
                label=day.strftime("%m/%d"),
                sessions=counts["sessions"],
                completed=counts["completed"],
                red_flags=counts["red_flags"],
            )
            for day, counts in daily_map.items()
        ]

        return MonthlySummaryResponse(
            month=month_key,
            month_label=month_label,
            total_sessions=total_sessions,
            completed_sessions=completed_sessions,
            aborted_red_flag_sessions=aborted_red_flag_sessions,
            pending_reviews=pending_reviews,
            total_red_flag_alerts=total_red_flag_alerts,
            completion_rate=completion_rate,
            status_distribution=status_distribution,
            chief_complaint_distribution=chief_complaint_distribution,
            alert_severity_distribution=alert_severity_distribution,
            daily_trend=daily_trend,
            generated_at=utc_now(),
        )
