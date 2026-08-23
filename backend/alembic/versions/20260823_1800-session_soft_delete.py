"""sessions.is_deleted / deleted_at / deleted_by —— 管理員軟刪除問診場次

2026-08-23 使用者拍板：要有一個最高權限（admin）能刪掉問診的問答內容。
與 `patients` 同一條原則——**醫療記錄不硬刪**：標記 is_deleted 之後所有讀取
路徑一律過濾掉（清單、詳情、逐字稿、SOAP 報告、儀表板統計、紅旗、研究分析、
病患自己的歷史），但 row 與 conversations / soap_reports / red_flag_alerts 的
FK 全部留著——誤刪救得回來，稽核軌跡也不斷。

deleted_by 記操作者（FK users.id，SET NULL 語意由應用層負責，這裡只做 FK），
另有一筆 AuditAction.DELETE 的稽核日誌記下誰在何時刪了哪一場。

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-08-23 18:00:00.000000+08:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e3f4a5b6c7d8"
down_revision: Union[str, None] = "d2e3f4a5b6c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sessions",
        sa.Column(
            "is_deleted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "sessions",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "sessions",
        sa.Column("deleted_by", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_sessions_deleted_by_users",
        "sessions",
        "users",
        ["deleted_by"],
        ["id"],
    )
    op.create_index("ix_sessions_is_deleted", "sessions", ["is_deleted"])


def downgrade() -> None:
    op.drop_index("ix_sessions_is_deleted", table_name="sessions")
    op.drop_constraint("fk_sessions_deleted_by_users", "sessions", type_="foreignkey")
    op.drop_column("sessions", "deleted_by")
    op.drop_column("sessions", "deleted_at")
    op.drop_column("sessions", "is_deleted")
