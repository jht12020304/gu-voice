"""問診 WS row-level 授權測試（P0 安全修復，2026-07-19）。

守護 `_authorize_ws_session_access`：WS 連線在 `_validate_session` 之後、
`connect_session` 之前必須做與 REST `_authorize_session_access` 同模型的
row-level 檢查——先前 WS 只驗 JWT 不驗擁有權，任何病患帳號拿到別人的
session UUID 就能接上別人的問診（IDOR）。

權限模型：admin 放行；doctor 於未指派或指派給本人時放行；patient 僅本人
場次放行；role/user 缺失一律拒絕（fail-closed）。
"""

from __future__ import annotations

from app.models.enums import UserRole
from app.websocket.conversation_handler import _authorize_ws_session_access

PATIENT_USER = "11111111-1111-4111-8111-111111111111"
DOCTOR_USER = "22222222-2222-4222-8222-222222222222"
OTHER_USER = "33333333-3333-4333-8333-333333333333"

SESSION = {"patient_user_id": PATIENT_USER, "doctor_id": DOCTOR_USER}


def test_patient_own_session_allowed():
    assert _authorize_ws_session_access(SESSION, PATIENT_USER, "patient") is True


def test_patient_other_session_denied():
    """核心 IDOR 情境：別的病患帳號連別人的場次必須拒絕。"""
    assert _authorize_ws_session_access(SESSION, OTHER_USER, "patient") is False


def test_assigned_doctor_allowed():
    assert _authorize_ws_session_access(SESSION, DOCTOR_USER, "doctor") is True


def test_other_doctor_denied_when_assigned():
    assert _authorize_ws_session_access(SESSION, OTHER_USER, "doctor") is False


def test_doctor_allowed_when_unassigned():
    data = {"patient_user_id": PATIENT_USER, "doctor_id": None}
    assert _authorize_ws_session_access(data, OTHER_USER, "doctor") is True


def test_admin_always_allowed():
    assert _authorize_ws_session_access(SESSION, OTHER_USER, "admin") is True


def test_enum_role_accepted():
    """role 可能是 UserRole enum（B 修復後 DB 來源）或字串（token claim），都要吃。"""
    assert _authorize_ws_session_access(SESSION, PATIENT_USER, UserRole.PATIENT) is True
    assert _authorize_ws_session_access(SESSION, OTHER_USER, UserRole.PATIENT) is False


def test_missing_role_or_user_denied():
    assert _authorize_ws_session_access(SESSION, PATIENT_USER, None) is False
    assert _authorize_ws_session_access(SESSION, None, "patient") is False
    assert _authorize_ws_session_access(SESSION, PATIENT_USER, "superuser") is False


def test_patient_session_without_user_link_denied():
    """病患記錄無 user_id（kiosk 代建）→ patient 角色一律拒絕，不得誤放行。"""
    data = {"patient_user_id": None, "doctor_id": None}
    assert _authorize_ws_session_access(data, PATIENT_USER, "patient") is False
