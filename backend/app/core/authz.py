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


def clinician_can_access_session(session_doctor_id: Any, clinician_id: Any) -> bool:
    """臨床帳號能否讀這場問診：自己負責的、或**尚未指派**的。

    未指派要放行的理由（2026-09-09 生產實證）：kiosk 問診在當下不會指派醫師
    （`sessions.doctor_id` 恆 NULL），而 `notification_service._doctor_targets()`
    對未指派場次是**刻意 fan-out 給全體臨床帳號**的。存取面若把未指派排除，
    醫師收到「報告已生成」推播、點進去必得 403 —— 四位測試醫師 09-09 全中，
    近 30 天 20 場未指派場次一場都打不開。

    WebSocket 那條路（`_authorize_session_access` 的 WS 版）本來就是「未指派或
    指派給本人」放行；這裡是把 REST 對齊回同一個模型。
    """
    return session_doctor_id is None or session_doctor_id == clinician_id


def clinician_session_filter(clinician_id: Any):
    """`clinician_can_access_session` 的 SQL 版，給 query 層限縮用。"""
    from sqlalchemy import or_

    from app.models.session import Session

    return or_(Session.doctor_id == clinician_id, Session.doctor_id.is_(None))
