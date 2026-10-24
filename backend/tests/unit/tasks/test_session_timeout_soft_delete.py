"""逾時清理任務必須套 ``session_not_deleted()``（CLAUDE.md 軟刪除鐵律）。

2026-10-23 稽核發現 ``_async_check`` 的 stale-session SELECT 沒有軟刪除過濾：
admin 已軟刪除、但狀態仍是 in_progress 的場次會被逾時任務 CAS 成 cancelled，
然後以 ``session_status_changed`` 廣播回醫師儀表板——使用者以為刪掉的場次
從這條路徑漏回畫面。

這支用既有的 FakeSession 把 SELECT 的 SQL 字面抓下來，斷言它帶著
``sessions.is_deleted`` 條件；真 Postgres 行為由
``tests/integration/test_session_timeout_soft_delete_pg.py`` 釘住。
"""

from __future__ import annotations

import asyncio

from app.tasks import session_timeout as st
from tests.unit.tasks.test_session_timeout import _FakeSession, patch_factory, spy_broadcasts  # noqa: F401


def test_stale_session_select_filters_soft_deleted(patch_factory, spy_broadcasts):  # noqa: F811
    sess = _FakeSession(stale_rows=[])
    patch_factory(sess)

    asyncio.run(st._async_check())

    selects = [sql for sql in sess.executed_sql if sql.lstrip().upper().startswith("SELECT")]
    assert selects, "逾時任務應先 SELECT 逾時場次"
    assert "is_deleted" in selects[0], (
        "逾時場次 SELECT 缺 session_not_deleted()：軟刪除場次會被逾時取消並廣播回儀表板"
    )
