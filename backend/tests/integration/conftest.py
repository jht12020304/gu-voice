"""
整合測試共用設施 —— 真 Postgres，驗 row-level 授權限縮在 SQL 層真的隔離資料。

設計取捨（與 tests/unit/services/test_session_authorization.py 一致）:
- 不依賴 pytest-asyncio（環境未裝）。改用 `asyncio.run(...)` 把 coroutine 跑在
  sync test 內，由 `run_with_session` 統一開 AsyncSession 並善後。
- 對著一個獨立的測試引擎（TEST_DATABASE_URL，預設指向已 migrate 的本機 PG），
  *不* 重用 app.core.database.engine —— 避免測試把 cleanup 推到生產設定的 DB。
- DB 連不上時整個 module SKIP（collection 期），CI 沒 DB 也維持綠燈。

每個測試自己 seed 自己要的列並在 finally 清掉（FK 反序刪除）。引擎用 NullPool，
確保連線不被 pool 留住、測試結束乾淨關閉。
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Awaitable, Callable, TypeVar

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

# 確保所有 ORM model 都被 import 過（mapper 完整註冊），避免 relationship 解析失敗。
import app.models  # noqa: F401

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/gu_voice",
)

_T = TypeVar("_T")


def _db_reachable(url: str) -> bool:
    """快速探測 DB 是否可連線（open + SELECT 1 + close）。

    任何例外都視為不可達 → 讓 module 被 skip，而非報錯。
    """
    async def _probe() -> bool:
        engine = create_async_engine(url, poolclass=NullPool)
        try:
            async with engine.connect() as conn:
                from sqlalchemy import text

                await conn.execute(text("SELECT 1"))
            return True
        finally:
            await engine.dispose()

    try:
        return asyncio.run(_probe())
    except Exception:
        return False


# Collection 期就決定要不要 skip：DB 不可達 → 整個 module skip，CI 無 DB 仍綠燈。
DB_AVAILABLE = _db_reachable(TEST_DATABASE_URL)

requires_db = pytest.mark.skipif(
    not DB_AVAILABLE,
    reason=(
        "integration DB unreachable at "
        f"{TEST_DATABASE_URL!r}; set TEST_DATABASE_URL to a migrated Postgres"
    ),
)


def make_engine():
    """建立一個對著測試 DB 的獨立 async 引擎（NullPool，乾淨關閉）。"""
    return create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)


def run_with_session(coro_fn: Callable[[AsyncSession], Awaitable[_T]]) -> _T:
    """在 sync test 內開一個 AsyncSession 跑 coroutine，跑完一律 rollback + 關閉。

    `coro_fn` 形如 `async def body(session): ...`。body 內若有 seed，請於自身
    finally 清理（cleanup 須 commit，因為這層只負責把『未明確 commit 的』殘留
    rollback 掉，並非依賴它回滾已 commit 的 seed）。

    回傳 body 的回傳值，方便 assert。
    """

    async def _runner() -> _T:
        engine = make_engine()
        session_factory = async_sessionmaker(
            bind=engine, class_=AsyncSession, expire_on_commit=False
        )
        session = session_factory()
        try:
            return await coro_fn(session)
        finally:
            await session.rollback()
            await session.close()
            await engine.dispose()

    return asyncio.run(_runner())


async def delete_all(session: AsyncSession, instances: list[Any]) -> None:
    """依給定（已是 FK 反序）順序刪除 seed 列並 commit。容忍已不存在者。"""
    for obj in instances:
        try:
            await session.delete(obj)
        except Exception:
            # 物件可能已 expire / detach；改用 PK 直接刪。
            pass
    await session.commit()
