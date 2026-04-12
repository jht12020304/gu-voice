"""
共用列舉型別定義
所有 Enum 繼承 (str, Enum) 以便序列化為字串值
"""

from enum import Enum


class UserRole(str, Enum):
    """使用者角色"""
    PATIENT = "patient"
    DOCTOR = "doctor"
    ADMIN = "admin"


class SessionStatus(str, Enum):
    """問診場次狀態"""
    WAITING = "waiting"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    ABORTED_RED_FLAG = "aborted_red_flag"
    CANCELLED = "cancelled"


class ConversationRole(str, Enum):
    """對話角色"""
    PATIENT = "patient"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class AlertSeverity(str, Enum):
    """紅旗警示嚴重度"""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"


class AlertType(str, Enum):
    """紅旗警示偵測方式"""
    RULE_BASED = "rule_based"
    SEMANTIC = "semantic"
    COMBINED = "combined"


class ReportStatus(str, Enum):
    """SOAP 報告狀態"""
    GENERATING = "generating"
    GENERATED = "generated"
    FAILED = "failed"


class ReviewStatus(str, Enum):
    """審閱狀態"""
    PENDING = "pending"
    APPROVED = "approved"
    REVISION_NEEDED = "revision_needed"


class NotificationType(str, Enum):
    """通知類型"""
    RED_FLAG = "red_flag"
    SESSION_COMPLETE = "session_complete"
    REPORT_READY = "report_ready"
    SYSTEM = "system"


class AuditAction(str, Enum):
    """稽核日誌操作類型"""
    CREATE = "create"
    READ = "read"
    UPDATE = "update"
    DELETE = "delete"
    LOGIN = "login"
    LOGOUT = "logout"
    EXPORT = "export"
    REVIEW = "review"
    ACKNOWLEDGE = "acknowledge"
    SESSION_START = "session_start"
    SESSION_END = "session_end"


class DevicePlatform(str, Enum):
    """推播裝置平台"""
    IOS = "ios"
    ANDROID = "android"
    WEB = "web"


class Gender(str, Enum):
    """性別"""
    MALE = "male"
    FEMALE = "female"
    OTHER = "other"
