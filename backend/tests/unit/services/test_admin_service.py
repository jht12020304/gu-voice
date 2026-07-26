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


# ──────────────────────────────────────────────────────
# H1：管理員代為重設密碼（生產無 email transport 時唯一可行路徑）
# ──────────────────────────────────────────────────────

def test_generate_temp_password_always_satisfies_strength_rules():
    """臨時密碼必須保證通過 RegisterRequest 的強度驗證，不能靠隨機碰運氣。"""
    import re

    from app.core.security import generate_temp_password

    for _ in range(200):
        pw = generate_temp_password()
        assert len(pw) >= 8
        assert re.search(r"[A-Z]", pw), pw
        assert re.search(r"[a-z]", pw), pw
        assert re.search(r"\d", pw), pw
        # 易混淆字元會讓醫護口頭轉達出錯
        assert not (set(pw) & set("0Oo1lI")), pw


def test_reset_user_password_blocks_self():
    """不可重設自己（會繞過 change-password 的舊密碼驗證）→ 不進 DB。"""
    admin_id = uuid.uuid4()
    db = _FakeDB()
    with pytest.raises(ForbiddenException):
        _run(AdminService().reset_user_password(db, user_id=admin_id, reset_by=admin_id))
    assert db.flush_calls == 0


def test_reset_user_password_unknown_user_raises():
    from app.core.exceptions import NotFoundException

    db = _FakeDB([None])
    with pytest.raises(NotFoundException):
        _run(
            AdminService().reset_user_password(
                db, user_id=uuid.uuid4(), reset_by=uuid.uuid4()
            )
        )
    assert db.flush_calls == 0


def test_reset_user_password_rotates_hash_revokes_refresh_and_audits(monkeypatch):
    """成功路徑：換 hash、撤銷 refresh token、寫 audit（且 audit 不含密碼）。"""
    import re

    target = _make_user(email="patient@example.com")
    target.password_hash = "OLD-HASH"
    admin_id = uuid.uuid4()
    db = _FakeDB([target])

    hashed: list[str] = []
    monkeypatch.setattr(
        "app.services.admin_service.hash_password",
        lambda pw: hashed.append(pw) or f"HASHED::{pw}",
    )

    revoked_for: list[str] = []

    async def _fake_revoke(_redis, user_id):
        revoked_for.append(str(user_id))
        return 3

    async def _fake_get_redis():
        return object()

    monkeypatch.setattr("app.cache.redis_client.get_redis", _fake_get_redis)
    monkeypatch.setattr(
        "app.services.auth_service._revoke_all_refresh_tokens", _fake_revoke
    )

    audits: list[dict] = []

    async def _fake_log(_db, **kwargs):
        audits.append(kwargs)

    monkeypatch.setattr(AuditLogService, "log", _fake_log)

    result = _run(
        AdminService().reset_user_password(db, user_id=target.id, reset_by=admin_id)
    )

    # 回應帶明文臨時密碼（只此一次），且通過強度規則
    assert result.temp_password
    assert re.search(r"[A-Z]", result.temp_password)
    assert re.search(r"\d", result.temp_password)
    assert result.email == target.email

    # hash 真的被換掉，且存的是 hash 不是明文
    assert target.password_hash == f"HASHED::{result.temp_password}"
    assert hashed == [result.temp_password]
    assert db.flush_calls == 1

    # 舊 session 必須一起失效（重設常見情境＝帳號可能已外洩）
    assert revoked_for == [str(target.id)]

    # audit 有寫，但 details 不可含密碼
    assert len(audits) == 1
    details = audits[0]["details"]
    assert details["password_reset"] is True
    assert details["refresh_tokens_revoked"] == 3
    assert result.temp_password not in str(audits[0])


def test_reset_user_password_survives_redis_failure(monkeypatch):
    """Redis 掛掉不該讓重設失敗——密碼已經換掉了，回滾反而更糟。"""
    target = _make_user()
    target.password_hash = "OLD"
    db = _FakeDB([target])

    monkeypatch.setattr(
        "app.services.admin_service.hash_password", lambda pw: f"H::{pw}"
    )

    async def _boom():
        raise RuntimeError("redis down")

    monkeypatch.setattr("app.cache.redis_client.get_redis", _boom)

    async def _fake_log(_db, **kwargs):
        return None

    monkeypatch.setattr(AuditLogService, "log", _fake_log)

    result = _run(
        AdminService().reset_user_password(
            db, user_id=target.id, reset_by=uuid.uuid4()
        )
    )
    assert result.temp_password
    assert target.password_hash.startswith("H::")


def test_audit_rules_cover_admin_reset_password():
    """ADMIN-8 同精神：代為重設密碼比 toggle-active 更敏感，必須留稽核軌跡，
    且要抽出 user_id，不可被通用 /admin/users 的 CREATE 規則誤吞。"""
    from app.core.middleware import _match_audit_rule
    from app.models.enums import AuditAction

    uid = str(uuid.uuid4())
    matched = _match_audit_rule("POST", f"/api/v1/admin/users/{uid}/reset-password")
    assert matched is not None, "reset-password 未被 _AUDIT_RULES 覆蓋"

    action, resource_type, resource_id = matched
    assert action is AuditAction.UPDATE
    assert resource_type == "user"
    assert resource_id == uid, "resource_id 應為被重設的使用者，不是 None"
