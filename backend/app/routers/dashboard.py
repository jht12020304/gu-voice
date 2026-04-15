"""
醫師儀表板路由 — 統計摘要、病患佇列、近期警示與場次
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db, require_role
from app.core.exceptions import AppException
from app.schemas.dashboard import (
    DashboardStatsResponse,
    MonthlySummaryResponse,
    PatientQueueResponse,
    RecentAlertsResponse,
    RecentSessionsResponse,
)
from app.services.dashboard_service import DashboardService

router = APIRouter(
    prefix="/api/v1/dashboard",
    tags=["儀表板"],
    dependencies=[Depends(require_role("doctor", "admin"))],
)

dashboard_service = DashboardService()


@router.get(
    "/stats",
    response_model=DashboardStatsResponse,
    status_code=status.HTTP_200_OK,
    summary="取得今日統計",
)
async def get_stats(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
    date: str | None = None,
    doctor_id: UUID | None = None,
) -> DashboardStatsResponse:
    """
    取得指定日期的統計摘要資料，用於儀表板首頁。
    預設為今日。醫師角色自動帶入自己的 ID，管理員可指定。
    """
    return await dashboard_service.get_stats(
        db,
        current_user=current_user,
        date=date,
        doctor_id=doctor_id,
    )


@router.get(
    "/monthly-summary",
    response_model=MonthlySummaryResponse,
    status_code=status.HTTP_200_OK,
    summary="取得月份摘要",
)
async def get_monthly_summary(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
    month: str | None = Query(None, description="月份，格式 YYYY-MM"),
    doctor_id: UUID | None = None,
) -> MonthlySummaryResponse:
    """取得指定月份的統計摘要、分類分佈與趨勢資料。"""
    return await dashboard_service.get_monthly_summary(
        db,
        current_user=current_user,
        month=month,
        doctor_id=doctor_id,
    )


@router.get(
    "/queue",
    response_model=PatientQueueResponse,
    status_code=status.HTTP_200_OK,
    summary="取得病患佇列",
)
async def get_queue(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
    doctor_id: UUID | None = None,
    status_filter: str | None = Query("waiting,in_progress", alias="status"),
) -> PatientQueueResponse:
    """取得目前的病患佇列，包含等待中與進行中的場次，用於即時看診排隊資訊。"""
    return await dashboard_service.get_queue(
        db,
        current_user=current_user,
        doctor_id=doctor_id,
        status=status_filter,
    )


@router.get(
    "/recent-alerts",
    response_model=RecentAlertsResponse,
    status_code=status.HTTP_200_OK,
    summary="取得近期未確認警示",
)
async def get_recent_alerts(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
    severity: str | None = None,
    limit: int = Query(50, ge=1, le=100),
) -> RecentAlertsResponse:
    """取得所有未確認的紅旗警示，依嚴重程度排序（critical 優先）。"""
    return await dashboard_service.get_recent_alerts(
        db,
        current_user=current_user,
        severity=severity,
        limit=limit,
    )


@router.get(
    "/recent-sessions",
    response_model=RecentSessionsResponse,
    status_code=status.HTTP_200_OK,
    summary="取得近期場次",
)
async def get_recent_sessions(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
    doctor_id: UUID | None = None,
    limit: int = Query(20, ge=1, le=100),
) -> RecentSessionsResponse:
    """取得近期的問診場次列表，用於儀表板快速瀏覽。"""
    return await dashboard_service.get_recent_sessions(
        db,
        current_user=current_user,
        doctor_id=doctor_id,
        limit=limit,
    )
