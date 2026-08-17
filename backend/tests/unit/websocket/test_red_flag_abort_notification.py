"""aborted_red_flag 必須留下醫師站內通知，否則就是對病患說謊。

病患在紅旗中止後收到的提示原文（`ws.session_terminated_aborted_notice`）明說
「系統已將您先前描述、需要留意的症狀**通知現場醫護人員**」，但
`_update_session_status` 的通知區塊以前只有 `new_status == "completed"` 一個分支
→ 紅旗中止一則通知都不建。真跑實測 notifications 表 0 筆。

第二個根因：`AlertService.create` 附帶的那則 RED_FLAG 通知只在
`sessions.doctor_id` 有值時才建，而院內 kiosk 的場次在問診當下**通常還沒指派
醫師**（實測 DB 內 sessions.doctor_id 全為 NULL）。所以「只通知 assigned doctor」
等於什麼都沒做——未指派時必須發給所有在職醫師。
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import app.websocket.conversation_handler as ch
from app.models.enums import NotificationType
from tests.unit.websocket.conftest import DEFAULT_SESSION_ID, FakeRedis, StubDB

SID = DEFAULT_SESSION_ID
DOC_A = uuid.UUID("22222222-2222-4222-8222-222222222222")
DOC_B = uuid.UUID("33333333-3333-4333-8333-333333333333")


def _row(doctor_id: Any = None, language: str = "zh-TW") -> SimpleNamespace:
    return SimpleNamespace(language=language, doctor_id=doctor_id, patient_id=None)


def _run(monkeypatch, db: StubDB, new_status: str, **kwargs):
    """跑 _update_session_status，回傳 NotificationService.create 的 spy。"""
    from app.services.notification_service import NotificationService

    create_spy = AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4()))
    monkeypatch.setattr(NotificationService, "create", create_spy)
    monkeypatch.setattr(
        NotificationService, "notify_session_complete", AsyncMock(return_value=None)
    )
    ok = asyncio.run(
        ch._update_session_status(
            db, FakeRedis(), SID, new_status, "in_progress", **kwargs
        )
    )
    return ok, create_spy


def _red_flag_calls(spy) -> list[Any]:
    return [
        c
        for c in spy.call_args_list
        if c.kwargs.get("type") is NotificationType.RED_FLAG
    ]


# ── 核心回歸 ────────────────────────────────────────────
def test_aborted_with_assigned_doctor_creates_notification(monkeypatch):
    db = StubDB(rowcount=1, returning_row=_row(doctor_id=DOC_A))
    ok, spy = _run(monkeypatch, db, "aborted_red_flag", red_flag_reason="睪丸扭轉")
    assert ok is True
    calls = _red_flag_calls(spy)
    assert calls, "aborted_red_flag 沒建任何醫師通知，但病患被告知『已通知現場醫護人員』"
    assert len(calls) == 1
    assert calls[0].kwargs["user_id"] == DOC_A
    assert "睪丸扭轉" in calls[0].kwargs["title"]
    assert calls[0].kwargs["data"]["session_id"] == SID
    assert calls[0].kwargs["data"]["status"] == "aborted_red_flag"
    # 有指派醫師時不該多跑一趟 SELECT
    assert len(db.executed) == 1


def test_aborted_unassigned_fans_out_to_active_doctors(monkeypatch):
    """kiosk 場次 doctor_id 為 NULL —— 只通知 assigned doctor 等於零通知。"""
    db = StubDB(rowcount=1, returning_row=_row(doctor_id=None), doctor_ids=[DOC_A, DOC_B])
    ok, spy = _run(monkeypatch, db, "aborted_red_flag", red_flag_reason="疑似泌尿道敗血症")
    assert ok is True
    calls = _red_flag_calls(spy)
    assert [c.kwargs["user_id"] for c in calls] == [DOC_A, DOC_B]
    assert all(c.kwargs["data"]["unassigned_fanout"] is True for c in calls)


def test_aborted_without_reason_still_notifies(monkeypatch):
    """red_flag_reason 為 None（title 解析不到）也不可靜默跳過通知。"""
    db = StubDB(rowcount=1, returning_row=_row(doctor_id=DOC_A))
    ok, spy = _run(monkeypatch, db, "aborted_red_flag")
    assert ok is True
    calls = _red_flag_calls(spy)
    assert len(calls) == 1
    assert calls[0].kwargs["title"]
    assert "{" not in calls[0].kwargs["title"], "i18n 模板沒被套用"


def test_notification_language_follows_session(monkeypatch):
    """與 AlertService 既有的紅旗推播一致，用場次語言解析標題。"""
    db = StubDB(rowcount=1, returning_row=_row(doctor_id=DOC_A, language="en-US"))
    _ok, spy = _run(monkeypatch, db, "aborted_red_flag", red_flag_reason="Testicular torsion")
    title = _red_flag_calls(spy)[0].kwargs["title"]
    assert title == "Red flag alert: Testicular torsion"


# ── 邊界 / 不回歸 ───────────────────────────────────────
def test_no_doctor_at_all_does_not_crash(monkeypatch):
    """一個在職醫師都沒有：記 error、回 0，但狀態轉移仍必須成立。"""
    db = StubDB(rowcount=1, returning_row=_row(doctor_id=None), doctor_ids=[])
    ok, spy = _run(monkeypatch, db, "aborted_red_flag", red_flag_reason="x")
    assert ok is True
    assert _red_flag_calls(spy) == []


def test_doctor_lookup_failure_does_not_roll_back_transition(monkeypatch):
    """撈醫師的 SELECT 炸掉時不可讓外層 except 回滾已寫好的稽核紀錄。"""
    from app.models.audit_log import AuditLog

    class _BoomOnSelect(StubDB):
        async def execute(self, stmt: Any):
            from sqlalchemy.sql.selectable import Select

            if isinstance(stmt, Select):
                raise RuntimeError("db down")
            return await super().execute(stmt)

    db = _BoomOnSelect(rowcount=1, returning_row=_row(doctor_id=None))
    ok, spy = _run(monkeypatch, db, "aborted_red_flag", red_flag_reason="x")
    assert ok is True
    assert _red_flag_calls(spy) == []
    assert [o for o in db.added if isinstance(o, AuditLog)], "稽核紀錄被連帶回滾了"
    assert db.rollbacks == 0


def test_completed_does_not_create_red_flag_notification(monkeypatch):
    """正常結束走 SESSION_COMPLETE，不可誤送紅旗通知。"""
    db = StubDB(rowcount=1, returning_row=_row(doctor_id=DOC_A))
    ok, spy = _run(monkeypatch, db, "completed")
    assert ok is True
    assert _red_flag_calls(spy) == []


def test_no_transition_creates_no_notification(monkeypatch):
    """CAS 未命中（場次早已終態）→ 不重複通知。"""
    db = StubDB(rowcount=0)
    ok, spy = _run(monkeypatch, db, "aborted_red_flag", red_flag_reason="x")
    assert ok is False
    assert spy.call_args_list == []
