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

from app.core.authz import get_user_role as _get_user_role
from app.core.exceptions import (
    NotFoundException,
    ReportAlreadyExistsException,
    ReportNotReadyException,
    SessionNotActiveException,
)
from app.models.enums import (
    ReportRevisionReason,
    ReportStatus,
    ReviewStatus,
    SessionStatus,
    UserRole,
)
from app.models.patient import Patient
from app.models.session import Session
from app.models.soap_report import SOAPReport
from app.models.soap_report_revision import SOAPReportRevision
from app.utils.datetime_utils import parse_iso, utc_now

logger = logging.getLogger(__name__)


async def _authorize_report_access(
    db: AsyncSession,
    report: SOAPReport,
    current_user: Any,
) -> None:
    """
    Row-level 權限校驗：current_user 是否能讀取此 SOAP 報告。

    報告本身不帶 patient_id / doctor_id，故透過其 session 對映：
      - admin   → 無限制
      - doctor  → session.doctor_id == self 或 doctor_id 為空(未指派)
      - patient → session.patient → patient.user_id == self.id
      - 其餘/未知角色 / 無 current_user → 拒絕

    與 session_service._authorize_session_access 同權限模型。為避免洩漏報告存在與否，
    違規時 raise NotFoundException（與「報告不存在」回應一致），而非 403。
    """
    role = _get_user_role(current_user)
    user_id = getattr(current_user, "id", None)

    if role == UserRole.ADMIN:
        return

    # 取出此報告對映 session 的 doctor_id / patient_id（明確 query 避免 lazy-load）
    result = await db.execute(
        select(Session.doctor_id, Session.patient_id).where(
            Session.id == report.session_id
        )
    )
    row = result.one_or_none()
    if row is None:
        # session 不存在 → 視同報告不可見
        raise NotFoundException("errors.report_not_found")
    doctor_id, patient_id = row

    if role == UserRole.DOCTOR:
        if doctor_id is None or doctor_id == user_id:
            return
        raise NotFoundException("errors.report_not_found")

    if role == UserRole.PATIENT:
        owner_result = await db.execute(
            select(Patient.user_id).where(Patient.id == patient_id)
        )
        owner_user_id = owner_result.scalar_one_or_none()
        if owner_user_id is not None and owner_user_id == user_id:
            return
        raise NotFoundException("errors.report_not_found")

    # 未知角色 / 無 current_user — 保守拒絕
    raise NotFoundException("errors.report_not_found")


