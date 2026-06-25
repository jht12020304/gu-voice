"""soft-delete patients + red_flag_alerts.action_taken

Wave 3 資安/完整性修復（production readiness audit 2026-06-14）：
  1. patients.is_deleted / deleted_at —— 病患為醫療資料，刪除一律 soft-delete，
     保留既有 session FK 與審計軌跡；router DELETE 走 soft_delete_patient。
     讀取路徑（get / list / sessions）一律過濾 is_deleted = false。
  2. red_flag_alerts.action_taken —— 醫師 acknowledge 紅旗時記錄實際處置，
     對齊 router payload.action_taken ↔ service.acknowledge() 簽章（原本會
     TypeError，醫師無法 acknowledge）。

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-06-14 10:00:00.000000+08:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e2f3a4b5c6d7"
down_revision: Union[str, None] = "d1e2f3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── patients soft-delete ───────────────────────────
    op.add_column(
        "patients",
        sa.Column(
            "is_deleted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "patients",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_patients_is_deleted", "patients", ["is_deleted"])

    # ── red_flag_alerts.action_taken ───────────────────
    op.add_column(
        "red_flag_alerts",
        sa.Column("action_taken", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("red_flag_alerts", "action_taken")
    op.drop_index("ix_patients_is_deleted", table_name="patients")
    op.drop_column("patients", "deleted_at")
    op.drop_column("patients", "is_deleted")
