"""
Unit tests for SOAP report row-level ownership / authorization logic.

守護 REPORTS-1 / REPORTS-7 / REPORTS-10 資安阻斷：
- patient 只能讀取自己名下 Patient → session 的報告
- doctor 只能讀取 doctor_id == self 或 doctor_id IS NULL(未指派)的 session 報告
- admin 無限制
- 未知角色 / 缺 current_user → 拒絕（以 NotFound 避免洩漏存在與否）

測試採純 Python stub（無真 DB），只驗 `_authorize_report_access` 與
`_get_user_role` 兩個核心函式，以及 generate_report 所呼叫之 service 方法簽章存在性。
list_reports 的 SQL 範圍限縮走 DB，留給 integration test 覆蓋。
"""

from __future__ import annotations

import asyncio
import inspect
import uuid
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Optional

import pytest

from app.core.exceptions import NotFoundException
from app.models.enums import UserRole
from app.services.report_service import (
    ReportService,
    _authorize_report_access,
    _get_user_role,
)


def _run(coro):
    """在 sync test 裡跑 coroutine，避免多裝 pytest-asyncio。"""
    return asyncio.run(coro)


# ──────────────────────────────────────────────────────
# 測試工具
# ──────────────────────────────────────────────────────

@dataclass
class _Row:
    """模擬 result.one_or_none() 回傳的 (doctor_id, patient_id) tuple-row。"""
    doctor_id: Any
    patient_id: Any

    def __iter__(self):
        return iter((self.doctor_id, self.patient_id))


@dataclass
class _ScalarResult:
    value: Any

    def scalar_one_or_none(self) -> Any:
        return self.value


@dataclass
class _RowResult:
    row: Any

    def one_or_none(self) -> Any:
        return self.row


class _FakeDB:
    """
    最小 AsyncSession 替身。

    第一個 execute 回傳 session 的 (doctor_id, patient_id) row；
    若 caller 進入 patient 分支，第二個 execute 回傳 Patient.user_id scalar。
    """

    def __init__(
        self,
        session_row: Optional[_Row],
        patient_owner_id: Any = None,
    ) -> None:
        self._session_row = session_row
        self._patient_owner_id = patient_owner_id
        self.execute_calls = 0

    async def execute(self, stmt: Any):
        self.execute_calls += 1
        if self.execute_calls == 1:
            return _RowResult(self._session_row)
        # 第二次 → patient owner 查詢
        return _ScalarResult(self._patient_owner_id)


def _make_user(role: UserRole | str, user_id: Optional[uuid.UUID] = None) -> SimpleNamespace:
    return SimpleNamespace(id=user_id or uuid.uuid4(), role=role)


def _make_report(session_id: Optional[uuid.UUID] = None) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), session_id=session_id or uuid.uuid4())


# ──────────────────────────────────────────────────────
# _get_user_role（與 session_service 同語意）
# ──────────────────────────────────────────────────────

def test_get_user_role_none_returns_none():
    assert _get_user_role(None) is None


def test_get_user_role_enum():
    assert _get_user_role(_make_user(UserRole.DOCTOR)) is UserRole.DOCTOR


def test_get_user_role_string_converts():
    assert _get_user_role(_make_user("patient")) is UserRole.PATIENT


def test_get_user_role_unknown_string_is_none():
    assert _get_user_role(_make_user("hacker")) is None


# ──────────────────────────────────────────────────────
# admin: 無限制（不查 session/patient）
# ──────────────────────────────────────────────────────

def test_admin_can_access_any_report():
    admin = _make_user(UserRole.ADMIN)
    report = _make_report()
    db = _FakeDB(session_row=_Row(uuid.uuid4(), uuid.uuid4()))
    _run(_authorize_report_access(db, report, admin))
    assert db.execute_calls == 0  # admin 短路，不查 DB


# ──────────────────────────────────────────────────────
# doctor: 自己負責 + 未指派 → ok；其他醫師 → 拒絕
# ──────────────────────────────────────────────────────

def test_doctor_can_access_own_assigned_report():
    doctor = _make_user(UserRole.DOCTOR)
    report = _make_report()
    db = _FakeDB(session_row=_Row(doctor.id, uuid.uuid4()))
    _run(_authorize_report_access(db, report, doctor))
    assert db.execute_calls == 1


def test_doctor_can_access_unassigned_report():
    doctor = _make_user(UserRole.DOCTOR)
    report = _make_report()
    db = _FakeDB(session_row=_Row(None, uuid.uuid4()))
    _run(_authorize_report_access(db, report, doctor))


def test_doctor_cannot_access_other_doctor_report():
    doctor_self = _make_user(UserRole.DOCTOR)
    report = _make_report()
    db = _FakeDB(session_row=_Row(uuid.uuid4(), uuid.uuid4()))  # 別的醫師
    with pytest.raises(NotFoundException):
        _run(_authorize_report_access(db, report, doctor_self))


# ──────────────────────────────────────────────────────
# patient: 自己名下 patient → ok；別人的 → 拒絕
# ──────────────────────────────────────────────────────

def test_patient_can_access_own_report():
    patient_user = _make_user(UserRole.PATIENT)
    patient_entity_id = uuid.uuid4()
    report = _make_report()
    db = _FakeDB(
        session_row=_Row(None, patient_entity_id),
        patient_owner_id=patient_user.id,
    )
    _run(_authorize_report_access(db, report, patient_user))
    assert db.execute_calls == 2  # session row + patient owner


def test_patient_cannot_access_other_users_report():
    """關鍵測試：patient A 拿 patient B 的報告 → 必須被拒絕（防 PII 外洩）。"""
    patient_a = _make_user(UserRole.PATIENT)
    patient_b_owner_id = uuid.uuid4()
    report = _make_report()
    db = _FakeDB(
        session_row=_Row(None, uuid.uuid4()),
        patient_owner_id=patient_b_owner_id,
    )
    with pytest.raises(NotFoundException):
        _run(_authorize_report_access(db, report, patient_a))


def test_patient_denied_when_patient_record_missing():
    patient_user = _make_user(UserRole.PATIENT)
    report = _make_report()
    db = _FakeDB(session_row=_Row(None, uuid.uuid4()), patient_owner_id=None)
    with pytest.raises(NotFoundException):
        _run(_authorize_report_access(db, report, patient_user))


# ──────────────────────────────────────────────────────
# 邊界：session 不存在 / 未知角色 / 無 current_user
# ──────────────────────────────────────────────────────

def test_missing_session_raises_not_found():
    doctor = _make_user(UserRole.DOCTOR)
    report = _make_report()
    db = _FakeDB(session_row=None)
    with pytest.raises(NotFoundException):
        _run(_authorize_report_access(db, report, doctor))


def test_unknown_role_is_rejected():
    user = _make_user("hacker")
    report = _make_report()
    db = _FakeDB(session_row=_Row(None, uuid.uuid4()))
    with pytest.raises(NotFoundException):
        _run(_authorize_report_access(db, report, user))


def test_missing_current_user_is_rejected():
    report = _make_report()
    db = _FakeDB(session_row=_Row(None, uuid.uuid4()))
    with pytest.raises(NotFoundException):
        _run(_authorize_report_access(db, report, None))


# ──────────────────────────────────────────────────────
# 簽章契約：router 呼叫的 service 方法存在且接受 current_user
# ──────────────────────────────────────────────────────

def test_service_methods_accept_current_user_for_ownership():
    for name in ("get_report", "review_report", "export_pdf"):
        method = getattr(ReportService, name)
        params = inspect.signature(method).parameters
        assert "current_user" in params, f"{name} 應接受 current_user 以做 ownership 校驗"
