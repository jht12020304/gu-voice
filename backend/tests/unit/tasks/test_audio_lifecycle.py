"""
守護 P3 #30 音訊生命週期清理：

- 保留期 cutoff 計算正確（AUDIO_RETENTION_DAYS=90）
- dry_run=True 時：不動 DB、不呼叫實際刪除 helper，但仍盤點 would_delete
- 單筆 blob 刪除失敗不會中斷其他筆
- FakeSession 風格對齊 tests/unit/tasks/test_audit_retention.py
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

import pytest

from app.tasks import audio_lifecycle as al
from app.utils.datetime_utils import utc_now


def _run(coro):
    return asyncio.run(coro)


# ──────────────────────────────────────────────────────────
# FakeSession：模仿 audit_retention 的測試
# ──────────────────────────────────────────────────────────

class _FakeResult:
    def __init__(self, rows: list[tuple]):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _FakeSession:
    """收集 execute() 呼叫；第一次 SELECT conversations 回預設列。"""

    def __init__(self, list_rows: list[tuple]):
        self.list_rows = list_rows
        self.executed: list[tuple[str, dict | None]] = []
        self.commits = 0

    async def execute(self, stmt, params: dict | None = None):
        sql = str(stmt)
        self.executed.append((sql, params))
        if "FROM conversations" in sql:
            return _FakeResult(self.list_rows)
        return _FakeResult([])

    async def commit(self):
        self.commits += 1

    async def close(self):
        pass


class _FakeSessionFactory:
    def __init__(self, session: _FakeSession):
        self.session = session

    def __call__(self):
        return self._CM(self.session)

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
    def _install(session: _FakeSession) -> _FakeSessionFactory:
        factory = _FakeSessionFactory(session)
        import app.core.database as db_mod
        monkeypatch.setattr(db_mod, "async_session_factory", factory)
        return factory

    return _install


# ──────────────────────────────────────────────────────────
# 實際測試
# ──────────────────────────────────────────────────────────

def test_retention_days_default_is_90():
    """防止有人誤改預設值；若真要調整請同步更新合規文件。"""
    assert al.AUDIO_RETENTION_DAYS == 90


def test_cutoff_calculation_uses_retention_days(patch_factory, monkeypatch):
    """確保 cutoff 真的以 AUDIO_RETENTION_DAYS 為準（SELECT params 含正確 cutoff）。"""
    session = _FakeSession([])
    patch_factory(session)

    before = utc_now()
    _run(al._async_cleanup(dry_run=True))
    after = utc_now()

    # 第一個 execute 是 SELECT，params["cutoff"] 應落在 [before - N, after - N] 之間
    select_sql, select_params = session.executed[0]
    assert "FROM conversations" in select_sql
    cutoff = select_params["cutoff"]
    assert before - timedelta(days=al.AUDIO_RETENTION_DAYS) <= cutoff
    assert cutoff <= after - timedelta(days=al.AUDIO_RETENTION_DAYS)


def test_dry_run_does_not_call_delete_helper_or_commit(patch_factory, monkeypatch):
    rows = [
        ("conv-1", "https://example.com/bucket/a.webm"),
        ("conv-2", "https://example.com/bucket/b.webm"),
    ]
    session = _FakeSession(rows)
    patch_factory(session)

    called: list[str] = []

    async def _spy(url: str) -> None:
        called.append(url)

    monkeypatch.setattr(al, "_delete_audio_blob", _spy)

    result = _run(al._async_cleanup(dry_run=True))

    assert result["scanned"] == 2
    assert result["would_delete"] == 2
    assert result["deleted"] == 0
    assert result["dry_run"] is True
    # dry_run 不可以碰 blob，也不該 commit
    assert called == []
    assert session.commits == 0
    # dry_run 也不該跑 UPDATE
    update_sqls = [sql for sql, _ in session.executed if sql.strip().startswith("UPDATE")]
    assert update_sqls == []


def test_error_in_one_blob_does_not_abort_others(patch_factory, monkeypatch):
    rows = [
        ("conv-1", "https://example.com/a.webm"),  # 會失敗
        ("conv-2", "https://example.com/b.webm"),  # 成功
        ("conv-3", "https://example.com/c.webm"),  # 成功
    ]
    session = _FakeSession(rows)
    patch_factory(session)

    async def _flaky(url: str) -> None:
        if url.endswith("a.webm"):
            raise RuntimeError("supabase network error")

    monkeypatch.setattr(al, "_delete_audio_blob", _flaky)

    result = _run(al._async_cleanup(dry_run=False))

    assert result["scanned"] == 3
    assert result["would_delete"] == 3
    assert result["deleted"] == 2
    assert len(result["errors"]) == 1
    assert result["errors"][0]["url"] == "https://example.com/a.webm"
    assert "supabase network error" in result["errors"][0]["error"]
    # 非 dry_run → commit 應該被叫一次（逐筆 UPDATE 後）
    assert session.commits == 1
    # 成功的兩筆要送 UPDATE；失敗的那筆不該
    update_sqls = [sql for sql, _ in session.executed if sql.strip().startswith("UPDATE")]
    assert len(update_sqls) == 2


def test_empty_table_returns_safely(patch_factory, monkeypatch):
    session = _FakeSession([])
    patch_factory(session)

    async def _noop(url: str) -> None:  # pragma: no cover — 不該被呼叫
        raise AssertionError("不應該走到這裡")

    monkeypatch.setattr(al, "_delete_audio_blob", _noop)

    result = _run(al._async_cleanup(dry_run=False))
    assert result["scanned"] == 0
    assert result["deleted"] == 0
    assert result["errors"] == []
