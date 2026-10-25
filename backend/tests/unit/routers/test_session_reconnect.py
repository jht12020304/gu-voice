"""`POST /sessions/{id}/reconnect` 與 WS handler 共用 history 載入與 checksum。

兩邊各寫一份時任一邊漂移（key 格式、序列化欄位）都會讓 resumeFrom 永遠比對不上。
"""

import asyncio
import json
import uuid
from types import SimpleNamespace

from app.routers import sessions as sessions_router
from app.websocket.conversation_handler import _SESSION_CONTEXT_KEY, _history_checksum
from tests.unit.websocket.conftest import FakeRedis


def test_reconnect_uses_ws_handler_history_and_checksum(monkeypatch):
    session_id = uuid.uuid4()
    history = [
        {"role": "assistant", "content": "請問哪裡不舒服？", "timestamp": "t1"},
        {"role": "user", "content": "小便會痛", "timestamp": "t2"},
    ]
    redis = FakeRedis()
    asyncio.run(
        redis.hset(
            _SESSION_CONTEXT_KEY.format(session_id=session_id),
            "conversation_history",
            json.dumps(history, ensure_ascii=False),
        )
    )

    async def _get_session(db, session_id, current_user):
        return SimpleNamespace(status="in_progress")

    monkeypatch.setattr(sessions_router.session_service, "get_session", _get_session)

    result = asyncio.run(
        sessions_router.reconnect_session(
            session_id, db=None, redis=redis, current_user=SimpleNamespace(id=uuid.uuid4())
        )
    )

    assert result["conversationHistory"] == history
    assert result["lastMessageIndex"] == 1
    assert result["checksum"] == _history_checksum(history)
    assert result["resumeToken"] == result["checksum"]
