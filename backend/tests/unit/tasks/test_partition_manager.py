"""
守護分區 runway 可靠性修復：

- `_add_months` / `_target_month_starts`：跨年進位正確、從當月起共 4 個月
- `_async_ensure`：對兩張表 × 4 個月共發 8 個冪等 CREATE（IF NOT EXISTS），
  已存在的分區跳過不重建；單一分區建立失敗不會中斷其他分區
- `ensure_partitions_on_startup`：內部任何例外都被吞掉（只 log），
  保證 API 啟動 hook 失敗不阻擋啟動
"""

from __future__ import annotations

import asyncio
from datetime import date

import pytest

from app.tasks import partition_manager as pm


def _run(coro):
    return asyncio.run(coro)


# ──────────────────────────────────────────────────────────
# 純函式
# ──────────────────────────────────────────────────────────

def test_add_months_basic_and_year_rollover():
    assert pm._add_months(date(2026, 7, 1), 0) == date(2026, 7, 1)
    assert pm._add_months(date(2026, 7, 1), 1) == date(2026, 8, 1)
    assert pm._add_months(date(2026, 11, 1), 2) == date(2027, 1, 1)
    assert pm._add_months(date(2026, 12, 1), 1) == date(2027, 1, 1)
    assert pm._add_months(date(2026, 12, 1), 13) == date(2028, 1, 1)


def test_target_month_starts_four_months_from_current():
    # 月中任何一天都應從當月 1 號起算
    assert pm._target_month_starts(date(2026, 7, 19)) == [
        date(2026, 7, 1),
        date(2026, 8, 1),
        date(2026, 9, 1),
        date(2026, 10, 1),
    ]


def test_target_month_starts_crosses_year_boundary():
    assert pm._target_month_starts(date(2026, 11, 25)) == [
        date(2026, 11, 1),
        date(2026, 12, 1),
        date(2027, 1, 1),
        date(2027, 2, 1),
    ]


def test_partition_runway_is_four_months():
    # runway 縮短會回到「beat 掛一次就撞牆」的故障模式 —— 守住常數
    assert pm.PARTITION_MONTHS_AHEAD == 4


# ──────────────────────────────────────────────────────────
# _async_ensure：注入 FakeSession
# ──────────────────────────────────────────────────────────

class _FakeResult:
    def __init__(self, scalar=None):
        self._scalar = scalar

    def scalar_one_or_none(self):
        return self._scalar


class _FakeSession:
    """收集 execute() 呼叫；pg_class 檢查依 existing 集合回吐存在與否。"""

    def __init__(self, existing: set[str] | None = None, execute_side_effect=None):
        self.existing = existing or set()
        self.executed_sql: list[str] = []
        self.execute_side_effect = execute_side_effect
        self.commits = 0
        self.rollbacks = 0

    async def execute(self, stmt, params: dict | None = None):
        sql = str(stmt)
        self.executed_sql.append(sql)
        if "pg_class" in sql:
            name = (params or {}).get("partition_name")
            return _FakeResult(1 if name in self.existing else None)
        # CREATE：讓 caller 用 side_effect 模擬失敗
        if self.execute_side_effect is not None:
            maybe = self.execute_side_effect(sql)
            if isinstance(maybe, Exception):
                raise maybe
        return _FakeResult()

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1

    async def close(self):
        pass


class _FakeSessionFactory:
    """模仿 `async_session_factory`：回傳 async context manager。"""

    def __init__(self, sess: _FakeSession):
        self.sess = sess

    def __call__(self):
        return self._CM(self.sess)

    class _CM:
        def __init__(self, sess):
            self.sess = sess

        async def __aenter__(self):
            return self.sess

        async def __aexit__(self, *exc):
            await self.sess.close()
            return False


