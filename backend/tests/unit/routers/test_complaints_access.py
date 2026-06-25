"""
主訴列表存取授權 contract test（P0 launch blocker 回歸守護）。

驗證重點：
1. GET /api/v1/complaints 的 router 依賴允許 patient 角色讀取列表
   （先前是 require_role("doctor","admin")，病患拿到 403 無法開始問診）。
2. 病患路徑被限縮：handler 強制 is_active=True 且 is_default=True，
   病患看不到醫師的私有自訂主訴；醫師 / 管理員不受限。
3. create / update / delete 不受此放寬影響——這裡用 router 依賴
   metadata 斷言 list 端點放寬、其餘維持限縮，不需起 DB / HTTP server。

不需真 DB：直接呼叫 router handler（async callable），以 AsyncMock
替身 service，並檢查傳給 service 的 scoping kwargs。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.dependencies import require_role
from app.core.exceptions import ForbiddenException
from app.models.enums import UserRole
from app.routers import complaints as complaints_router


def _run(coro):
    return asyncio.run(coro)


def _user(role: UserRole) -> SimpleNamespace:
    return SimpleNamespace(role=role, id="00000000-0000-0000-0000-000000000001")


def _request() -> SimpleNamespace:
    # get_request_language 先讀 request.state.language；給定即可避免即時解析。
    return SimpleNamespace(state=SimpleNamespace(language="zh-TW"))


# ──────────────────────────────────────────────────────
# 1. 角色授權：patient 被允許讀 list；非授權角色被擋
# ──────────────────────────────────────────────────────

def test_require_role_permits_patient_for_list():
    """list 端點的依賴工廠應放行 doctor / admin / patient 三者。"""
    checker = require_role("doctor", "admin", "patient")
    for role in (UserRole.PATIENT, UserRole.DOCTOR, UserRole.ADMIN):
        result = _run(checker(current_user=_user(role)))
        assert result.role == role


def test_require_role_rejects_unknown_role():
    """未列入的角色仍應被擋（確保放寬範圍精準）。"""
    checker = require_role("doctor", "admin", "patient")
    bogus = SimpleNamespace(role=SimpleNamespace(value="nurse"), id="x")
    with pytest.raises(ForbiddenException):
        _run(checker(current_user=bogus))


def test_list_endpoint_dependency_allows_patient():
    """GET list 的 router metadata 必須宣告允許 patient（防止回歸成 403）。"""
    route = next(
        r for r in complaints_router.router.routes
        if getattr(r, "path", None) == "/api/v1/complaints"
        and "GET" in getattr(r, "methods", set())
    )
    # 依賴鏈裡至少有一個 require_role 的 closure 含 patient
    captured: list[tuple[str, ...]] = []
    for dep in route.dependencies:
        call = getattr(dep, "dependency", None)
        closure = getattr(call, "__closure__", None) or ()
        for cell in closure:
            val = cell.cell_contents
            if isinstance(val, tuple) and all(isinstance(v, str) for v in val):
                captured.append(val)
    assert any("patient" in roles for roles in captured), (
        "list 端點未放行 patient，病患會拿到 403 無法開始問診"
    )


# ──────────────────────────────────────────────────────
# 2. 病患路徑被限縮：is_active=True 且 is_default=True
# ──────────────────────────────────────────────────────

def test_patient_list_is_scoped_to_active_default():
    """病患呼叫時，傳給 service 的查詢被強制限縮。"""
    fake_service = AsyncMock()
    fake_service.list_complaints.return_value = {
        "data": [],
        "pagination": {"next_cursor": None, "has_more": False, "limit": 20, "total_count": 0},
    }
    original = complaints_router.complaint_service
    complaints_router.complaint_service = fake_service
    try:
        _run(
            complaints_router.list_complaints(
                request=_request(),
                db=AsyncMock(),
                current_user=_user(UserRole.PATIENT),
                cursor=None,
                limit=20,
                category=None,
                # 即使病患嘗試傳入 is_default=False / is_active=False，
                # handler 也必須覆寫回限縮值（不可信任 client 輸入）。
                is_default=False,
                search=None,
                is_active=False,
            )
        )
    finally:
        complaints_router.complaint_service = original

    fake_service.list_complaints.assert_awaited_once()
    kwargs = fake_service.list_complaints.await_args.kwargs
    assert kwargs["is_active"] is True, "病患路徑必須限縮為啟用中主訴"
    assert kwargs["is_default"] is True, "病患路徑必須限縮為系統預設主訴"


def test_doctor_list_is_not_scoped():
    """醫師查詢不被覆寫，維持原有自由篩選能力。"""
    fake_service = AsyncMock()
    fake_service.list_complaints.return_value = {
        "data": [],
        "pagination": {"next_cursor": None, "has_more": False, "limit": 20, "total_count": 0},
    }
    original = complaints_router.complaint_service
    complaints_router.complaint_service = fake_service
    try:
        _run(
            complaints_router.list_complaints(
                request=_request(),
                db=AsyncMock(),
                current_user=_user(UserRole.DOCTOR),
                cursor=None,
                limit=20,
                category=None,
                is_default=False,
                search=None,
                is_active=False,
            )
        )
    finally:
        complaints_router.complaint_service = original

    kwargs = fake_service.list_complaints.await_args.kwargs
    assert kwargs["is_active"] is False, "醫師的 is_active 篩選不應被覆寫"
    assert kwargs["is_default"] is False, "醫師的 is_default 篩選不應被覆寫"


# ──────────────────────────────────────────────────────
# 3. 寫入端點仍維持 doctor/admin-only（放寬僅限 GET list）
# ──────────────────────────────────────────────────────

def test_mutation_endpoints_stay_doctor_admin_only():
    """create / reorder 端點的依賴不得放行 patient。"""
    write_paths = {"/api/v1/complaints", "/api/v1/complaints/reorder"}
    for route in complaints_router.router.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", set())
        if path not in write_paths:
            continue
        # 只檢查非 GET 的寫入方法
        if methods <= {"GET", "HEAD"}:
            continue
        for dep in route.dependencies:
            call = getattr(dep, "dependency", None)
            closure = getattr(call, "__closure__", None) or ()
            for cell in closure:
                val = cell.cell_contents
                if isinstance(val, tuple) and all(isinstance(v, str) for v in val):
                    assert "patient" not in val, (
                        f"寫入端點 {methods} {path} 不應放行 patient"
                    )
