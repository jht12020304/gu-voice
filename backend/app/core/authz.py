"""共用授權小工具。

get_user_role 原本在 patient / session / report / alert 四個 service
各有一份逐字相同的複製，收斂到這裡單一來源。
"""

from typing import Any, Optional

from app.models.enums import UserRole


def get_user_role(current_user: Any) -> Optional[UserRole]:
    """從 current_user 取出 role，容忍 string 或 enum 兩種來源。"""
    if current_user is None:
        return None
    raw = getattr(current_user, "role", None)
    if raw is None:
        return None
    if isinstance(raw, UserRole):
        return raw
    try:
        return UserRole(raw)
    except ValueError:
        return None


def get_clinician_scope_id(current_user: Any) -> Any:
    """回傳需要依指派病患隔離的臨床帳號 ID。"""
    role = get_user_role(current_user)
    if role == UserRole.DOCTOR or (
        role == UserRole.ADMIN and getattr(current_user, "license_number", None)
    ):
        return getattr(current_user, "id", None)
    return None
