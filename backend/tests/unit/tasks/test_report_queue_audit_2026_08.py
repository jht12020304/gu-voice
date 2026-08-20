"""
2026-08-20 稽核修復的 Celery 側回歸測試。

三件事，共通點都是「報告已經生成／已經失敗，但沒有人知道」：

## SO-4：`report_not_found` 直接放棄

不變式 #13 規定 SOAP 生成是「API 行程建 GENERATING row → 派 Celery」。
這兩件事分屬**不同交易**，worker 快一步就會查不到列。舊版在這個分支
`return {"reason": "report_not_found"}` —— 不重試、不標 FAILED，於是：
OpenAI 的錢花掉了、生成好的 SOAP **整份丟棄**，而報告列隨後才出現、
永遠停在 GENERATING。這是時序問題不是資料問題，必須可重試。

## 病患語言版摘要

不變式 #12 不變（主報告與 `report.language` 固定 zh-TW），但 `summary` 與
`plan.patient_education` 是**病患自己**在畫面上讀的（#24）——en/ja/ko/vi
場次的病患拿到看不懂的中文。新欄位 `patient_facing_localized` 由主報告
commit **之後**的一次小 LLM 呼叫產出，失敗留 NULL。
本檔的斷言重點是「**絕不影響主報告**」：轉述爆炸時報告仍是 GENERATED。

## FAILED 可觀測性（SO-2 通知半邊）

舊版 `_mark_report_failed` 只改一個 DB 欄位。儀表板不會重抓、通知中心
沒有一筆、iOS 不響——只有正在盯著那一場又剛好手動重整的醫師才會發現。
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date, datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest
from celery.exceptions import Retry

from app.core.exceptions import AIServiceUnavailableException
from app.models.enums import Gender, ReportStatus
from app.tasks import report_queue


# ══════════════════════════════════════════════════════════
# Fakes
# ══════════════════════════════════════════════════════════


def _fake_conversation(seq: int, role: str, text: str) -> SimpleNamespace:
    return SimpleNamespace(
        sequence_number=seq,
        role=SimpleNamespace(value=role),
        content_text=text,
        created_at=datetime(2026, 8, 20, 9, seq, tzinfo=timezone.utc),
    )


def _fake_session(language: str = "zh-TW") -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        language=language,
        chief_complaint_text="血尿",
        intake_data=None,
        patient=SimpleNamespace(
            name="王大明",
            gender=Gender.MALE,
            date_of_birth=date(1960, 1, 1),
            medical_history=None,
            current_medications=None,
            allergies=None,
        ),
        chief_complaint=SimpleNamespace(name="血尿", name_en="Hematuria"),
        conversations=[
            _fake_conversation(1, "assistant", "請描述症狀"),
            _fake_conversation(2, "patient", "小便有血兩天"),
        ],
    )


def _fake_report() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        subjective=None,
        objective=None,
        assessment=None,
        plan=None,
        raw_transcript=None,
        summary=None,
        icd10_codes=None,
        icd10_verified=None,
        ai_confidence_score=None,
        language=None,
        patient_facing_localized=None,
        status=ReportStatus.GENERATING,
        generated_at=None,
    )


class _FakeResult:
    def __init__(self, obj: Any = None, rows: list[Any] | None = None):
        self._obj = obj
        self._rows = rows or []

    def scalar_one_or_none(self):
        return self._obj

    def scalars(self):
        return SimpleNamespace(all=lambda: self._rows)


class _FakeDB:
    def __init__(self, session_obj, report_obj):
        self._session_obj = session_obj
        self._report_obj = report_obj
        self.commits = 0
        self.rollbacks = 0

    async def execute(self, stmt):
        s = str(stmt)
        if "red_flag_alerts" in s:
            return _FakeResult(rows=[])
        if "soap_reports" in s:
            return _FakeResult(obj=self._report_obj)
        return _FakeResult(obj=self._session_obj)

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1

    async def flush(self):
        pass

    def add(self, obj):
        pass


class _FakeSessionFactory:
    def __init__(self, db: _FakeDB):
        self._db = db

    def __call__(self):
        return self

    async def __aenter__(self):
        return self._db

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeTask:
    def __init__(self, retries: int = 0, max_retries: int = 2, delay: int = 30):
        self.request = SimpleNamespace(retries=retries)
        self.max_retries = max_retries
        self.default_retry_delay = delay
        self.retry_calls: list[dict[str, Any]] = []

    def retry(self, exc=None, countdown=None):
        self.retry_calls.append({"exc": exc, "countdown": countdown})
        raise Retry("retry scheduled")


_SOAP_PAYLOAD: dict[str, Any] = {
    "subjective": {"chief_complaint": "血尿"},
    "objective": {},
    "assessment": {"differential_diagnoses": [], "clinical_impression": "疑似 UTI"},
    "plan": {
        "patient_education": ["多喝水。", "若症狀加重，請立即告知現場醫護人員。"],
        "urgency": "this_week",
    },
    "summary": "60 歲男性血尿兩天，無疼痛。",
    "icd10_codes": ["N39.0"],
    "icd10_verified": True,
    "confidence_score": 0.8,
}


def _install(monkeypatch, db: _FakeDB, *, generate=None, localize=None):
    """把 `_async_generate` 的外部相依換成替身。

    `localize` 為 None 時代表「轉述層不該被呼叫」——會直接讓測試炸掉，
    比事後 assert 呼叫次數更早暴露問題。
    """
    import app.core.database as core_db
    import app.pipelines.soap_generator as sg_mod
    from app.services.notification_service import NotificationService
    from app.services.report_service import ReportService

    monkeypatch.setattr(core_db, "async_session_factory", _FakeSessionFactory(db))

    async def _default_generate(**_kwargs):
        import copy

        return copy.deepcopy(_SOAP_PAYLOAD)

    async def _forbidden_localize(**kwargs):
        raise AssertionError(f"不該呼叫轉述層：{kwargs}")

    gen_fn = generate or _default_generate
    loc_fn = localize or _forbidden_localize

    class _FakeGenerator:
        def __init__(self, _settings):
            pass

        async def generate(self, **kwargs):
            return await gen_fn(**kwargs)

        async def localize_patient_facing(self, **kwargs):
            return await loc_fn(**kwargs)

    monkeypatch.setattr(sg_mod, "SOAPGenerator", _FakeGenerator)

    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(ReportService, "_snapshot_revision", staticmethod(_noop))
    monkeypatch.setattr(
        NotificationService, "notify_report_ready", staticmethod(_noop)
    )
    monkeypatch.setattr(report_queue, "_publish_report_generated", _noop)


# ══════════════════════════════════════════════════════════
# 1. SO-4：report_not_found 要可重試
# ══════════════════════════════════════════════════════════


def test_report_row_missing_raises_retryable(monkeypatch):
    """報告列還沒 commit → 拋可重試例外，不可安靜 return 把 SOAP 丟掉。"""
    session_obj = _fake_session()
    db = _FakeDB(session_obj, None)  # 場次在、報告列不在
    _install(monkeypatch, db)

    with pytest.raises(report_queue.ReportRowNotReadyError):
        asyncio.run(report_queue._async_generate(str(session_obj.id)))

    assert report_queue._is_retryable(report_queue.ReportRowNotReadyError()) is True


def test_report_row_missing_schedules_a_retry(monkeypatch):
    """走完整的 `_run_task`：第一次要排重試，而不是標 FAILED。"""
    session_obj = _fake_session()
    db = _FakeDB(session_obj, None)
    _install(monkeypatch, db)

    task = _FakeTask(retries=0, max_retries=2)
    with pytest.raises(Retry):
        report_queue._run_task(task, str(session_obj.id))

    assert len(task.retry_calls) == 1
    assert task.retry_calls[0]["countdown"] == 30


def test_report_row_missing_marks_failed_only_after_retries_exhausted(monkeypatch):
    """重試耗盡才 FAILED —— 不變式「重試前絕不標 FAILED」不受本修復影響。"""
    session_obj = _fake_session()
    db = _FakeDB(session_obj, None)
    _install(monkeypatch, db)

    marked: list[str] = []

    async def _fake_mark(session_id):
        marked.append(session_id)

    monkeypatch.setattr(report_queue, "_mark_report_failed", _fake_mark)

    task = _FakeTask(retries=2, max_retries=2)
    with pytest.raises(report_queue.ReportRowNotReadyError):
        report_queue._run_task(task, str(session_obj.id))

    assert task.retry_calls == []
    assert marked == [str(session_obj.id)]


def test_report_row_present_still_takes_the_happy_path(monkeypatch):
    """誤傷防線：報告列在的時候一切照舊。"""
    session_obj = _fake_session()
    report_obj = _fake_report()
    db = _FakeDB(session_obj, report_obj)
    _install(monkeypatch, db)

    result = asyncio.run(report_queue._async_generate(str(session_obj.id)))

    assert result["status"] == "generated"
    assert report_obj.status == ReportStatus.GENERATED


# ══════════════════════════════════════════════════════════
# 2. 病患語言版摘要
# ══════════════════════════════════════════════════════════


def test_zh_session_does_not_call_the_localizer(monkeypatch):
    """
    中文場次 no-op：報告本來就是中文，多打一次 LLM 是純浪費。
    `_install` 的預設 localize 替身會直接 raise，所以這條測試靠
    「主報告仍然成功」證明它沒被呼叫。
    """
    session_obj = _fake_session(language="zh-TW")
    report_obj = _fake_report()
    db = _FakeDB(session_obj, report_obj)
    _install(monkeypatch, db)

    result = asyncio.run(report_queue._async_generate(str(session_obj.id)))

    assert result["status"] == "generated"
    assert report_obj.patient_facing_localized is None


@pytest.mark.parametrize("language", ["en-US", "ja-JP", "ko-KR", "vi-VN"])
def test_non_zh_session_writes_localized_field(monkeypatch, language):
    session_obj = _fake_session(language=language)
    report_obj = _fake_report()
    db = _FakeDB(session_obj, report_obj)
    captured: dict[str, Any] = {}

    async def _localize(**kwargs):
        captured.update(kwargs)
        return {
            "language": kwargs["target_language"],
            "summary": "localized summary",
            "patient_education": "localized education",
        }

    _install(monkeypatch, db, localize=_localize)
    asyncio.run(report_queue._async_generate(str(session_obj.id)))

    assert captured["target_language"] == language
    assert report_obj.patient_facing_localized == {
        "language": language,
        "summary": "localized summary",
        "patient_education": "localized education",
    }


def test_localizer_receives_the_sanitized_zh_source(monkeypatch):
    """轉述的輸入必須是**主報告寫進 DB 的那份**（已過中文消毒層），
    不是 LLM 原始輸出——否則等於把禁語餵給翻譯層再翻一遍。"""
    session_obj = _fake_session(language="ja-JP")
    report_obj = _fake_report()
    db = _FakeDB(session_obj, report_obj)
    captured: dict[str, Any] = {}

    async def _localize(**kwargs):
        captured.update(kwargs)
        return {"language": "ja-JP", "summary": "x", "patient_education": "y"}

    _install(monkeypatch, db, localize=_localize)
    asyncio.run(report_queue._async_generate(str(session_obj.id)))

    assert captured["summary"] == _SOAP_PAYLOAD["summary"]
    # list 的 patient_education 併成單一字串，每一條都要在
    for item in _SOAP_PAYLOAD["plan"]["patient_education"]:
        assert item in captured["patient_education"]


def test_main_report_survives_localizer_failure(monkeypatch):
    """**最重要的一條**：轉述層爆炸不得影響已 commit 的主報告。"""
    session_obj = _fake_session(language="ko-KR")
    report_obj = _fake_report()
    db = _FakeDB(session_obj, report_obj)

    async def _boom(**_kwargs):
        raise RuntimeError("openai down")

    _install(monkeypatch, db, localize=_boom)
    result = asyncio.run(report_queue._async_generate(str(session_obj.id)))

    assert result["status"] == "generated"
    assert report_obj.status == ReportStatus.GENERATED
    assert report_obj.summary == _SOAP_PAYLOAD["summary"]
    assert report_obj.patient_facing_localized is None, "失敗要留 NULL"


def test_localizer_failure_is_logged_not_raised(monkeypatch, caplog):
    session_obj = _fake_session(language="vi-VN")
    db = _FakeDB(session_obj, _fake_report())

    async def _boom(**_kwargs):
        raise RuntimeError("openai down")

    _install(monkeypatch, db, localize=_boom)
    with caplog.at_level("WARNING"):
        asyncio.run(report_queue._async_generate(str(session_obj.id)))
    assert any("病患語言版摘要生成失敗" in r.getMessage() for r in caplog.records)


def test_report_language_stays_zh_even_for_localized_sessions(monkeypatch):
    """不變式 #12：主報告與 `report.language` 仍固定 zh-TW。"""
    from app.core.config import settings

    session_obj = _fake_session(language="ja-JP")
    report_obj = _fake_report()
    db = _FakeDB(session_obj, report_obj)

    async def _localize(**kwargs):
        return {"language": "ja-JP", "summary": "s", "patient_education": "e"}

    _install(monkeypatch, db, localize=_localize)
    asyncio.run(report_queue._async_generate(str(session_obj.id)))

    assert report_obj.language == settings.SOAP_REPORT_LANGUAGE == "zh-TW"
    assert report_obj.summary == _SOAP_PAYLOAD["summary"]  # 中文原文原封不動


