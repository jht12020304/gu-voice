"""共用授權小工具。

get_user_role 原本在 patient / session / report / alert 四個 service
各有一份逐字相同的複製，收斂到這裡單一來源。
"""

from typing import Any, Optional
from uuid import UUID

from app.core.exceptions import ForbiddenException
from app.models.enums import UserRole
from app.models.user import User


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


def is_system_admin(actor: User | None) -> bool:
    return (
        get_user_role(actor) == UserRole.ADMIN
        and getattr(actor, "id", None) is not None
        and hasattr(actor, "license_number")
        and actor.license_number is None
    )


def check_system_admin(actor: User) -> None:
    if not is_system_admin(actor):
        raise ForbiddenException()


def clinical_reader_id(actor: User) -> UUID | None:
    """只有明確的系統管理員可使用全院的稽核或研究母體。"""
    if is_system_admin(actor):
        return None
    role = get_user_role(actor)
    license_number = getattr(actor, "license_number", None)
    licensed_admin = role == UserRole.ADMIN and isinstance(license_number, str) and license_number.strip()
    if getattr(actor, "id", None) is None or not (role == UserRole.DOCTOR or licensed_admin):
        raise ForbiddenException()
    return actor.id


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


async def patient_owned_by(db: Any, patient_id: Any, user_id: Any) -> bool:
    """病患帳號是否擁有此 patient（`patients.user_id == user_id`）。

    session_service／report_service 的病患分支先前各自寫同一段 query；共用一份，
    避免「病患只能看自己名下場次／報告」這條規則兩邊漂移。
    """
    from sqlalchemy import select

    from app.models.patient import Patient

    result = await db.execute(select(Patient.user_id).where(Patient.id == patient_id))
    owner_user_id = result.scalar_one_or_none()
    return owner_user_id is not None and owner_user_id == user_id
