"""
守護 NP-notif-prefs（GDPR opt-out）的服務層病安與抑制邏輯。

純 stub 測試：不起 FastAPI、不連 PG / Redis、不裝 pytest-asyncio，
以 asyncio.run 跑 coroutine。覆蓋：
- PREF-001：update_preferences 拒絕關閉 red_flag（病安關鍵），維持為 True，
  其餘提供的欄位照常更新。
- PREF-002：create() 對「被關閉的類型」抑制（回傳 None，不建立 Notification）。
- PREF-003：create() 對 red_flag 恆送（即使偏好列把它當關閉也不抑制）。
- PREF-004：create() 在無 pref 列時防禦性照常發送。
- PREF-005：send_push_notification 於 push_enabled=False 時略過、回傳 False。
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Optional

from app.models.enums import NotificationType
from app.schemas.notification import NotificationPreferenceUpdate
from app.services.notification_service import NotificationService


def _run(coro):
    return asyncio.run(coro)


# ──────────────────────────────────────────────────────
# 測試工具
# ──────────────────────────────────────────────────────

class _FakeResult:
    def __init__(self, scalar: Any = None) -> None:
        self._scalar = scalar

    def scalar_one_or_none(self) -> Any:
        return self._scalar


class _FakePref:
    """NotificationPreference 的最小替身，預設全開。"""

    def __init__(self, user_id: uuid.UUID) -> None:
        self.user_id = user_id
        self.red_flag_enabled = True
        self.session_complete_enabled = True
        self.report_ready_enabled = True
        self.system_enabled = True
        self.email_enabled = True
        self.push_enabled = True


class _FakeDB:
    """
    依序回傳預先準備好的 execute 結果。可選擇性讓 get_or_create_preferences
    取得既有 pref（避免走新建分支）。記錄 add / commit / flush 是否被呼叫。
    """

    def __init__(self, results: Optional[list[_FakeResult]] = None) -> None:
        self._results = results or []
        self._i = 0
        self.added: list[Any] = []
        self.committed = False
        self.flushed = False
        self.statements: list[str] = []

    async def execute(self, stmt: Any, params: Any = None) -> _FakeResult:
        self.statements.append(str(stmt))
        if self._i < len(self._results):
            res = self._results[self._i]
            self._i += 1
            return res
        return _FakeResult()

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        self.flushed = True

    async def commit(self) -> None:
        self.committed = True

    async def refresh(self, obj: Any) -> None:
        pass


# ──────────────────────────────────────────────────────
# PREF-001：red_flag 不可被關閉
# ──────────────────────────────────────────────────────

def test_update_preferences_refuses_to_disable_red_flag():
    """嘗試把 red_flag_enabled 設 False 必須被忽略，維持 True；其餘欄位照常更新。"""
    user_id = uuid.uuid4()
    pref = _FakePref(user_id)
    # get_or_create_preferences 的查詢回傳既有 pref
    db = _FakeDB(results=[_FakeResult(scalar=pref)])

    out = _run(
        NotificationService.update_preferences(
            db,  # type: ignore[arg-type]
            user_id=user_id,
            update=NotificationPreferenceUpdate(
                red_flag_enabled=False,
                session_complete_enabled=False,
            ),
        )
    )

    assert out.red_flag_enabled is True, "red_flag 病安關鍵，不可被關閉"
    assert out.session_complete_enabled is False, "其餘提供欄位應正常更新"
    assert db.committed is True


def test_update_preferences_updates_only_provided_fields():
    """未提供的欄位不應被動到（exclude_unset 行為）。"""
    user_id = uuid.uuid4()
    pref = _FakePref(user_id)
    pref.report_ready_enabled = True
    db = _FakeDB(results=[_FakeResult(scalar=pref)])

    out = _run(
        NotificationService.update_preferences(
            db,  # type: ignore[arg-type]
            user_id=user_id,
            update=NotificationPreferenceUpdate(push_enabled=False),
        )
    )
    assert out.push_enabled is False
    assert out.report_ready_enabled is True  # 未提供 → 不變


# ──────────────────────────────────────────────────────
# PREF-002 / 003 / 004：create() 抑制
# ──────────────────────────────────────────────────────

def test_create_suppresses_disabled_type():
    """類型開關關閉時，create() 回傳 None 且不建立 Notification。"""
    user_id = uuid.uuid4()
    # _is_type_enabled 查 session_complete_enabled → False
    db = _FakeDB(results=[_FakeResult(scalar=False)])

    out = _run(
        NotificationService.create(
            db,  # type: ignore[arg-type]
            user_id=user_id,
            type=NotificationType.SESSION_COMPLETE,
            title="場次完成",
        )
    )
    assert out is None
    assert db.added == [], "被抑制時不應建立 Notification"


def test_create_always_sends_red_flag_even_if_pref_disabled():
    """red_flag 恆送：即使偏好列把它設 False（不在 _is_type_enabled 查詢路徑）。"""
    user_id = uuid.uuid4()
    # 即便 db 對任何 scalar 查詢回 False，red_flag 也不查 pref → 一律建立
    db = _FakeDB(results=[_FakeResult(scalar=False)])

    out = _run(
        NotificationService.create(
            db,  # type: ignore[arg-type]
            user_id=user_id,
            type=NotificationType.RED_FLAG,
            title="紅旗警示",
        )
    )
    assert out is not None
    assert len(db.added) == 1
    assert db.added[0].type == NotificationType.RED_FLAG


def test_create_sends_when_no_pref_row():
    """防禦性：查無偏好列（scalar=None）時照常建立。"""
    user_id = uuid.uuid4()
    db = _FakeDB(results=[_FakeResult(scalar=None)])

    out = _run(
        NotificationService.create(
            db,  # type: ignore[arg-type]
            user_id=user_id,
            type=NotificationType.SYSTEM,
            title="系統通知",
        )
    )
    assert out is not None
    assert len(db.added) == 1


def test_create_sends_when_type_enabled():
    """類型開關開啟（True）時照常建立。"""
    user_id = uuid.uuid4()
    db = _FakeDB(results=[_FakeResult(scalar=True)])

    out = _run(
        NotificationService.create(
            db,  # type: ignore[arg-type]
            user_id=user_id,
            type=NotificationType.REPORT_READY,
            title="報告完成",
        )
    )
    assert out is not None
    assert len(db.added) == 1


# ──────────────────────────────────────────────────────
# PREF-005：send_push_notification push 通道閘控
# ──────────────────────────────────────────────────────

def test_send_push_skipped_when_push_disabled():
    """push_enabled=False 時略過派送、回傳 False。"""
    user_id = uuid.uuid4()
    db = _FakeDB(results=[_FakeResult(scalar=False)])

    out = _run(
        NotificationService.send_push_notification(
            user_id=user_id,
            title="t",
            body="b",
            db=db,  # type: ignore[arg-type]
        )
    )
    assert out is False
