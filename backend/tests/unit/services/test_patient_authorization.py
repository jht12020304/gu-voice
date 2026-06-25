"""
Unit tests for patient ownership / authorization logic.

守護 P2-patients 資安阻斷:
- doctor 只能存取 patient.user_id == self 的病患
- admin 無限制
- patient / 未知角色 / 缺 current_user → 拒絕

測試採用純 Python stub(無真 DB),只驗 `_authorize_patient_access` 與
`_get_user_role` 這兩個核心函式,並以反射確認 router 呼叫的
`soft_delete_patient` / `list_patients` / `get_patient_sessions` 簽章存在。
"""

from __future__ import annotations

import inspect
import uuid
from typing import Any, Optional
from types import SimpleNamespace

import pytest

from app.core.exceptions import ForbiddenException
from app.models.enums import UserRole
from app.services.patient_service import (
    PatientService,
    _authorize_patient_access,
    _get_user_role,
)


# ──────────────────────────────────────────────────────
# 測試工具
# ──────────────────────────────────────────────────────

def _make_user(role: UserRole | str, user_id: Optional[uuid.UUID] = None) -> SimpleNamespace:
    return SimpleNamespace(id=user_id or uuid.uuid4(), role=role)


def _make_patient(
    patient_id: Optional[uuid.UUID] = None,
    owner_user_id: Optional[uuid.UUID] = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=patient_id or uuid.uuid4(),
        user_id=owner_user_id or uuid.uuid4(),
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
    user = _make_user("admin")
    assert _get_user_role(user) is UserRole.ADMIN


def test_get_user_role_unknown_string_is_none():
    user = _make_user("hacker")
    assert _get_user_role(user) is None


# ──────────────────────────────────────────────────────
# admin: 無限制
# ──────────────────────────────────────────────────────

def test_admin_can_access_any_patient():
    admin = _make_user(UserRole.ADMIN)
    patient = _make_patient(owner_user_id=uuid.uuid4())  # 任意醫師名下
    _authorize_patient_access(patient, admin)  # 不應 raise


# ──────────────────────────────────────────────────────
# doctor: 只能存取自己名下病患
# ──────────────────────────────────────────────────────

def test_doctor_can_access_own_patient():
    doctor = _make_user(UserRole.DOCTOR)
    patient = _make_patient(owner_user_id=doctor.id)
    _authorize_patient_access(patient, doctor)  # 不應 raise


def test_doctor_cannot_access_other_doctor_patient():
    """關鍵測試: doctor A 拿 doctor B 名下病患的 UUID 來讀 → 必須被拒絕。"""
    doctor_a = _make_user(UserRole.DOCTOR)
    patient_of_b = _make_patient(owner_user_id=uuid.uuid4())  # 非 doctor_a
    with pytest.raises(ForbiddenException):
        _authorize_patient_access(patient_of_b, doctor_a)


# ──────────────────────────────────────────────────────
# 邊界: patient 角色 / 未知角色 / 缺 current_user
# ──────────────────────────────────────────────────────

def test_patient_role_is_rejected():
    patient_user = _make_user(UserRole.PATIENT)
    patient = _make_patient(owner_user_id=patient_user.id)
    with pytest.raises(ForbiddenException):
        _authorize_patient_access(patient, patient_user)


def test_unknown_role_is_rejected():
    user = _make_user("hacker")
    patient = _make_patient()
    with pytest.raises(ForbiddenException):
        _authorize_patient_access(patient, user)


def test_missing_current_user_raises():
    patient = _make_patient()
    with pytest.raises(ForbiddenException):
        _authorize_patient_access(patient, None)


# ──────────────────────────────────────────────────────
# 簽章存在性: router 呼叫的方法必須存在且簽章相容
# ──────────────────────────────────────────────────────

def test_soft_delete_patient_exists_with_expected_signature():
    """PATIENT-DELETE-1: router DELETE 呼叫 soft_delete_patient,需存在。"""
    method = getattr(PatientService, "soft_delete_patient", None)
    assert method is not None and callable(method)
    params = inspect.signature(method).parameters
    assert "patient_id" in params
    assert "deleted_by" in params


def test_list_patients_accepts_current_user():
    """PATIENT-AUTHZ-2: list_patients 需接受 current_user 以做 doctor scoping。"""
    params = inspect.signature(PatientService.list_patients).parameters
    assert "current_user" in params


def test_get_patient_sessions_accepts_current_user():
    """PATIENT-AUTHZ-1: get_patient_sessions 需接受 current_user 以做 ownership 校驗。"""
    params = inspect.signature(PatientService.get_patient_sessions).parameters
    assert "current_user" in params
