"""醫師＝管理員（2026-08-22 拍板）的 router 守衛 contract test。

拍板內容：admin 四頁與其 API 對醫師開放。當時只改了 app/routers/admin.py 的
`require_role("admin", "doctor")`，**漏掉稽核日誌那支獨立 router**
（app/routers/audit_logs.py）——iOS 稽核日誌頁對醫師 403 的根因之一
（另一半是 Flutter 打錯路徑，同輪修正）。

這支測試把「admin 區的每一支 router 都要放行 doctor」寫成清單斷言：
之後再新增 admin 區 router 而漏開 doctor，這裡會紅。
檢法比照 test_complaints_access.py：讀 router 依賴 metadata，不起 DB/HTTP。
"""

from __future__ import annotations

from app.routers import admin as admin_router
from app.routers import audit_logs as audit_logs_router

# admin 區的 router 清單（新增 admin 區 router 時要登記進來）
_ADMIN_AREA_ROUTERS = {
    "admin": admin_router.router,
    "audit_logs": audit_logs_router.router,
}


def _router_allowed_roles(router) -> set[str]:
    """自 router 層級依賴撈出 require_role 的允許清單。

    require_role(*roles) 回傳的 checker 是 closure，允許的角色存在
    `__closure__` 的 cell 裡；比對字串值即可（roles 以 str 傳入）。
    """
    allowed: set[str] = set()
    for dep in router.dependencies:
        fn = dep.dependency
        for cell in getattr(fn, "__closure__", None) or ():
            value = cell.cell_contents
            if isinstance(value, (tuple, list, set, frozenset)):
                allowed.update(str(v) for v in value)
    return allowed


def test_every_admin_area_router_admits_doctor():
    for name, router in _ADMIN_AREA_ROUTERS.items():
        allowed = _router_allowed_roles(router)
        assert "admin" in allowed, f"{name} router 應允許 admin（實際：{allowed}）"
        assert "doctor" in allowed, (
            f"{name} router 未放行 doctor——違反 2026-08-22 醫師＝管理員拍板"
            f"（實際允許：{allowed}）。audit_logs 就是這樣漏掉過一次。"
        )


def test_admin_area_routers_do_not_admit_patient():
    for name, router in _ADMIN_AREA_ROUTERS.items():
        allowed = _router_allowed_roles(router)
        assert "patient" not in allowed, f"{name} router 不得放行 patient（實際：{allowed}）"
