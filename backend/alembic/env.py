"""
Alembic 環境設定
- 使用 app.core.config.settings 讀取連線設定
- 走 sync psycopg2 driver（asyncpg 與 PgBouncer transaction pool 不相容，
  會遇到 __asyncpg_stmt_1__ 衝突；migrations 不需要非同步）
- Supabase 連線會強制 SSL
"""

import os
import sys
from logging.config import fileConfig

from sqlalchemy import create_engine, pool
from sqlalchemy.engine import Connection

from alembic import context

# ── 確保 backend 根目錄在 sys.path 裡 ──────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── 載入 app 設定與所有 ORM Model ──────────────────────────────────
from app.core.config import settings  # noqa: E402
from app.core.database import Base    # noqa: E402
import app.models  # noqa: E402, F401  # 確保所有 model 都被 import 並註冊到 Base.metadata

# ── Alembic Config 物件 ─────────────────────────────────────────────
config = context.config

# 從 alembic.ini 設定日誌
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ── Target Metadata：指向所有 ORM Model ────────────────────────────
target_metadata = Base.metadata

# ── 建立 sync engine（psycopg2 driver）──────────────────────────
_use_ssl = "supabase" in settings.DB_HOST or "pooler.supabase" in settings.DB_HOST
_sync_url = settings.DATABASE_URL  # postgresql:// (defaults to psycopg2)
_connect_args: dict = {}
if _use_ssl:
    _connect_args["sslmode"] = "require"


def run_migrations_offline() -> None:
    """Offline mode：不需要實際資料庫連線，只產生 SQL 腳本"""
    context.configure(
        url=_sync_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Online mode：sync engine + psycopg2，PgBouncer transaction mode 下安全"""
    connectable = create_engine(
        _sync_url,
        poolclass=pool.NullPool,
        connect_args=_connect_args,
    )
    with connectable.connect() as connection:
        do_run_migrations(connection)
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
