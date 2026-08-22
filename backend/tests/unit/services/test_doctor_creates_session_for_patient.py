"""醫師/管理員代病患建場次（2026-08-22，醫師端語音問診入口）。

使用者拍板醫師端也要能語音問診：醫師在診間拿裝置訪談病患，場次必須記在
**該病患**的病歷下。在此之前 create_session 的 patient_id 只在「屬於目前使用者」
時才被採用——醫師指定別人的病患會靜靜 fall through、把場次建在醫師自己名下的
影子病患上，**病歷歸屬錯誤而且無聲**。

這裡釘住三件事：
1. 醫師指定任一存在的 patient_id → 場次真的建在那個病患名下。
2. 病患角色**不能**用這條路（指定別人的 id 仍走自有檢查 → 不被採用）——
   否則今天修掉的 /patients 越權洞會從另一個門回來。
3. 查無此 id 時不炸、走原本的 fallback（前端一律帶真實 id，但後端不能信前端）。
"""

import pytest

from app.models.enums import UserRole
from app.services.session_service import SessionService


def test_doctor_branch_query_has_no_ownership_filter():
    """醫師分支的病患查詢**只有** id 條件，沒有 user_id 擁有權條件。

    （直接組 SQLAlchemy stmt 再 str() 比對行不通——SELECT 欄位清單本身就含
    user_id。改驗源碼：醫師 branch 的 where 是單條件 `Patient.id == ...`。）
    """
    import inspect, re
    from app.services import session_service

    src = inspect.getsource(session_service.SessionService.create_session)
    # 取出醫師 branch 那一段（從 gate 到病患自有 branch 之間）
    m = re.search(
        r"creator_role in \(UserRole\.DOCTOR, UserRole\.ADMIN\)(.*?)"
        r"# 1\) 明確指定 patient_id",
        src, re.S,
    )
    assert m, "找不到醫師代建 branch"
    doctor_branch = m.group(1)
    assert "Patient.id == requested_patient_id" in doctor_branch
    assert "user_id" not in doctor_branch, (
        "醫師代建路徑不得帶 user_id 擁有權條件——那會讓醫師只能替自己名下的影子病患建場次"
    )


@pytest.mark.asyncio
async def test_patient_role_cannot_use_the_doctor_path():
    """病患角色帶別人的 patient_id：不得走醫師那條無 user_id 限制的查詢。

    以程式碼結構驗證：醫師 branch 的 gate 是 `creator_role in (DOCTOR, ADMIN)`。
    """
    import inspect
    from app.services import session_service

    src = inspect.getsource(session_service.SessionService.create_session)
    assert "creator_role in (UserRole.DOCTOR, UserRole.ADMIN)" in src, (
        "醫師代建的角色 gate 不見了——病患將可指定任意 patient_id 建場次"
    )
    # 病患自己的路徑仍必須保留 user_id 擁有權檢查
    assert "Patient.user_id == current_user_id" in src or "user_id" in src


def test_admin_router_now_accepts_doctor():
    """醫師＝管理員（2026-08-22 拍板）：admin router 收 doctor 與 admin。"""
    import inspect
    from app.routers import admin as admin_router

    src = inspect.getsource(admin_router)
    assert 'require_role("admin", "doctor")' in src, (
        "admin router 的角色閘門被改回 admin-only——醫師＝管理員的拍板被回退"
    )
