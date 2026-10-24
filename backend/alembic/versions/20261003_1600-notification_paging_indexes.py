"""Index notification paging and unread counts without blocking table writes."""
from alembic import op
import sqlalchemy as sa

revision = "smoothness_20261003"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


_INDEXES = [
    ("ix_notifications_user_created_id", "notifications", "(user_id, created_at, id)", None),
    ("ix_notifications_user_unread", "notifications", "(user_id)", "is_read = false"),
]


def _index_validity(conn, name):
    """None＝不存在；True＝有效；False＝INVALID（CONCURRENTLY 中途失敗殘留）。"""
    row = conn.execute(
        sa.text("SELECT i.indisvalid FROM pg_class c JOIN pg_index i ON i.indexrelid = c.oid WHERE c.relname = :n"),
        {"n": name},
    ).first()
    return None if row is None else bool(row[0])


def upgrade():
    # start.sh 每次啟動都重跑 upgrade 並重試；CONCURRENTLY 失敗殘留的 INVALID 索引會讓
    # 單純的 create_index 撞 "already exists"。先查狀態：INVALID → 先 DROP；VALID → 略過。
    with op.get_context().autocommit_block():
        conn = op.get_bind()
        for name, table, cols, where in _INDEXES:
            state = _index_validity(conn, name)
            if state is False:
                conn.execute(sa.text(f"DROP INDEX CONCURRENTLY IF EXISTS {name}"))
                state = None
            if state is None:
                sql = f"CREATE INDEX CONCURRENTLY {name} ON {table} {cols}"
                if where:
                    sql += f" WHERE {where}"
                conn.execute(sa.text(sql))


def downgrade():
    with op.get_context().autocommit_block():
        op.drop_index("ix_notifications_user_unread", table_name="notifications", postgresql_concurrently=True)
        op.drop_index("ix_notifications_user_created_id", table_name="notifications", postgresql_concurrently=True)
