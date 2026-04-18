"""
共用列舉型別定義
所有 Enum 繼承 (str, Enum) 以便序列化為字串值
"""

from enum import Enum
from typing import Type, TypeVar

from sqlalchemy import Enum as SQLEnum

_E = TypeVar("_E", bound=Enum)


def pg_enum(enum_cls: Type[_E], name: str) -> SQLEnum:
    """
    回傳一個告訴 PostgreSQL 用「Enum 的 value（小寫）」而非
    「member 名稱（大寫）」存值的 SQLAlchemy Enum type。

    Why: SQLAlchemy 預設用 member 名稱存（PATIENT），但 enums.py 的值是小寫
    （patient），導致寫入時 member 名稱 vs value 不對齊，造成 ORM ↔ 手寫 SQL
    ↔ API response 三方不一致。統一用 values_callable 強制存 value。
    """
    return SQLEnum(
        enum_cls,
        name=name,
        values_callable=lambda e: [m.value for m in e],
        native_enum=True,
    )


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
    # 對話中語言切換 → 強制結束當前 session（M16）
    LANGUAGE_SWITCH_END_SESSION = "language_switch_end_session"


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


class SupportedLanguage(str, Enum):
    """
    支援的 UI / 語音 / SOAP 語言（BCP-47）。

    設計決定：
    - 用 `String(10)` 欄位 + 應用層驗證，不用 PG 原生 enum。
      理由：未來擴 locale（ko-KR、vi-VN…）不用 `ALTER TYPE`，避免交易鎖問題。
    - `DEFAULT_LANGUAGE` 在 `app.core.config.settings.DEFAULT_LANGUAGE` 單一來源。
    """
    ZH_TW = "zh-TW"
    EN_US = "en-US"
