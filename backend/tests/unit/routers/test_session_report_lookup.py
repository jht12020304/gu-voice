"""GET /sessions/{id}/report：一趟取回場次報告（取代客戶端 list→get 兩趟）。

授權與軟刪除走既有 `ReportService.get_report`；沒有報告 → 404。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.exceptions import NotFoundException
from app.services import report_service as rs


class _Result:
    def __init__(self, v):
        self._v = v

    def scalar_one_or_none(self):
        return self._v


class _DB:
    def __init__(self, report_id):
        self.report_id = report_id
        self.statements = []

    async def execute(self, stmt):
        self.statements.append(str(stmt))
        return _Result(self.report_id)


def test_returns_detail_via_get_report(monkeypatch):
    rid, sid = uuid4(), uuid4()
    seen = {}

    async def _get_report(db, report_id, current_user=None):
        seen["report_id"] = report_id
        return SimpleNamespace(id=report_id)

    monkeypatch.setattr(rs.ReportService, "get_report", staticmethod(_get_report))
    db = _DB(rid)
    out = asyncio.run(rs.ReportService.get_report_by_session(db, session_id=sid, current_user=SimpleNamespace(role="admin")))
    assert out.id == rid and seen["report_id"] == rid
    assert "is_deleted" in db.statements[0], "場次查詢必須套軟刪除過濾"


def test_missing_report_is_404():
    db = _DB(None)
    with pytest.raises(NotFoundException):
        asyncio.run(rs.ReportService.get_report_by_session(db, session_id=uuid4(), current_user=None))
