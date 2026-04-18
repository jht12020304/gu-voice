"""
SOAPReportRevision — SOAP 報告版本快照（M15 append-only）。

每次 SOAP 內容被寫入或覆寫前，將前一版（或該版本）內容存入此表，
確保歷次報告內容可追溯，不會被醫師審閱或 regenerate 覆蓋而遺失。
此模型只提供 INSERT，不存在任何 UPDATE / DELETE 路徑。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import ReportRevisionReason, pg_enum

if TYPE_CHECKING:
    from app.models.soap_report import SOAPReport
    from app.models.user import User


class SOAPReportRevision(Base):
    __tablename__ = "soap_report_revisions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    report_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("soap_reports.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[ReportRevisionReason] = mapped_column(
        pg_enum(ReportRevisionReason, "reportrevisionreason"),
        nullable=False,
    )
    subjective: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    objective: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    assessment: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    plan: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    icd10_codes: Mapped[Optional[list[str]]] = mapped_column(ARRAY(String), nullable=True)
    language: Mapped[str] = mapped_column(String(10), nullable=False)
    ai_confidence_score: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(3, 2), nullable=True
    )
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )

    report: Mapped["SOAPReport"] = relationship("SOAPReport", back_populates="revisions")
    author: Mapped[Optional["User"]] = relationship("User", foreign_keys=[created_by])

    def __repr__(self) -> str:
        return (
            f"<SOAPReportRevision report={self.report_id} "
            f"rev={self.revision_no} reason={self.reason.value}>"
        )
