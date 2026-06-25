"""
Unit tests for alert_service red-flag safety fixes (P3-alerts-realtime).

純 Python stub（無真 DB），守護兩個 production blocker 的核心邏輯：

- API-1：醫師 acknowledge 警示時 router 會傳 action_taken=，
  AlertService.acknowledge() / acknowledge_alert() 別名必須接受並寫入
  RedFlagAlert.action_taken 欄位，否則 TypeError → 醫師無法 acknowledge。
- AUTH-1：get_list 對 doctor 角色須以 session.doctor_id == self.id 限縮範圍，
  admin 看全部。此處驗 _get_user_role（範圍判斷的閘門）。

acknowledge 的 SQL 走 _get_by_id，因此用最小 AsyncSession 替身回傳預備好的
RedFlagAlert，驗 action_taken / notes / acknowledged_by 被正確寫入。
get_list 的 SQL 組裝（join Session）留給 integration test，本處只守角色閘門 +
方法簽章相容性（router 真正呼叫的 kwargs）。
"""

from __future__ import annotations

import asyncio
import inspect
import uuid
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Optional

import pytest

from app.models.enums import UserRole
from app.services.alert_service import (
    AlertService,
    _doctor_scope_id,
    _get_user_role,
)


def _run(coro):
    """在 sync test 裡跑 coroutine，避免多裝 pytest-asyncio。"""
    return asyncio.run(coro)


# ──────────────────────────────────────────────────────
# 測試工具
# ──────────────────────────────────────────────────────

@dataclass
class _FakeScalarResult:
    value: Any

    def scalar_one_or_none(self) -> Any:
        return self.value


class _FakeDB:
    """最小 AsyncSession 替身：execute 回傳預備好的 alert；flush 不做事。"""

    def __init__(self, alert: Any) -> None:
        self._alert = alert
        self.flush_calls = 0

    async def execute(self, stmt: Any) -> _FakeScalarResult:
        return _FakeScalarResult(self._alert)

    async def flush(self) -> None:
        self.flush_calls += 1


@dataclass
class _FakeAlert:
    """RedFlagAlert 的最小替身，只放 acknowledge 會寫的欄位。"""
    acknowledged_by: Optional[uuid.UUID] = None
    acknowledged_at: Any = None
    acknowledge_notes: Optional[str] = None
    action_taken: Optional[str] = None


def _make_user(role: UserRole | str, user_id: Optional[uuid.UUID] = None) -> SimpleNamespace:
    return SimpleNamespace(id=user_id or uuid.uuid4(), role=role)


# ──────────────────────────────────────────────────────
# AUTH-1：_get_user_role 角色閘門（get_list doctor 範圍限縮的依據）
# ──────────────────────────────────────────────────────

def test_get_user_role_none_returns_none():
    assert _get_user_role(None) is None


def test_get_user_role_doctor_enum():
    assert _get_user_role(_make_user(UserRole.DOCTOR)) == UserRole.DOCTOR


def test_get_user_role_admin_string():
    assert _get_user_role(_make_user("admin")) == UserRole.ADMIN


def test_get_user_role_unknown_string_returns_none():
    assert _get_user_role(_make_user("superhacker")) is None


def test_get_list_accepts_current_user_kwarg():
    # router 會以 current_user= 傳入；簽章必須接受，否則 TypeError。
    sig = inspect.signature(AlertService.get_list)
    assert "current_user" in sig.parameters


# ──────────────────────────────────────────────────────
# API-1：acknowledge 寫入 action_taken（router 傳 action_taken= 不可 TypeError）
# ──────────────────────────────────────────────────────

def test_acknowledge_persists_action_taken_and_notes():
    alert = _FakeAlert()
    db = _FakeDB(alert)
    user_id = uuid.uuid4()

    result = _run(
        AlertService.acknowledge(
            db,
            alert_id=uuid.uuid4(),
            user_id=user_id,
            notes="已轉急診",
            action_taken="安排立即就醫並通報主治",
        )
    )

    assert result.acknowledged_by == user_id
    assert result.acknowledge_notes == "已轉急診"
    assert result.action_taken == "安排立即就醫並通報主治"
    assert result.acknowledged_at is not None
    assert db.flush_calls == 1


def test_acknowledge_action_taken_defaults_none():
    alert = _FakeAlert()
    db = _FakeDB(alert)

    result = _run(
        AlertService.acknowledge(db, alert_id=uuid.uuid4(), user_id=uuid.uuid4())
    )
    # 未傳 action_taken 時應為 None（向後相容，欄位 nullable）。
    assert result.action_taken is None


