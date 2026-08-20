"""soap_reports.patient_facing_localized — 病患語言版的病患面兩欄

新增 `soap_reports.patient_facing_localized`（JSONB, nullable），形狀為
    {"language": "<BCP-47>", "summary": "...", "patient_education": "..."}

背景：不變式 #12 規定 SOAP 主報告與 `soap_reports.language` **一律 zh-TW**
（讀者是院內醫護）。但 `summary` 與 `plan.patient_education` 這兩欄會**原文**
渲染在病患自己的畫面上（不變式 #24），對 en/ja/ko/vi 場次的病患而言等於
拿到一份看不懂的中文摘要。

本欄是主報告之外的**附加產物**：由 `app.tasks.report_queue._async_generate`
在主報告 commit 之後、以一次小 LLM 呼叫把兩欄轉述成場次語言，並過
病患面措辭消毒層的對應語言規則。轉述失敗就留 NULL（前端 fallback 回
中文原文），絕不影響主報告成敗。zh-TW 場次恆為 NULL。

nullable 且無 server_default：NULL 本身就是「沒有在地化版本」的語意，
既有 rows 不需要 backfill。

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-08-20 10:00:00.000000+08:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "d2e3f4a5b6c7"
down_revision: Union[str, None] = "c1d2e3f4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "soap_reports",
        sa.Column(
            "patient_facing_localized",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("soap_reports", "patient_facing_localized")
