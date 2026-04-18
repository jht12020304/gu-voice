"""chief_complaints *_by_lang JSONB — TODO A2

Phase 3 擴展主訴表為多語 schema，採 expand-migrate-contract 策略：

- name_by_lang          JSONB NOT NULL default '{}'
- description_by_lang   JSONB NULL
- category_by_lang      JSONB NOT NULL default '{}'

Backfill：
  name_by_lang        = {zh-TW: name, en-US: COALESCE(name_en, name)}
  description_by_lang = {zh-TW: description}   （description 為 NULL 時仍 NULL）
  category_by_lang    = {zh-TW: category}      （舊資料 category 為繁中）

**Expand only**：legacy `name / name_en / description / category` 暫留，
由 `app.utils.localized_field.pick()` helper 在讀取時 fallback；
待 admin UI / seed（B1）改走 _by_lang 後以獨立 contract migration drop。

為什麼是 JSONB 而不是 per-language 欄位？
- 加新語言不需改 DDL（避免 `ALTER TABLE ADD COLUMN` 的鎖 + code-gen 污染）
- `pick()` helper 以 dict lookup 讀取，index 非必要（列表查詢以 category 為主）
- 若未來需要全文檢索特定語言，可另加 `gin((name_by_lang -> 'zh-TW'))` partial index

Revision ID: a8b9c0d1e2f3
Revises: f6a7b8c9d0e1
Create Date: 2026-04-18 18:00:00.000000+08:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "a8b9c0d1e2f3"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 新增欄位 ───────────────────────────────────────────────
    op.add_column(
        "chief_complaints",
        sa.Column(
            "name_by_lang",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "chief_complaints",
        sa.Column("description_by_lang", postgresql.JSONB, nullable=True),
    )
    op.add_column(
        "chief_complaints",
        sa.Column(
            "category_by_lang",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )

    # ── Backfill legacy → _by_lang ─────────────────────────────
    # jsonb_strip_nulls 確保 name_en 為 NULL 時不留 {"en-US": null} 垃圾 key。
    op.execute(
        """
        UPDATE chief_complaints
        SET name_by_lang = jsonb_strip_nulls(
            jsonb_build_object(
                'zh-TW', name,
                'en-US', COALESCE(name_en, name)
            )
        )
        WHERE name_by_lang = '{}'::jsonb
        """
    )
    op.execute(
        """
        UPDATE chief_complaints
        SET description_by_lang = jsonb_build_object('zh-TW', description)
        WHERE description IS NOT NULL AND description_by_lang IS NULL
        """
    )
    op.execute(
        """
        UPDATE chief_complaints
        SET category_by_lang = jsonb_build_object('zh-TW', category)
        WHERE category_by_lang = '{}'::jsonb
        """
    )


def downgrade() -> None:
    op.drop_column("chief_complaints", "category_by_lang")
    op.drop_column("chief_complaints", "description_by_lang")
    op.drop_column("chief_complaints", "name_by_lang")
