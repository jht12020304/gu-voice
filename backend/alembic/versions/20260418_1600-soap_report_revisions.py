"""soap_report_revisions — M15 append-only 版本快照

追加 soap_report_revisions 表，保留 SOAP 每次被覆寫前的完整內容。
讓重生 / 審閱覆寫皆可追溯（append-only，無 UPDATE）。

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-04-18 16:00:00.000000+08:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # reportrevisionreason enum 走 lowercase values（與其他 enums 一致，見 20260417_0900）
    op.execute(
        "DO $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'reportrevisionreason') THEN "
        "CREATE TYPE reportrevisionreason AS ENUM "
        "('initial', 'regenerate', 'review_override'); "
        "END IF; END $$;"
    )
    reason_enum = postgresql.ENUM(
        "initial",
        "regenerate",
        "review_override",
        name="reportrevisionreason",
        create_type=False,
    )

    op.create_table(
        "soap_report_revisions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "report_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("soap_reports.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("revision_no", sa.Integer, nullable=False),
        sa.Column("reason", reason_enum, nullable=False),
        sa.Column("subjective", postgresql.JSONB, nullable=True),
        sa.Column("objective", postgresql.JSONB, nullable=True),
        sa.Column("assessment", postgresql.JSONB, nullable=True),
        sa.Column("plan", postgresql.JSONB, nullable=True),
        sa.Column("summary", sa.Text, nullable=True),
        sa.Column("icd10_codes", postgresql.ARRAY(sa.String), nullable=True),
        sa.Column("language", sa.String(10), nullable=False),
        sa.Column("ai_confidence_score", sa.Numeric(3, 2), nullable=True),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_soap_report_revisions_report_id",
        "soap_report_revisions",
        ["report_id"],
    )
    # (report_id, revision_no) 必唯一，避免同一 report 同一 revision_no 重複
    op.create_unique_constraint(
        "uq_soap_report_revisions_report_id_rev_no",
        "soap_report_revisions",
        ["report_id", "revision_no"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_soap_report_revisions_report_id_rev_no",
        "soap_report_revisions",
        type_="unique",
    )
    op.drop_index("ix_soap_report_revisions_report_id", "soap_report_revisions")
    op.drop_table("soap_report_revisions")
    op.execute("DROP TYPE IF EXISTS reportrevisionreason")
