"""
守護 conversations.metadata / stt_confidence 落庫（session_data_inventory
§11-2 / §11-4 修復）：

1. `Conversation(metadata=...)` 是陷阱：declarative constructor 的
   hasattr(cls, "metadata") 會命中 Base.metadata（MetaData 集合），值被
   instance attr 遮蔽、靜默丟失不落 DB —— mapped attr 名是 `metadata_`。
2. ConversationService.create 必須把 metadata / stt_confidence 真的寫上
   ORM 物件（用 metadata_ kwarg）。
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from app.models.conversation import Conversation
from app.services.conversation_service import ConversationService


class _RecordingDB:
    """回 MAX(seq)=0 的最小 stub；捕捉 add 的 ORM 物件。"""

    def __init__(self) -> None:
        self.added: list[Any] = []
        self._max_seq_returned = False

    async def execute(self, stmt: Any, params: Any = None) -> Any:
        class _R:
            def __init__(self, value: Any = None) -> None:
                self._value = value

            def scalar(self) -> Any:
                return self._value

        if not self._max_seq_returned and params is None:
            self._max_seq_returned = True
            return _R(0)
        return _R(None)

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        return None


def test_ctor_metadata_kwarg_is_a_trap_documented():
    """`metadata=` kwarg 不會落到 mapped 欄位 —— 這就是必須用 metadata_ 的原因。

    若未來 SQLAlchemy 改變此行為讓本測試失敗，代表陷阱解除，可安全重審
    ConversationService.create 的 kwarg 寫法。
    """
    conv = Conversation(metadata={"x": 1})
    assert getattr(conv, "metadata_", None) is None


def test_ctor_metadata_underscore_maps_to_column():
    conv = Conversation(metadata_={"input_source": "voice"})
    assert conv.metadata_ == {"input_source": "voice"}


def test_service_create_persists_metadata_and_confidence():
    db = _RecordingDB()
    meta = {"input_source": "voice", "stt_language": "zh"}
    conv = asyncio.run(
        ConversationService.create(
            db=db,  # type: ignore[arg-type]
            session_id=uuid.uuid4(),
            role="patient",
            content_text="我最近排尿會痛",
            stt_confidence=0.8321,
            metadata=meta,
        )
    )
    assert conv.metadata_ == meta
    assert conv.stt_confidence == 0.8321
    added_conv = next(o for o in db.added if isinstance(o, Conversation))
    assert added_conv.metadata_ == meta
