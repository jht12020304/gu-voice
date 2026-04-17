"""RedFlagAlert 紅旗警示模型"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import DateTime, ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import AlertSeverity, AlertType, pg_enum

if TYPE_CHECKING:
    from app.models.red_flag_rule import RedFlagRule
    from app.models.session import Session
    from app.models.user import User


class RedFlagAlert(Base):
    __tablename__ = "red_flag_alerts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False, index=True
    )
    # conversation_id 不設外鍵約束（conversations 為分區表）
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    alert_type: Mapped[AlertType] = mapped_column(pg_enum(AlertType, "alerttype"), nullable=False)
    severity: Mapped[AlertSeverity] = mapped_column(
        pg_enum(AlertSeverity, "alertseverity"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    trigger_reason: Mapped[str] = mapped_column(Text, nullable=False)
    trigger_keywords: Mapped[Optional[list[str]]] = mapped_column(
        ARRAY(Text), nullable=True
    )
    matched_rule_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("red_flag_rules.id"), nullable=True
    )
    llm_analysis: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    suggested_actions: Mapped[Optional[list[str]]] = mapped_column(
        ARRAY(Text), nullable=True
    )
    acknowledged_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    acknowledge_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )

    # ── 關聯 ──────────────────────────────────────────
    session: Mapped["Session"] = relationship("Session", back_populates="red_flag_alerts")
    matched_rule: Mapped[Optional["RedFlagRule"]] = relationship(
        "RedFlagRule", foreign_keys=[matched_rule_id]
    )
    acknowledger: Mapped[Optional["User"]] = relationship("User", foreign_keys=[acknowledged_by])

    def __repr__(self) -> str:
        return f"<RedFlagAlert {self.title} severity={self.severity.value}>"
