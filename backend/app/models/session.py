"""Session 問診場次模型"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import SessionStatus, pg_enum

if TYPE_CHECKING:
    from app.models.chief_complaint import ChiefComplaint
    from app.models.conversation import Conversation
    from app.models.patient import Patient
    from app.models.red_flag_alert import RedFlagAlert
    from app.models.soap_report import SOAPReport
    from app.models.user import User


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("patients.id"), nullable=False, index=True
    )
    doctor_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True
    )
    chief_complaint_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chief_complaints.id"), nullable=False
    )
    chief_complaint_text: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    status: Mapped[SessionStatus] = mapped_column(
        pg_enum(SessionStatus, "sessionstatus"),
        nullable=False,
        server_default=text("'waiting'"),
    )
    red_flag: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    red_flag_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    language: Mapped[str] = mapped_column(String(10), server_default=text("'zh-TW'"), nullable=False)
    intake_data: Mapped[Optional[dict[str, object]]] = mapped_column(JSONB, nullable=True)
    intake_completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), onupdate=text("now()"), nullable=False
    )

    # ── 關聯 ──────────────────────────────────────────
    patient: Mapped["Patient"] = relationship("Patient", back_populates="sessions")
    doctor: Mapped[Optional["User"]] = relationship("User", foreign_keys=[doctor_id])
    chief_complaint: Mapped["ChiefComplaint"] = relationship(
        "ChiefComplaint", back_populates="sessions"
    )
    conversations: Mapped[list["Conversation"]] = relationship(
        "Conversation", back_populates="session", order_by="Conversation.sequence_number"
    )
    soap_report: Mapped[Optional["SOAPReport"]] = relationship(
        "SOAPReport", back_populates="session", uselist=False
    )
    red_flag_alerts: Mapped[list["RedFlagAlert"]] = relationship(
        "RedFlagAlert", back_populates="session"
    )

    def __repr__(self) -> str:
        return f"<Session {self.id} status={self.status.value}>"
