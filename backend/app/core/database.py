"""
資料庫連線設定 — Async SQLAlchemy 2.0
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

# 建立非同步引擎
# 雲端環境（Supabase）強制需要 SSL，本地 Docker 不需要
_connect_args: dict = {}
# Supabase 的 pooler host 形如 `aws-1-<region>.pooler.supabase.com`，不是
# `*.supabase.co` —— 早期判斷只比 "supabase.co" 會漏掉 pooler，導致在 Railway
# 生產環境上 DuplicatePreparedStatementError。這裡改比對較寬：只要 host 含
# "supabase" 或 "pooler"（任何透過 PgBouncer 連上 Postgres 的情境）都算。
_db_host = (settings.DB_HOST or "").lower()
_is_supabase = ("supabase" in _db_host) or ("pooler" in _db_host)

if _is_supabase:
    _connect_args["ssl"] = "require"
    # PgBouncer transaction pool mode → 停用 asyncpg 原生 prepared statement cache
    _connect_args["statement_cache_size"] = 0

# SQLAlchemy asyncpg dialect 自己還有一層 prepared statement cache，
# 這個是 *dialect* 參數，只能透過 URL query string 注入
# （不是 create_async_engine kwarg，也不是 connect_args）
_async_url = settings.ASYNC_DATABASE_URL
if _is_supabase:
    sep = "&" if "?" in _async_url else "?"
    _async_url = f"{_async_url}{sep}prepared_statement_cache_size=0"

engine = create_async_engine(
    _async_url,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    echo=(settings.APP_ENV == "development"),
    pool_pre_ping=True,
    connect_args=_connect_args,
)

# 建立 session 工廠
async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """所有 ORM Model 的基底類別"""
    pass


@asynccontextmanager
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """取得資料庫 session（上下文管理器版本）"""
    session = async_session_factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
