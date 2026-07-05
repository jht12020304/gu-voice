"""soap_report_revisions.raw_transcript

數據盤點缺口修復（docs/session_data_inventory.md §11-9）：
revision 快照原本不含 raw_transcript，regenerate 覆寫主表逐字稿後
「當時 LLM 看到的輸入」無法追溯。補上 nullable Text 欄；舊 revision
維持 NULL（可由 conversations 表重組還原）。

Revision ID: b7c8d9e0f1a2
Revises: a5b6c7d8e9f0
Create Date: 2026-07-06 10:00:00.000000+08:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b7c8d9e0f1a2"
down_revision: Union[str, None] = "a5b6c7d8e9f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "soap_report_revisions",
        sa.Column("raw_transcript", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("soap_report_revisions", "raw_transcript")