def test_response_schema_exposes_the_localized_field():
    """
    寫進 DB 卻沒有出 API 就等於沒做。`SOAPReportResponse` 是簡要回應、
    `SOAPReportDetailResponse`（= 路由的 `ReportDetail`）繼承它——病患端
    session detail 走的是後者，兩個都要看得到這一欄。

    順帶釘住 Decimal 鐵律沒有被這次改動波及：`ai_confidence_score` 仍是
    `JsonFloatDecimal`（pydantic v2 預設會把 Decimal 序列化成 JSON 字串，
    炸掉 Flutter 的 `as num?` 解析）。
    """
    from datetime import datetime as _dt
    from decimal import Decimal

    from app.schemas.report import SOAPReportDetailResponse, SOAPReportResponse

    assert "patient_facing_localized" in SOAPReportResponse.model_fields
    assert "patient_facing_localized" in SOAPReportDetailResponse.model_fields

    payload = SimpleNamespace(
        id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        status=ReportStatus.GENERATED,
        review_status="pending",
        summary="中文摘要",
        patient_facing_localized={
            "language": "ja-JP",
            "summary": "日本語の要約",
            "patient_education": "そのままお待ちください。",
        },
        ai_confidence_score=Decimal("0.85"),
        generated_at=None,
        reviewed_by=None,
        reviewed_at=None,
        created_at=_dt(2026, 8, 20, tzinfo=timezone.utc),
        updated_at=_dt(2026, 8, 20, tzinfo=timezone.utc),
    )
    dumped = SOAPReportResponse.model_validate(payload).model_dump(mode="json")

    assert dumped["patient_facing_localized"]["language"] == "ja-JP"
    assert dumped["summary"] == "中文摘要", "主報告 summary 仍是 zh-TW（不變式 #12）"
    assert isinstance(dumped["ai_confidence_score"], float), "Decimal 鐵律"


