"""
G35b：切語言守衛端點 `POST /sessions/{id}/end-for-language-switch` 的守護測試。

test_end_for_language_switch.py 已覆蓋 happy path / 冪等 / audit 內容，本檔補齊
「守衛」面向——授權與狀態機：

- 授權走既有 `_authorize_session_access`（不另立一套）：病患本人 / 負責醫師 /
  未指派醫師 / admin 可呼叫；他人 403
- 場次不存在 → SessionNotFoundException（404）
- 轉移合法性確實經過 `is_valid_transition`，而非自帶狀態白名單
- 轉移表不允許 `→ cancelled` 的非終態 → 409 且**不**靜默成功、不動場次

這裡刻意不 stub `_authorize_session_access`，也不 stub `get_by_id`：假 DB 依
SQL 的 FROM 子句分派結果，讓授權與 404 都走真正的程式路徑。
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Optional

import pytest

from app.core.exceptions import (
    ForbiddenException,
    InvalidStatusTransitionException,
    SessionNotFoundException,
)
from app.core.session_state import VALID_TRANSITIONS
from app.models.enums import SessionStatus, UserRole
from app.services.session_service import SessionService


def _run(coro):
    return asyncio.run(coro)


@dataclass
class _FakeSession:
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    patient_id: uuid.UUID = field(default_factory=uuid.uuid4)
    doctor_id: Optional[uuid.UUID] = None
    status: SessionStatus = SessionStatus.IN_PROGRESS
    language: str = "zh-TW"
    started_at: Any = None
    completed_at: Any = None
    updated_at: Any = None
    duration_seconds: Optional[int] = None


@dataclass
class _FakeUser:
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    role: UserRole = UserRole.PATIENT
    preferred_language: Optional[str] = None
    updated_at: Any = None


class _Result:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value


class _FakeDB:
    """依 SQL 的 FROM 子句分派結果，讓 get_by_id 與授權查詢都走真實程式路徑。"""

    def __init__(
        self,
        *,
        session: Optional[_FakeSession] = None,
        owner_user_id: Optional[uuid.UUID] = None,
        user: Optional[_FakeUser] = None,
    ) -> None:
        self._session = session
        self._owner_user_id = owner_user_id
        self._user = user
        self.flushed = 0

    async def execute(self, stmt: Any) -> _Result:
        sql = str(stmt).lower()
        if "from sessions" in sql:
            return _Result(self._session)
        if "from patients" in sql:
            return _Result(self._owner_user_id)
        if "from users" in sql:
            return _Result(self._user)
        raise AssertionError(f"未預期的查詢：{sql}")

    async def flush(self) -> None:
        self.flushed += 1


@pytest.fixture(autouse=True)
def _capture_audit(monkeypatch):
    """攔截 audit log 寫入（真實實作會 db.add ORM 物件，假 DB 不支援）。"""
    calls: list[dict[str, Any]] = []

    from app.services import audit_log_service as als_mod

    async def _log(db, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(**kwargs)

    monkeypatch.setattr(als_mod.AuditLogService, "log", _log)
    return calls


def _end(db: _FakeDB, session: _FakeSession, actor: Any, to_language: str = "en-US"):
    return _run(
        SessionService.end_for_language_switch(
            db,
            session_id=session.id,
            to_language=to_language,
            current_user=actor,
        )
    )


# ── 授權：沿用 _authorize_session_access ────────────────────

def test_owner_patient_can_end_session(_capture_audit):
    patient_user = _FakeUser(role=UserRole.PATIENT)
    session = _FakeSession(status=SessionStatus.IN_PROGRESS)
    db = _FakeDB(session=session, owner_user_id=patient_user.id, user=patient_user)

    result = _end(db, session, patient_user)

    assert result.status == SessionStatus.CANCELLED
    assert patient_user.preferred_language == "en-US"
    assert len(_capture_audit) == 1


def test_other_patient_gets_forbidden(_capture_audit):
    """病患 A 拿病患 B 的 session id 來收場次 → 403，且場次不得被動到。"""
    attacker = _FakeUser(role=UserRole.PATIENT)
    session = _FakeSession(status=SessionStatus.IN_PROGRESS)
    db = _FakeDB(session=session, owner_user_id=uuid.uuid4(), user=attacker)

    with pytest.raises(ForbiddenException) as excinfo:
        _end(db, session, attacker)

    assert excinfo.value.status_code == 403
    assert session.status == SessionStatus.IN_PROGRESS
    assert attacker.preferred_language is None
    assert _capture_audit == []


def test_assigned_doctor_can_end_session(_capture_audit):
    doctor = _FakeUser(role=UserRole.DOCTOR)
    session = _FakeSession(status=SessionStatus.IN_PROGRESS, doctor_id=doctor.id)
    db = _FakeDB(session=session, user=doctor)

    assert _end(db, session, doctor).status == SessionStatus.CANCELLED


def test_other_doctors_session_is_forbidden(_capture_audit):
    doctor = _FakeUser(role=UserRole.DOCTOR)
    session = _FakeSession(status=SessionStatus.IN_PROGRESS, doctor_id=uuid.uuid4())
    db = _FakeDB(session=session, user=doctor)

    with pytest.raises(ForbiddenException):
        _end(db, session, doctor)
    assert session.status == SessionStatus.IN_PROGRESS


def test_admin_can_end_any_session(_capture_audit):
    admin = _FakeUser(role=UserRole.ADMIN)
    session = _FakeSession(status=SessionStatus.IN_PROGRESS, doctor_id=uuid.uuid4())
    db = _FakeDB(session=session, user=admin)

    assert _end(db, session, admin).status == SessionStatus.CANCELLED


def test_unknown_role_is_rejected(_capture_audit):
    stranger = SimpleNamespace(id=uuid.uuid4(), role="hacker")
    session = _FakeSession(status=SessionStatus.IN_PROGRESS)
    db = _FakeDB(session=session, owner_user_id=uuid.uuid4())

    with pytest.raises(ForbiddenException):
        _end(db, session, stranger)


# ── 不存在的場次 ────────────────────────────────────────────

def test_missing_session_raises_not_found(_capture_audit):
    admin = _FakeUser(role=UserRole.ADMIN)
    db = _FakeDB(session=None, user=admin)

    with pytest.raises(SessionNotFoundException) as excinfo:
        _run(
            SessionService.end_for_language_switch(
                db,
                session_id=uuid.uuid4(),
                to_language="en-US",
                current_user=admin,
            )
        )

    assert excinfo.value.status_code == 404
    assert _capture_audit == []


# ── 狀態機：單一權威 is_valid_transition ────────────────────

def test_transition_goes_through_is_valid_transition(monkeypatch, _capture_audit):
    """守衛必須問 `is_valid_transition`，不得自帶狀態白名單（不變式 #16）。"""
    from app.services import session_service as ss_mod

    real = ss_mod.is_valid_transition
    seen: list[tuple[Any, Any]] = []

    def _spy(current, new, **kwargs):
        seen.append((current, new))
        return real(current, new, **kwargs)

    monkeypatch.setattr(ss_mod, "is_valid_transition", _spy)

    admin = _FakeUser(role=UserRole.ADMIN)
    session = _FakeSession(status=SessionStatus.IN_PROGRESS)
    db = _FakeDB(session=session, user=admin)

    assert _end(db, session, admin).status == SessionStatus.CANCELLED
    assert (SessionStatus.IN_PROGRESS, SessionStatus.CANCELLED) in seen


