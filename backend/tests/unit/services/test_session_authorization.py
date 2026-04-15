"""
Unit tests for session ownership / authorization logic.

守護 Wave 2 資安阻斷（問題 ⑪ / ⑫）:
- patient 只能存取自己名下 Patient 的 session
- doctor 只能存取 doctor_id == self 或 doctor_id IS NULL(未指派)的 session
- admin 無限制
- 不認得的角色、缺 current_user → 拒絕

測試採用純 Python stub(無真 DB),只驗 `_authorize_session_access` 與
`_get_user_role` 這兩個核心函式。list_sessions 的 SQL 組裝走 DB,留給
future integration test 覆蓋。
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from typing import Any, Optional
from types import SimpleNamespace

import pytest

from app.core.exceptions import ForbiddenException
from app.models.enums import UserRole
from app.services.session_service import (
    _authorize_session_access,
    _get_user_role,
)


def _run(coro):
    """在 sync test 裡跑 coroutine,避免多裝一個 pytest-asyncio 套件。"""
    return asyncio.run(coro)


# ──────────────────────────────────────────────────────
# 測試工具
# ──────────────────────────────────────────────────────

@dataclass
class _FakeScalarResult:
    value: Any

    def scalar_one_or_none(self) -> Any:
        return self.value


class _FakeDB:
    """
    最小的 AsyncSession 替身。`execute` 會回傳預先準備好的 Patient.user_id
    查詢結果(值 = patient_user_id_map[patient_id])。只用於 patient 分支的
    權限檢查;doctor / admin 分支不碰 db。
    """

    def __init__(self, patient_user_id_map: dict[uuid.UUID, uuid.UUID] | None = None) -> None:
        self._map = patient_user_id_map or {}
        self.execute_calls = 0

    async def execute(self, stmt: Any) -> _FakeScalarResult:
        self.execute_calls += 1
        # stmt 是 SQLAlchemy select(Patient.user_id).where(Patient.id == patient_id)。
        # 為了不解析 SQL,直接從 map 取第一個可用值;測試會確保 map 裡只放一個目標。
        if not self._map:
            return _FakeScalarResult(None)
        return _FakeScalarResult(next(iter(self._map.values())))


def _make_user(role: UserRole | str, user_id: Optional[uuid.UUID] = None) -> SimpleNamespace:
    return SimpleNamespace(id=user_id or uuid.uuid4(), role=role)


def _make_session(
    session_id: Optional[uuid.UUID] = None,
    patient_id: Optional[uuid.UUID] = None,
    doctor_id: Optional[uuid.UUID] = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=session_id or uuid.uuid4(),
        patient_id=patient_id or uuid.uuid4(),
        doctor_id=doctor_id,
    )


# ──────────────────────────────────────────────────────
# _get_user_role
# ──────────────────────────────────────────────────────

def test_get_user_role_none_returns_none():
    assert _get_user_role(None) is None


def test_get_user_role_enum():
    user = _make_user(UserRole.DOCTOR)
    assert _get_user_role(user) is UserRole.DOCTOR


def test_get_user_role_string_converts():
    user = _make_user("patient")
    assert _get_user_role(user) is UserRole.PATIENT


def test_get_user_role_unknown_string_is_none():
    user = _make_user("hacker")
    assert _get_user_role(user) is None


# ──────────────────────────────────────────────────────
# admin: 無限制
# ──────────────────────────────────────────────────────

def test_admin_can_access_any_session():
    admin = _make_user(UserRole.ADMIN)
    # 任何 session,無論 doctor_id / patient_id 是誰
    session = _make_session(doctor_id=uuid.uuid4())
    db = _FakeDB()
    # 不應 raise
    _run(_authorize_session_access(db, session, admin))
    assert db.execute_calls == 0  # admin 不查 DB


# ──────────────────────────────────────────────────────
# doctor: 自己負責 + 未指派
# ──────────────────────────────────────────────────────

def test_doctor_can_access_own_session():
    doctor = _make_user(UserRole.DOCTOR)
    session = _make_session(doctor_id=doctor.id)
    db = _FakeDB()
    _run(_authorize_session_access(db, session, doctor))
    assert db.execute_calls == 0


def test_doctor_can_access_unassigned_session():
    doctor = _make_user(UserRole.DOCTOR)
    session = _make_session(doctor_id=None)
    db = _FakeDB()
    _run(_authorize_session_access(db, session, doctor))
    assert db.execute_calls == 0


def test_doctor_cannot_access_other_doctor_session():
    doctor_self = _make_user(UserRole.DOCTOR)
    other_doctor_id = uuid.uuid4()
    session = _make_session(doctor_id=other_doctor_id)
    db = _FakeDB()
    with pytest.raises(ForbiddenException):
        _run(_authorize_session_access(db, session, doctor_self))


# ──────────────────────────────────────────────────────
# patient: 自己名下 patient → ok; 其他人的 patient → 拒絕
# ──────────────────────────────────────────────────────

def test_patient_can_access_own_session():
    patient_user = _make_user(UserRole.PATIENT)
    patient_entity_id = uuid.uuid4()
    session = _make_session(patient_id=patient_entity_id)
    # db 模擬: Patient(patient_entity_id).user_id == patient_user.id
    db = _FakeDB({patient_entity_id: patient_user.id})
    _run(_authorize_session_access(db, session, patient_user))
    assert db.execute_calls == 1


def test_patient_cannot_access_other_users_session():
    """
    關鍵測試: patient A 拿 patient B 的 session UUID 來讀 → 必須被拒絕。
    這就是 Wave 2 要堵的資料外洩漏洞。
    """
    patient_a = _make_user(UserRole.PATIENT)
    patient_b_owner_id = uuid.uuid4()  # 另一個 User.id
    patient_b_entity_id = uuid.uuid4()
    session = _make_session(patient_id=patient_b_entity_id)
    # db 模擬: Patient(patient_b_entity_id).user_id == patient_b_owner_id (非 patient_a)
    db = _FakeDB({patient_b_entity_id: patient_b_owner_id})
    with pytest.raises(ForbiddenException):
        _run(_authorize_session_access(db, session, patient_a))


def test_patient_denied_when_patient_record_missing():
    patient_user = _make_user(UserRole.PATIENT)
    session = _make_session()
    # db 模擬: Patient 查不到(user_id = None)
    db = _FakeDB()
    with pytest.raises(ForbiddenException):
        _run(_authorize_session_access(db, session, patient_user))


# ──────────────────────────────────────────────────────
# 邊界: 沒有 current_user / 未知角色
# ──────────────────────────────────────────────────────

def test_missing_current_user_raises():
    session = _make_session()
    db = _FakeDB()
    with pytest.raises(ForbiddenException):
        _run(_authorize_session_access(db, session, None))


def test_unknown_role_is_rejected():
    user = _make_user("hacker")
    session = _make_session()
    db = _FakeDB()
    with pytest.raises(ForbiddenException):
        _run(_authorize_session_access(db, session, user))
