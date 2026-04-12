"""對話紀錄相關 Pydantic Schema"""

from datetime import datetime
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import ConversationRole


class ConversationCreate(BaseModel):
    """新增對話紀錄"""
    session_id: UUID
    role: ConversationRole
    content_text: str = Field(..., min_length=1)
    audio_url: Optional[str] = Field(None, max_length=500)
    audio_duration_seconds: Optional[Decimal] = None
    stt_confidence: Optional[Decimal] = None
    metadata_: Optional[dict[str, Any]] = Field(None, alias="metadata")


class ConversationResponse(BaseModel):
    """對話紀錄回應"""
    id: UUID
    session_id: UUID
    sequence_number: int
    role: ConversationRole
    content_text: str
    audio_url: Optional[str] = None
    audio_duration_seconds: Optional[Decimal] = None
    stt_confidence: Optional[Decimal] = None
    red_flag_detected: bool
    metadata: Optional[dict[str, Any]] = Field(None, alias="metadata_")
    created_at: datetime

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
