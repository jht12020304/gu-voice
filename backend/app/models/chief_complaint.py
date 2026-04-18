"""ChiefComplaint 主訴模型

多語欄位採 expand-migrate-contract：
- `name_by_lang` / `description_by_lang` / `category_by_lang` 為新權威來源（JSONB）
- legacy `name / name_en / description / category` 暫留給管理後台寫入與 fallback；
  待 B1 seed 與 admin UI 遷移完成後以獨立 migration drop。
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.session import Session
    from app.models.user import User


class ChiefComplaint(Base):
    __tablename__ = "chief_complaints"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    name_en: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(String(100), nullable=False)

    # 多語欄位（JSONB，key = BCP-47 locale；由 localized_field.pick() 讀取）
    name_by_lang: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    description_by_lang: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )
    category_by_lang: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    is_default: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), onupdate=text("now()"), nullable=False
    )

    # ── 關聯 ──────────────────────────────────────────
    creator: Mapped[Optional["User"]] = relationship("User", foreign_keys=[created_by])
    sessions: Mapped[list["Session"]] = relationship("Session", back_populates="chief_complaint")

    def __repr__(self) -> str:
        return f"<ChiefComplaint {self.name} category={self.category}>"
