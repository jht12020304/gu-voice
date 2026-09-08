"""檢查醫囑（快速開單）的單元測試。

純 Python stub（無真 DB），守住四件會出人命或會靜默走樣的事：

- **授權不得自己重寫一份**：`create_order` / `get_latest` 都必須先過
  `SessionService.get_session()`。那支才是軟刪除、`get_clinician_scope_id()`
  row-level 隔離的唯一來源；這裡若繞過它，A 醫師就能對 B 醫師的場次開單。
  測法是讓它拋例外，然後斷言「一列都沒寫進去」。
- **空陣列是合法臨床決策**：「看過摘要、這次不開任何檢查」必須與「還沒看」
  分得出來，所以空 items 要成功建立一列，而不是被擋掉。
- **append-only**：每次送出都是新列，不 update 既有列（醫師可重新勾選再送，
  以最新一張為準）。
- **稽核失敗不可擋住開單**：稽核是附加動作，AuditLogService 炸掉時醫囑仍要成立。
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from typing import Any, Optional

import pytest

from app.schemas.exam_order import ExamOrderCreate, ExamOrderItem
from app.services.exam_order_service import ExamOrderService


def _run(coro):
    """在 sync test 裡跑 coroutine，避免多裝 pytest-asyncio。"""
    return asyncio.run(coro)


class _FakeResult:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value


class _FakeDB:
    """最小 AsyncSession 替身：記錄 add 進來的物件。"""

    def __init__(self, select_result: Any = None) -> None:
        self.added: list[Any] = []
        self.flushes = 0
        self.refreshes = 0
        self._select_result = select_result

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        self.flushes += 1

    async def refresh(self, obj: Any) -> None:
        self.refreshes += 1

    async def execute(self, stmt: Any) -> _FakeResult:
        return _FakeResult(self._select_result)


def _fake_session(doctor_id: Optional[uuid.UUID] = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        doctor_id=doctor_id or uuid.uuid4(),
        language="zh-TW",
    )


def _user() -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), role=SimpleNamespace(value="doctor"))


def _patch_session_access(monkeypatch, *, session=None, raises: Exception | None = None):
    """把 SessionService.get_session 換掉，記錄它被呼叫過。"""
    calls: list[tuple] = []

    async def _get_session(self, db, session_id, current_user=None):  # noqa: ANN001
        calls.append((session_id, current_user))
        if raises is not None:
            raise raises
        return session

    from app.services.session_service import SessionService

    monkeypatch.setattr(SessionService, "get_session", _get_session, raising=True)
    return calls


def _silence_audit(monkeypatch, *, raises: Exception | None = None):
    logged: list[dict] = []

    async def _log(db, user_id, action, resource_type, resource_id=None, **kw):  # noqa: ANN001
        if raises is not None:
            raise raises
        logged.append(
            {
                "user_id": user_id,
                "action": action,
                "resource_type": resource_type,
                "resource_id": resource_id,
                "details": kw.get("details"),
            }
        )
        return SimpleNamespace(id=uuid.uuid4())

    from app.services.audit_log_service import AuditLogService

    monkeypatch.setattr(AuditLogService, "log", staticmethod(_log), raising=True)
    return logged


# ── 授權 ────────────────────────────────────────────────

def test_create_order_goes_through_session_authorization(monkeypatch):
    """開單前必須先過 SessionService.get_session（軟刪除 + 臨床 scope 的單一來源）。"""
    session = _fake_session()
    calls = _patch_session_access(monkeypatch, session=session)
    _silence_audit(monkeypatch)
    db = _FakeDB()
    user = _user()

    order = _run(
        ExamOrderService.create_order(
            db,
            session_id=session.id,
            payload=ExamOrderCreate(items=[ExamOrderItem(test_name="尿液常規")]),
            current_user=user,
        )
    )

    assert len(calls) == 1
    assert calls[0][0] == session.id
    assert calls[0][1] is user
    assert order.ordered_by == user.id


def test_create_order_writes_nothing_when_session_access_denied(monkeypatch):
    """授權失敗時例外要往上冒，且一列都不能寫進去。"""
    from app.core.exceptions import ForbiddenException

    _patch_session_access(
        monkeypatch, raises=ForbiddenException("errors.session_forbidden_other_doctor")
    )
    _silence_audit(monkeypatch)
    db = _FakeDB()

    with pytest.raises(ForbiddenException):
        _run(
            ExamOrderService.create_order(
                db,
                session_id=uuid.uuid4(),
                payload=ExamOrderCreate(items=[ExamOrderItem(test_name="尿液常規")]),
                current_user=_user(),
            )
        )

    assert db.added == []
    assert db.flushes == 0


def test_get_latest_goes_through_session_authorization(monkeypatch):
    session = _fake_session()
    calls = _patch_session_access(monkeypatch, session=session)
    db = _FakeDB(select_result=None)

    result = _run(
        ExamOrderService.get_latest(db, session_id=session.id, current_user=_user())
    )

    assert len(calls) == 1
    # 沒開過回 None，不是 404 —— 「還沒開」是正常狀態。
    assert result is None


# ── 內容 ────────────────────────────────────────────────

def test_items_are_snapshotted_not_referenced(monkeypatch):
    """勾選當下的項目原文（含緊急度、理由）要凍結進 items。"""
    session = _fake_session()
    _patch_session_access(monkeypatch, session=session)
    _silence_audit(monkeypatch)
    db = _FakeDB()

    order = _run(
        ExamOrderService.create_order(
            db,
            session_id=session.id,
            payload=ExamOrderCreate(
                items=[
                    ExamOrderItem(
                        test_name="尿液常規", urgency="routine", rationale="排除感染"
                    ),
                    ExamOrderItem(test_name="腎臟超音波", urgency="this_week"),
                ],
                note="病患自述無發燒",
            ),
            current_user=_user(),
        )
    )

    assert [i["test_name"] for i in order.items] == ["尿液常規", "腎臟超音波"]
    assert order.items[0]["urgency"] == "routine"
    assert order.items[0]["rationale"] == "排除感染"
    assert order.items[1]["rationale"] is None
    assert order.note == "病患自述無發燒"
    # JSONB 要吃得下的純量型別（不能留 pydantic 物件）
    assert all(isinstance(i, dict) for i in order.items)


def test_empty_selection_is_a_valid_clinical_decision(monkeypatch):
    """「看過摘要、這次不開任何檢查」必須寫得進去，與「還沒看」分得出來。"""
    session = _fake_session()
    _patch_session_access(monkeypatch, session=session)
    _silence_audit(monkeypatch)
    db = _FakeDB()

    order = _run(
        ExamOrderService.create_order(
            db,
            session_id=session.id,
            payload=ExamOrderCreate(items=[]),
            current_user=_user(),
        )
    )

    assert order.items == []
    assert len(db.added) == 1


def test_resubmit_appends_a_new_row(monkeypatch):
    """append-only：重送是新增一列，不是改寫既有列。"""
    session = _fake_session()
    _patch_session_access(monkeypatch, session=session)
    _silence_audit(monkeypatch)
    db = _FakeDB()
    user = _user()

    first = _run(
        ExamOrderService.create_order(
            db,
            session_id=session.id,
            payload=ExamOrderCreate(items=[ExamOrderItem(test_name="尿液常規")]),
            current_user=user,
        )
    )
    second = _run(
        ExamOrderService.create_order(
            db,
            session_id=session.id,
            payload=ExamOrderCreate(items=[ExamOrderItem(test_name="腎臟超音波")]),
            current_user=user,
        )
    )

    assert len(db.added) == 2
    assert first is not second
    assert [i["test_name"] for i in db.added[0].items] == ["尿液常規"]
    assert [i["test_name"] for i in db.added[1].items] == ["腎臟超音波"]


# ── 稽核 ────────────────────────────────────────────────

def test_audit_records_who_ordered_what(monkeypatch):
    session = _fake_session()
    _patch_session_access(monkeypatch, session=session)
    logged = _silence_audit(monkeypatch)
    db = _FakeDB()
    user = _user()

    _run(
        ExamOrderService.create_order(
            db,
            session_id=session.id,
            payload=ExamOrderCreate(
                items=[
                    ExamOrderItem(test_name="尿液常規"),
                    ExamOrderItem(test_name="腎臟超音波"),
                ]
            ),
            current_user=user,
        )
    )

    assert len(logged) == 1
    entry = logged[0]
    assert entry["user_id"] == user.id
    assert entry["resource_type"] == "exam_order"
    assert entry["details"]["item_count"] == 2
    assert entry["details"]["test_names"] == ["尿液常規", "腎臟超音波"]


def test_audit_failure_does_not_block_the_order(monkeypatch):
    """稽核是附加動作；它炸掉時醫囑仍要成立（同 report review 的既有作法）。"""
    session = _fake_session()
    _patch_session_access(monkeypatch, session=session)
    _silence_audit(monkeypatch, raises=RuntimeError("audit down"))
    db = _FakeDB()

    order = _run(
        ExamOrderService.create_order(
            db,
            session_id=session.id,
            payload=ExamOrderCreate(items=[ExamOrderItem(test_name="尿液常規")]),
            current_user=_user(),
        )
    )

    assert len(db.added) == 1
    assert [i["test_name"] for i in order.items] == ["尿液常規"]
