"""lowercase_enum_values

把所有 Postgres ENUM type 的 value 從「member 名稱（大寫）」rename 成
「enum value（小寫）」，讓 DB ↔ ORM ↔ API response 對齊。

背景：
  初始 migration（c98fa7840c8c）把 Column 指定為 `sa.Enum('PATIENT','DOCTOR',...)`，
  因為 SQLAlchemy 預設從 `Mapped[UserRole]` 自動推導時用 member name。但
  `app.models.enums` 的 UserRole value 其實是小寫 "patient"，導致 ORM 存/取時
  因為 pg_enum helper 指定 values_callable=lambda e: [m.value for m in e]
  會期待 DB 內是小寫。

此 migration 執行 `ALTER TYPE ... RENAME VALUE '<UPPER>' TO '<lower>'`。
需要 Postgres 12+。

Revision ID: f1b2c3d4e5f6
Revises: 8e3e8a4d5f01
Create Date: 2026-04-17 09:00:00.000000+08:00
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f1b2c3d4e5f6"
down_revision: Union[str, None] = "8e3e8a4d5f01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (enum_type_name, [(upper, lower), ...])
# 對齊 backend/app/models/enums.py
_RENAMES: list[tuple[str, list[tuple[str, str]]]] = [
    ("userrole", [("PATIENT", "patient"), ("DOCTOR", "doctor"), ("ADMIN", "admin")]),
    (
        "sessionstatus",
        [
            ("WAITING", "waiting"),
            ("IN_PROGRESS", "in_progress"),
            ("COMPLETED", "completed"),
            ("ABORTED_RED_FLAG", "aborted_red_flag"),
            ("CANCELLED", "cancelled"),
        ],
    ),
    (
        "conversationrole",
        [("PATIENT", "patient"), ("ASSISTANT", "assistant"), ("SYSTEM", "system")],
    ),
    ("alertseverity", [("CRITICAL", "critical"), ("HIGH", "high"), ("MEDIUM", "medium")]),
    (
        "alerttype",
        [("RULE_BASED", "rule_based"), ("SEMANTIC", "semantic"), ("COMBINED", "combined")],
    ),
    (
        "reportstatus",
        [("GENERATING", "generating"), ("GENERATED", "generated"), ("FAILED", "failed")],
    ),
    (
        "reviewstatus",
        [("PENDING", "pending"), ("APPROVED", "approved"), ("REVISION_NEEDED", "revision_needed")],
    ),
    (
        "notificationtype",
        [
            ("RED_FLAG", "red_flag"),
            ("SESSION_COMPLETE", "session_complete"),
            ("REPORT_READY", "report_ready"),
            ("SYSTEM", "system"),
        ],
    ),
    (
        "auditaction",
        [
            ("CREATE", "create"),
            ("READ", "read"),
            ("UPDATE", "update"),
            ("DELETE", "delete"),
            ("LOGIN", "login"),
            ("LOGOUT", "logout"),
            ("EXPORT", "export"),
            ("REVIEW", "review"),
            ("ACKNOWLEDGE", "acknowledge"),
            ("SESSION_START", "session_start"),
            ("SESSION_END", "session_end"),
        ],
    ),
    ("deviceplatform", [("IOS", "ios"), ("ANDROID", "android"), ("WEB", "web")]),
    ("gender", [("MALE", "male"), ("FEMALE", "female"), ("OTHER", "other")]),
]


def _rename_if_exists(enum_name: str, old: str, new: str) -> None:
    """只在 old value 仍存在時 rename，避免重跑報錯。"""
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM pg_enum e
                JOIN pg_type t ON t.oid = e.enumtypid
                WHERE t.typname = '{enum_name}' AND e.enumlabel = '{old}'
            ) THEN
                EXECUTE 'ALTER TYPE {enum_name} RENAME VALUE ''{old}'' TO ''{new}''';
            END IF;
        END$$;
        """
    )


# (table, column, enum_name, lowercase_default)
# 初始 migration 設了大寫 default（e.g. 'WAITING'::sessionstatus），
# ALTER TYPE RENAME VALUE 不會改已存的 default 表達式字串，需手動覆寫。
_DEFAULTS: list[tuple[str, str, str, str]] = [
    ("sessions", "status", "sessionstatus", "waiting"),
    ("soap_reports", "status", "reportstatus", "generating"),
    ("soap_reports", "review_status", "reviewstatus", "pending"),
]


def upgrade() -> None:
    # 1. 暫時 drop 使用舊值的 column default
    for table, column, _, _ in _DEFAULTS:
        op.execute(f"ALTER TABLE {table} ALTER COLUMN {column} DROP DEFAULT")

    # 2. 將所有 enum value 小寫化
    for enum_name, pairs in _RENAMES:
        for old, new in pairs:
            _rename_if_exists(enum_name, old, new)

    # 3. 以小寫值重設 default
    for table, column, enum_name, lower_default in _DEFAULTS:
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {column} "
            f"SET DEFAULT '{lower_default}'::{enum_name}"
        )


def downgrade() -> None:
    # 反向：小寫改回大寫（含 default 還原）
    reverse_defaults = {
        ("sessions", "status"): "WAITING",
        ("soap_reports", "status"): "GENERATING",
        ("soap_reports", "review_status"): "PENDING",
    }

    for table, column, _, _ in _DEFAULTS:
        op.execute(f"ALTER TABLE {table} ALTER COLUMN {column} DROP DEFAULT")

    for enum_name, pairs in _RENAMES:
        for old, new in pairs:
            _rename_if_exists(enum_name, new, old)

    for (table, column), upper_default in reverse_defaults.items():
        enum_name = {
            ("sessions", "status"): "sessionstatus",
            ("soap_reports", "status"): "reportstatus",
            ("soap_reports", "review_status"): "reviewstatus",
        }[(table, column)]
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {column} "
            f"SET DEFAULT '{upper_default}'::{enum_name}"
        )
