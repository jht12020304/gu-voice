"""
Conversation 對話紀錄模型
NOTE: 此表使用按月 Range Partition（以 created_at 為分區鍵），
      分區邏輯由 migration SQL 處理，ORM model 不直接管理分區。
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import ConversationRole, pg_enum

if TYPE_CHECKING:
    from app.models.session import Session


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False, index=True
    )
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[ConversationRole] = mapped_column(
        pg_enum(ConversationRole, "conversationrole"), nullable=False
    )
    content_text: Mapped[str] = mapped_column(Text, nullable=False)
    audio_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    audio_duration_seconds: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(8, 2), nullable=True
    )
    stt_confidence: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(5, 4), nullable=True
    )
    red_flag_detected: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), nullable=False
    )
    metadata_: Mapped[Optional[dict[str, Any]]] = mapped_column(
        "metadata", JSONB, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    # updated_at 由 20260418_1400 trigger `conversations_set_updated_at_trg` 自動更新；
    # 不靠 SQLAlchemy 的 onupdate，因為我們也會走 raw SQL / 背景任務更新。
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )

    # ── 關聯 ──────────────────────────────────────────
    session: Mapped["Session"] = relationship("Session", back_populates="conversations")

    # NOTE: 跨分區 (session_id, sequence_number) 唯一性由 BEFORE INSERT trigger
    #       `conversations_check_seq_unique_trg` 維護（分區表無法做 native UNIQUE
    #       除非把 created_at 也納入鍵）。ConversationService.create 另用 advisory
    #       lock 序列化 seq 分配，避免兩個併發寫爆 trigger。

    def __repr__(self) -> str:
        return f"<Conversation session={self.session_id} seq={self.sequence_number} role={self.role.value}>"
