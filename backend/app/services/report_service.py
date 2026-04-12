"""
SOAP 報告服務
- 報告列表 / 詳情
- 觸發報告生成（Celery 任務）
- 醫師審閱
- PDF 匯出
"""

import logging
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    NotFoundException,
    ReportAlreadyExistsException,
    ReportNotReadyException,
)
from app.models.enums import ReportStatus, ReviewStatus
from app.models.soap_report import SOAPReport
from app.utils.datetime_utils import utc_now

logger = logging.getLogger(__name__)


class ReportService:
    """SOAP 報告業務邏輯"""

    @staticmethod
    async def list_reports(
        db: AsyncSession,
        current_user: Any = None,
        cursor: Optional[str] = None,
        limit: int = 20,
        status: Optional[str] = None,
        review_status: Optional[str] = None,
        doctor_id: Optional[UUID] = None,
        patient_id: Optional[UUID] = None,
        session_id: Optional[UUID] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        取得報告列表（Cursor-based 分頁）

        Args:
            cursor: 分頁游標
            limit: 每頁筆數
            status: 篩選報告狀態
            review_status: 篩選審閱狀態
            doctor_id: 篩選審閱醫師
            session_id: 篩選場次 ID
        """
        limit = min(limit, 100)

        query = select(SOAPReport).order_by(
            SOAPReport.created_at.desc(), SOAPReport.id.desc()
        )

        if status:
            query = query.where(SOAPReport.status == status)
        if review_status:
            query = query.where(SOAPReport.review_status == review_status)
        if doctor_id:
            query = query.where(SOAPReport.reviewed_by == doctor_id)
        if session_id:
            query = query.where(SOAPReport.session_id == session_id)

        if cursor:
            result = await db.execute(
                select(SOAPReport).where(SOAPReport.id == cursor)
            )
            cursor_record = result.scalar_one_or_none()
            if cursor_record:
                query = query.where(
                    (SOAPReport.created_at < cursor_record.created_at)
                    | (
                        (SOAPReport.created_at == cursor_record.created_at)
                        & (SOAPReport.id < cursor_record.id)
                    )
                )

        result = await db.execute(query.limit(limit + 1))
        reports = result.scalars().all()

        has_more = len(reports) > limit
        if has_more:
            reports = reports[:limit]

        count_query = select(func.count()).select_from(SOAPReport)
        if status:
            count_query = count_query.where(SOAPReport.status == status)
        if review_status:
            count_query = count_query.where(SOAPReport.review_status == review_status)
        total_result = await db.execute(count_query)
        total_count = total_result.scalar() or 0

        return {
            "data": reports,
            "pagination": {
                "next_cursor": str(reports[-1].id) if has_more and reports else None,
                "has_more": has_more,
                "limit": limit,
                "total_count": total_count,
            },
        }

    @staticmethod
    async def get_report(
        db: AsyncSession,
        report_id: UUID,
        current_user: Any = None,
    ) -> SOAPReport:
        """
        根據 ID 取得報告

        Raises:
            NotFoundException: 報告不存在
        """
        result = await db.execute(
            select(SOAPReport).where(SOAPReport.id == report_id)
        )
        report = result.scalar_one_or_none()
        if report is None:
            raise NotFoundException("報告不存在")
        return report

    @staticmethod
    async def generate_report(
        db: AsyncSession,
        session_id: UUID,
        regenerate: bool = False,
        additional_notes: Optional[str] = None,
        requested_by: Optional[UUID] = None,
    ) -> SOAPReport:
        """
        觸發 SOAP 報告生成

        1. 建立 status=generating 的報告記錄
        2. 派送 Celery 任務進行非同步生成

        Raises:
            ReportAlreadyExistsException: 此場次已有報告（且未要求重新產生）
        """
        # 檢查是否已有報告
        existing = await db.execute(
            select(SOAPReport).where(SOAPReport.session_id == session_id)
        )
        existing_report = existing.scalar_one_or_none()
        if existing_report is not None and not regenerate:
            raise ReportAlreadyExistsException()

        now = utc_now()
        report = SOAPReport(
            session_id=session_id,
            status=ReportStatus.GENERATING,
            review_status=ReviewStatus.PENDING,
            created_at=now,
            updated_at=now,
        )
        db.add(report)
        await db.flush()

        # 派送 Celery 任務
        from app.tasks.report_queue import generate_soap_report

        generate_soap_report.delay(str(session_id))
        logger.info("已派送 SOAP 報告生成任務: session=%s", session_id)

        return report

    @staticmethod
    async def update_report_content(
        db: AsyncSession,
        report_id: UUID,
        soap_data: dict[str, Any],
    ) -> SOAPReport:
        """
        更新報告內容（由 Celery worker 呼叫）

        Args:
            report_id: 報告 ID
            soap_data: SOAP 結構化資料
        """
        report = await ReportService.get_report(db, report_id)

        report.subjective = soap_data.get("subjective")
        report.objective = soap_data.get("objective")
        report.assessment = soap_data.get("assessment")
        report.plan = soap_data.get("plan")
        report.raw_transcript = soap_data.get("raw_transcript")
        report.summary = soap_data.get("summary")
        report.icd10_codes = soap_data.get("icd10_codes", [])
        report.ai_confidence_score = soap_data.get("ai_confidence_score")
        report.status = ReportStatus.GENERATED
        report.generated_at = utc_now()
        report.updated_at = utc_now()

        await db.flush()
        return report

    @staticmethod
    async def review_report(
        db: AsyncSession,
        report_id: UUID,
        reviewed_by: UUID,
        review_status: ReviewStatus,
        review_notes: Optional[str] = None,
        soap_overrides: Optional[dict[str, Any]] = None,
    ) -> SOAPReport:
        """
        醫師審閱報告

        Args:
            report_id: 報告 ID
            reviewed_by: 審閱醫師 ID
            review_status: 審閱狀態（approved / revision_needed）
            review_notes: 審閱備註
            soap_overrides: SOAP 內容覆寫

        Raises:
            NotFoundException: 報告不存在
            ReportNotReadyException: 報告尚未生成完成
        """
        report = await ReportService.get_report(db, report_id)

        if report.status != ReportStatus.GENERATED:
            raise ReportNotReadyException()

        now = utc_now()
        report.review_status = review_status
        report.reviewed_by = reviewed_by
        report.reviewed_at = now
        report.review_notes = review_notes
        report.updated_at = now

        # 若提供 SOAP 覆寫，更新對應欄位
        if soap_overrides:
            if "subjective" in soap_overrides:
                report.subjective = soap_overrides["subjective"]
            if "objective" in soap_overrides:
                report.objective = soap_overrides["objective"]
            if "assessment" in soap_overrides:
                report.assessment = soap_overrides["assessment"]
            if "plan" in soap_overrides:
                report.plan = soap_overrides["plan"]

        await db.flush()
        return report

    @staticmethod
    async def export_pdf(
        db: AsyncSession,
        report_id: UUID,
        include_transcript: bool = False,
        language: str = "zh-TW",
    ) -> tuple[bytes, str]:
        """
        匯出報告為 PDF

        使用 WeasyPrint 將 SOAP 報告渲染為 PDF

        Raises:
            NotFoundException: 報告不存在
            ReportNotReadyException: 報告尚未生成完成

        Returns:
            (PDF 二進制資料, 檔案名稱)
        """
        report = await ReportService.get_report(db, report_id)

        if report.status != ReportStatus.GENERATED:
            raise ReportNotReadyException()

        # 組裝 HTML 內容
        html_content = _build_report_html(report)

        # 使用 WeasyPrint 生成 PDF
        from weasyprint import HTML

        pdf_bytes = HTML(string=html_content).write_pdf()
        filename = f"SOAP_Report_{report.id}.pdf"
        return pdf_bytes, filename


def _build_report_html(report: SOAPReport) -> str:
    """將 SOAP 報告轉換為 HTML（PDF 渲染用）"""
    from app.utils.datetime_utils import format_iso

    subjective = report.subjective or {}
    objective = report.objective or {}
    assessment = report.assessment or {}
    plan = report.plan or {}

    return f"""
    <!DOCTYPE html>
    <html lang="zh-TW">
    <head>
        <meta charset="utf-8">
        <style>
            body {{ font-family: "Noto Sans TC", "Microsoft JhengHei", sans-serif; font-size: 12pt; line-height: 1.6; margin: 40px; }}
            h1 {{ color: #1a365d; border-bottom: 2px solid #2b6cb0; padding-bottom: 8px; }}
            h2 {{ color: #2b6cb0; margin-top: 24px; }}
            .section {{ margin-bottom: 20px; padding: 16px; background: #f7fafc; border-radius: 8px; }}
            .meta {{ color: #718096; font-size: 10pt; }}
            table {{ width: 100%; border-collapse: collapse; margin: 12px 0; }}
            td, th {{ padding: 8px; border: 1px solid #e2e8f0; text-align: left; }}
            th {{ background: #edf2f7; }}
        </style>
    </head>
    <body>
        <h1>SOAP 問診報告</h1>
        <p class="meta">
            報告 ID: {report.id}<br>
            生成時間: {format_iso(report.generated_at)}<br>
            審閱狀態: {report.review_status.value if report.review_status else "pending"}
        </p>

        <div class="section">
            <h2>S — Subjective（主觀）</h2>
            <p><strong>主訴:</strong> {subjective.get("chief_complaint", "N/A")}</p>
            <p><strong>摘要:</strong> {report.summary or "N/A"}</p>
        </div>

        <div class="section">
            <h2>O — Objective（客觀）</h2>
            <p>{_format_dict(objective) if objective else "N/A"}</p>
        </div>

        <div class="section">
            <h2>A — Assessment（評估）</h2>
            <p><strong>臨床印象:</strong> {assessment.get("clinical_impression", "N/A")}</p>
            <p><strong>ICD-10:</strong> {", ".join(report.icd10_codes) if report.icd10_codes else "N/A"}</p>
        </div>

        <div class="section">
            <h2>P — Plan（計畫）</h2>
            <p>{_format_dict(plan) if plan else "N/A"}</p>
        </div>

        <div class="section">
            <p class="meta">AI 信心分數: {report.ai_confidence_score or "N/A"}</p>
            {f'<p class="meta">審閱備註: {report.review_notes}</p>' if report.review_notes else ""}
        </div>
    </body>
    </html>
    """


def _format_dict(d: dict) -> str:
    """將 dict 格式化為 HTML 段落"""
    import json
    return f"<pre>{json.dumps(d, ensure_ascii=False, indent=2)}</pre>"
