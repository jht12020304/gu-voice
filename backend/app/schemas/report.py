"""SOAP 報告相關 Pydantic Schema"""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import ReportRevisionReason, ReportStatus, ReviewStatus
from app.schemas.common import CursorPagination, JsonFloatDecimal


class SOAPReportResponse(BaseModel):
    """SOAP 報告回應（簡要）"""
    id: UUID
    session_id: UUID
    status: ReportStatus
    review_status: ReviewStatus
    summary: Optional[str] = None
    # 病患語言版的病患面兩欄（2026-08-20）。
    # 形狀：{"language": "<BCP-47>", "summary": str, "patient_education": str}。
    # 主報告與 `summary` 仍固定 zh-TW（不變式 #12）；本欄是給**病患自己**看的
    # 轉述版，只在場次語言 != zh-TW 且轉述成功時有值，否則為 None
    # （前端 fallback 回上面的中文 `summary` / `plan.patient_education`）。
    #
    # 型別刻意用 `dict[str, Any]` 而不是巢狀 model：內容是 LLM 產物 + 消毒層
    # 輸出，欄位少且純字串，多一層 model 只會在 LLM 吐怪東西時多一個 500。
    # ⚠️ 這一欄裡不會有 Decimal，故不涉及 `JsonFloatDecimal` 鐵律
    #（Decimal 欄位仍只有 `ai_confidence_score`，維持原樣）。
    patient_facing_localized: Optional[dict[str, Any]] = None
    ai_confidence_score: Optional[JsonFloatDecimal] = None
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
    # M3：ICD-10 是否通過泌尿科白名單 + symptom↔code 驗證
    icd10_verified: bool = False
    review_notes: Optional[str] = None


class ReviewRequest(BaseModel):
    """審閱請求"""
    review_status: ReviewStatus
    review_notes: Optional[str] = Field(None, description="審閱備註")
    soap_overrides: Optional[dict[str, Any]] = Field(None, description="SOAP 內容覆寫")


class GenerateReportRequest(BaseModel):
    """
    請求產生 SOAP 報告。**整個 body 皆為可選**。

    SO-2：`session_id` 原本是必填，與端點 path param
    `POST /api/v1/sessions/{session_id}/reports/generate` 重複。前端「重新產生」
    只送 `{"regenerate": true}`（或完全不送 body）會被 pydantic 擋成 422，
    整條 regenerate 路徑因此形同不存在。

    現在：
    - `session_id` 保留為可選欄位僅為回溯相容（舊 client 仍可送），**值一律被忽略**；
      場次一律以 path param 為準，避免「body 指向另一場次」的越權風險。
    - body 可以整個省略（router 端 `payload: GenerateReportRequest | None = None`）。
    """
    session_id: Optional[UUID] = Field(
        None,
        description="已忽略（回溯相容用）；實際場次以 path param 為準",
    )
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


class SOAPReportRevisionResponse(BaseModel):
    """
    M15：SOAP 報告版本快照回應（append-only 歷史紀錄）。

    由 ReportService.list_revisions 產出；revision_no 從 1 起算、嚴格單調遞增。
    reason 描述該快照建立的時機：初次產生 / 重生前 / 審閱覆寫前。
    """
    id: UUID
    report_id: UUID
    revision_no: int
    reason: ReportRevisionReason
    subjective: Optional[dict[str, Any]] = None
    objective: Optional[dict[str, Any]] = None
    assessment: Optional[dict[str, Any]] = None
    plan: Optional[dict[str, Any]] = None
    summary: Optional[str] = None
    raw_transcript: Optional[str] = None
    icd10_codes: Optional[list[str]] = None
    language: str
    ai_confidence_score: Optional[JsonFloatDecimal] = None
    created_by: Optional[UUID] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SOAPReportRevisionListResponse(BaseModel):
    """SOAP 報告版本列表回應"""
    data: list[SOAPReportRevisionResponse]


# 別名
ReportDetail = SOAPReportDetailResponse