def test_flatten_patient_education_shapes():
    """`plan.patient_education` 三種形狀都要能併成字串（不可丟資料）。"""
    flatten = report_queue._flatten_patient_education
    assert flatten(["a", "b"]) == "a\nb"
    assert flatten("a") == "a"
    assert flatten(None) == ""
    assert flatten(["a", None, "b"]) == "a\nb"


# ══════════════════════════════════════════════════════════
# 3. FAILED 可觀測性
# ══════════════════════════════════════════════════════════


class _AnnounceDB:
    """`_mark_report_failed` / `_announce_report_failure` 用的 DB 替身。"""

    def __init__(self, session_obj, report_obj):
        self._session_obj = session_obj
        self._report_obj = report_obj
        self.commits = 0
        self.rollbacks = 0

    async def execute(self, stmt):
        s = str(stmt)
        if "soap_reports" in s:
            return _FakeResult(obj=self._report_obj)
        return _FakeResult(obj=self._session_obj)

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1

    async def flush(self):
        pass

    def add(self, obj):
        pass


def _install_announce(monkeypatch, db):
    import app.core.database as core_db

    monkeypatch.setattr(core_db, "async_session_factory", _FakeSessionFactory(db))

    published: list[dict[str, Any]] = []
    notified: list[dict[str, Any]] = []

    async def _publish(**kwargs):
        published.append(kwargs)

    async def _notify(db_arg, **kwargs):
        notified.append(kwargs)
        return []

    from app.services.notification_service import NotificationService

    monkeypatch.setattr(report_queue, "_publish_report_generated", _publish)
    monkeypatch.setattr(
        NotificationService, "notify_report_failed", staticmethod(_notify)
    )
    return published, notified


