"""
M15：SOAP append-only 版本快照守護。

- review_report + soap_overrides → 覆寫前寫一筆 REVIEW_OVERRIDE revision
- review_report 僅審閱 metadata（無 overrides）→ 不寫 revision
- generate_report(regenerate=True) 且原報告已 GENERATED → 寫一筆 REGENERATE revision
- generate_report 首次（無 existing）→ 不寫 revision（Celery worker 完成時才寫 INITIAL）
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Optional
from unittest.mock import AsyncMock

import pytest

from app.models.enums import (
    ReportRevisionReason,
    ReportStatus,
    ReviewStatus,
)
from app.services.report_service import ReportService


def _run(coro):
    return asyncio.run(coro)


@dataclass
class _FakeReport:
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    session_id: uuid.UUID = field(default_factory=uuid.uuid4)
    status: ReportStatus = ReportStatus.GENERATED
    review_status: ReviewStatus = ReviewStatus.PENDING
    subjective: Optional[dict] = field(default_factory=lambda: {"chief_complaint": "dysuria"})
    objective: Optional[dict] = field(default_factory=lambda: {"vital": "stable"})
    assessment: Optional[dict] = field(default_factory=lambda: {"clinical_impression": "UTI"})
    plan: Optional[dict] = field(default_factory=lambda: {"treatment": "antibiotics"})
    summary: Optional[str] = "Patient presents with dysuria."
    icd10_codes: Optional[list[str]] = field(default_factory=lambda: ["N39.0"])
    language: str = "zh-TW"
    ai_confidence_score: Optional[Decimal] = Decimal("0.82")
    raw_transcript: Optional[str] = None
    reviewed_by: Optional[uuid.UUID] = None
    reviewed_at: Any = None
    review_notes: Optional[str] = None
    generated_at: Any = None
    updated_at: Any = None


class _FakeDB:
    """極簡 AsyncSession：僅追蹤 add + flush；Service 其餘查詢用 monkeypatch 取代。"""

    def __init__(self) -> None:
        self.added: list[Any] = []
        self.flushed = 0

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        self.flushed += 1

    async def execute(self, stmt: Any):  # default — 會被 monkeypatch 覆蓋
        class _Empty:
            def scalar_one_or_none(self):
                return None

        return _Empty()


@pytest.fixture
def fake_db():
    return _FakeDB()


@pytest.fixture
def fake_report():
    return _FakeReport()


@pytest.fixture
def patch_snapshot(monkeypatch):
    """把 _snapshot_revision 換成 AsyncMock，直接觀察呼叫參數。"""
    mock = AsyncMock(return_value=None)
    monkeypatch.setattr(ReportService, "_snapshot_revision", mock)
    return mock


def test_review_with_overrides_snapshots_pre_override(
    monkeypatch, fake_db, fake_report, patch_snapshot
):
    async def _fake_get_report(db, report_id):
        return fake_report

    monkeypatch.setattr(ReportService, "get_report", staticmethod(_fake_get_report))

    reviewer_id = uuid.uuid4()
    _run(
        ReportService.review_report(
            fake_db,
            report_id=fake_report.id,
            reviewed_by=reviewer_id,
            review_status=ReviewStatus.APPROVED,
            review_notes="looks good",
            soap_overrides={"assessment": {"clinical_impression": "cystitis"}},
        )
    )

    assert patch_snapshot.await_count == 1
    args, kwargs = patch_snapshot.await_args
    # 呼叫簽名：_snapshot_revision(db, report, reason, created_by=...)
    assert args[1] is fake_report
    assert args[2] == ReportRevisionReason.REVIEW_OVERRIDE
    assert kwargs.get("created_by") == reviewer_id
    # 覆寫已發生
    assert fake_report.assessment == {"clinical_impression": "cystitis"}


def test_review_metadata_only_does_not_snapshot(
    monkeypatch, fake_db, fake_report, patch_snapshot
):
    async def _fake_get_report(db, report_id):
        return fake_report

    monkeypatch.setattr(ReportService, "get_report", staticmethod(_fake_get_report))

    _run(
        ReportService.review_report(
            fake_db,
            report_id=fake_report.id,
            reviewed_by=uuid.uuid4(),
            review_status=ReviewStatus.APPROVED,
            review_notes="no content changes",
            soap_overrides=None,
        )
    )

    assert patch_snapshot.await_count == 0


def test_review_with_empty_overrides_dict_does_not_snapshot(
    monkeypatch, fake_db, fake_report, patch_snapshot
):
    async def _fake_get_report(db, report_id):
        return fake_report

    monkeypatch.setattr(ReportService, "get_report", staticmethod(_fake_get_report))

    _run(
        ReportService.review_report(
            fake_db,
            report_id=fake_report.id,
            reviewed_by=uuid.uuid4(),
            review_status=ReviewStatus.REVISION_NEEDED,
            soap_overrides={},
        )
    )

    assert patch_snapshot.await_count == 0


def test_regenerate_existing_report_snapshots_before_reset(
    monkeypatch, fake_db, fake_report, patch_snapshot
):
    """generate_report(regenerate=True) 且已 GENERATED → 先 snapshot 再 reset。"""
    fake_report.status = ReportStatus.GENERATED

    # 模擬 db.execute(select(SOAPReport).where(session_id=...)) 回傳既有 report
    class _Result:
        def __init__(self, v):
            self._v = v

        def scalar_one_or_none(self):
            return self._v

    async def _fake_execute(stmt):
        return _Result(fake_report)

    monkeypatch.setattr(fake_db, "execute", _fake_execute)

    # Celery.delay 避免真的送任務
    import app.tasks.report_queue as rq

    monkeypatch.setattr(rq.generate_soap_report, "delay", lambda *a, **kw: None)

    requested_by = uuid.uuid4()
    _run(
        ReportService.generate_report(
            fake_db,
            session_id=fake_report.session_id,
            regenerate=True,
            requested_by=requested_by,
        )
    )

    assert patch_snapshot.await_count == 1
    args, kwargs = patch_snapshot.await_args
    assert args[1] is fake_report
    assert args[2] == ReportRevisionReason.REGENERATE
    assert kwargs.get("created_by") == requested_by
    # reset 後，現有 report 的內容欄位應該被清空、狀態回到 GENERATING
    assert fake_report.status == ReportStatus.GENERATING
    assert fake_report.subjective is None
    assert fake_report.assessment is None
    assert fake_report.review_status == ReviewStatus.PENDING


def test_regenerate_empty_existing_report_does_not_snapshot(
    monkeypatch, fake_db, patch_snapshot
):
    """舊 report 還沒有內容（例如上次 generating 失敗）→ 不寫 revision。"""
    empty = _FakeReport(
        status=ReportStatus.FAILED,
        subjective=None,
        objective=None,
        assessment=None,
        plan=None,
        summary=None,
    )

    class _Result:
        def __init__(self, v):
            self._v = v

        def scalar_one_or_none(self):
            return self._v

    async def _fake_execute(stmt):
        return _Result(empty)

    monkeypatch.setattr(fake_db, "execute", _fake_execute)

    import app.tasks.report_queue as rq

    monkeypatch.setattr(rq.generate_soap_report, "delay", lambda *a, **kw: None)

    _run(
        ReportService.generate_report(
            fake_db,
            session_id=empty.session_id,
            regenerate=True,
        )
    )

    assert patch_snapshot.await_count == 0


def test_generate_first_time_does_not_snapshot(monkeypatch, fake_db, patch_snapshot):
    """沒有 existing → 直接建 row，snapshot 由 Celery 完成時才寫。"""

    class _Result:
        def scalar_one_or_none(self):
            return None

    async def _fake_execute(stmt):
        return _Result()

    monkeypatch.setattr(fake_db, "execute", _fake_execute)

    import app.tasks.report_queue as rq

    monkeypatch.setattr(rq.generate_soap_report, "delay", lambda *a, **kw: None)

    _run(
        ReportService.generate_report(
            fake_db,
            session_id=uuid.uuid4(),
            regenerate=False,
        )
    )

    assert patch_snapshot.await_count == 0
    # 新 row 應該被加到 session
    assert len(fake_db.added) == 1
