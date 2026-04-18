"""
匯出所有 SQLAlchemy ORM 模型
確保 Alembic 能偵測到所有模型以產生正確的 migration
"""

from app.models.audit_log import AuditLog
from app.models.chief_complaint import ChiefComplaint
from app.models.conversation import Conversation
from app.models.enums import (
    AlertSeverity,
    AlertType,
    AuditAction,
    ConversationRole,
    DevicePlatform,
    Gender,
    NotificationType,
    RedFlagConfidence,
    ReportRevisionReason,
    ReportStatus,
    ReviewStatus,
    SessionStatus,
    UserRole,
)
from app.models.fcm_device import FCMDevice
from app.models.notification import Notification
from app.models.patient import Patient
from app.models.red_flag_alert import RedFlagAlert
from app.models.red_flag_rule import RedFlagRule
from app.models.session import Session
from app.models.soap_report import SOAPReport
from app.models.soap_report_revision import SOAPReportRevision
from app.models.user import User

__all__ = [
    # Models
    "User",
    "Patient",
    "Session",
    "Conversation",
    "ChiefComplaint",
    "SOAPReport",
    "SOAPReportRevision",
    "RedFlagAlert",
    "RedFlagRule",
    "Notification",
    "AuditLog",
    "FCMDevice",
    # Enums
    "UserRole",
    "SessionStatus",
    "ConversationRole",
    "AlertSeverity",
    "AlertType",
    "RedFlagConfidence",
    "ReportStatus",
    "ReviewStatus",
    "ReportRevisionReason",
    "NotificationType",
    "AuditAction",
    "DevicePlatform",
    "Gender",
]
