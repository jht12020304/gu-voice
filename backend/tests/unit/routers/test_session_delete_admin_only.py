"""`DELETE /api/v1/sessions/{id}` 只放行 admin 的 contract test。

2026-08-23 拍板：「要有一個最高權限，可以刪除問答內容」。這條路徑是**刻意**
不套用「醫師＝管理員（2026-08-22）」慣例的少數端點之一——admin 區的頁面對醫師
開放沒問題，但刪病歷不是一般醫師可代行的動作。要給誰就把那個帳號升成 admin。

這支測試把它寫成斷言：日後誰把 `require_role("admin")` 放寬成
`require_role("admin", "doctor")`（很容易，因為隔壁每一支都是那樣寫的），
這裡會紅。檢法比照 test_admin_area_doctor_access.py：讀 route 依賴 metadata，
不起 DB / HTTP。
"""

from __future__ import annotations

from app.routers import sessions as sessions_router


def _route_allowed_roles(route) -> set[str]:
    """自單一 route 的依賴撈出 require_role 的允許清單（closure cell）。"""
    allowed: set[str] = set()
    for dep in getattr(route, "dependencies", []):
        fn = dep.dependency
        for cell in getattr(fn, "__closure__", None) or ():
            value = cell.cell_contents
            if isinstance(value, (tuple, list, set, frozenset)):
                allowed.update(str(v) for v in value)
    return allowed


def _delete_session_route():
    for route in sessions_router.router.routes:
        if "DELETE" in getattr(route, "methods", set()) and route.path.endswith(
            "/{session_id}"
        ):
            return route
    raise AssertionError("找不到 DELETE /sessions/{session_id} route")


def test_delete_session_route_exists():
    route = _delete_session_route()
    assert route is not None


def test_delete_session_is_admin_only():
    allowed = _route_allowed_roles(_delete_session_route())
    assert allowed == {"admin"}, (
        "刪除問診場次只准 admin。實際允許："
        f"{allowed}——若這裡被放寬成含 doctor，等於全院每位醫師都能刪病歷，"
        "違反 2026-08-23 的拍板（要給誰就把那個帳號升成 admin）。"
    )


def test_other_session_routes_still_open_to_non_admin():
    """回歸守衛：別為了這條 DELETE 把整個 router 掛上 admin-only 依賴。

    整個 sessions router 若被加上 router 層級的 require_role("admin")，
    病患就再也開不了問診——這比刪不掉場次嚴重得多。
    """
    assert not sessions_router.router.dependencies, (
        "sessions router 不得有 router 層級的角色依賴（病患要能建立場次）"
    )
