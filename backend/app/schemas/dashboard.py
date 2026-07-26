"""儀表板相關 Pydantic Schema"""

from datetime import date, datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.enums import SessionStatus


class DashboardStatsResponse(BaseModel):
    """儀表板統計回應

    語意說明：
    - sessions_today / completed / red_flags / pending_reviews 依 `date`
      區間（當日 UTC）統計。
    - average_duration_seconds：該區間內「已完成」場次的平均時長（秒），
      取 completed_at / started_at（缺則退回 duration_seconds）計算；
      無已完成場次時為 None。
    - in_progress / waiting：刻意為「即時」狀態快照（目前進行中 / 等待中），
      不受 `date` 區間限制，反映當下佇列狀況。
    """
    sessions_today: int = 0
    completed: int = 0
    red_flags: int = 0
    pending_reviews: int = 0
    # 即時狀態快照，不受 date 區間限制（見 class docstring）
    in_progress: int = 0
    waiting: int = 0
    # 區間內已完成場次的平均時長（秒）；無資料為 None
    average_duration_seconds: Optional[float] = None
    timestamp: datetime


class QueueItemResponse(BaseModel):
    """等候佇列項目"""
    session_id: UUID
    patient_id: UUID
    patient_name: str
    chief_complaint: str
    status: SessionStatus
    has_red_flag: bool
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


class SummaryBucketItem(BaseModel):
    """摘要分桶項目"""
    key: str
    label: str
    count: int = 0


class DailyTrendItem(BaseModel):
    """每日趨勢項目"""
    date: date
    label: str
    sessions: int = 0
    completed: int = 0
    red_flags: int = 0


class MonthlySummaryResponse(BaseModel):
    """月份摘要回應

    月份欄位刻意分三個，語意不同：
    - `month`：機器可讀的零填補 `YYYY-MM`（既有欄位，回應所查詢的區間）。
      **前端要格式化年月請用它**——曾短暫加過一個值完全相同的 `month_key`，
      是多餘的欄位，已移除。
    - `month_label`：後端產的中文字串（「2026 年 7 月」）。**僅為向後相容保留**，
      新前端請改用 `month` 自行以當地語系格式化——日期格式必須跟隨使用者
      語系（zh-TW / en-US / ja-JP / ko-KR / vi-VN），不能由後端硬寫單一語言，
      否則非中文語系的醫師會看到中英混雜的標題。
    """
    month: str
    month_label: str
    total_sessions: int = 0
    completed_sessions: int = 0
    aborted_red_flag_sessions: int = 0
    pending_reviews: int = 0
    total_red_flag_alerts: int = 0
    completion_rate: float = 0
    status_distribution: list[SummaryBucketItem] = []
    chief_complaint_distribution: list[SummaryBucketItem] = []
    alert_severity_distribution: list[SummaryBucketItem] = []
    daily_trend: list[DailyTrendItem] = []
    generated_at: datetime


# 別名（供 router 匯入相容）
PatientQueueResponse = QueueResponse
