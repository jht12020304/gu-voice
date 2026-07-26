"""補上 auditaction enum 缺少的 language_switch_end_session

Revision ID: c1d2e3f4a5b6
Revises: b7c8d9e0f1a2
Create Date: 2026-07-27

`AuditAction.LANGUAGE_SWITCH_END_SESSION`（models/enums.py）自加入以來從未被任何
migration 寫進 DB 的 `auditaction` enum type。後果：`POST /sessions/{id}/end-for-language-switch`
只要走到寫 audit log 那步就 500——

    asyncpg.exceptions.InvalidTextRepresentationError:
    invalid input value for enum auditaction: "language_switch_end_session"

也就是說**這個端點在生產從來沒有成功過**。先前之所以沒被發現，是因為「已終態場次」
會在更早的地方先回 409，而唯一會走到 audit 的路徑（active 場次真的切語言）在
React 端只會顯示「切換失敗」的 toast，看起來像使用者操作問題。
2026-07-26 把該端點改為冪等（終態回 200）之後，終態路徑也會走到 audit，才讓它浮出來。

`ALTER TYPE ... ADD VALUE` 在 PostgreSQL 12+ 可在交易內執行（本專案為 PG 15）；
本 migration 只新增值、不在同一交易內使用它，因此安全。加 IF NOT EXISTS 以便重跑。

降級刻意 no-op：PostgreSQL 沒有 DROP VALUE，硬要移除得重建整個 type 並改寫所有
引用該 type 的欄位——對一張七年保留的稽核表做這種事，風險遠高於留著一個未使用的值。
"""

from alembic import op

revision = "c1d2e3f4a5b6"
down_revision = "b7c8d9e0f1a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE auditaction ADD VALUE IF NOT EXISTS 'language_switch_end_session'"
    )


def downgrade() -> None:
    # 見 docstring：PostgreSQL 無 DROP VALUE，刻意不做。
    pass
