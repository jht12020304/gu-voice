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
    def __init__(
        self, scalar: Any = None, first: Any = None, rows: Optional[list[Any]] = None
    ) -> None:
        self._scalar = scalar
        self._first = first
        self._rows = rows or []

    def scalar_one_or_none(self) -> Any:
        return self._scalar

    def first(self) -> Any:
        return self._first

    def scalars(self) -> Any:
        """未指派場次的 fan-out 會走 `select(User.id)` → `.scalars().all()`。"""
        rows = self._rows
        return type("_S", (), {"all": staticmethod(lambda: rows)})()


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

    notifications = _run(
        NotificationService.notify_report_ready(
            db,  # type: ignore[arg-type]
            session_id=session_id,
            report_id=report_id,
        )
    )

    assert len(notifications) == 1, "已指派醫師時只通知他一位"
    notification = notifications[0]
    assert len(push_task.calls) == 1
    call = push_task.calls[0]
    assert call["user_id"] == str(doctor_id)
    assert call["title"] == notification.title
    assert call["body"] == notification.body
    assert call["data"]["session_id"] == str(session_id)
    assert call["data"]["report_id"] == str(report_id)
    assert call["data"] == notification.data


# ──────────────────────────────────────────────────────
# PUSH-007：doctor_id IS NULL → fan-out 給全體在職醫師
# ──────────────────────────────────────────────────────
#
# 院內 kiosk 的場次在問診當下通常還沒指派醫師（實測 DB 內
# sessions.doctor_id 全為 NULL）。舊版在這個分支直接 return None ——
# 報告生成完了、一個人都不會知道。紅旗路徑
#（conversation_handler._notify_doctors_red_flag）早就修過同一個坑。


def _report_ready_fanout_db(
    doctors: list[uuid.UUID],
    *,
    type_enabled: Any = True,
    push_enabled: Any = True,
) -> _FakeDB:
    """未指派場次的 execute 序列：
    session+patient 列（doctor_id=None）→ 在職醫師清單
    → 每位醫師各三次（lang → 類型開關 → push 開關）。
    """
    results = [
        _FakeResult(first=_FakeRow(None, "王小明")),
        _FakeResult(rows=list(doctors)),
    ]
    for _ in doctors:
        # 類型被抑制時 create() 提早 return，**不會**再查 push 通道開關——
        # 序列要跟著少一格，否則下一位醫師會吃到錯位的結果。
        results.extend([_FakeResult(scalar="zh-TW"), _FakeResult(scalar=type_enabled)])
        if type_enabled:
            results.append(_FakeResult(scalar=push_enabled))
    return _FakeDB(results=results)


def test_report_ready_without_doctor_fans_out_to_all_active_doctors(push_task):
    doctors = [uuid.uuid4() for _ in range(3)]
    session_id = uuid.uuid4()
    db = _report_ready_fanout_db(doctors)

    notifications = _run(
        NotificationService.notify_report_ready(
            db,  # type: ignore[arg-type]
            session_id=session_id,
            report_id=uuid.uuid4(),
        )
    )

    assert len(notifications) == 3
    assert {n.user_id for n in notifications} == set(doctors)
    assert len(db.added) == 3
    # 站內通知與推播一一對應（比照 red_flag fan-out）
    assert {call["user_id"] for call in push_task.calls} == {str(d) for d in doctors}


def test_report_ready_fanout_respects_type_preference(push_task):
    """fan-out **不是**繞過偏好：關掉 report_ready 的醫師不會收到。

    （這一點與紅旗不同——紅旗是病安關鍵、恆送；報告就緒不是。）
    """
    doctors = [uuid.uuid4() for _ in range(2)]
    db = _report_ready_fanout_db(doctors, type_enabled=False)

    notifications = _run(
        NotificationService.notify_report_ready(
            db,  # type: ignore[arg-type]
            session_id=uuid.uuid4(),
            report_id=uuid.uuid4(),
        )
    )

    assert notifications == []
    assert db.added == []
    assert push_task.calls == [], "站內通知被抑制時不應偷發推播"