def test_mark_failed_sets_status_and_commits(monkeypatch):
    session_obj = _fake_session()
    report_obj = _fake_report()
    db = _AnnounceDB(session_obj, report_obj)
    _install_announce(monkeypatch, db)

    asyncio.run(report_queue._mark_report_failed(str(session_obj.id)))

    assert report_obj.status == ReportStatus.FAILED
    assert db.commits >= 1


def test_mark_failed_broadcasts_a_dashboard_event(monkeypatch):
    """
    兩份前端對 `report_generated` 的四個訂閱點**全部**是「收到就用 REST
    重抓」、沒有一處讀 payload。所以帶 status="failed" 的同一個事件型別
    就能讓儀表板重抓到 FAILED 狀態——不必新增兩端都沒訂的事件型別
    （不變式 #27 的教訓：`resume_failed` 後端有發、兩端都沒訂）。
    """
    session_obj = _fake_session()
    report_obj = _fake_report()
    db = _AnnounceDB(session_obj, report_obj)
    published, _ = _install_announce(monkeypatch, db)

    asyncio.run(report_queue._mark_report_failed(str(session_obj.id)))

    assert len(published) == 1
    event = published[0]
    assert event["status"] == "failed"
    assert event["session_id"] == str(session_obj.id)
    assert event["report_id"] == str(report_obj.id)
    assert event["patient_name"] == "王大明"


