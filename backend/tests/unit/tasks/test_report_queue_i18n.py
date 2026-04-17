"""
守護 Phase 3 follow-up：Celery SOAP 報告任務
- 模組可正常 import（舊版 `from app.pipelines.soap_generator import generate_soap`
  不存在會 ImportError；新版應直接走 SOAPGenerator class）
- _async_generate 正確將 session.language 傳入 SOAPGenerator.generate()
- 生成成功後 SOAPReport.language 與 session.language 一致
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date, datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest

from app.models.enums import ReportStatus
from app.tasks import report_queue


# ──────────────────────────────────────────────────────────
# Fake ORM objects
# ──────────────────────────────────────────────────────────


def _fake_conversation(seq: int, role: str, text: str) -> SimpleNamespace:
    return SimpleNamespace(
        sequence_number=seq,
        role=SimpleNamespace(value=role),
        content_text=text,
        created_at=datetime(2026, 4, 18, 9, seq, tzinfo=timezone.utc),
    )


def _fake_session(language: str = "zh-TW") -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        language=language,
        chief_complaint_text="排尿困難",
        patient=SimpleNamespace(
            name="Test Patient",
            gender=SimpleNamespace(value="male"),
            date_of_birth=date(1990, 4, 18),
        ),
        chief_complaint=SimpleNamespace(name="排尿困難"),
        conversations=[
            _fake_conversation(1, "assistant", "請描述症狀"),
            _fake_conversation(2, "patient", "小便困難兩天"),
        ],
    )


def _fake_report() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        subjective=None,
        objective=None,
        assessment=None,
        plan=None,
        raw_transcript=None,
        summary=None,
        icd10_codes=None,
        ai_confidence_score=None,
        language=None,
        status=ReportStatus.GENERATING,
        generated_at=None,
    )


class _FakeResult:
    def __init__(self, obj: Any):
        self._obj = obj

    def scalar_one_or_none(self):
        return self._obj


class _FakeDB:
    def __init__(self, session_obj, report_obj):
        self._session_obj = session_obj
        self._report_obj = report_obj
        self._calls = 0
        self.commits = 0

    async def execute(self, stmt):
        self._calls += 1
        # 第一次查 Session、之後查 SOAPReport
        if self._calls == 1:
            return _FakeResult(self._session_obj)
        return _FakeResult(self._report_obj)

    async def commit(self):
        self.commits += 1


class _FakeSessionFactory:
    def __init__(self, db: _FakeDB):
        self._db = db

    def __call__(self):
        return self

    async def __aenter__(self):
        return self._db

    async def __aexit__(self, exc_type, exc, tb):
        return False


# ──────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────


def test_module_imports_cleanly():
    """舊版 `from app.pipelines.soap_generator import generate_soap` 會 ImportError；
    新版應能直接 import 模組與其核心 coroutine。"""

    assert callable(report_queue.generate_soap_report)
    assert asyncio.iscoroutinefunction(report_queue._async_generate)


@pytest.mark.parametrize("language", ["zh-TW", "en-US"])
def test_async_generate_passes_session_language_to_soap_generator(
    monkeypatch, language
):
    session_obj = _fake_session(language=language)
    report_obj = _fake_report()
    db = _FakeDB(session_obj, report_obj)

    monkeypatch.setattr(
        report_queue, "__name__", report_queue.__name__
    )  # noop; anchor for other patches

    import app.core.database as core_db

    monkeypatch.setattr(
        core_db, "async_session_factory", _FakeSessionFactory(db)
    )

    captured: dict[str, Any] = {}

    class _FakeGenerator:
        def __init__(self, _settings):
            pass

        async def generate(
            self,
            transcript,
            patient_info,
            chief_complaint,
            language,
        ):
            captured["transcript"] = transcript
            captured["patient_info"] = patient_info
            captured["chief_complaint"] = chief_complaint
            captured["language"] = language
            return {
                "subjective": {"summary": "s"},
                "objective": {"summary": "o"},
                "assessment": {"summary": "a"},
                "plan": {"summary": "p"},
                "summary": "ok",
                "icd10_codes": ["N39.0"],
                "confidence_score": 0.9,
            }

    import app.pipelines.soap_generator as sg_mod

    monkeypatch.setattr(sg_mod, "SOAPGenerator", _FakeGenerator)

    result = asyncio.run(report_queue._async_generate(str(session_obj.id)))

    assert result["status"] == "generated"
    assert captured["language"] == language
    assert captured["chief_complaint"] == "排尿困難"
    assert captured["patient_info"]["name"] == "Test Patient"
    # transcript 的 role / content 結構正確
    assert captured["transcript"][0]["role"] == "assistant"
    assert captured["transcript"][1]["content"] == "小便困難兩天"
    # Report language 與 session language 一致
    assert report_obj.language == language
    assert report_obj.status == ReportStatus.GENERATED


def test_async_generate_no_conversations_marks_failed(monkeypatch):
    session_obj = _fake_session()
    session_obj.conversations = []
    report_obj = _fake_report()
    db = _FakeDB(session_obj, report_obj)

    import app.core.database as core_db

    monkeypatch.setattr(
        core_db, "async_session_factory", _FakeSessionFactory(db)
    )

    result = asyncio.run(report_queue._async_generate(str(session_obj.id)))

    assert result["status"] == "failed"
    assert result["reason"] == "no_conversations"
    assert report_obj.status == ReportStatus.FAILED


def test_async_generate_session_missing(monkeypatch):
    db = _FakeDB(None, None)
    import app.core.database as core_db

    monkeypatch.setattr(
        core_db, "async_session_factory", _FakeSessionFactory(db)
    )

    result = asyncio.run(report_queue._async_generate("missing-id"))

    assert result["status"] == "failed"
    assert result["reason"] == "session_not_found"
