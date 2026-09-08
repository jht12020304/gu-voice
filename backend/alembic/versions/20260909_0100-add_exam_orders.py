"""新增 exam_orders（醫師快速開單的檢查醫囑）

Revision ID: a1b2c3d4e5f6
Revises: f4a5b6c7d8e9
Create Date: 2026-09-09

append-only 設計：每次送出一列，以 `(session_id, created_at)` 最新的那列為準。
沒有唯一鍵，所以不會有「重送要不要 upsert」的競態問題。
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "a1b2c3d4e5f6"
down_revision = "f4a5b6c7d8e9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "exam_orders",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("report_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("ordered_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "items",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["report_id"], ["soap_reports.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["ordered_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_exam_orders_session_created",
        "exam_orders",
        ["session_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_exam_orders_session_created", table_name="exam_orders")
    op.drop_table("exam_orders")