def test_mark_failed_creates_a_doctor_notification(monkeypatch):
    session_obj = _fake_session()
    db = _AnnounceDB(session_obj, _fake_report())
    _, notified = _install_announce(monkeypatch, db)

    asyncio.run(report_queue._mark_report_failed(str(session_obj.id)))

    assert len(notified) == 1
    assert notified[0]["session_id"] == str(session_obj.id)


def test_broadcast_failure_does_not_block_the_notification(monkeypatch):
    """兩條通道互相獨立：Redis 掛了不可讓站內通知也一起消失。"""
    session_obj = _fake_session()
    db = _AnnounceDB(session_obj, _fake_report())
    _, notified = _install_announce(monkeypatch, db)

    async def _boom(**_kwargs):
        raise RuntimeError("redis down")

    monkeypatch.setattr(report_queue, "_publish_report_generated", _boom)

    asyncio.run(report_queue._mark_report_failed(str(session_obj.id)))
    assert len(notified) == 1


def test_notification_failure_does_not_break_mark_failed(monkeypatch):
    """反向：通知建立失敗也不可讓 FAILED 狀態本身沒落地。"""
    session_obj = _fake_session()
    report_obj = _fake_report()
    db = _AnnounceDB(session_obj, report_obj)
    _install_announce(monkeypatch, db)

    from app.services.notification_service import NotificationService

    async def _boom(db_arg, **_kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(
        NotificationService, "notify_report_failed", staticmethod(_boom)
    )

    asyncio.run(report_queue._mark_report_failed(str(session_obj.id)))
    assert report_obj.status == ReportStatus.FAILED
    assert db.rollbacks >= 1


def test_missing_session_row_still_announces(monkeypatch):
    """場次查不到（已刪）時 payload 少幾個欄位，但事件仍要發出去。"""
    db = _AnnounceDB(None, None)
    published, notified = _install_announce(monkeypatch, db)

    session_id = str(uuid.uuid4())
    asyncio.run(report_queue._mark_report_failed(session_id))

    assert published[0]["status"] == "failed"
    assert published[0]["session_id"] == session_id
    assert len(notified) == 1


def test_retry_exhaustion_path_reaches_the_announcement(monkeypatch):
    """接線測試：真的走 `_run_task` 重試耗盡 → 廣播與通知都到位。"""
    session_obj = _fake_session()
    report_obj = _fake_report()
    gen_db = _FakeDB(session_obj, report_obj)

    async def _boom(**_kwargs):
        raise AIServiceUnavailableException()

    _install(monkeypatch, gen_db, generate=_boom)
    # `_mark_report_failed` 自己開新 session，換成 announce 用的替身
    announce_db = _AnnounceDB(session_obj, report_obj)
    published, notified = _install_announce(monkeypatch, announce_db)

    task = _FakeTask(retries=2, max_retries=2)
    with pytest.raises(AIServiceUnavailableException):
        report_queue._run_task(task, str(session_obj.id))

    assert report_obj.status == ReportStatus.FAILED
    assert published and published[0]["status"] == "failed"
    assert len(notified) == 1
