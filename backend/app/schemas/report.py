"""SOAP 報告相關 Pydantic Schema"""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import (
    ReportRevisionReason,
    ReportStatus,
    ReviewStatus,
    SessionStatus,
)
from app.schemas.common import CursorPagination, JsonFloatDecimal


class SOAPReportResponse(BaseModel):
    """SOAP 報告回應（簡要）"""
    id: UUID
    session_id: UUID
    status: ReportStatus
    review_status: ReviewStatus
    summary: Optional[str] = None
    # 2026-08-23 稽核補漏：列表卡要渲染 ICD-10 標籤與「需修改」原因框
    # （report_list_page），但這兩欄原本只在 Detail 子類——列表永遠 null。
    # 皆為小標量（≤3 個代碼＋短文字），不影響列表負載。
    icd10_codes: Optional[list[str]] = None
    review_notes: Optional[str] = None
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

    # ── 場次上下文（2026-08-22）────────────────────────────
    # 醫師端報告列表每一列要顯示的四個欄位。它們屬於 Session 而不是 SOAPReport，
    # 而 report 上只有 session_id，所以前端過去是「先拿 20 筆報告，再對每一筆打一次
    # GET /sessions/{id}」——開一次列表 22 個 round trip，而且列先畫出 20 行 UUID、
    # 名字與主訴再一筆一筆補進來，整份清單跟著重排。
    #
    # 只有 `list_reports` 會 eager-load 這條關聯；沒載到時下面的 validator 靜靜留 None
    # （它走 `__dict__`，不會觸發 lazy load —— 在 async session 裡那會直接
    # MissingGreenlet）。所以單筆 detail 端點行為完全不變。
    #
    # 這裡沒有新增任何資料曝光：list_reports 的 scope 子查詢本來就把報告限縮在該
    # 使用者看得到的場次內，而前端原本就是逐筆去打 /sessions/{id} 拿同樣這些值。
    patient_name: Optional[str] = None
    chief_complaint_text: Optional[str] = None
    session_status: Optional[SessionStatus] = None
    session_red_flag: Optional[bool] = None

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def _flatten_session_context(cls, data: Any) -> Any:
        # 只在「從 ORM 物件載入」且 `session` 已被 eager-load 時才攤平。
        # 一律用 `data.__dict__`：`getattr(data, "session")` 在關聯沒載到時會觸發
        # lazy load，在 asyncio 下就是 MissingGreenlet 500。
        if data is None or isinstance(data, dict):
            return data
        try:
            session = data.__dict__.get("session") if hasattr(data, "__dict__") else None
        except Exception:  # noqa: BLE001 — 攤平失敗絕不能讓報告本身取不到
            session = None
        if session is None:
            return data
        try:
            patient = session.__dict__.get("patient")
            data.patient_name = getattr(patient, "name", None) if patient else None
            data.chief_complaint_text = getattr(session, "chief_complaint_text", None)
            data.session_status = getattr(session, "status", None)
            data.session_red_flag = getattr(session, "red_flag", None)
        except Exception:  # noqa: BLE001
            pass
        return data


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
