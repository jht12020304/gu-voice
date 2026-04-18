"""soap_reports.icd10_verified — M3 ICD-10 驗證旗標

新增 `soap_reports.icd10_verified` 布林欄位，
由 `app.pipelines.icd10_validator.validate_icd10_codes` 填入，
代表 LLM 輸出的 ICD-10 碼是否通過泌尿科白名單 + symptom↔code 對映雙檢。

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-04-18 17:30:00.000000+08:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 既有 rows 一律視為未驗證（server_default='false'）。
    # NOT NULL 以免前端要多處理 None。
    op.add_column(
        "soap_reports",
        sa.Column(
            "icd10_verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("soap_reports", "icd10_verified")