def test_acknowledge_alert_alias_matches_router_kwargs():
    # router 呼叫：acknowledge_alert(db, alert_id=, acknowledged_by=, acknowledge_notes=, action_taken=)
    sig = inspect.signature(AlertService.acknowledge_alert)
    params = sig.parameters
    for expected in ("alert_id", "acknowledged_by", "acknowledge_notes", "action_taken"):
        assert expected in params, f"acknowledge_alert 缺少 router 需要的 kwarg: {expected}"


def test_acknowledge_alert_alias_routes_action_taken():
    alert = _FakeAlert()
    db = _FakeDB(alert)
    svc = AlertService()
    user_id = uuid.uuid4()

    result = _run(
        svc.acknowledge_alert(
            db,
            alert_id=uuid.uuid4(),
            acknowledged_by=user_id,
            acknowledge_notes="note",
            action_taken="action",
        )
    )
    assert result.acknowledged_by == user_id
    assert result.acknowledge_notes == "note"
    assert result.action_taken == "action"


# ──────────────────────────────────────────────────────
# AL-alert-count-scope：get_unacknowledged_count 依角色範圍限縮
# 補上 AUTH-1 follow-up — count endpoint 先前 select(func.count()) 無醫師範圍，
# 任何醫師都看到全域未確認數。這裡守 count 的範圍閘門 + 共用 scoping helper。
# ──────────────────────────────────────────────────────


@dataclass
class _CountFakeResult:
    value: int

    def scalar(self) -> int:
        return self.value


class _CountCapturingDB:
    """最小 AsyncSession 替身：擷取 execute 收到的 statement，回傳固定 count。"""

    def __init__(self, count: int = 7) -> None:
        self._count = count
        self.executed_stmt: Any = None
        self.execute_calls = 0

    async def execute(self, stmt: Any) -> _CountFakeResult:
        self.execute_calls += 1
        self.executed_stmt = stmt
        return _CountFakeResult(self._count)


def _stmt_sql(stmt: Any) -> str:
    """把 SQLAlchemy statement 轉成 SQL 字串以便檢查 join / where。"""
    return str(stmt).lower()


def test_doctor_scope_id_doctor_returns_self_id():
    doctor = _make_user(UserRole.DOCTOR)
    assert _doctor_scope_id(doctor) == doctor.id


def test_doctor_scope_id_admin_returns_none():
    assert _doctor_scope_id(_make_user(UserRole.ADMIN)) is None


def test_count_signature_accepts_current_user_kwarg():
    # router 以 current_user= 呼叫；簽章必須接受，否則 TypeError。
    sig = inspect.signature(AlertService.get_unacknowledged_count)
    assert "current_user" in sig.parameters


def test_count_applies_doctor_filter_for_doctor():
    doctor = _make_user(UserRole.DOCTOR)
    db = _CountCapturingDB(count=3)

    count = _run(AlertService.get_unacknowledged_count(db, current_user=doctor))

    assert count == 3
    assert db.execute_calls == 1
    sql = _stmt_sql(db.executed_stmt)
    # 醫師範圍：join sessions 並以 doctor_id 過濾 + 只算未確認。
    assert "join sessions" in sql or "join \"sessions\"" in sql
    assert "doctor_id" in sql
    assert "acknowledged_by is null" in sql


def test_count_no_doctor_filter_for_admin():
    admin = _make_user(UserRole.ADMIN)
    db = _CountCapturingDB(count=12)

    count = _run(AlertService.get_unacknowledged_count(db, current_user=admin))

    assert count == 12
    assert db.execute_calls == 1
    sql = _stmt_sql(db.executed_stmt)
    # admin 看全部：不得 join sessions、不得有 doctor_id 過濾。
    assert "join sessions" not in sql
    assert "doctor_id" not in sql
    # 但仍只算未確認。
    assert "acknowledged_by is null" in sql


def test_count_returns_zero_for_patient_without_db():
    patient = _make_user(UserRole.PATIENT)
    db = _CountCapturingDB(count=99)

    count = _run(AlertService.get_unacknowledged_count(db, current_user=patient))

    # patient / 未知角色 fail-safe 回 0，且不查 DB（避免任何洩漏）。
    assert count == 0
    assert db.execute_calls == 0


def test_count_returns_zero_for_unknown_role_without_db():
    hacker = _make_user("superhacker")
    db = _CountCapturingDB(count=99)

    count = _run(AlertService.get_unacknowledged_count(db, current_user=hacker))

    assert count == 0
    assert db.execute_calls == 0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
