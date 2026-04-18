"""
M16：SessionService.end_for_language_switch 行為守護。

- active session (waiting / in_progress) → 狀態轉 CANCELLED + 寫 audit log
- 已 completed / aborted / cancelled → 409 ConflictException
- user.preferred_language 會被更新
- audit log 帶 from_lang / to_lang / session_id
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Optional

import pytest

from app.core.exceptions import ConflictException
from app.models.enums import AuditAction, SessionStatus, UserRole
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


class _FakeAuditLog:
    def __init__(self):
        self.calls: list[dict[str, Any]] = []

    async def log(self, db, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(**kwargs)


class _FakeDB:
    """
    模擬 AsyncSession：get_by_id 透過 monkeypatch 注入；execute 只用來查 User。
    """
    def __init__(self, user: Optional[_FakeUser] = None) -> None:
        self._user = user
        self.flushed = 0

    async def execute(self, stmt: Any):
        class _Result:
            def __init__(self, v):
                self._v = v
            def scalar_one_or_none(self):
                return self._v
        return _Result(self._user)

    async def flush(self):
        self.flushed += 1


@pytest.fixture(autouse=True)
def _patch_audit_and_authorize(monkeypatch):
    """
    替換 AuditLogService.log 以捕獲呼叫；_authorize_session_access 放行。
    """
    fake_audit = _FakeAuditLog()

    from app.services import audit_log_service as als_mod
    monkeypatch.setattr(als_mod.AuditLogService, "log", fake_audit.log)

    from app.services import session_service as ss_mod

    async def _no_auth(db, session, current_user):
        return None

    monkeypatch.setattr(ss_mod, "_authorize_session_access", _no_auth)

    return fake_audit


def _install_get_by_id(monkeypatch, session: _FakeSession):
    async def _fake_get_by_id(db, session_id):
        return session
    monkeypatch.setattr(SessionService, "get_by_id", staticmethod(_fake_get_by_id))


def test_in_progress_session_ends_and_updates_language(monkeypatch, _patch_audit_and_authorize):
    session = _FakeSession(status=SessionStatus.IN_PROGRESS, language="zh-TW")
    user = _FakeUser(preferred_language="zh-TW")
    db = _FakeDB(user=user)

    _install_get_by_id(monkeypatch, session)

    result = _run(
        SessionService.end_for_language_switch(
            db, session_id=session.id, to_language="en-US", current_user=user
        )
    )

    assert result.status == SessionStatus.CANCELLED
    assert user.preferred_language == "en-US"
    assert db.flushed >= 1

    # audit log 寫入一筆
    calls = _patch_audit_and_authorize.calls
    assert len(calls) == 1
    assert calls[0]["action"] == AuditAction.LANGUAGE_SWITCH_END_SESSION
    assert calls[0]["resource_type"] == "session"
    assert calls[0]["details"] == {"from_lang": "zh-TW", "to_lang": "en-US"}
    assert calls[0]["user_id"] == user.id


def test_waiting_session_also_endable(monkeypatch, _patch_audit_and_authorize):
    session = _FakeSession(status=SessionStatus.WAITING, language="en-US")
    user = _FakeUser(preferred_language="en-US")
    db = _FakeDB(user=user)

    _install_get_by_id(monkeypatch, session)

    result = _run(
        SessionService.end_for_language_switch(
            db, session_id=session.id, to_language="zh-TW", current_user=user
        )
    )

    assert result.status == SessionStatus.CANCELLED
    assert user.preferred_language == "zh-TW"
    assert _patch_audit_and_authorize.calls[0]["details"]["from_lang"] == "en-US"
    assert _patch_audit_and_authorize.calls[0]["details"]["to_lang"] == "zh-TW"


@pytest.mark.parametrize(
    "terminal_status",
    [SessionStatus.COMPLETED, SessionStatus.CANCELLED, SessionStatus.ABORTED_RED_FLAG],
)
def test_terminal_session_rejects_with_409(monkeypatch, _patch_audit_and_authorize, terminal_status):
    session = _FakeSession(status=terminal_status, language="zh-TW")
    user = _FakeUser()
    db = _FakeDB(user=user)

    _install_get_by_id(monkeypatch, session)

    with pytest.raises(ConflictException) as excinfo:
        _run(
            SessionService.end_for_language_switch(
                db, session_id=session.id, to_language="en-US", current_user=user
            )
        )

    assert excinfo.value.message == "errors.session_not_switchable"
    # 不應呼叫 audit log
    assert _patch_audit_and_authorize.calls == []
    # 不應變更 user preference
    assert user.preferred_language is None


def test_anonymous_user_skips_preference_update(monkeypatch, _patch_audit_and_authorize):
    """current_user 無 id（近乎不會發生，但防禦式檢查）→ 不寫 user，audit user_id=None。"""
    session = _FakeSession(status=SessionStatus.IN_PROGRESS, language="zh-TW")
    db = _FakeDB(user=None)
    anonymous = SimpleNamespace(role=UserRole.PATIENT, id=None)

    _install_get_by_id(monkeypatch, session)

    _run(
        SessionService.end_for_language_switch(
            db, session_id=session.id, to_language="en-US", current_user=anonymous
        )
    )

    assert _patch_audit_and_authorize.calls[0]["user_id"] is None
