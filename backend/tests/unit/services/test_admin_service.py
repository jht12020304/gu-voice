"""
Unit tests for AdminService user-management + audit fixes (P5-admin-audit).

純 Python stub（無真 DB / 無真 Redis），只驗 production blocker 的核心邏輯：

- ADMIN-4 / ADMIN-9：toggle_active 必須真實 flip User.is_active，
  且禁止管理員對自己操作（self-deactivation guard → ForbiddenException）。
- ADMIN-2：create_user 重複 email 必須拋 EmailAlreadyExistsException。
- ADMIN-1：audit_logs router 呼叫的 list_audit_logs() / get_audit_log()
  必須存在於 AuditLogService（caller/callee 命名一致）。
- ADMIN-7：AdminUserUpdate 必須含 email 欄位（前端會送）。
- ADMIN-8（HIPAA）：middleware _AUDIT_RULES 必須覆蓋 admin 使用者
  建立 / 更新 / 啟用停用三類 mutation。

toggle_active / create_user 的 DB 寫入走 flush（commit 交給 get_db 依賴），
這裡用最小 AsyncSession 替身只驗純邏輯；完整 DB 行為留給 integration test。
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from typing import Any, Optional

import pytest

from app.core.exceptions import EmailAlreadyExistsException, ForbiddenException
from app.models.enums import UserRole
from app.schemas.admin import AdminUserCreate, AdminUserUpdate
from app.services.admin_service import AdminService
from app.services.audit_log_service import AuditLogService


def _run(coro):
    """在 sync test 裡跑 coroutine，避免多裝 pytest-asyncio。"""
    return asyncio.run(coro)


# ──────────────────────────────────────────────────────
# 測試工具
# ──────────────────────────────────────────────────────

class _FakeScalarResult:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value


class _FakeDB:
    """
    最小 AsyncSession 替身。

    `execute` 依序回傳 `results` 佇列裡的下一個值（None = 查不到）。
    `add` / `flush` / `commit` 只記錄被呼叫，不做事。
    """

    def __init__(self, results: Optional[list[Any]] = None) -> None:
        self._results = list(results or [])
        self.added: list[Any] = []
        self.flush_calls = 0
        self.commit_calls = 0

    async def execute(self, stmt: Any) -> _FakeScalarResult:
        value = self._results.pop(0) if self._results else None
        return _FakeScalarResult(value)

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        self.flush_calls += 1

    async def commit(self) -> None:
        self.commit_calls += 1


def _make_user(
    user_id: Optional[uuid.UUID] = None,
    *,
    email: str = "u@example.com",
    is_active: bool = True,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=user_id or uuid.uuid4(),
        email=email,
        name="Existing",
        role=UserRole.DOCTOR,
        is_active=is_active,
        updated_at=None,
    )


# ──────────────────────────────────────────────────────
# ADMIN-9：self-deactivation guard
# ──────────────────────────────────────────────────────

def test_toggle_active_blocks_self():
    """管理員不可切換自己的啟用狀態 → ForbiddenException，且不查 DB。"""
    admin_id = uuid.uuid4()
    db = _FakeDB()
    svc = AdminService()
    with pytest.raises(ForbiddenException):
        _run(svc.toggle_active(db, user_id=admin_id, toggled_by=admin_id))
    # 應在進 DB 前就擋下
    assert db.flush_calls == 0
    assert db.added == []


# ──────────────────────────────────────────────────────
# ADMIN-4：真實 flip is_active
# ──────────────────────────────────────────────────────

def test_toggle_active_flips_state_and_returns_new_state():
    target = _make_user(is_active=True)
    admin_id = uuid.uuid4()
    # 第一個 execute = 查 target user
    db = _FakeDB(results=[target])
    svc = AdminService()
    resp = _run(svc.toggle_active(db, user_id=target.id, toggled_by=admin_id))
    # DB 物件真的被 flip
    assert target.is_active is False
    # 回應反映實際新狀態（非寫死 False）
    assert resp.is_active is False
    assert resp.id == target.id
    # 應有寫 audit（AuditLogService.log → db.add 一筆 AuditLog）
    assert len(db.added) == 1


def test_toggle_active_flips_back_to_true():
    target = _make_user(is_active=False)
    db = _FakeDB(results=[target])
    svc = AdminService()
    resp = _run(svc.toggle_active(db, user_id=target.id, toggled_by=uuid.uuid4()))
    assert target.is_active is True
    assert resp.is_active is True


# ──────────────────────────────────────────────────────
# ADMIN-2：create_user 重複 email
# ──────────────────────────────────────────────────────

def test_create_user_duplicate_email_rejected():
    existing = _make_user(email="dup@example.com")
    # 第一個 execute = email 唯一性查詢，回傳既有 user → 視為重複
    db = _FakeDB(results=[existing])
    svc = AdminService()
    payload = AdminUserCreate(
        email="dup@example.com",
        password="password123",
        name="New",
        role=UserRole.DOCTOR,
    )
    with pytest.raises(EmailAlreadyExistsException):
        _run(svc.create_user(db, data=payload, created_by=uuid.uuid4()))
    # 不應建立任何 User
    assert db.added == []


# ──────────────────────────────────────────────────────
# ADMIN-1：caller/callee 命名一致
# ──────────────────────────────────────────────────────

def test_audit_log_service_has_router_facing_methods():
    """audit_logs router 呼叫的方法名必須存在於 AuditLogService。"""
    svc = AuditLogService()
    assert callable(getattr(svc, "list_audit_logs", None))
    assert callable(getattr(svc, "get_audit_log", None))


# ──────────────────────────────────────────────────────
# ADMIN-7：AdminUserUpdate 含 email
# ──────────────────────────────────────────────────────

def test_admin_user_update_has_email_field():
    assert "email" in AdminUserUpdate.model_fields
    # email 為可選（前端可只送 name / role）
    assert AdminUserUpdate().email is None


# ──────────────────────────────────────────────────────
# ADMIN-8（HIPAA）：admin mutation 必被 audit 規則覆蓋
# ──────────────────────────────────────────────────────

def test_audit_rules_cover_admin_mutations():
    from app.core.middleware import _match_audit_rule
    from app.models.enums import AuditAction

    rid = "11111111-2222-3333-4444-555555555555"

    create = _match_audit_rule("POST", "/api/v1/admin/users")
    assert create is not None and create[0] is AuditAction.CREATE and create[1] == "user"

    update = _match_audit_rule("PUT", f"/api/v1/admin/users/{rid}")
    assert update is not None and update[0] is AuditAction.UPDATE and update[1] == "user"

    patch = _match_audit_rule("PATCH", f"/api/v1/admin/users/{rid}")
    assert patch is not None and patch[0] is AuditAction.UPDATE

    toggle = _match_audit_rule("PUT", f"/api/v1/admin/users/{rid}/toggle-active")
    assert toggle is not None and toggle[0] is AuditAction.UPDATE and toggle[1] == "user"
