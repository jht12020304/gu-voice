"""儀表板熱路徑索引：sessions(status, created_at)、red_flag_alerts 未確認 partial index。

每次場次狀態變更都會重算 queue/stats（dashboard_handler.broadcast_queue_and_stats）：
排隊清單 `WHERE status IN (...) ORDER BY created_at`、今日場次數 `created_at` 範圍、
待確認紅旗 `acknowledged_by IS NULL`——先前只有 doctor_id/patient_id/is_deleted 索引。

CONCURRENTLY + 自我修復：`start.sh` 每次容器啟動都跑 `alembic upgrade head` 並重試；
CONCURRENTLY 中途失敗會留下 INVALID 索引，單純重跑會撞 "relation already exists"。
這裡先查 pg_index：INVALID 就先 DROP 再建，已 VALID 就略過。
"""
from alembic import op
import sqlalchemy as sa

revision = "audit_20261024_idx"
down_revision = "smoothness_20261003"
branch_labels = None
depends_on = None

_INDEXES = [
    ("ix_sessions_status_created_at", "sessions", "(status, created_at)", None),
    ("ix_red_flag_alerts_pending_created", "red_flag_alerts", "(created_at)", "acknowledged_by IS NULL"),
]


def _index_validity(conn, name):
    """None＝不存在；True＝存在且有效；False＝存在但 INVALID（CONCURRENTLY 中途失敗）。"""
    row = conn.execute(
        sa.text("SELECT i.indisvalid FROM pg_class c JOIN pg_index i ON i.indexrelid = c.oid WHERE c.relname = :n"),
        {"n": name},
    ).first()
    return None if row is None else bool(row[0])


def _create_concurrently(conn, name, table, cols, where):
    state = _index_validity(conn, name)
    if state is False:
        conn.execute(sa.text(f"DROP INDEX CONCURRENTLY IF EXISTS {name}"))
        state = None
    if state is None:
        sql = f"CREATE INDEX CONCURRENTLY {name} ON {table} {cols}"
        if where:
            sql += f" WHERE {where}"
        conn.execute(sa.text(sql))


def upgrade():
    with op.get_context().autocommit_block():
        conn = op.get_bind()
        for name, table, cols, where in _INDEXES:
            _create_concurrently(conn, name, table, cols, where)


def downgrade():
    with op.get_context().autocommit_block():
        conn = op.get_bind()
        for name, _table, _cols, _where in reversed(_INDEXES):
            conn.execute(sa.text(f"DROP INDEX CONCURRENTLY IF EXISTS {name}"))
