"""
Alembic 環境設定
- 使用 app.core.config.settings 讀取連線設定
- 支援 async（asyncpg） + Supabase SSL
"""

import asyncio
import os
import sys
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

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

# ── 決定是否需要 SSL（Supabase 強制，本地 Docker 不需要）──────────────
_use_ssl = "supabase" in settings.DB_HOST or "pooler.supabase" in settings.DB_HOST
_connect_args: dict = {
    # PgBouncer transaction pool mode 需停用 asyncpg 原生 prepared statement cache
    "statement_cache_size": 0,
}
if _use_ssl:
    _connect_args["ssl"] = "require"

# ── 建立 async engine（直接使用 settings URL，避免 configparser % 解析問題）──
_async_url = settings.ASYNC_DATABASE_URL


def run_migrations_offline() -> None:
    """Offline mode：不需要實際資料庫連線，只產生 SQL 腳本"""
    context.configure(
        url=_async_url,
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


async def run_async_migrations() -> None:
    """Online mode：使用非同步引擎連接資料庫

    在 Supabase / PgBouncer transaction pool 模式下，必須雙重停用
    prepared statement cache，否則會出現 `__asyncpg_stmt_1__ already exists`：
      - connect_args.statement_cache_size=0  → asyncpg 原生 cache
      - create_async_engine(prepared_statement_cache_size=0) → SQLAlchemy dialect cache（必須是 engine 層參數，不能放 connect_args）
    """
    connectable = create_async_engine(
        _async_url,
        poolclass=pool.NullPool,
        prepared_statement_cache_size=0,
        connect_args=_connect_args,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
