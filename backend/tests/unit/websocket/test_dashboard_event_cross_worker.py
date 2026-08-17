"""儀表板事件跨 worker 推播回歸測試（多 worker 漏發缺陷）。

缺陷背景：三處推播入口原本在 publish 前檢查
``manager.dashboard_connection_count == 0`` 就提早 return，但該計數是**單一
uvicorn worker 的行程本地值**，而下游 ``broadcast_dashboard_event`` 實際走
Redis pub/sub 跨行程橋接（H-8）。多 worker 部署下，處理請求的 worker 若本地
沒有 dashboard 連線就會提早 return，事件根本進不了 Redis，即使其他 worker 上
有醫師連著也收不到（4 worker、1 連線時約 3/4 機率漏發）。

本檔守護修復後的不變式：**本行程 dashboard 連線數為 0 時，事件仍必須 publish
到 Redis**。三處各至少一條：

- ``session_service._broadcast_session_created``     → ``session_created``
- ``alert_service._broadcast_red_flag_acknowledged`` → ``red_flag_acknowledged``
- ``dashboard_handler.broadcast_queue_and_stats``    → ``queue_updated`` /
  ``stats_updated``

作法：不接真 Redis，改為攔截 ``manager.publish_dashboard_event``（Redis 橋接的
唯一出口）記錄事件；同時斷言 ``manager.dashboard_connection_count == 0``，確保
測到的正是「本地無連線」情境。沿用專案 asyncio.run + stub + monkeypatch 慣例。
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from app.services import alert_service as alert_service_module
from app.services import session_service as session_service_module
from app.websocket import dashboard_handler as dashboard_handler_module
from app.websocket.connection_manager import manager


def _run(coro):
    """在 sync test 裡跑 coroutine，避免多裝 pytest-asyncio。"""
    return asyncio.run(coro)


@pytest.fixture
def published(monkeypatch) -> list[tuple[str, dict[str, Any]]]:
    """攔截 Redis publish 出口，回傳 (event_type, payload) 記錄串列。

    同時把 dashboard_connections 清空，模擬「本 worker 行程無任何儀表板連線」
    （多 worker 部署下最常見的情況）。
    """
    events: list[tuple[str, dict[str, Any]]] = []

    async def _fake_publish(event_type: str, payload: dict[str, Any] | None = None) -> None:
        events.append((event_type, payload or {}))

    monkeypatch.setattr(manager, "publish_dashboard_event", _fake_publish)
    monkeypatch.setattr(manager, "dashboard_connections", [])
    # 前提條件：本行程本地連線數為 0——正是舊程式會提早 return 的情境
    assert manager.dashboard_connection_count == 0
    return events


@pytest.fixture
def stub_queue_and_stats(monkeypatch) -> None:
    """讓 broadcast_queue_and_stats 的 DB 查詢改回固定值（不接真 DB）。"""

    async def _fake_queue(db, redis, doctor_id=None):
        return {
            "total_waiting": 3,
            "total_in_progress": 1,
            "queue": [
                {
                    "session_id": "s-1",
                    "chief_complaint": "血尿",
                    "status": "waiting",
                }
            ],
        }

    async def _fake_stats(db, redis, doctor_id=None):
        return {
            "sessions_today": 7,
            "completed": 4,
            "red_flags": 2,
            "pending_reviews": 1,
        }

    monkeypatch.setattr(dashboard_handler_module, "_get_queue_status", _fake_queue)
    monkeypatch.setattr(dashboard_handler_module, "_get_dashboard_stats", _fake_stats)


@pytest.fixture
def stub_get_redis(monkeypatch) -> None:
    """讓 helper 內部的 ``get_redis()`` 不去連真 Redis。"""
    from app.cache import redis_client

    async def _fake_get_redis():
        return SimpleNamespace()

    monkeypatch.setattr(redis_client, "get_redis", _fake_get_redis)


# ── 1. session_service._broadcast_session_created ──────────────────

def test_session_created_published_even_with_zero_local_connections(
    published, stub_queue_and_stats, stub_get_redis
):
    """本行程無 dashboard 連線時，session_created 仍必須 publish 到 Redis。"""
    session = SimpleNamespace(
        id=uuid.uuid4(),
        patient=SimpleNamespace(name="王小明"),
        chief_complaint_text="血尿",
        status="waiting",
    )

    _run(session_service_module._broadcast_session_created(db=object(), session=session))

    types = [event_type for event_type, _ in published]
    assert "session_created" in types, (
        "本地連線數為 0 時仍須 publish session_created（多 worker 下其他行程可能有連線）"
    )
    payload = next(p for t, p in published if t == "session_created")
    assert payload["sessionId"] == str(session.id)
    assert payload["patientName"] == "王小明"
    assert payload["chiefComplaint"] == "血尿"
    # 順帶刷新的 queue/stats 也不得被本地連線數擋掉
    assert "queue_updated" in types
    assert "stats_updated" in types


def test_session_created_broadcast_swallows_exceptions(published, monkeypatch):
    """推播失敗不得影響場次建立主流程（既有吞例外語意須保留）。"""

    async def _boom(*args, **kwargs):
        raise RuntimeError("redis down")

    monkeypatch.setattr(manager, "publish_dashboard_event", _boom)

    session = SimpleNamespace(
        id=uuid.uuid4(), patient=None, chief_complaint_text="", status="waiting"
    )
    # 不得拋出
    _run(session_service_module._broadcast_session_created(db=object(), session=session))


# ── 2. alert_service._broadcast_red_flag_acknowledged ──────────────

def test_red_flag_acknowledged_published_even_with_zero_local_connections(
    published, stub_queue_and_stats, stub_get_redis
):
    """本行程無 dashboard 連線時，red_flag_acknowledged 仍必須 publish 到 Redis。"""
    alert = SimpleNamespace(id=uuid.uuid4())
    acknowledged_by = uuid.uuid4()

    _run(
        alert_service_module._broadcast_red_flag_acknowledged(
            db=object(), alert=alert, acknowledged_by=acknowledged_by
        )
    )

    types = [event_type for event_type, _ in published]
    assert "red_flag_acknowledged" in types, (
        "本地連線數為 0 時仍須 publish red_flag_acknowledged"
    )
    payload = next(p for t, p in published if t == "red_flag_acknowledged")
    assert payload["alertId"] == str(alert.id)
    assert payload["acknowledgedBy"] == str(acknowledged_by)
    assert "queue_updated" in types
    assert "stats_updated" in types


def test_red_flag_acknowledged_broadcast_swallows_exceptions(published, monkeypatch):
    """推播失敗不得影響 acknowledge 主流程（既有吞例外語意須保留）。"""

    async def _boom(*args, **kwargs):
        raise RuntimeError("redis down")

    monkeypatch.setattr(manager, "publish_dashboard_event", _boom)

    _run(
        alert_service_module._broadcast_red_flag_acknowledged(
            db=object(), alert=SimpleNamespace(id=uuid.uuid4()), acknowledged_by=uuid.uuid4()
        )
    )


# ── 3. dashboard_handler.broadcast_queue_and_stats ─────────────────

def test_queue_and_stats_published_even_with_zero_local_connections(
    published, stub_queue_and_stats
):
    """本行程無 dashboard 連線時，queue_updated / stats_updated 仍必須 publish。"""
    _run(dashboard_handler_module.broadcast_queue_and_stats(db=object(), redis=object()))

    types = [event_type for event_type, _ in published]
    assert types == ["queue_updated", "stats_updated"], (
        "本地連線數為 0 時仍須 publish queue/stats（此處刻意放棄『無人看就不查 DB』的優化）"
    )
    queue_payload = next(p for t, p in published if t == "queue_updated")
    assert queue_payload["totalWaiting"] == 3
    assert queue_payload["totalInProgress"] == 1
    assert queue_payload["queue"][0]["sessionId"] == "s-1"

    stats_payload = next(p for t, p in published if t == "stats_updated")
    assert stats_payload["sessionsToday"] == 7
    assert stats_payload["pendingReviews"] == 1


def test_queue_and_stats_swallows_query_failures(published, monkeypatch):
    """queue 查詢失敗不得阻斷 stats 推播，且本函式不可拋例外。"""

    async def _boom(db, redis, doctor_id=None):
        raise RuntimeError("db down")

    async def _fake_stats(db, redis, doctor_id=None):
        return {"sessions_today": 1, "completed": 0, "red_flags": 0, "pending_reviews": 0}

    monkeypatch.setattr(dashboard_handler_module, "_get_queue_status", _boom)
    monkeypatch.setattr(dashboard_handler_module, "_get_dashboard_stats", _fake_stats)

    _run(dashboard_handler_module.broadcast_queue_and_stats(db=object(), redis=object()))

    assert [t for t, _ in published] == ["stats_updated"]
