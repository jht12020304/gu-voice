"""
WS 路徑 `_generate_soap_report_async` 的觸發語意測試（P0-2 架構修復，2026-07-19）。

此函式已從「inline LLM 生成 + 寫入」改為「建 GENERATING row → 派 Celery
generate_soap_report」。內容欄位（language / icd10_verified / symptom_id /
red_flags 注入）的持久化測試已隨單一生成路徑移至
tests/unit/tasks/test_report_queue_i18n.py（Celery 路徑）。

本檔守護觸發器的四個承重點：
- 無既有報告 → 建立 GENERATING row（status/review_status 正確）並派送任務。
- 已有報告（任何狀態）→ 不重建、不重派（多結束路徑冪等）。
- 建 row 撞 UNIQUE（IntegrityError）→ 冪等略過、不派送、不拋。
- 派送失敗（broker 掛）→ 不拋（row 已標 GENERATING，可由 regenerate 補救）。

Mock 策略：函式內為 function-local import ⇒ patch 來源模組屬性
（app.core.database.get_db_session / app.tasks.report_queue.generate_soap_report）。
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

from sqlalchemy.exc import IntegrityError

import app.core.database as core_db
import app.tasks.report_queue as rq_mod
import app.websocket.conversation_handler as ch
from app.models.enums import ReportStatus, ReviewStatus


class _FakeResult:
    def __init__(self, obj: Any = None):
        self._obj = obj

    def scalar_one_or_none(self):
        return self._obj


class _FakeDB:
    """最小 AsyncSession 替身：execute 回存在性查詢結果、add 收集、可指定 commit 失敗。"""

    def __init__(self, existing_soap_id: Any = None, commit_error: Exception | None = None):
        self.existing_soap_id = existing_soap_id
        self.commit_error = commit_error
        self.added: list[Any] = []
        self.committed = False

    async def execute(self, stmt: Any):
        return _FakeResult(self.existing_soap_id)

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        if self.commit_error is not None:
            raise self.commit_error
        self.committed = True

    async def rollback(self) -> None:
        pass


def _run(monkeypatch, *, existing_soap_id=None, commit_error=None, delay_error=None):
    db = _FakeDB(existing_soap_id=existing_soap_id, commit_error=commit_error)

    @asynccontextmanager
    async def _fake_get_db_session():
        # 模擬 get_db_session 的 context 結束自動 commit 行為
        yield db
        await db.commit()

    monkeypatch.setattr(core_db, "get_db_session", _fake_get_db_session)

    delay_calls: list[str] = []

    def _delay(session_id: str):
        if delay_error is not None:
            raise delay_error
        delay_calls.append(session_id)

    monkeypatch.setattr(
        rq_mod, "generate_soap_report", SimpleNamespace(delay=_delay)
    )

    session_id = str(uuid.uuid4())
    asyncio.run(ch._generate_soap_report_async(session_id=session_id))
    return SimpleNamespace(db=db, delay_calls=delay_calls, session_id=session_id)


def test_creates_generating_row_and_dispatches(monkeypatch):
    r = _run(monkeypatch)
    assert len(r.db.added) == 1
    report = r.db.added[0]
    assert report.status == ReportStatus.GENERATING
    assert report.review_status == ReviewStatus.PENDING
    assert str(report.session_id) == r.session_id
    assert r.db.committed is True
    assert r.delay_calls == [r.session_id]


def test_existing_report_skips_create_and_dispatch(monkeypatch):
    """已有報告（含 GENERATING 中）→ 不重建不重派；多結束路徑同時觸發的冪等。"""
    r = _run(monkeypatch, existing_soap_id=uuid.uuid4())
    assert r.db.added == []
    assert r.delay_calls == []


def test_unique_collision_swallowed_no_dispatch(monkeypatch):
    """早期檢查與 insert 間的競態：UNIQUE 撞擊視為另一路徑已觸發，不派送不拋。"""
    err = IntegrityError("dup", params=None, orig=Exception("unique"))
    r = _run(monkeypatch, commit_error=err)
    assert r.delay_calls == []


def test_dispatch_failure_does_not_raise(monkeypatch):
    """broker 掛：row 已 GENERATING（狀態可見），派送失敗只 log 不拋。"""
    r = _run(monkeypatch, delay_error=RuntimeError("broker down"))
    assert len(r.db.added) == 1  # row 仍建立
    assert r.delay_calls == []


def test_generic_db_failure_does_not_raise(monkeypatch):
    """DB 失敗：不拋（呼叫端是 fire-and-forget create_task），且不派送孤兒任務。"""
    r = _run(monkeypatch, commit_error=RuntimeError("db down"))
    assert r.delay_calls == []
