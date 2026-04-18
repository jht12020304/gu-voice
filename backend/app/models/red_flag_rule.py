"""RedFlagRule 紅旗規則模型"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import AlertSeverity, pg_enum

if TYPE_CHECKING:
    from app.models.user import User


class RedFlagRule(Base):
    __tablename__ = "red_flag_rules"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    # TODO-E6：canonical_id 為跨語言穩定的 snake_case 標識符。
    # Dedup 以此為 key(取代 name);alert serializer 依此 + Accept-Language
    # 在 display_title_by_lang 解析顯示 title。
    canonical_id: Mapped[str] = mapped_column(
        String(100), nullable=False, unique=True
    )
    # 舊 name 欄位維持向後相容(可視為 zh-TW display title)。
    # 新版 display title 走 display_title_by_lang JSONB。
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # TODO-E6：多語言 display title,key = BCP-47 locale,value = 該語言顯示文字。
    # 若某 locale 缺翻譯,fallback 回 zh-TW 或 canonical_id。
    display_title_by_lang: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    keywords: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    regex_pattern: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    severity: Mapped[AlertSeverity] = mapped_column(
        pg_enum(AlertSeverity, "alertseverity"), nullable=False
    )
    suspected_diagnosis: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    suggested_action: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), nullable=False)
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

    def __repr__(self) -> str:
        return f"<RedFlagRule {self.name} severity={self.severity.value}>"
