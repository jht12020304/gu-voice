"""
守護 P4-notifications happy-path 契約（router ↔ service ↔ schema 對齊）。

純 stub 測試：不起 FastAPI、不連 PG / Redis，只驗：
- NOTIF-001：router 呼叫的 `list_notifications` 確實存在且接受 is_read /
  notification_type 篩選參數，並回傳含 unread_count 的 dict。
- NOTIF-002：FCMTokenCreate schema 欄位為 device_token（router 已對齊）。
- NOTIF-003：mark_all_read 回傳 MarkAllReadResponse(updated_count=...)。
- NOTIF-004：remove_fcm_token 帶 user_id 參數，且查詢時以 user_id scope，
  避免越權停用他人裝置。
"""

from __future__ import annotations

import asyncio
import inspect
import uuid
from typing import Any

from app.schemas.notification import FCMTokenCreate, MarkAllReadResponse
from app.services.notification_service import NotificationService


def _run(coro):
    return asyncio.run(coro)


# ──────────────────────────────────────────────────────
# 測試工具
# ──────────────────────────────────────────────────────

class _FakeResult:
    def __init__(self, *, scalar: Any = None, rowcount: int = 0) -> None:
        self._scalar = scalar
        self.rowcount = rowcount

    def scalar(self) -> Any:
        return self._scalar

    def scalar_one_or_none(self) -> Any:
        return self._scalar

    def scalars(self):  # noqa: ANN201
        class _S:
            def __init__(self, value: Any) -> None:
                self._value = value

            def all(self) -> list[Any]:
                return list(self._value or [])

        return _S(self._scalar)


class _RecordingDB:
    """記錄每次 execute 的 SQL 文字，並依序回傳預先準備好的結果。"""

    def __init__(self, results: list[_FakeResult]) -> None:
        self._results = results
        self.statements: list[str] = []
        self._i = 0

    async def execute(self, stmt: Any, params: Any = None) -> _FakeResult:
        self.statements.append(str(stmt))
        if self._i < len(self._results):
            res = self._results[self._i]
            self._i += 1
            return res
        return _FakeResult()

    def add(self, obj: Any) -> None:  # pragma: no cover - 本測試未走新建分支
        pass

    async def flush(self) -> None:
        pass


# ──────────────────────────────────────────────────────
# NOTIF-001：method 名稱 + 篩選參數對齊
# ──────────────────────────────────────────────────────

def test_list_notifications_exists_with_filter_params():
    """router 呼叫的方法必須存在且接受 is_read / notification_type。"""
    assert hasattr(NotificationService, "list_notifications")
    assert not hasattr(NotificationService, "get_list")  # 舊名已移除
    sig = inspect.signature(NotificationService.list_notifications)
    for param in ("user_id", "cursor", "limit", "is_read", "notification_type"):
        assert param in sig.parameters, f"missing param: {param}"


def test_list_notifications_returns_unread_count_and_filters_applied():
    """回傳 dict 含 unread_count；指定 is_read 時 WHERE 子句帶 is_read 篩選。"""
    db = _RecordingDB(
        results=[
            _FakeResult(scalar=[]),   # list query → 空
            _FakeResult(scalar=3),    # total_count
            _FakeResult(scalar=2),    # unread_count
        ]
    )
    out = _run(
        NotificationService.list_notifications(
            db,  # type: ignore[arg-type]
            user_id=uuid.uuid4(),
            is_read=False,
            notification_type="system",
        )
    )
    assert out["unread_count"] == 2
    assert out["pagination"]["total_count"] == 3
    # list query 應帶 is_read 與 type 篩選
    list_sql = db.statements[0]
    assert "is_read" in list_sql
    assert "type" in list_sql


# ──────────────────────────────────────────────────────
# NOTIF-002：schema 欄位名
# ──────────────────────────────────────────────────────

def test_fcm_token_create_field_is_device_token():
    assert "device_token" in FCMTokenCreate.model_fields
    assert "token" not in FCMTokenCreate.model_fields


# ──────────────────────────────────────────────────────
# NOTIF-003：mark_all_read 回傳型別
# ──────────────────────────────────────────────────────

def test_mark_all_read_returns_response_model():
    db = _RecordingDB(results=[_FakeResult(rowcount=5)])
    out = _run(NotificationService.mark_all_read(db, user_id=uuid.uuid4()))  # type: ignore[arg-type]
    assert isinstance(out, MarkAllReadResponse)
    assert out.updated_count == 5


# ──────────────────────────────────────────────────────
# NOTIF-004：remove_fcm_token 帶 user_id 並 scope
# ──────────────────────────────────────────────────────

def test_remove_fcm_token_requires_user_id_param():
    sig = inspect.signature(NotificationService.remove_fcm_token)
    assert "user_id" in sig.parameters
    assert "token" in sig.parameters


def test_remove_fcm_token_scopes_query_by_user_id():
    """查詢語句須同時帶 device_token 與 user_id 條件，防越權。"""
    db = _RecordingDB(results=[_FakeResult(scalar=None)])  # 查無屬於該 user 的裝置
    _run(
        NotificationService.remove_fcm_token(
            db,  # type: ignore[arg-type]
            user_id=uuid.uuid4(),
            token="abc",
        )
    )
    select_sql = db.statements[0]
    assert "device_token" in select_sql
    assert "user_id" in select_sql
