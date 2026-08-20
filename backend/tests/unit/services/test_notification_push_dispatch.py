"""
守護「問診完成 / 報告就緒」兩條通知路徑真的會派推播（iOS 醫師端 App 依賴）。

純 stub 測試：不起 FastAPI、不連 PG / Redis / Celery，以 asyncio.run 跑 coroutine，
並把 Celery 的 ``send_push_notification_task`` 換成記錄用替身。覆蓋：
- PUSH-001：notify_session_complete 建立站內通知後派送推播，且 title/body 與站內
  通知同一份文案、data 帶 session_id（App tap 導頁用）。
- PUSH-002：notify_report_ready 同理，data 帶 session_id + report_id。
- PUSH-003：push_enabled=False 時不派推播，但站內通知照建（通道閘控只擋推播）。
- PUSH-004：推播派送拋例外（Celery / Redis 不可用）時函式不炸，站內通知仍建立。
- PUSH-005：類型偏好把站內通知抑制掉時，推播也一併略過（不會偷跑）。
- PUSH-006：通用 create() 不得自行派推播——RED_FLAG 已由 alert_service 派送，
  放進 create() 會造成重複推播。
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Optional

import pytest

from app.models.enums import NotificationType
from app.services.notification_service import NotificationService


def _run(coro):
    return asyncio.run(coro)


# ──────────────────────────────────────────────────────
# 測試工具
# ──────────────────────────────────────────────────────

class _FakeResult:
    def __init__(self, scalar: Any = None, first: Any = None) -> None:
        self._scalar = scalar
        self._first = first

    def scalar_one_or_none(self) -> Any:
        return self._scalar

    def first(self) -> Any:
        return self._first


class _FakeRow:
    """notify_report_ready 的 (doctor_id, patient name) 列替身。"""

    def __init__(self, doctor_id: Optional[uuid.UUID], name: Optional[str]) -> None:
        self.doctor_id = doctor_id
        self.name = name


class _FakeDB:
    """依序回傳預先準備好的 execute 結果，並記錄 add / flush。"""

    def __init__(self, results: Optional[list[_FakeResult]] = None) -> None:
        self._results = results or []
        self._i = 0
        self.added: list[Any] = []
        self.flushed = False

    async def execute(self, stmt: Any, params: Any = None) -> _FakeResult:
        if self._i < len(self._results):
            res = self._results[self._i]
            self._i += 1
            return res
        return _FakeResult()

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        self.flushed = True

    async def commit(self) -> None:  # pragma: no cover - 本測試不 commit
        pass


class _RecordingTask:
    """send_push_notification_task 的替身：記錄 .delay(...) 的 kwargs。"""

    def __init__(self, raises: Optional[BaseException] = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._raises = raises

    def delay(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)
        if self._raises is not None:
            raise self._raises


@pytest.fixture()
def push_task(monkeypatch):
    """把 Celery task 換成記錄替身；回傳可檢查的 _RecordingTask。"""
    import app.tasks.notification_retry as notification_retry

    task = _RecordingTask()
    monkeypatch.setattr(notification_retry, "send_push_notification_task", task)
    return task


def _session_complete_db(*, type_enabled: Any = True, push_enabled: Any = True) -> _FakeDB:
    """notify_session_complete 的 execute 序列：
    doctor lang → patient name → 類型開關 → push 通道開關。
    """
    return _FakeDB(
        results=[
            _FakeResult(scalar="zh-TW"),
            _FakeResult(scalar="王小明"),
            _FakeResult(scalar=type_enabled),
            _FakeResult(scalar=push_enabled),
        ]
    )


def _report_ready_db(
    *,
    doctor_id: uuid.UUID,
    type_enabled: Any = True,
    push_enabled: Any = True,
) -> _FakeDB:
    """notify_report_ready 的 execute 序列：
    session+patient 列 → doctor lang → 類型開關 → push 通道開關。
    """
    return _FakeDB(
        results=[
            _FakeResult(first=_FakeRow(doctor_id, "王小明")),
            _FakeResult(scalar="zh-TW"),
            _FakeResult(scalar=type_enabled),
            _FakeResult(scalar=push_enabled),
        ]
    )


# ──────────────────────────────────────────────────────
# PUSH-001：session_complete 有派推播
# ──────────────────────────────────────────────────────

def test_session_complete_dispatches_push(push_task):
    doctor_id = uuid.uuid4()
    session_id = uuid.uuid4()
    db = _session_complete_db()

    notification = _run(
        NotificationService.notify_session_complete(
            db,  # type: ignore[arg-type]
            session_id=session_id,
            doctor_id=doctor_id,
            patient_id=uuid.uuid4(),
        )
    )

    assert notification is not None, "站內通知應建立"
    assert len(push_task.calls) == 1, "應派送一次推播"
    call = push_task.calls[0]
    assert call["user_id"] == str(doctor_id)
    # 推播文案沿用站內通知同一份
    assert call["title"] == notification.title
    assert call["body"] == notification.body
    # data 帶與站內通知一致的識別欄位（App tap 導頁）
    assert call["data"]["session_id"] == str(session_id)
    assert call["data"] == notification.data


# ──────────────────────────────────────────────────────
# PUSH-002：report_ready 有派推播
# ──────────────────────────────────────────────────────

def test_report_ready_dispatches_push(push_task):
    doctor_id = uuid.uuid4()
    session_id = uuid.uuid4()
    report_id = uuid.uuid4()
    db = _report_ready_db(doctor_id=doctor_id)

    notification = _run(
        NotificationService.notify_report_ready(
            db,  # type: ignore[arg-type]
            session_id=session_id,
            report_id=report_id,
        )
    )

    assert notification is not None
    assert len(push_task.calls) == 1
    call = push_task.calls[0]
    assert call["user_id"] == str(doctor_id)
    assert call["title"] == notification.title
    assert call["body"] == notification.body
    assert call["data"]["session_id"] == str(session_id)
    assert call["data"]["report_id"] == str(report_id)
    assert call["data"] == notification.data


def test_report_ready_without_doctor_is_noop(push_task):
    """場次無負責醫師 → 不建通知也不推播。"""
    db = _FakeDB(results=[_FakeResult(first=_FakeRow(None, "王小明"))])

    out = _run(
        NotificationService.notify_report_ready(
            db,  # type: ignore[arg-type]
            session_id=uuid.uuid4(),
            report_id=uuid.uuid4(),
        )
    )
    assert out is None
    assert push_task.calls == []
    assert db.added == []


# ──────────────────────────────────────────────────────
# PUSH-003：push_enabled=False 只擋推播，不擋站內通知
# ──────────────────────────────────────────────────────

def test_push_disabled_still_creates_in_app_notification(push_task):
    db = _session_complete_db(push_enabled=False)

    notification = _run(
        NotificationService.notify_session_complete(
            db,  # type: ignore[arg-type]
            session_id=uuid.uuid4(),
            doctor_id=uuid.uuid4(),
            patient_id=uuid.uuid4(),
        )
    )

    assert notification is not None, "push 通道關閉不應影響站內通知"
    assert len(db.added) == 1
    assert push_task.calls == [], "push_enabled=False 時不應派推播"


def test_report_ready_push_disabled_still_creates_in_app_notification(push_task):
    doctor_id = uuid.uuid4()
    db = _report_ready_db(doctor_id=doctor_id, push_enabled=False)

    notification = _run(
        NotificationService.notify_report_ready(
            db,  # type: ignore[arg-type]
            session_id=uuid.uuid4(),
            report_id=uuid.uuid4(),
        )
    )

    assert notification is not None
    assert len(db.added) == 1
    assert push_task.calls == []


# ──────────────────────────────────────────────────────
# PUSH-004：推播派送失敗不可影響通知建立
# ──────────────────────────────────────────────────────

def test_session_complete_survives_push_dispatch_failure(monkeypatch):
    """Celery / Redis 不可用（.delay 拋例外）時仍回傳已建立的站內通知。"""
    import app.tasks.notification_retry as notification_retry

    task = _RecordingTask(raises=RuntimeError("redis unavailable"))
    monkeypatch.setattr(notification_retry, "send_push_notification_task", task)

    db = _session_complete_db()
    notification = _run(
        NotificationService.notify_session_complete(
            db,  # type: ignore[arg-type]
            session_id=uuid.uuid4(),
            doctor_id=uuid.uuid4(),
            patient_id=uuid.uuid4(),
        )
    )

    assert notification is not None, "推播失敗不可讓通知建立失敗"
    assert len(db.added) == 1
    assert len(task.calls) == 1, "確實嘗試過派送"


def test_report_ready_survives_push_dispatch_failure(monkeypatch):
    """報告已 commit，通知/推播失敗都不可炸掉呼叫端（report_queue 第二段交易）。"""
    import app.tasks.notification_retry as notification_retry

    task = _RecordingTask(raises=RuntimeError("celery broker down"))
    monkeypatch.setattr(notification_retry, "send_push_notification_task", task)

    doctor_id = uuid.uuid4()
    db = _report_ready_db(doctor_id=doctor_id)
    notification = _run(
        NotificationService.notify_report_ready(
            db,  # type: ignore[arg-type]
            session_id=uuid.uuid4(),
            report_id=uuid.uuid4(),
        )
    )

    assert notification is not None
    assert len(db.added) == 1
    assert len(task.calls) == 1


# ──────────────────────────────────────────────────────
# PUSH-005：站內通知被類型偏好抑制時，推播一併略過
# ──────────────────────────────────────────────────────

def test_suppressed_type_skips_push(push_task):
    db = _session_complete_db(type_enabled=False)

    out = _run(
        NotificationService.notify_session_complete(
            db,  # type: ignore[arg-type]
            session_id=uuid.uuid4(),
            doctor_id=uuid.uuid4(),
            patient_id=uuid.uuid4(),
        )
    )

    assert out is None
    assert db.added == []
    assert push_task.calls == [], "站內通知被抑制時不應偷發推播"


# ──────────────────────────────────────────────────────
# PUSH-006：create() 不得自行派推播（避免 RED_FLAG 重複推播）
# ──────────────────────────────────────────────────────

def test_generic_create_does_not_dispatch_push(push_task):
    """RED_FLAG 的推播由 alert_service 自行派送；create() 再派會重複。"""
    db = _FakeDB(results=[_FakeResult(scalar=None)])

    out = _run(
        NotificationService.create(
            db,  # type: ignore[arg-type]
            user_id=uuid.uuid4(),
            type=NotificationType.RED_FLAG,
            title="紅旗警示",
            body="b",
        )
    )

    assert out is not None
    assert push_task.calls == [], "create() 不應自行派推播"
