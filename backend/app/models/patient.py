"""Patient 病患模型"""

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import Date, DateTime, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import Gender

if TYPE_CHECKING:
    from app.models.session import Session
    from app.models.user import User


class Patient(Base):
    __tablename__ = "patients"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    medical_record_number: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    gender: Mapped[Gender] = mapped_column(nullable=False)
    date_of_birth: Mapped[date] = mapped_column(Date, nullable=False)
    phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    emergency_contact: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    medical_history: Mapped[Optional[list[dict[str, Any]]]] = mapped_column(JSONB, nullable=True)
    allergies: Mapped[Optional[list[dict[str, Any]]]] = mapped_column(JSONB, nullable=True)
    current_medications: Mapped[Optional[list[dict[str, Any]]]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), onupdate=text("now()"), nullable=False
    )

    # ── 關聯 ──────────────────────────────────────────
    user: Mapped["User"] = relationship("User", back_populates="patients")
    sessions: Mapped[list["Session"]] = relationship("Session", back_populates="patient")

    def __repr__(self) -> str:
        return f"<Patient {self.name} MRN={self.medical_record_number}>"
