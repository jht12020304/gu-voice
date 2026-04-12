"""儀表板相關 Pydantic Schema"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.enums import SessionStatus


class DashboardStatsResponse(BaseModel):
    """儀表板統計回應"""
    sessions_today: int = 0
    completed: int = 0
    red_flags: int = 0
    pending_reviews: int = 0
    in_progress: int = 0
    waiting: int = 0
    average_duration_seconds: Optional[float] = None
    timestamp: datetime


class QueueItemResponse(BaseModel):
    """等候佇列項目"""
    session_id: UUID
    patient_id: UUID
    patient_name: str
    chief_complaint: str
    status: SessionStatus
    red_flag: bool
    created_at: datetime
    started_at: Optional[datetime] = None
    waiting_seconds: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


class QueueResponse(BaseModel):
    """等候佇列回應"""
    total_waiting: int = 0
    total_in_progress: int = 0
    queue: list[QueueItemResponse] = []


class RecentSessionItem(BaseModel):
    """近期場次項目"""
    session_id: UUID
    patient_name: str
    chief_complaint: str
    status: SessionStatus
    red_flag: bool
    created_at: datetime
    completed_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class RecentSessionsResponse(BaseModel):
    """近期場次回應"""
    data: list[RecentSessionItem] = []


class RecentAlertItem(BaseModel):
    """近期警示項目"""
    alert_id: UUID
    session_id: UUID
    patient_name: str
    severity: str
    title: str
    acknowledged: bool = False
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RecentAlertsResponse(BaseModel):
    """近期警示回應"""
    data: list[RecentAlertItem] = []


# 別名（供 router 匯入相容）
PatientQueueResponse = QueueResponse