def test_illegal_transition_is_rejected_not_silently_succeeded(
    monkeypatch, _capture_audit
):
    """
    轉移表若把 `in_progress → cancelled` 拿掉，守衛必須回 409 而非靜默成功。

    以 monkeypatch 暫時改表（不改原始碼）來證明判斷來源是 VALID_TRANSITIONS：
    此時 in_progress 仍非終態（還能 → completed），所以走「非法轉移」分支。
    """
    monkeypatch.setitem(
        VALID_TRANSITIONS, SessionStatus.IN_PROGRESS, [SessionStatus.COMPLETED]
    )

    admin = _FakeUser(role=UserRole.ADMIN)
    session = _FakeSession(status=SessionStatus.IN_PROGRESS)
    db = _FakeDB(session=session, user=admin)

    with pytest.raises(InvalidStatusTransitionException) as excinfo:
        _end(db, session, admin)

    assert excinfo.value.status_code == 409
    assert excinfo.value.message == "errors.session_not_switchable"
    assert excinfo.value.details["allowed_transitions"] == ["completed"]
    # 沒有半套的副作用：場次狀態、語言偏好、audit log 都不動
    assert session.status == SessionStatus.IN_PROGRESS
    assert admin.preferred_language is None
    assert _capture_audit == []


def test_terminal_state_derives_from_transition_table(monkeypatch, _capture_audit):
    """
    終態清單不得硬編：把 waiting 的出邊清空後，waiting 就該走冪等分支。

    （現行表裡 waiting 是可轉移狀態，這個測試只證明判斷來源是轉移表。）
    """
    monkeypatch.setitem(VALID_TRANSITIONS, SessionStatus.WAITING, [])

    admin = _FakeUser(role=UserRole.ADMIN)
    session = _FakeSession(status=SessionStatus.WAITING)
    db = _FakeDB(session=session, user=admin)

    result = _end(db, session, admin)

    assert result.status == SessionStatus.WAITING  # 未轉移
    assert _capture_audit[0]["details"]["session_already_terminal"] is True
