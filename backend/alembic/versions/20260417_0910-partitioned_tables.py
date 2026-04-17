"""partitioned_tables

把 `conversations` 與 `audit_logs` 轉成「按月 Range Partition」表。
partition_manager.py 每月 25 日建立下月分區，本 migration 只負責：
  1) DROP 舊的非分區表
  2) CREATE 新的 partitioned parent table（PK 必須含 created_at 分區鍵）
  3) 建立「當月 + 下月」兩個初始分區，讓 partition_manager 有 runway

前提：DB 可重置（見 docs/TODO.md 對話記錄，使用者已確認）。
兩張表在 downgrade 時會還原為原 initial_schema 的非分區版本。

Revision ID: a7b8c9d0e1f2
Revises: f1b2c3d4e5f6
Create Date: 2026-04-17 09:10:00.000000+08:00
"""

from datetime import date
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, None] = "f1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _month_bounds(year: int, month: int) -> tuple[str, str]:
    """回傳 ('YYYY-MM-01', '下個月 YYYY-MM-01') 字串對"""
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1)
    else:
        end = date(year, month + 1, 1)
    return start.isoformat(), end.isoformat()


def _initial_partitions() -> list[tuple[str, str, str]]:
    """當月 + 下月兩個初始分區 (suffix, from, to)"""
    today = date.today()
    this_from, this_to = _month_bounds(today.year, today.month)
    if today.month == 12:
        next_year, next_month = today.year + 1, 1
    else:
        next_year, next_month = today.year, today.month + 1
    next_from, next_to = _month_bounds(next_year, next_month)
    return [
        (f"{today.year:04d}_{today.month:02d}", this_from, this_to),
        (f"{next_year:04d}_{next_month:02d}", next_from, next_to),
    ]


def upgrade() -> None:
    # ── conversations：drop → recreate partitioned ──────────────────────────
    op.drop_index("ix_conversations_session_id", table_name="conversations")
    op.drop_table("conversations")

    op.execute(
        """
        CREATE TABLE conversations (
            id UUID NOT NULL DEFAULT gen_random_uuid(),
            session_id UUID NOT NULL REFERENCES sessions(id),
            sequence_number INTEGER NOT NULL,
            role conversationrole NOT NULL,
            content_text TEXT NOT NULL,
            audio_url VARCHAR(500),
            audio_duration_seconds NUMERIC(8, 2),
            stt_confidence NUMERIC(5, 4),
            red_flag_detected BOOLEAN NOT NULL DEFAULT FALSE,
            metadata JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (id, created_at),
            UNIQUE (session_id, sequence_number, created_at)
        ) PARTITION BY RANGE (created_at)
        """
    )
    op.create_index(
        "ix_conversations_session_id",
        "conversations",
        ["session_id"],
        unique=False,
    )

    for suffix, date_from, date_to in _initial_partitions():
        op.execute(
            f"""
            CREATE TABLE conversations_{suffix}
            PARTITION OF conversations
            FOR VALUES FROM ('{date_from}') TO ('{date_to}')
            """
        )

    # ── audit_logs：drop → recreate partitioned ─────────────────────────────
    op.drop_index("ix_audit_logs_user_id", table_name="audit_logs")
    op.drop_table("audit_logs")

    # audit_logs.id 為 BigInt + sequence；分區表中 PK 必須含 partition key
    op.execute("CREATE SEQUENCE IF NOT EXISTS audit_logs_id_seq AS BIGINT")
    op.execute(
        """
        CREATE TABLE audit_logs (
            id BIGINT NOT NULL DEFAULT nextval('audit_logs_id_seq'),
            user_id UUID REFERENCES users(id),
            action auditaction NOT NULL,
            resource_type VARCHAR(50) NOT NULL,
            resource_id VARCHAR(100),
            details JSONB,
            ip_address INET,
            user_agent VARCHAR(500),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (id, created_at)
        ) PARTITION BY RANGE (created_at)
        """
    )
    op.execute("ALTER SEQUENCE audit_logs_id_seq OWNED BY audit_logs.id")
    op.create_index(
        "ix_audit_logs_user_id",
        "audit_logs",
        ["user_id"],
        unique=False,
    )

    for suffix, date_from, date_to in _initial_partitions():
        op.execute(
            f"""
            CREATE TABLE audit_logs_{suffix}
            PARTITION OF audit_logs
            FOR VALUES FROM ('{date_from}') TO ('{date_to}')
            """
        )


def downgrade() -> None:
    # 分區會隨著 parent DROP TABLE 一起消失
    op.drop_index("ix_conversations_session_id", table_name="conversations")
    op.drop_table("conversations")

    op.create_table(
        "conversations",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column(
            "role",
            sa.Enum("patient", "assistant", "system", name="conversationrole"),
            nullable=False,
        ),
        sa.Column("content_text", sa.Text(), nullable=False),
        sa.Column("audio_url", sa.String(length=500), nullable=True),
        sa.Column("audio_duration_seconds", sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column("stt_confidence", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column(
            "red_flag_detected",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_conversations_session_id",
        "conversations",
        ["session_id"],
        unique=False,
    )

    op.drop_index("ix_audit_logs_user_id", table_name="audit_logs")
    op.drop_table("audit_logs")
    op.execute("DROP SEQUENCE IF EXISTS audit_logs_id_seq")

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column(
            "action",
            sa.Enum(
                "create",
                "read",
                "update",
                "delete",
                "login",
                "logout",
                "export",
                "review",
                "acknowledge",
                "session_start",
                "session_end",
                name="auditaction",
            ),
            nullable=False,
        ),
        sa.Column("resource_type", sa.String(length=50), nullable=False),
        sa.Column("resource_id", sa.String(length=100), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("ip_address", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_audit_logs_user_id",
        "audit_logs",
        ["user_id"],
        unique=False,
    )
