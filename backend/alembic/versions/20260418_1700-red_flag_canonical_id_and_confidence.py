"""red_flag_canonical_id_and_confidence

TODO-E6 + TODO-M8：紅旗規則 i18n 三項 P0。

1. red_flag_rules.canonical_id（NOT NULL, UNIQUE）
   - 跨語言穩定的 snake_case 標識符，取代 name 成為 dedup key
   - 既有資料以 name 作 seed backfill；隨後加 NOT NULL + UNIQUE
2. red_flag_rules.display_title_by_lang（JSONB, nullable）
   - 多語言 display title（zh-TW / en-US），alert serializer 按
     Accept-Language 在此查詢
3. red_flag_alerts.canonical_id（nullable, indexed）
   - 建立 alert 時 snapshot 當下紅旗的 canonical_id；舊資料 NULL
4. red_flag_alerts.confidence（redflagconfidence enum, default 'rule_hit'）
   - rule_hit / semantic_only / uncovered_locale 三級信心
   - 非 rule_hit 代表 i18n fail-safe 觸發；前端 UI 應顯示 banner

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-04-18 17:00:00.000000+08:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. red_flag_rules.canonical_id / display_title_by_lang ────────
    op.add_column(
        "red_flag_rules",
        sa.Column("canonical_id", sa.String(100), nullable=True),
    )
    op.add_column(
        "red_flag_rules",
        sa.Column("display_title_by_lang", postgresql.JSONB, nullable=True),
    )

    # Backfill：既有 row 以 name 作 seed（slugify 簡化版：去空白 / 小寫）。
    # 若 name 為英文 / 混語，仍以轉小寫後的 name 當臨時 canonical；
    # 管理員可之後手動覆寫為正式 snake_case。
    op.execute(
        """
        UPDATE red_flag_rules
        SET canonical_id = LOWER(REGEXP_REPLACE(name, '[^A-Za-z0-9]+', '_', 'g'))
        WHERE canonical_id IS NULL
        """
    )
    # 去重：若 slugify 後撞名，加 id 後綴確保 UNIQUE 不失敗
    op.execute(
        """
        UPDATE red_flag_rules
        SET canonical_id = canonical_id || '_' || SUBSTRING(id::text, 1, 8)
        WHERE canonical_id IN (
            SELECT canonical_id FROM red_flag_rules
            GROUP BY canonical_id HAVING COUNT(*) > 1
        )
        """
    )

    op.alter_column(
        "red_flag_rules", "canonical_id", nullable=False
    )
    op.create_unique_constraint(
        "uq_red_flag_rules_canonical_id",
        "red_flag_rules",
        ["canonical_id"],
    )

    # ── 2. red_flag_alerts.canonical_id（nullable, indexed） ───────────
    op.add_column(
        "red_flag_alerts",
        sa.Column("canonical_id", sa.String(100), nullable=True),
    )
    op.create_index(
        "ix_red_flag_alerts_canonical_id",
        "red_flag_alerts",
        ["canonical_id"],
    )

    # ── 3. red_flag_alerts.confidence（enum） ────────────────────────
    # redflagconfidence enum：走 lowercase values（與其他 enums 一致）。
    op.execute(
        "DO $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'redflagconfidence') THEN "
        "CREATE TYPE redflagconfidence AS ENUM "
        "('rule_hit', 'semantic_only', 'uncovered_locale'); "
        "END IF; END $$;"
    )
    confidence_enum = postgresql.ENUM(
        "rule_hit",
        "semantic_only",
        "uncovered_locale",
        name="redflagconfidence",
        create_type=False,
    )
    op.add_column(
        "red_flag_alerts",
        sa.Column(
            "confidence",
            confidence_enum,
            server_default=sa.text("'rule_hit'"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    # ── 3. red_flag_alerts.confidence ─────────────────────────────────
    op.drop_column("red_flag_alerts", "confidence")
    op.execute("DROP TYPE IF EXISTS redflagconfidence")

    # ── 2. red_flag_alerts.canonical_id ───────────────────────────────
    op.drop_index("ix_red_flag_alerts_canonical_id", "red_flag_alerts")
    op.drop_column("red_flag_alerts", "canonical_id")

    # ── 1. red_flag_rules.canonical_id / display_title_by_lang ────────
    op.drop_constraint(
        "uq_red_flag_rules_canonical_id", "red_flag_rules", type_="unique"
    )
    op.drop_column("red_flag_rules", "display_title_by_lang")
    op.drop_column("red_flag_rules", "canonical_id")
