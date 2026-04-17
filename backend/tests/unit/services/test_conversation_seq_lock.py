"""
守護 P2 #13：ConversationService.create 在算 seq 前要先拿 pg_advisory_xact_lock，
才能在併發 WS 訊息下不產生同序號。

純 stub 測試：不起 FastAPI、不連 PG，只看 SQL 呼叫順序。
Trigger 本身的正確性已於 migration 階段對真 PG 驗證（見 migration 檔 docstring）。
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from app.services.conversation_service import ConversationService


class _RecordingDB:
    """記錄 execute 呼叫順序的假 db；第一次回 MAX(seq)=0，之後的語句都回空結果。"""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self._max_seq_returned = False

    async def execute(self, stmt: Any, params: Any = None) -> Any:
        self.calls.append(str(stmt))

        class _R:
            def __init__(self, value: Any = None) -> None:
                self._value = value

            def scalar(self) -> Any:
                return self._value

        # 第一個 MAX(seq) query（沒有 params 的 select）→ 回 0
        if not self._max_seq_returned and params is None:
            self._max_seq_returned = True
            return _R(0)
        return _R(None)

    def add(self, obj: Any) -> None:
        self.calls.append(f"add:{type(obj).__name__}")

    async def flush(self) -> None:
        self.calls.append("flush")


def _run(coro):
    return asyncio.run(coro)


def test_advisory_lock_taken_before_max_seq_select():
    db = _RecordingDB()
    session_id = uuid.uuid4()
    _run(ConversationService.create(
        db=db,  # type: ignore[arg-type]
        session_id=session_id,
        role="patient",
        content_text="hi",
    ))

    # 第一個 execute 必須是 advisory lock
    assert "pg_advisory_xact_lock" in db.calls[0], (
        f"預期 advisory lock 為第一個呼叫，實際：{db.calls[0]}"
    )
    # 並且後面才是 MAX(sequence_number)
    max_seen = any("max(conversations.sequence_number)" in c.lower() for c in db.calls[1:])
    assert max_seen, f"沒看到 MAX(seq) 在 lock 之後：{db.calls}"


def test_advisory_lock_key_matches_session_id():
    """確認 lock 的 :sid 參數就是 session_id 的字串形式。"""
    session_id = uuid.uuid4()

    captured: dict[str, Any] = {}

    class _CaptureDB(_RecordingDB):
        async def execute(self, stmt: Any, params: Any = None) -> Any:  # type: ignore[override]
            if "pg_advisory_xact_lock" in str(stmt):
                captured["params"] = params
            return await super().execute(stmt, params)

    _run(ConversationService.create(
        db=_CaptureDB(),  # type: ignore[arg-type]
        session_id=session_id,
        role="patient",
        content_text="hi",
    ))

    assert captured["params"] == {"sid": str(session_id)}
