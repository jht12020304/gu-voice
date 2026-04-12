"""SOAP 報告相關 Pydantic Schema"""

from datetime import datetime
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import ReportStatus, ReviewStatus
from app.schemas.common import CursorPagination


class SOAPReportResponse(BaseModel):
    """SOAP 報告回應（簡要）"""
    id: UUID
    session_id: UUID
    status: ReportStatus
    review_status: ReviewStatus
    summary: Optional[str] = None
    ai_confidence_score: Optional[Decimal] = None
    generated_at: Optional[datetime] = None
    reviewed_by: Optional[UUID] = None
    reviewed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SOAPReportDetailResponse(SOAPReportResponse):
    """SOAP 報告詳細回應（含四段 JSONB）"""
    subjective: Optional[dict[str, Any]] = None
    objective: Optional[dict[str, Any]] = None
    assessment: Optional[dict[str, Any]] = None
    plan: Optional[dict[str, Any]] = None
    raw_transcript: Optional[str] = None
    icd10_codes: Optional[list[str]] = None
    review_notes: Optional[str] = None


class ReviewRequest(BaseModel):
    """審閱請求"""
    review_status: ReviewStatus
    review_notes: Optional[str] = Field(None, description="審閱備註")
    soap_overrides: Optional[dict[str, Any]] = Field(None, description="SOAP 內容覆寫")


class GenerateReportRequest(BaseModel):
    """請求產生 SOAP 報告"""
    session_id: UUID
    regenerate: bool = False
    additional_notes: Optional[str] = None


class GenerateReportResponse(BaseModel):
    """報告產生回應"""
    report_id: UUID
    session_id: UUID
    status: ReportStatus
    message: str = "報告產生中"


class ReportListResponse(BaseModel):
    """報告列表回應"""
    data: list[SOAPReportResponse]
    pagination: CursorPagination


class ReviewReportRequest(ReviewRequest):
    """審閱報告請求（別名）"""
    pass


class ReviewReportResponse(BaseModel):
    """審閱報告回應"""
    id: UUID
    review_status: ReviewStatus
    reviewed_by: UUID
    reviewed_at: datetime
    review_notes: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


# 別名
ReportDetail = SOAPReportDetailResponse