class ReportService:
    """SOAP 報告業務邏輯"""

    @staticmethod
    async def _snapshot_revision(
        db: AsyncSession,
        report: SOAPReport,
        reason: ReportRevisionReason,
        created_by: Optional[UUID] = None,
    ) -> SOAPReportRevision:
        """
        M15 append-only：在 SOAP 內容被覆寫前（或新內容寫入後）留下不可變快照。

        revision_no 會取 `MAX(existing) + 1`；若沒有既有 revision 則從 1 起算。
        只做 INSERT —呼叫方負責在同一 transaction 內觸發。
        """
        max_rev_result = await db.execute(
            select(func.coalesce(func.max(SOAPReportRevision.revision_no), 0)).where(
                SOAPReportRevision.report_id == report.id
            )
        )
        next_no = int(max_rev_result.scalar_one() or 0) + 1

        revision = SOAPReportRevision(
            report_id=report.id,
            revision_no=next_no,
            reason=reason,
            subjective=report.subjective,
            objective=report.objective,
            assessment=report.assessment,
            plan=report.plan,
            summary=report.summary,
            raw_transcript=report.raw_transcript,
            icd10_codes=list(report.icd10_codes) if report.icd10_codes else None,
            language=report.language,
            ai_confidence_score=report.ai_confidence_score,
            created_by=created_by,
        )
        db.add(revision)
        await db.flush()
        return revision

    @staticmethod
    async def list_revisions(
        db: AsyncSession,
        report_id: UUID,
    ) -> list[SOAPReportRevision]:
        """回傳指定報告的全部版本快照，依 revision_no 升冪排序。"""
        result = await db.execute(
            select(SOAPReportRevision)
            .where(SOAPReportRevision.report_id == report_id)
            .order_by(SOAPReportRevision.revision_no.asc())
        )
        return list(result.scalars().all())

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
            patient_id: 篩選病患（透過 session.patient_id 對映）
            session_id: 篩選場次 ID
            date_from: 起始建立時間（ISO 8601，含界，>=）
            date_to: 結束建立時間（ISO 8601，含界，<=）

        Raises:
            ValidationException: date_from / date_to 非合法 ISO 8601 字串
        """
        limit = min(limit, 100)

        # date_from / date_to 提早解析；非法格式由 parse_iso 直接 raise
        # ValidationException 擋下，避免「以為有篩選實際全撈」的資料外洩預期落差（S-6）。
        _date_from = parse_iso(date_from)
        _date_to = parse_iso(date_to)

        # ── Row-level 範圍限縮（依角色，於 query 層過濾，非後處理）──────────
        # report 不帶 patient/doctor，故以 session_id IN (符合角色的 session 子查詢) 限縮。
        # 無 current_user 或未知角色 → 限縮為空集合（保守拒絕，回空清單）。
        role = _get_user_role(current_user)
        user_id = getattr(current_user, "id", None)

        scope_subquery = None  # None = admin（無限縮）
        if role == UserRole.ADMIN:
            scope_subquery = None
        elif role == UserRole.DOCTOR:
            scope_subquery = select(Session.id).where(
                (Session.doctor_id == user_id) | (Session.doctor_id.is_(None))
            )
        elif role == UserRole.PATIENT:
            owned_patient_ids = select(Patient.id).where(Patient.user_id == user_id)
            scope_subquery = select(Session.id).where(
                Session.patient_id.in_(owned_patient_ids)
            )
        else:
            # 無角色 / 未知角色：限縮成不可能命中的集合
            scope_subquery = select(Session.id).where(Session.id.is_(None))

        def _apply_scope(stmt):
            stmt = stmt.where(SOAPReport.session_id.in_(scope_subquery))
            return stmt

        query = select(SOAPReport).order_by(
            SOAPReport.created_at.desc(), SOAPReport.id.desc()
        )
        if scope_subquery is not None:
            query = _apply_scope(query)

        # report 不帶 patient_id，故透過符合該病患的 session 子查詢限縮（與 scope 同手法）。
        patient_session_subquery = None
        if patient_id:
            patient_session_subquery = select(Session.id).where(
                Session.patient_id == patient_id
            )

        if status:
            query = query.where(SOAPReport.status == status)
        if review_status:
            query = query.where(SOAPReport.review_status == review_status)
        if doctor_id:
            query = query.where(SOAPReport.reviewed_by == doctor_id)
        if session_id:
            query = query.where(SOAPReport.session_id == session_id)
        if patient_session_subquery is not None:
            query = query.where(
                SOAPReport.session_id.in_(patient_session_subquery)
            )
        if _date_from:
            query = query.where(SOAPReport.created_at >= _date_from)
        if _date_to:
            query = query.where(SOAPReport.created_at <= _date_to)

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
        if scope_subquery is not None:
            count_query = count_query.where(
                SOAPReport.session_id.in_(scope_subquery)
            )
        if status:
            count_query = count_query.where(SOAPReport.status == status)
        if review_status:
            count_query = count_query.where(SOAPReport.review_status == review_status)
        if doctor_id:
            count_query = count_query.where(SOAPReport.reviewed_by == doctor_id)
        if session_id:
            count_query = count_query.where(SOAPReport.session_id == session_id)
        if patient_session_subquery is not None:
            count_query = count_query.where(
                SOAPReport.session_id.in_(patient_session_subquery)
            )
        if _date_from:
            count_query = count_query.where(SOAPReport.created_at >= _date_from)
        if _date_to:
            count_query = count_query.where(SOAPReport.created_at <= _date_to)
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
        根據 ID 取得報告，並做 row-level 權限校驗。

        當 `current_user` 提供時（所有來自 router 的呼叫），會依角色檢查
        是否可讀取此報告；違規 raise NotFoundException（避免洩漏存在與否）。
        內部 worker / 已授權路徑不帶 current_user，則略過權限檢查。

        Raises:
            NotFoundException: 報告不存在或無權存取
        """
        result = await db.execute(
            select(SOAPReport).where(SOAPReport.id == report_id)
        )
        report = result.scalar_one_or_none()
        if report is None:
            raise NotFoundException("errors.report_not_found")
        if current_user is not None:
            await _authorize_report_access(db, report, current_user)
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
            NotFoundException: 場次不存在
            SessionNotActiveException: 場次尚未 completed，無法產生報告
            ReportAlreadyExistsException: 此場次已有報告（且未要求重新產生）
        """
        # 場次必須存在且處於 completed 狀態，才可產生 SOAP 報告
        session_result = await db.execute(
            select(Session.status).where(Session.id == session_id)
        )
        session_status = session_result.scalar_one_or_none()
        if session_status is None:
            raise NotFoundException("errors.session_not_found")
        if session_status != SessionStatus.COMPLETED:
            raise SessionNotActiveException(
                details={
                    "session_id": str(session_id),
                    "current_status": session_status.value
                    if hasattr(session_status, "value")
                    else str(session_status),
                }
            )

        # 檢查是否已有報告
        existing = await db.execute(
            select(SOAPReport).where(SOAPReport.session_id == session_id)
        )
        existing_report = existing.scalar_one_or_none()
        if existing_report is not None and not regenerate:
            raise ReportAlreadyExistsException()

        now = utc_now()
        if existing_report is not None:
            # M15：regenerate 時先把當前內容快照成 revision（reason=regenerate），
            # 再把現有 row 重置為 generating 等 Celery 寫回；避免 unique(session_id)
            # 衝突，也保留舊版內容。
            if existing_report.status == ReportStatus.GENERATED and existing_report.subjective is not None:
                await ReportService._snapshot_revision(
                    db,
                    existing_report,
                    ReportRevisionReason.REGENERATE,
                    created_by=requested_by,
                )
            existing_report.status = ReportStatus.GENERATING
            existing_report.review_status = ReviewStatus.PENDING
            existing_report.subjective = None
            existing_report.objective = None
            existing_report.assessment = None
            existing_report.plan = None
            existing_report.summary = None
            existing_report.icd10_codes = None
            existing_report.ai_confidence_score = None
            existing_report.reviewed_by = None
            existing_report.reviewed_at = None
            existing_report.review_notes = None
            existing_report.generated_at = None
            existing_report.updated_at = now
            report = existing_report
            await db.flush()
        else:
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

        # H-8：此處僅「觸發」生成（狀態仍為 generating），非完成點，故不在此推播。
        # report_generated 事件改在報告真正完成（commit）後推播——由 Celery worker
        # （tasks/report_queue._async_generate）經 Redis pub/sub 橋接觸發，
        # 解決 worker 與 API 行程不同、in-memory 廣播跨不了行程的問題。
        return report

    @staticmethod
    async def review_report(
        db: AsyncSession,
        report_id: UUID,
        reviewed_by: UUID,
        review_status: ReviewStatus,
        review_notes: Optional[str] = None,
        soap_overrides: Optional[dict[str, Any]] = None,
        current_user: Any = None,
    ) -> SOAPReport:
        """
        醫師審閱報告

        Args:
            report_id: 報告 ID
            reviewed_by: 審閱醫師 ID
            review_status: 審閱狀態（approved / revision_needed）
            review_notes: 審閱備註
            soap_overrides: SOAP 內容覆寫
            current_user: 審閱者（用於 row-level ownership 校驗）

        Raises:
            NotFoundException: 報告不存在或無權存取
            ReportNotReadyException: 報告尚未生成完成
        """
        report = await ReportService.get_report(db, report_id, current_user=current_user)

        if report.status != ReportStatus.GENERATED:
            raise ReportNotReadyException()

        # M15：只要 soap_overrides 會改寫內容，覆寫前先 snapshot 當前版本
        if soap_overrides and any(
            key in soap_overrides
            for key in ("subjective", "objective", "assessment", "plan")
        ):
            await ReportService._snapshot_revision(
                db,
                report,
                ReportRevisionReason.REVIEW_OVERRIDE,
                created_by=reviewed_by,
            )

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
        current_user: Any = None,
    ) -> tuple[bytes, str]:
        """
        匯出報告為 PDF

        使用 WeasyPrint 將 SOAP 報告渲染為 PDF

        Raises:
            NotFoundException: 報告不存在或無權存取
            ReportNotReadyException: 報告尚未生成完成

        Returns:
            (PDF 二進制資料, 檔案名稱)
        """
        report = await ReportService.get_report(db, report_id, current_user=current_user)

        if report.status != ReportStatus.GENERATED:
            raise ReportNotReadyException()

        # 組裝 HTML 內容；language 控制版面語系標籤，include_transcript 決定是否附逐字稿。
        html_content = _build_report_html(
            report,
            language=language,
            include_transcript=include_transcript,
        )

        # 使用 WeasyPrint 生成 PDF。url_fetcher 一律拒絕，
        # 防止注入內容經 img src / CSS url() 觸發 SSRF／本地檔讀取。
        from weasyprint import HTML

        pdf_bytes = HTML(
            string=html_content, url_fetcher=_forbid_url_fetch
        ).write_pdf()
        filename = f"SOAP_Report_{report.id}.pdf"
        return pdf_bytes, filename


# PDF 版面語系標籤。key 為 BCP-47 locale；未支援的 language 一律 fallback 至 zh-TW
# （與 i18n_messages 的 DEFAULT_LANGUAGE 一致），確保 language 參數真實影響輸出。
# 註：SOAP 內容本身的翻譯由生成階段決定（report.language），此處僅切換版面/欄位標籤。
_PDF_LABELS: dict[str, dict[str, str]] = {
    "zh-TW": {
        "title": "SOAP 問診報告",
        "report_id": "報告 ID",
        "generated_at": "生成時間",
        "review_status": "審閱狀態",
        "subjective": "S — Subjective（主觀）",
        "chief_complaint": "主訴",
        "summary": "摘要",
        "objective": "O — Objective（客觀）",
        "assessment": "A — Assessment（評估）",
        "clinical_impression": "臨床印象",
        "plan": "P — Plan（計畫）",
        "confidence": "AI 信心分數",
        "review_notes": "審閱備註",
        "transcript": "對話逐字稿",
    },
    "en-US": {
        "title": "SOAP Consultation Report",
        "report_id": "Report ID",
        "generated_at": "Generated at",
        "review_status": "Review status",
        "subjective": "S — Subjective",
        "chief_complaint": "Chief complaint",
        "summary": "Summary",
        "objective": "O — Objective",
        "assessment": "A — Assessment",
        "clinical_impression": "Clinical impression",
        "plan": "P — Plan",
        "confidence": "AI confidence score",
        "review_notes": "Review notes",
        "transcript": "Conversation transcript",
    },
    "ja-JP": {
        "title": "SOAP 診察レポート",
        "report_id": "レポート ID",
        "generated_at": "生成日時",
        "review_status": "レビュー状態",
        "subjective": "S — Subjective（主観）",
        "chief_complaint": "主訴",
        "summary": "要約",
        "objective": "O — Objective（客観）",
        "assessment": "A — Assessment（評価）",
        "clinical_impression": "臨床的印象",
        "plan": "P — Plan（計画）",
        "confidence": "AI 信頼度スコア",
        "review_notes": "レビューメモ",
        "transcript": "会話の文字起こし",
    },
    "ko-KR": {
        "title": "SOAP 진료 보고서",
        "report_id": "보고서 ID",
        "generated_at": "생성 시간",
        "review_status": "검토 상태",
        "subjective": "S — Subjective(주관)",
        "chief_complaint": "주 호소",
        "summary": "요약",
        "objective": "O — Objective(객관)",
        "assessment": "A — Assessment(평가)",
        "clinical_impression": "임상 인상",
        "plan": "P — Plan(계획)",
        "confidence": "AI 신뢰도 점수",
        "review_notes": "검토 메모",
        "transcript": "대화 전사본",
    },
}


def _build_report_html(
    report: SOAPReport,
    language: str = "zh-TW",
    include_transcript: bool = False,
) -> str:
    """將 SOAP 報告轉換為 HTML（PDF 渲染用）。

    Args:
        report: SOAP 報告
        language: 版面語系（BCP-47）；未支援者 fallback zh-TW
        include_transcript: 是否附上原始對話逐字稿（report.raw_transcript）

    TODO-i18n：目前僅切換版面/欄位「標籤」語系；SOAP 內容文字本身的翻譯
    仍沿用生成階段語言（report.language），尚未於匯出時即時翻譯。
    """
    import html as _html

    from app.utils.datetime_utils import format_iso

    # 未支援的 language 一律 fallback 至 zh-TW，確保標籤一定有值。
    labels = _PDF_LABELS.get(language) or _PDF_LABELS["zh-TW"]

    subjective = report.subjective or {}
    objective = report.objective or {}
    assessment = report.assessment or {}
    plan = report.plan or {}

    # 安全：所有插入 HTML 的資料欄位一律逃逸。這些欄位源自 LLM 生成
    # （可被病患語音 prompt-inject）與醫師自由文字，未逃逸會讓注入的
    # <img src> / CSS url() 經 WeasyPrint 觸發伺服器端資源抓取。
    esc = _html.escape
    chief_complaint = esc(str(subjective.get("chief_complaint", "N/A")))
    summary = esc(str(report.summary or "N/A"))
    clinical_impression = esc(str(assessment.get("clinical_impression", "N/A")))
    icd10 = esc(", ".join(report.icd10_codes)) if report.icd10_codes else "N/A"
    review_status = esc(
        report.review_status.value if report.review_status else "pending"
    )
    confidence = esc(str(report.ai_confidence_score or "N/A"))
    review_notes_html = (
        f'<p class="meta">{labels["review_notes"]}: {esc(str(report.review_notes))}</p>'
        if report.review_notes
        else ""
    )

    # include_transcript=True 時附逐字稿區塊；raw_transcript 為自由文字，逃逸後輸出。
    transcript_section = ""
    if include_transcript:
        raw = report.raw_transcript or ""
        transcript_body = (
            f"<pre>{_html.escape(raw)}</pre>" if raw else "N/A"
        )
        transcript_section = f"""
        <div class="section">
            <h2>{labels["transcript"]}</h2>
            {transcript_body}
        </div>
        """

    return f"""
    <!DOCTYPE html>
    <html lang="{_html.escape(language, quote=True)}">
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
            pre {{ white-space: pre-wrap; word-break: break-word; font-family: inherit; }}
        </style>
    </head>
    <body>
        <h1>{labels["title"]}</h1>
        <p class="meta">
            {labels["report_id"]}: {report.id}<br>
            {labels["generated_at"]}: {format_iso(report.generated_at)}<br>
            {labels["review_status"]}: {review_status}
        </p>

        <div class="section">
            <h2>{labels["subjective"]}</h2>
            <p><strong>{labels["chief_complaint"]}:</strong> {chief_complaint}</p>
            <p><strong>{labels["summary"]}:</strong> {summary}</p>
        </div>

        <div class="section">
            <h2>{labels["objective"]}</h2>
            <p>{_format_dict(objective) if objective else "N/A"}</p>
        </div>

        <div class="section">
            <h2>{labels["assessment"]}</h2>
            <p><strong>{labels["clinical_impression"]}:</strong> {clinical_impression}</p>
            <p><strong>ICD-10:</strong> {icd10}</p>
        </div>

        <div class="section">
            <h2>{labels["plan"]}</h2>
            <p>{_format_dict(plan) if plan else "N/A"}</p>
        </div>
        {transcript_section}
        <div class="section">
            <p class="meta">{labels["confidence"]}: {confidence}</p>
            {review_notes_html}
        </div>
    </body>
    </html>
    """


def _format_dict(d: dict) -> str:
    """將 dict 格式化為 HTML 段落（內容一律逃逸，值可能含 LLM 生成文字）"""
    import html as _html
    import json
    return f"<pre>{_html.escape(json.dumps(d, ensure_ascii=False, indent=2))}</pre>"


def _forbid_url_fetch(url: str) -> dict:
    """WeasyPrint url_fetcher：一律拒絕抓取任何資源。

    報告 HTML 樣式全為 inline CSS、不需任何外部資源；拒絕所有 URL
    （http/https/file/...）可阻斷經注入內容觸發的伺服器端 SSRF／本地檔讀取。
    WeasyPrint 對 fetch 失敗僅記 log 並略過該資源，不影響 PDF 產出。
    """
    raise ValueError(f"PDF 匯出禁止抓取外部資源: {url}")
