"""add_multilang_fields

Phase 1 of multi-language rollout（docs/i18n_plan.md）：

1. users.preferred_language (nullable)
2. soap_reports.language (NOT NULL, default 'zh-TW')
3. red_flag_alerts.language (NOT NULL, default 'zh-TW')
4. audit_logs.language (nullable, indexed) — partitioned parent，用 raw SQL

設計決定：
- 用 `String(10)` 欄位 + 應用層驗證，不用 PG 原生 enum：未來擴 locale
  不用 `ALTER TYPE`，避免長交易鎖問題。
- NOT NULL 欄位以 `server_default` 讓 Postgres 原地 backfill 既有 row，
  不做手動 UPDATE；PG 11+ 為 metadata-only 操作。
- audit_logs.language 走 raw SQL：分區表 parent add column 會 propagate 到所有子分區，
  但 alembic op.add_column 在某些 PG 版本對分區處理不穩，raw SQL 最可控。

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-04-18 15:00:00.000000+08:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. users.preferred_language（nullable — NULL = 尚未選擇） ─────────
    op.add_column(
        "users",
        sa.Column("preferred_language", sa.String(10), nullable=True),
    )

    # ── 2. soap_reports.language（NOT NULL + server_default，原地 backfill） ─
    op.add_column(
        "soap_reports",
        sa.Column(
            "language",
            sa.String(10),
            server_default=sa.text("'zh-TW'"),
            nullable=False,
        ),
    )

    # ── 3. red_flag_alerts.language ─────────────────────────────────────
    op.add_column(
        "red_flag_alerts",
        sa.Column(
            "language",
            sa.String(10),
            server_default=sa.text("'zh-TW'"),
            nullable=False,
        ),
    )

    # ── 4. audit_logs.language（partitioned table，用 raw SQL） ──────────
    # parent 的 ADD COLUMN 會自動 propagate 到所有子分區。nullable：login/logout
    # 等事件無 session 上下文時可留空。加 index 以便 `GROUP BY language` 分析。
    op.execute(
        "ALTER TABLE audit_logs ADD COLUMN language VARCHAR(10) NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_audit_logs_language "
        "ON audit_logs (language)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_audit_logs_language")
    op.execute("ALTER TABLE audit_logs DROP COLUMN IF EXISTS language")
    op.drop_column("red_flag_alerts", "language")
    op.drop_column("soap_reports", "language")
    op.drop_column("users", "preferred_language")
