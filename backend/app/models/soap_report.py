"""SOAPReport SOAP 報告模型"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import DateTime, ForeignKey, Numeric, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import String

from app.core.database import Base
from app.models.enums import ReportStatus, ReviewStatus

if TYPE_CHECKING:
    from app.models.session import Session
    from app.models.user import User


class SOAPReport(Base):
    __tablename__ = "soap_reports"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id"), unique=True, nullable=False, index=True
    )
    status: Mapped[ReportStatus] = mapped_column(
        nullable=False, server_default=text("'generating'")
    )
    review_status: Mapped[ReviewStatus] = mapped_column(
        nullable=False, server_default=text("'pending'")
    )
    subjective: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    objective: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    assessment: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    plan: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    raw_transcript: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    icd10_codes: Mapped[Optional[list[str]]] = mapped_column(
        ARRAY(String), nullable=True
    )
    ai_confidence_score: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(3, 2), nullable=True
    )
    reviewed_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    review_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    generated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), onupdate=text("now()"), nullable=False
    )

    # ── 關聯 ──────────────────────────────────────────
    session: Mapped["Session"] = relationship("Session", back_populates="soap_report")
    reviewer: Mapped[Optional["User"]] = relationship("User", foreign_keys=[reviewed_by])

    def __repr__(self) -> str:
        return f"<SOAPReport session={self.session_id} status={self.status.value}>"
