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
_is_supabase = bool(settings.DB_HOST) and "supabase.co" in settings.DB_HOST

if _is_supabase:
    _connect_args["ssl"] = "require"
    # PgBouncer 轉譯模式 → 停用 asyncpg 原生 prepared statement cache
    _connect_args["statement_cache_size"] = 0

# SQLAlchemy asyncpg dialect 自己還有一層 prepared statement cache，
# 這個必須走 engine 層參數而非 connect_args，否則會傳錯位置到 asyncpg.connect()
_engine_kwargs: dict = {}
if _is_supabase:
    _engine_kwargs["prepared_statement_cache_size"] = 0

engine = create_async_engine(
    settings.ASYNC_DATABASE_URL,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    echo=(settings.APP_ENV == "development"),
    pool_pre_ping=True,
    connect_args=_connect_args,
    **_engine_kwargs,
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
