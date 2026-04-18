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


class RedFlagConfidence(str, Enum):
    """
    紅旗警示信心層級（TODO-M8 i18n fail-safe）。

    - RULE_HIT：關鍵字 / regex 規則層命中（高信心，原生 rule-based）。
    - SEMANTIC_ONLY：僅由 LLM 語意層偵測，未被規則層命中（中信心，
      可能受 locale 覆蓋率影響；前端 UI 應顯示 banner）。
    - UNCOVERED_LOCALE：session.language 沒有該 canonical_id 的 trigger
      keywords 覆蓋；自動 escalate 為 physician review，並寫入 audit log。
    """
    RULE_HIT = "rule_hit"
    SEMANTIC_ONLY = "semantic_only"
    UNCOVERED_LOCALE = "uncovered_locale"


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


class ReportRevisionReason(str, Enum):
    """
    SOAPReportRevision 建立原因（M15 append-only 審計）。

    - INITIAL：Celery 第一次產完報告寫入的首版快照
    - REGENERATE：醫師要求 regenerate，舊內容被新生成覆寫前的快照
    - REVIEW_OVERRIDE：醫師審閱時用 soap_overrides 修改內容，覆寫前的快照
    """
    INITIAL = "initial"
    REGENERATE = "regenerate"
    REVIEW_OVERRIDE = "review_override"


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


class Urgency(str, Enum):
    """
    SOAP Plan 緊急度（TODO-M13）。

    4 個離散級別，由重到輕：
    - ER_NOW：立即至急診
    - WITHIN_24H：24 小時內就醫
    - THIS_WEEK：本週內就醫
    - ROUTINE：常規追蹤

    Notes
    -----
    - 與 UI 顯示文字分離：display string 見 `app.utils.i18n_messages`
      (key `soap.urgency.<value>`).
    - 若 LLM 吐回不符合的值，`SOAPGenerator._validate_and_fill` 會 fallback
      成 `ROUTINE` 並 log warning。
    - `24h` 為合法 enum value（但不符 Python identifier 規則），因此成員名
      使用 `WITHIN_24H`，value 保持 `24h` 以利前端與 prompt 直接使用。
    """
    ER_NOW = "er_now"
    WITHIN_24H = "24h"
    THIS_WEEK = "this_week"
    ROUTINE = "routine"


URGENCY_VALUES: frozenset[str] = frozenset(u.value for u in Urgency)


class SupportedLanguage(str, Enum):
    """
    支援的 UI / 語音 / SOAP 語言（BCP-47）。

    設計決定：
    - 用 `String(10)` 欄位 + 應用層驗證，不用 PG 原生 enum。
      理由：擴 locale 不用 `ALTER TYPE`，避免交易鎖問題。
    - `DEFAULT_LANGUAGE` 在 `app.core.config.settings.DEFAULT_LANGUAGE` 單一來源。
    - Phase C：ja-JP / ko-KR / vi-VN 已加入 enum，但 LLM prompt、red-flag
      trigger、臨床 / 法律 sign-off 尚未到位；僅前端可切換、骨架層級完成。
    """
    ZH_TW = "zh-TW"
    EN_US = "en-US"
    JA_JP = "ja-JP"
    KO_KR = "ko-KR"
    VI_VN = "vi-VN"