def test_report_ready_without_doctor_and_no_active_doctors_is_noop(push_task):
    """未指派且查無在職醫師 → 真的無人可送，安靜 no-op（不可炸）。"""
    db = _report_ready_fanout_db([])

    out = _run(
        NotificationService.notify_report_ready(
            db,  # type: ignore[arg-type]
            session_id=uuid.uuid4(),
            report_id=uuid.uuid4(),
        )
    )
    assert out == []
    assert push_task.calls == []
    assert db.added == []


def test_report_ready_missing_session_is_noop(push_task):
    """場次查不到（已刪除等）→ doctor_id 為 None 但也沒有 fan-out 目標。"""
    db = _FakeDB(results=[_FakeResult(first=None), _FakeResult(rows=[])])

    out = _run(
        NotificationService.notify_report_ready(
            db,  # type: ignore[arg-type]
            session_id=uuid.uuid4(),
            report_id=uuid.uuid4(),
        )
    )
    assert out == []
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

    notifications = _run(
        NotificationService.notify_report_ready(
            db,  # type: ignore[arg-type]
            session_id=uuid.uuid4(),
            report_id=uuid.uuid4(),
        )
    )

    assert len(notifications) == 1
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
    notifications = _run(
        NotificationService.notify_report_ready(
            db,  # type: ignore[arg-type]
            session_id=uuid.uuid4(),
            report_id=uuid.uuid4(),
        )
    )

    assert len(notifications) == 1
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

# ──────────────────────────────────────────────────────
# PUSH-008：報告生成失敗也要有人知道（SO-2 通知半邊）
# ──────────────────────────────────────────────────────
#
# 舊版 `_mark_report_failed` 只改一個 DB 欄位就結束：儀表板不會重抓、
# 通知中心沒有一筆、iOS 不響。只有正在盯著那一場、而且剛好手動重整的
# 醫師才會發現報告生不出來——實際上等於沒人知道。


def test_report_failed_notifies_assigned_doctor(push_task):
    doctor_id = uuid.uuid4()
    session_id = uuid.uuid4()
    db = _report_ready_db(doctor_id=doctor_id)

    notifications = _run(
        NotificationService.notify_report_failed(
            db,  # type: ignore[arg-type]
            session_id=session_id,
            report_id=uuid.uuid4(),
        )
    )

    assert len(notifications) == 1
    notification = notifications[0]
    assert notification.type is NotificationType.SYSTEM, (
        "報告沒有就緒，用 REPORT_READY 會讓醫師點進去看到空白；"
        "而且關掉 report_ready 的醫師會連『壞掉了』都收不到"
    )
    assert notification.data["session_id"] == str(session_id)
    assert notification.data["status"] == "failed"
    assert len(push_task.calls) == 1


def test_report_failed_fans_out_when_unassigned(push_task):
    doctors = [uuid.uuid4() for _ in range(2)]
    db = _report_ready_fanout_db(doctors)

    notifications = _run(
        NotificationService.notify_report_failed(
            db,  # type: ignore[arg-type]
            session_id=uuid.uuid4(),
        )
    )

    assert {n.user_id for n in notifications} == set(doctors)
    assert {call["user_id"] for call in push_task.calls} == {str(d) for d in doctors}


def test_report_failed_copy_is_localised_and_actionable(push_task):
    """文案要講清楚「壞了、請重試」，不能只是一句 error code。"""
    from app.services.notification_service import _report_failed_copy

    for language in ("zh-TW", "en-US", "ja-JP", "ko-KR", "vi-VN"):
        title, body = _report_failed_copy(language, "王小明")
        assert title.strip(), language
        assert "王小明" in body, language
    # 未支援語言退回 zh-TW（與 i18n_messages 的預設一致）
    assert _report_failed_copy("de-DE", "王小明") == _report_failed_copy("zh-TW", "王小明")
    assert _report_failed_copy(None, "王小明") == _report_failed_copy("zh-TW", "王小明")


def test_report_failed_without_report_id_omits_the_key(push_task):
    """報告列根本不存在時（session_not_found 之類）不可塞出 report_id=None。"""
    doctor_id = uuid.uuid4()
    db = _report_ready_db(doctor_id=doctor_id)

    notifications = _run(
        NotificationService.notify_report_failed(
            db,  # type: ignore[arg-type]
            session_id=uuid.uuid4(),
        )
    )
    assert "report_id" not in notifications[0].data


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