@pytest.fixture
def frozen_today(monkeypatch):
    """冷凍「今天」為 2026-11-25，涵蓋跨年月份。"""

    class _FrozenDate(date):
        @classmethod
        def today(cls):
            return date(2026, 11, 25)

    monkeypatch.setattr(pm, "date", _FrozenDate)


@pytest.fixture
def patch_factory(monkeypatch):
    def _install(sess: _FakeSession):
        import app.core.database as db_mod

        factory = _FakeSessionFactory(sess)
        monkeypatch.setattr(db_mod, "async_session_factory", factory)
        return factory

    return _install


def test_ensure_creates_four_months_for_both_tables(frozen_today, patch_factory):
    sess = _FakeSession()
    patch_factory(sess)

    result = _run(pm._async_ensure())

    expected = [
        f"{t}_{m}"
        for m in ("2026_11", "2026_12", "2027_01", "2027_02")
        for t in ("conversations", "audit_logs")
    ]
    assert result["created"] == expected
    assert result["skipped"] == []
    assert result["months"] == ["2026_11", "2026_12", "2027_01", "2027_02"]

    creates = [s for s in sess.executed_sql if s.startswith("CREATE TABLE")]
    assert len(creates) == 8
    # SQL 冪等 + range 邊界正確（含跨年）
    assert all("IF NOT EXISTS" in s for s in creates)
    assert (
        "CREATE TABLE IF NOT EXISTS conversations_2026_12 "
        "PARTITION OF conversations "
        "FOR VALUES FROM ('2026-12-01') TO ('2027-01-01')" in sess.executed_sql
    )
    assert (
        "CREATE TABLE IF NOT EXISTS audit_logs_2027_02 "
        "PARTITION OF audit_logs "
        "FOR VALUES FROM ('2027-02-01') TO ('2027-03-01')" in sess.executed_sql
    )


def test_ensure_skips_existing_partitions(frozen_today, patch_factory):
    # 當月兩張表都已存在 → 只補其餘 3 個月，重跑冪等
    sess = _FakeSession(existing={"conversations_2026_11", "audit_logs_2026_11"})
    patch_factory(sess)

    result = _run(pm._async_ensure())

    assert result["skipped"] == ["conversations_2026_11", "audit_logs_2026_11"]
    assert len(result["created"]) == 6
    creates = [s for s in sess.executed_sql if s.startswith("CREATE TABLE")]
    assert len(creates) == 6
    assert not any("2026_11" in s for s in creates)


def test_ensure_create_failure_does_not_block_others(frozen_today, patch_factory):
    # 模擬 2026_12 的 conversations 建立失敗（如多 worker 競態）
    def _side(sql: str):
        if "conversations_2026_12" in sql:
            return RuntimeError("duplicate key value")
        return None

    sess = _FakeSession(execute_side_effect=_side)
    patch_factory(sess)

    result = _run(pm._async_ensure())

    assert "conversations_2026_12" not in result["created"]
    assert sess.rollbacks == 1
    # 其餘 7 個分區照樣建立
    assert len(result["created"]) == 7
    assert "audit_logs_2026_12" in result["created"]
    assert "conversations_2027_02" in result["created"]


# ──────────────────────────────────────────────────────────
# 啟動 hook：失敗不阻擋啟動
# ──────────────────────────────────────────────────────────

def test_startup_hook_swallows_ensure_failure(monkeypatch):
    async def _boom():
        raise RuntimeError("DB unreachable")

    monkeypatch.setattr(pm, "_async_ensure", _boom)

    # 不應 raise
    assert _run(pm.ensure_partitions_on_startup()) is None


def test_startup_hook_runs_ensure_on_success(monkeypatch):
    calls = {"n": 0}

    async def _ok():
        calls["n"] += 1
        return {"created": ["conversations_2026_12"], "skipped": [], "months": []}

    monkeypatch.setattr(pm, "_async_ensure", _ok)

    assert _run(pm.ensure_partitions_on_startup()) is None
    assert calls["n"] == 1
