"""
SOAP 報告路由 — 報告生成、審閱、匯出
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db, require_role
from app.core.exceptions import AppException
from app.schemas.report import (
    GenerateReportRequest,
    GenerateReportResponse,
    ReportDetail,
    ReportListResponse,
    ReviewReportRequest,
    ReviewReportResponse,
    SOAPReportRevisionListResponse,
    SOAPReportRevisionResponse,
)
from app.services.report_service import ReportService

router = APIRouter(tags=["SOAP 報告"])

report_service = ReportService()


# ── 報告列表與詳情 ──────────────────────────────────────

@router.get(
    "/api/v1/reports",
    response_model=ReportListResponse,
    status_code=status.HTTP_200_OK,
    summary="取得報告列表",
)
async def list_reports(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
    cursor: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    status_filter: str | None = Query(None, alias="status"),
    review_status: str | None = None,
    doctor_id: UUID | None = None,
    patient_id: UUID | None = None,
    session_id: UUID | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> ReportListResponse:
    """
    取得報告列表，支援多條件篩選。
    病患僅能查看自己的報告；醫師可依醫師ID、審閱狀態、場次ID篩選。
    """
    return await report_service.list_reports(
        db,
        current_user=current_user,
        cursor=cursor,
        limit=limit,
        status=status_filter,
        review_status=review_status,
        doctor_id=doctor_id,
        patient_id=patient_id,
        session_id=session_id,
        date_from=date_from,
        date_to=date_to,
    )


@router.get(
    "/api/v1/reports/{report_id}",
    response_model=ReportDetail,
    status_code=status.HTTP_200_OK,
    summary="取得報告詳情",
)
async def get_report(
    report_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> ReportDetail:
    """取得指定 SOAP 報告的完整內容。病患僅可查看自己的報告。"""
    return await report_service.get_report(
        db,
        report_id=report_id,
        current_user=current_user,
    )


# ── 報告生成 ────────────────────────────────────────────

@router.post(
    "/api/v1/sessions/{session_id}/reports/generate",
    response_model=GenerateReportResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="觸發 SOAP 報告生成",
    dependencies=[Depends(require_role("doctor", "admin"))],
)
async def generate_report(
    session_id: UUID,
    payload: GenerateReportRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> GenerateReportResponse:
    """
    依指定場次的對話記錄，觸發 AI 生成 SOAP 格式報告。
    場次必須處於 completed 狀態。生成為非同步作業。
    """
    regenerate = payload.regenerate if payload else False
    additional_notes = payload.additional_notes if payload else None
    return await report_service.generate_report(
        db,
        session_id=session_id,
        regenerate=regenerate,
        additional_notes=additional_notes,
        requested_by=current_user.id,
    )


# ── 報告審閱 ────────────────────────────────────────────

@router.put(
    "/api/v1/reports/{report_id}/review",
    response_model=ReviewReportResponse,
    status_code=status.HTTP_200_OK,
    summary="審閱報告",
    dependencies=[Depends(require_role("doctor", "admin"))],
)
async def review_report(
    report_id: UUID,
    payload: ReviewReportRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> ReviewReportResponse:
    """醫師審閱 SOAP 報告，可核准 (approved) 或標記需修訂 (revision_needed)。"""
    return await report_service.review_report(
        db,
        report_id=report_id,
        review_status=payload.review_status,
        review_notes=payload.review_notes,
        soap_overrides=payload.soap_overrides,
        reviewed_by=current_user.id,
    )


# ── 報告歷史版本（M15 append-only） ─────────────────────

@router.get(
    "/api/v1/reports/{report_id}/revisions",
    response_model=SOAPReportRevisionListResponse,
    status_code=status.HTTP_200_OK,
    summary="取得報告歷次版本",
    dependencies=[Depends(require_role("doctor", "admin"))],
)
async def list_report_revisions(
    report_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> SOAPReportRevisionListResponse:
    """
    回傳指定 SOAP 報告的歷次版本快照（依 revision_no 升冪）。

    版本建立時機：
    - initial：Celery 首次產完報告
    - regenerate：醫師要求重生，舊內容覆寫前
    - review_override：醫師審閱時改寫 SOAP 欄位，覆寫前
    """
    # 驗證存取權（與 get_report 同權限模型）
    await report_service.get_report(
        db,
        report_id=report_id,
        current_user=current_user,
    )
    revisions = await ReportService.list_revisions(db, report_id=report_id)
    return SOAPReportRevisionListResponse(
        data=[SOAPReportRevisionResponse.model_validate(r) for r in revisions]
    )


# ── 報告匯出 ────────────────────────────────────────────

@router.get(
    "/api/v1/reports/{report_id}/pdf",
    status_code=status.HTTP_200_OK,
    summary="匯出報告為 PDF",
    dependencies=[Depends(require_role("doctor", "admin"))],
)
async def export_report_pdf(
    report_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
    include_transcript: bool = Query(False),
    language: str = Query("zh-TW"),
) -> StreamingResponse:
    """將 SOAP 報告匯出為 PDF 格式檔案。僅限醫師與管理員。"""
    pdf_bytes, filename = await report_service.export_pdf(
        db,
        report_id=report_id,
        include_transcript=include_transcript,
        language=language,
    )
    return StreamingResponse(
        content=iter([pdf_bytes]),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )
