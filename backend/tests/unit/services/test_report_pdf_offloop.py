"""PDF 匯出不得阻塞 event loop。

2026-10-23 實測：一次 ``GET /reports/{id}/pdf``（WeasyPrint 約 1.2 s）期間，
同 worker 的 ``/health`` 由 1 ms 變 956 ms——API worker 同時服務所有 kiosk WS，
等於所有問診音訊在那 1.2 秒內凍結（與先前 bcrypt 搬出 loop 是同一類問題）。

做法：把 WeasyPrint 換成會同步 sleep 的假物件，與一個每 10 ms 計數一次的
協程並跑；若 render 仍在 loop 上同步執行，計數器會停在 0。
"""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.enums import ReportStatus
from app.services import report_service as rs

_RENDER_SECONDS = 0.3


class _SlowHTML:
    def __init__(self, string: str, url_fetcher=None):  # noqa: ARG002
        self.string = string

    def write_pdf(self) -> bytes:
        time.sleep(_RENDER_SECONDS)
        return b"%PDF-1.4 fake"


@pytest.fixture
def fake_weasyprint(monkeypatch):
    import weasyprint
    from concurrent.futures import ThreadPoolExecutor

    monkeypatch.setattr(weasyprint, "HTML", _SlowHTML)
    # 預設 executor 是子行程，monkeypatch 到不了；這支測的是「loop 不被卡住」，用 thread 即可。
    rs.set_pdf_executor(ThreadPoolExecutor(max_workers=1))
    yield
    rs.set_pdf_executor(None)


@pytest.fixture
def fake_report(monkeypatch):
    report = SimpleNamespace(
        id=uuid4(), status=ReportStatus.GENERATED, language="zh-TW",
        subjective={}, objective={}, assessment={}, plan={},
        generated_at=None, review_status=None, session=None, conversations=[],
    )

    async def _get_report(db, report_id, current_user=None):  # noqa: ARG001
        return report

    monkeypatch.setattr(rs.ReportService, "get_report", staticmethod(_get_report))
    monkeypatch.setattr(rs, "_build_report_html", lambda *a, **k: "<html></html>")
    return report


def test_export_pdf_does_not_block_event_loop(fake_weasyprint, fake_report):
    async def scenario():
        ticks = 0
        stop = False

        async def ticker():
            nonlocal ticks
            while not stop:
                await asyncio.sleep(0.01)
                ticks += 1

        task = asyncio.create_task(ticker())
        pdf_bytes, filename = await rs.ReportService.export_pdf(
            db=None, report_id=fake_report.id, current_user=SimpleNamespace(role="admin")
        )
        stop = True
        await task
        return pdf_bytes, filename, ticks

    pdf_bytes, filename, ticks = asyncio.run(scenario())
    assert pdf_bytes.startswith(b"%PDF")
    assert filename.endswith(".pdf")
    # 0.3 s 的 render 期間，10 ms 的 ticker 若還在跑，至少會走十幾步。
    assert ticks >= 10, f"PDF render 阻塞 event loop（ticker 只走了 {ticks} 步）"


def test_default_executor_is_a_recycling_process_pool():
    """預設走子行程（記憶體可回收），且是單 worker（維持一次一份）。"""
    import concurrent.futures

    rs.set_pdf_executor(None)
    ex = rs._pdf_executor()
    try:
        assert isinstance(ex, concurrent.futures.ProcessPoolExecutor)
        assert ex._max_workers == 1
        assert ex._max_tasks_per_child == rs._PDF_TASKS_PER_CHILD
    finally:
        rs.set_pdf_executor(None)
