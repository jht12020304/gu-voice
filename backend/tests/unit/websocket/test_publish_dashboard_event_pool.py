"""`publish_dashboard_event` 在 API 行程重用連線池、在別的 loop 退回短命 client。

每則儀表板事件（queue_updated / stats_updated / session_status_changed …）原本都
`aioredis.from_url` 開一條新連線再 QUIT：本機量測 0.73 ms vs 共用池 0.21 ms／則，
差距隨 Redis RTT 線性放大（production 跨區時是數十 ms）。Celery 的 run_async
每個 task 新 loop，池裡的連線不可跨 loop 用，所以只有「同一個 loop」才重用。
"""

from __future__ import annotations

import asyncio

import redis.asyncio as aioredis

from app.cache import redis_client
from app.websocket import connection_manager as cm


class _FakeRedis:
    def __init__(self):
        self.published: list[tuple[str, str]] = []
        self.closed = False

    async def publish(self, channel, message):
        self.published.append((channel, message))

    async def aclose(self):
        self.closed = True


def test_same_loop_reuses_pool(monkeypatch):
    pool = _FakeRedis()

    def _no_new_client(*a, **k):
        raise AssertionError("同一 loop 不應再開短命連線")

    monkeypatch.setattr(aioredis, "from_url", _no_new_client)

    async def body():
        monkeypatch.setattr(redis_client, "_redis_pool", pool)
        monkeypatch.setattr(redis_client, "_pool_loop", asyncio.get_running_loop())
        await cm.manager.publish_dashboard_event("queue_updated", {"a": 1})

    asyncio.run(body())
    assert len(pool.published) == 1 and pool.published[0][0] == cm.DASHBOARD_EVENTS_CHANNEL
    assert pool.closed is False, "共用池不可被 publish 關掉"


def test_other_loop_falls_back_to_ephemeral_client(monkeypatch):
    pool = _FakeRedis()
    ephemeral = _FakeRedis()
    monkeypatch.setattr(aioredis, "from_url", lambda *a, **k: ephemeral)

    async def body():
        monkeypatch.setattr(redis_client, "_redis_pool", pool)
        monkeypatch.setattr(redis_client, "_pool_loop", asyncio.new_event_loop())  # 別的 loop
        await cm.manager.publish_dashboard_event("stats_updated", {})

    asyncio.run(body())
    assert pool.published == []
    assert len(ephemeral.published) == 1 and ephemeral.closed is True
