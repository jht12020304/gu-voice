"""
守護 P2 #17 audit_logs 分區保留：

- `_parse_suffix`：只認 `audit_logs_YYYY_MM`，亂格式回 None
- `_cutoff_yyyymm`：RETENTION_YEARS=7 時，2026-04 → 201904
- `_async_cleanup`：用 FakeSession 注入分區清單；只對 cutoff 以前的跑 DETACH+DROP，
  保留內與亂格式跳過；錯誤不會中斷其他分區處理
"""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Any

import pytest

from app.tasks import audit_retention as ar


def _run(coro):
    return asyncio.run(coro)


# ──────────────────────────────────────────────────────────
# 純函式
# ──────────────────────────────────────────────────────────

def test_parse_suffix_valid():
    assert ar._parse_suffix("audit_logs_2019_03") == 201903
    assert ar._parse_suffix("audit_logs_2026_12") == 202612


def test_parse_suffix_rejects_bad_format():
    assert ar._parse_suffix("audit_logs_2019") is None
    assert ar._parse_suffix("audit_logs_2019_03_extra") is None
    assert ar._parse_suffix("audit_logs_aa_bb") is None
    assert ar._parse_suffix("audit_logs_2019_13") is None  # 月份越界
    assert ar._parse_suffix("conversations_2019_03") is None  # 非目標表
    assert ar._parse_suffix("audit_logs_") is None


def test_cutoff_yyyymm():
    # 2026-04 - 7 年 = 2019-04
    assert ar._cutoff_yyyymm(date(2026, 4, 18)) == 201904
    assert ar._cutoff_yyyymm(date(2026, 1, 1)) == 201901
    assert ar._cutoff_yyyymm(date(2025, 12, 31)) == 201812


# ──────────────────────────────────────────────────────────
# _async_cleanup：注入 FakeSession
# ──────────────────────────────────────────────────────────

class _FakeResult:
    def __init__(self, rows: list[tuple]):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _FakeSession:
    """收集 execute() 呼叫，依序回吐預設結果。"""

    def __init__(self, list_rows: list[tuple], execute_side_effect=None):
        self.list_rows = list_rows
        self.executed_sql: list[str] = []
        self.execute_side_effect = execute_side_effect
        self.commits = 0
        self._first_list_call = True

    async def execute(self, stmt, params: dict | None = None):
        sql = str(stmt)
        self.executed_sql.append(sql)
        # 第一次 SELECT：列分區
        if "pg_inherits" in sql:
            return _FakeResult(self.list_rows)
        # 其他（DETACH / DROP）：讓 caller 用 side_effect 打斷模擬失敗
        if self.execute_side_effect is not None:
            maybe = self.execute_side_effect(sql)
            if isinstance(maybe, Exception):
                raise maybe
        return _FakeResult([])

    async def commit(self):
        self.commits += 1

    async def close(self):
        pass


class _FakeSessionFactory:
    """模仿 `async_session_factory`：每次呼叫回新 session 的 async context manager。"""

    def __init__(self, session_provider):
        self.session_provider = session_provider
        self.sessions: list[_FakeSession] = []

    def __call__(self):
        sess = self.session_provider()
        self.sessions.append(sess)
        return self._CM(sess)

    class _CM:
        def __init__(self, sess):
            self.sess = sess

        async def __aenter__(self):
            return self.sess

        async def __aexit__(self, *exc):
            await self.sess.close()
            return False


@pytest.fixture
def patch_factory(monkeypatch):
    """把 `app.core.database.async_session_factory` 換成 FakeSessionFactory。"""

    def _install(session_provider):
        factory = _FakeSessionFactory(session_provider)
        import app.core.database as db_mod
        monkeypatch.setattr(db_mod, "async_session_factory", factory)
        return factory

    return _install


def test_cleanup_drops_old_and_keeps_new(patch_factory, monkeypatch):
    # 冷凍「今天」為 2026-04-18 → cutoff = 201904；
    # 201903 應刪、201904 保留、202601 保留
    class _FrozenDate:
        @staticmethod
        def today():
            return date(2026, 4, 18)

    monkeypatch.setattr(ar, "date", _FrozenDate)

    rows = [
        ("audit_logs_2019_03",),
        ("audit_logs_2019_04",),
        ("audit_logs_2026_01",),
        ("conversations_2019_03",),  # 非目標：enumerate 本就不會撈到，但加進來確認 _parse_suffix 把關
        ("audit_logs_bad_name",),
    ]

    def _provide():
        return _FakeSession(rows)

    factory = patch_factory(_provide)

    result = _run(ar._async_cleanup())

    assert result["cutoff_yyyymm"] == 201904
    assert result["retention_years"] == 7
    assert result["detached"] == ["audit_logs_2019_03"]
    assert result["dropped"] == ["audit_logs_2019_03"]
    assert result["errors"] == []

    # 每個分區刪除會開 2 個新 session（detach + drop），list 查詢 1 個 → 共 3 個
    assert len(factory.sessions) == 3

    # 真的送過 DETACH + DROP
    all_sql = "\n".join(s for sess in factory.sessions for s in sess.executed_sql)
    assert "DETACH PARTITION audit_logs_2019_03" in all_sql
    assert "DROP TABLE IF EXISTS audit_logs_2019_03" in all_sql


def test_cleanup_detach_failure_does_not_block_others(patch_factory, monkeypatch):
    class _FrozenDate:
        @staticmethod
        def today():
            return date(2026, 4, 18)

    monkeypatch.setattr(ar, "date", _FrozenDate)

    rows = [("audit_logs_2019_02",), ("audit_logs_2019_03",)]

    call_count = {"n": 0}

    def _provide():
        # 第一次 DETACH（2019_02）失敗；第二次 DROP 不會跑；
        # 第三次開始處理 2019_03，全部成功
        def _side(sql: str):
            if "DETACH" in sql and "2019_02" in sql:
                return RuntimeError("lock timeout")
            return None

        return _FakeSession(rows, execute_side_effect=_side)

    factory = patch_factory(_provide)
    result = _run(ar._async_cleanup())

    assert "audit_logs_2019_03" in result["dropped"]
    assert result["detached"] == ["audit_logs_2019_03"]
    assert any(e["partition"] == "audit_logs_2019_02" and e["stage"] == "detach" for e in result["errors"])


def test_cleanup_empty_returns_safely(patch_factory, monkeypatch):
    class _FrozenDate:
        @staticmethod
        def today():
            return date(2026, 4, 18)

    monkeypatch.setattr(ar, "date", _FrozenDate)

    def _provide():
        return _FakeSession([])

    patch_factory(_provide)
    result = _run(ar._async_cleanup())

    assert result["detached"] == []
    assert result["dropped"] == []
    assert result["errors"] == []
