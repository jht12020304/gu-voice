"""
SOAP 報告服務
- 報告列表 / 詳情
- 觸發報告生成（Celery 任務）
- 醫師審閱
- PDF 匯出
"""

import html as _html
import logging
from datetime import timedelta, timezone
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.authz import get_user_role as _get_user_role
from app.core.exceptions import (
    ConflictException,
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


# ── 可產生 SOAP 報告的場次終態（SO-2）────────────────────────────
#
# 以前這裡是一行 `!= SessionStatus.COMPLETED` 的硬判斷，把 **aborted_red_flag
# 場次整類排除在報告之外**——那正好是最需要報告的一類：紅旗中止代表偵測到
# 危險徵象、問診被系統主動掐斷，醫師接手時最需要看到中止當下的完整臨床脈絡
# （主訴、已收集到的 HPI、觸發的紅旗）。沒有報告等於醫師只能從逐字稿裸讀。
#
# 刻意**不**納入：
#   waiting / in_progress — 問診還沒結束，沒有完整對話可摘要（會產出半截報告）
#   cancelled             — 病患／院方主動取消，通常無臨床內容
#
# 新增終態時記得回頭檢查這個集合（對照 CLAUDE.md 不變式「新增場次終態轉移時
# 六件事一起做」，派 SOAP 是其中一件）。
REPORT_ELIGIBLE_SESSION_STATUSES: frozenset[SessionStatus] = frozenset(
    {
        SessionStatus.COMPLETED,
        SessionStatus.ABORTED_RED_FLAG,
    }
)

# 以 value 比對用。SessionStatus 雖是 str Enum，但 Enum 的 __hash__ 走 name，
# 直接拿裸字串（例如從 DB driver 回來的 "completed"）對 enum set 做 `in` 會
# 誤判為不在集合內，故一律先正規化成 value 再比。
_REPORT_ELIGIBLE_SESSION_STATUS_VALUES: frozenset[str] = frozenset(
    s.value for s in REPORT_ELIGIBLE_SESSION_STATUSES
)

# regenerate=True 時允許重生的報告狀態。GENERATING 不在此列——那代表上一次
# 生成還在跑，重複派送會讓兩個 Celery 任務互相覆寫同一 row（醫師連點的典型後果）。
_REGENERATABLE_REPORT_STATUSES: frozenset[ReportStatus] = frozenset(
    {
        ReportStatus.GENERATED,
        ReportStatus.FAILED,
    }
)
# 同 session 狀態：Enum.__hash__ 走 name，比對前先正規化成 value
_REGENERATABLE_REPORT_STATUS_VALUES: frozenset[str] = frozenset(
    s.value for s in _REGENERATABLE_REPORT_STATUSES
)

# _snapshot_revision 的 MAX+1 撞號重試次數（首次 + 1 次重試）
_SNAPSHOT_MAX_ATTEMPTS = 2

# GENERATING 卡住多久之後允許 regenerate 強制接手。
#
# 為什麼一定要有這個逃生口：派任務是 `commit → delay()`，broker 掛掉時
# delay() 會失敗但 row 已經是 GENERATING（WS 觸發器同一模式，其註解寫的
# 「醫師端可手動 regenerate 補救」就是指這條路）。若「GENERATING 一律 409」
# 沒有時效，那條補救路徑會被自己的防連點守衛永久堵死。
#
# 門檻取 10 分鐘：SOAP 生成實測數十秒等級，10 分鐘足以涵蓋 LLM 重試與
# 佇列積壓，又不至於讓醫師在卡死時等太久。
_STALE_GENERATING_AFTER = timedelta(minutes=10)


def _is_stale_generating(report: SOAPReport, now: Any) -> bool:
    """GENERATING 是否已逾時（視為卡死，允許 regenerate 接手）。"""
    started = getattr(report, "updated_at", None)
    if started is None:
        # 沒有時間戳可判斷 → 保守視為「仍在跑」，走 409
        return False
    if getattr(started, "tzinfo", None) is None:
        started = started.replace(tzinfo=timezone.utc)
    return (now - started) > _STALE_GENERATING_AFTER


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

        revision_no 取 `MAX(existing) + 1`；若沒有既有 revision 則從 1 起算。
        只做 INSERT —呼叫方負責在同一 transaction 內觸發。

        併發撞號（SO-2）：`MAX+1` 是 read-then-write，兩個並行的 regenerate／
        審閱覆寫可能算出同一個 revision_no。DB 有
        `uq_soap_report_revisions_report_id_rev_no`（見 migration
        20260418_1600-soap_report_revisions）擋住，落地成 IntegrityError；
        此處**重讀 MAX 後重試一次**把後到者推到下一號，避免整個 regenerate
        因為競態直接 500。重試包在 SAVEPOINT（`begin_nested`）內，否則
        Postgres 會把整個 transaction 標成 aborted、重試也必敗。
        """
        last_error: Optional[IntegrityError] = None
        for attempt in range(_SNAPSHOT_MAX_ATTEMPTS):
            max_rev_result = await db.execute(
                select(
                    func.coalesce(func.max(SOAPReportRevision.revision_no), 0)
                ).where(SOAPReportRevision.report_id == report.id)
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

            # begin_nested 不存在時（單元測試的假 session）直接走無 SAVEPOINT 路徑；
            # 行為等價，只是撞號時不可重試——真 DB 上一定有 begin_nested。
            begin_nested = getattr(db, "begin_nested", None)
            try:
                if begin_nested is None:
                    db.add(revision)
                    await db.flush()
                else:
                    async with begin_nested():
                        db.add(revision)
                        await db.flush()
                return revision
            except IntegrityError as exc:
                last_error = exc
                logger.warning(
                    "SOAP revision 撞號，重試 | report=%s revision_no=%s attempt=%d",
                    report.id,
                    next_no,
                    attempt + 1,
                )
                continue

        # 重試用盡仍撞號 — 讓呼叫端看見真實錯誤（不要靜默吞掉快照遺失）
        assert last_error is not None
        raise last_error

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

        # 一起把場次與病患撈回來（見 SOAPReportResponse 的「場次上下文」）。
        # selectinload 而非 joinedload：兩張表都是 many-to-one，selectin 會多發一次
        # `WHERE id IN (...)`，但不會把報告本身的 JSONB 欄位（subjective/objective/
        # assessment/plan）在 join 結果裡複製 N 份。這是**兩次**查詢換掉前端原本
        # 每列一次、最多 20 次的 GET /sessions/{id}。
        query = (
            select(SOAPReport)
            .options(selectinload(SOAPReport.session).selectinload(Session.patient))
            .order_by(SOAPReport.created_at.desc(), SOAPReport.id.desc())
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

        1. 建立（或重置）status=generating 的報告記錄
        2. **先 commit**，再派送 Celery 任務進行非同步生成

        場次狀態閘門見 `REPORT_ELIGIBLE_SESSION_STATUSES`（completed 與
        aborted_red_flag 皆可）。

        regenerate 語意（SO-2）：
        - `regenerate=False` + 已有報告 → 409 REPORT_ALREADY_EXISTS
        - `regenerate=True`  + 報告為 GENERATED / FAILED → 重生
          （GENERATED 且有內容時先寫 REGENERATE revision 快照）
        - 報告為 GENERATING（不論 regenerate）→ 409 errors.report_generating，
          防止醫師連點派出多個互相覆寫的 Celery 任務

        Raises:
            NotFoundException: 場次不存在
            SessionNotActiveException: 場次不在可產報告的終態
            ReportAlreadyExistsException: 此場次已有報告（且未要求重新產生）
            ConflictException: 報告正在生成中
        """
        # 場次必須存在且處於可產報告的終態
        session_result = await db.execute(
            select(Session.status).where(Session.id == session_id)
        )
        session_status = session_result.scalar_one_or_none()
        if session_status is None:
            raise NotFoundException("errors.session_not_found")
        session_status_value = (
            session_status.value
            if hasattr(session_status, "value")
            else str(session_status)
        )
        if session_status_value not in _REPORT_ELIGIBLE_SESSION_STATUS_VALUES:
            raise SessionNotActiveException(
                details={
                    "session_id": str(session_id),
                    "current_status": session_status_value,
                    "eligible_statuses": sorted(
                        _REPORT_ELIGIBLE_SESSION_STATUS_VALUES
                    ),
                }
            )

        # 檢查是否已有報告
        existing = await db.execute(
            select(SOAPReport).where(SOAPReport.session_id == session_id)
        )
        now = utc_now()
        existing_report = existing.scalar_one_or_none()
        stale_takeover = False
        if existing_report is not None:
            report_status_value = str(
                getattr(existing_report.status, "value", existing_report.status)
            )
            # 防連點：生成中一律拒絕（優先於 already-exists 判斷，錯誤訊息才明確
            # ——「稍候再試」vs「已存在，要重生請帶 regenerate」是兩種不同的處置）。
            # 例外：明確要求 regenerate 且已卡在 GENERATING 超過
            # `_STALE_GENERATING_AFTER`（多半是 broker 掛掉導致 delay() 沒送出），
            # 允許強制接手，否則補救路徑會被自己的守衛堵死。
            if report_status_value == ReportStatus.GENERATING.value:
                if regenerate and _is_stale_generating(existing_report, now):
                    stale_takeover = True
                    logger.warning(
                        "SOAP 報告卡在 generating 逾時，regenerate 強制接手 | "
                        "session=%s report=%s since=%s",
                        session_id,
                        existing_report.id,
                        existing_report.updated_at,
                    )
                else:
                    raise ConflictException(
                        "errors.report_generating",
                        details={
                            "session_id": str(session_id),
                            "report_id": str(existing_report.id),
                            "current_status": report_status_value,
                        },
                    )
            if not regenerate:
                raise ReportAlreadyExistsException(
                    details={
                        "session_id": str(session_id),
                        "report_id": str(existing_report.id),
                    }
                )
            if (
                not stale_takeover
                and report_status_value not in _REGENERATABLE_REPORT_STATUS_VALUES
            ):
                # 未知／未來新增的狀態：保守拒絕而非默默覆寫
                raise ConflictException(
                    "errors.report_generating",
                    details={
                        "session_id": str(session_id),
                        "report_id": str(existing_report.id),
                        "current_status": report_status_value,
                    },
                )

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
            # D-8：icd10_verified 是「上一版 codes 通過泌尿科白名單 + symptom↔code
            # 驗證」的旗標。codes 已清空卻留著 verified=True，會讓 UI 對一份還沒
            # 生出來的報告顯示「已驗證」——重生前必須一併歸零。
            existing_report.icd10_verified = False
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

        # SO-4：**先 commit，再派送 Celery 任務**（對齊 WS 觸發器
        # `conversation_handler._trigger_soap_generation` 的「先 commit 再 delay」）。
        # Celery worker 是另一個行程、跑在另一個 DB 連線上：若在 commit 之前
        # delay()，worker 可能在 GENERATING row（或 regenerate 的欄位重置／
        # REGENERATE revision 快照）落地之前就開始 SELECT，讀到舊內容甚至
        # 整個查不到報告列。
        #
        # 冪等性：FastAPI 的 `dependencies.get_db` 在請求收尾時還會再 commit
        # 一次。對一個已經 commit、之後沒有再產生髒資料的 session 而言那是
        # no-op（SQLAlchemy 會開一個空 transaction 直接結束），不會重複寫入，
        # 也不會覆蓋這裡的提交。
        await db.commit()

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


# ── SOAP 內容欄位標籤（SO-5）─────────────────────────────────────
#
# key 一律**以 `soap_generator._SOAP_SYSTEM_PROMPT` 的輸出 schema 為準**逐一對照
# （snake_case，不得改名）。schema 有而此處沒有的鍵並不會被丟掉——`_pdf_label`
# 會 fallback 成把底線換成空白的原鍵名，確保 LLM 多吐的欄位仍印得出來。
#
# 語系與 `_PDF_LABELS` 同一組（zh-TW / en-US / ja-JP / ko-KR）；未支援語系
# fallback 至 zh-TW。
_PDF_FIELD_LABELS: dict[str, dict[str, str]] = {
    "zh-TW": {
        # subjective
        "hpi": "現病史（HPI）",
        "onset": "發作時間",
        "location": "部位",
        "duration": "持續時間",
        "characteristics": "性質",
        "severity": "嚴重度",
        "aggravating_factors": "加重因子",
        "relieving_factors": "緩解因子",
        "associated_symptoms": "伴隨症狀",
        "timing": "時序",
        "context": "情境",
        "past_medical_history": "過去病史",
        "medications": "用藥",
        "allergies": "過敏史",
        "family_history": "家族史",
        "social_history": "社會史",
        "review_of_systems": "系統回顧",
        # objective
        "vital_signs": "生命徵象",
        "physical_exam": "理學檢查",
        "lab_results": "檢驗結果",
        "imaging_results": "影像檢查",
        # assessment
        "differential_diagnoses": "鑑別診斷",
        "diagnosis": "診斷",
        "likelihood": "可能性",
        "reasoning": "判斷依據",
        # plan
        "recommended_tests": "建議檢查",
        "test_name": "檢查項目",
        "rationale": "檢查理由",
        "urgency": "緊急度",
        "clinical_reasoning": "臨床推論",
        "treatments": "處置",
        "follow_up": "追蹤安排",
        "patient_education": "衛教說明",
        "referrals": "轉診建議",
        "diagnostic_reasoning": "診斷推論",
    },
    "en-US": {
        "hpi": "History of present illness (HPI)",
        "onset": "Onset",
        "location": "Location",
        "duration": "Duration",
        "characteristics": "Characteristics",
        "severity": "Severity",
        "aggravating_factors": "Aggravating factors",
        "relieving_factors": "Relieving factors",
        "associated_symptoms": "Associated symptoms",
        "timing": "Timing",
        "context": "Context",
        "past_medical_history": "Past medical history",
        "medications": "Medications",
        "allergies": "Allergies",
        "family_history": "Family history",
        "social_history": "Social history",
        "review_of_systems": "Review of systems",
        "vital_signs": "Vital signs",
        "physical_exam": "Physical exam",
        "lab_results": "Lab results",
        "imaging_results": "Imaging results",
        "differential_diagnoses": "Differential diagnoses",
        "diagnosis": "Diagnosis",
        "likelihood": "Likelihood",
        "reasoning": "Reasoning",
        "recommended_tests": "Recommended tests",
        "test_name": "Test",
        "rationale": "Rationale",
        "urgency": "Urgency",
        "clinical_reasoning": "Clinical reasoning",
        "treatments": "Treatments",
        "follow_up": "Follow-up",
        "patient_education": "Patient education",
        "referrals": "Referrals",
        "diagnostic_reasoning": "Diagnostic reasoning",
    },
    "ja-JP": {
        "hpi": "現病歴（HPI）",
        "onset": "発症",
        "location": "部位",
        "duration": "持続時間",
        "characteristics": "性状",
        "severity": "重症度",
        "aggravating_factors": "増悪因子",
        "relieving_factors": "寛解因子",
        "associated_symptoms": "随伴症状",
        "timing": "時間経過",
        "context": "状況",
        "past_medical_history": "既往歴",
        "medications": "服用薬",
        "allergies": "アレルギー",
        "family_history": "家族歴",
        "social_history": "生活歴",
        "review_of_systems": "システムレビュー",
        "vital_signs": "バイタルサイン",
        "physical_exam": "身体所見",
        "lab_results": "検査結果",
        "imaging_results": "画像所見",
        "differential_diagnoses": "鑑別診断",
        "diagnosis": "診断",
        "likelihood": "可能性",
        "reasoning": "根拠",
        "recommended_tests": "推奨検査",
        "test_name": "検査項目",
        "rationale": "検査理由",
        "urgency": "緊急度",
        "clinical_reasoning": "臨床的根拠",
        "treatments": "処置",
        "follow_up": "フォローアップ",
        "patient_education": "患者教育",
        "referrals": "紹介",
        "diagnostic_reasoning": "診断的根拠",
    },
    "ko-KR": {
        "hpi": "현병력(HPI)",
        "onset": "발병 시점",
        "location": "부위",
        "duration": "지속 시간",
        "characteristics": "양상",
        "severity": "중증도",
        "aggravating_factors": "악화 요인",
        "relieving_factors": "완화 요인",
        "associated_symptoms": "동반 증상",
        "timing": "시간 양상",
        "context": "상황",
        "past_medical_history": "과거 병력",
        "medications": "복용 약물",
        "allergies": "알레르기",
        "family_history": "가족력",
        "social_history": "사회력",
        "review_of_systems": "계통 문진",
        "vital_signs": "활력징후",
        "physical_exam": "신체 검사",
        "lab_results": "검사 결과",
        "imaging_results": "영상 검사",
        "differential_diagnoses": "감별 진단",
        "diagnosis": "진단",
        "likelihood": "가능성",
        "reasoning": "판단 근거",
        "recommended_tests": "권장 검사",
        "test_name": "검사 항목",
        "rationale": "검사 사유",
        "urgency": "긴급도",
        "clinical_reasoning": "임상적 추론",
        "treatments": "처치",
        "follow_up": "추적 관찰",
        "patient_education": "환자 교육",
        "referrals": "의뢰",
        "diagnostic_reasoning": "진단적 추론",
    },
}


# enum value → 醫師可讀文字。value 取自 soap_generator 的 schema
# （urgency：er_now / 24h / this_week / routine；likelihood：high / moderate / low）。
# 對不上的值不會被吞掉——`_enum_text` 原樣回傳原始字串，方便發現 LLM 吐了怪值。
_PDF_ENUM_LABELS: dict[str, dict[str, dict[str, str]]] = {
    "urgency": {
        "zh-TW": {
            "er_now": "立即急診",
            "24h": "24 小時內",
            "this_week": "本週內",
            "routine": "常規安排",
        },
        "en-US": {
            "er_now": "Emergency (now)",
            "24h": "Within 24 hours",
            "this_week": "Within this week",
            "routine": "Routine",
        },
        "ja-JP": {
            "er_now": "直ちに救急",
            "24h": "24時間以内",
            "this_week": "今週中",
            "routine": "通常",
        },
        "ko-KR": {
            "er_now": "즉시 응급",
            "24h": "24시간 이내",
            "this_week": "이번 주 이내",
            "routine": "일반",
        },
    },
    "likelihood": {
        "zh-TW": {"high": "高", "moderate": "中", "low": "低"},
        "en-US": {"high": "High", "moderate": "Moderate", "low": "Low"},
        "ja-JP": {"high": "高", "moderate": "中", "low": "低"},
        "ko-KR": {"high": "높음", "moderate": "보통", "low": "낮음"},
    },
}

# 各段的已知欄位順序（= soap_generator schema 的順序）。列在這裡的欄位**一定**
# 會印出來（沒有值就印 `_PDF_EMPTY`），讓醫師分得出「沒收集到」與「渲染漏掉」。
_HPI_FIELDS: tuple[str, ...] = (
    "onset",
    "location",
    "duration",
    "characteristics",
    "severity",
    "aggravating_factors",
    "relieving_factors",
    "associated_symptoms",
    "timing",
    "context",
)
_SUBJECTIVE_FIELDS: tuple[str, ...] = (
    "chief_complaint",
    "hpi",
    "past_medical_history",
    "medications",
    "allergies",
    "family_history",
    "social_history",
    "review_of_systems",
)
_OBJECTIVE_FIELDS: tuple[str, ...] = (
    "vital_signs",
    "physical_exam",
    "lab_results",
    "imaging_results",
)
_ASSESSMENT_FIELDS: tuple[str, ...] = (
    "clinical_impression",
    "differential_diagnoses",
)
_DIFFERENTIAL_FIELDS: tuple[str, ...] = ("diagnosis", "likelihood", "reasoning")
_PLAN_FIELDS: tuple[str, ...] = (
    "urgency",
    "recommended_tests",
    "treatments",
    "medications",
    "follow_up",
    "patient_education",
    "referrals",
    "diagnostic_reasoning",
)
_RECOMMENDED_TEST_FIELDS: tuple[str, ...] = (
    "test_name",
    "rationale",
    "urgency",
    "clinical_reasoning",
)

# 空值佔位；出現它＝該欄位對話中沒收集到（不是渲染漏印）
_PDF_EMPTY = "—"


def _pdf_label(key: str, language: str) -> str:
    """
    欄位標籤。查找順序：

      1. `_PDF_FIELD_LABELS[language]`
      2. `_PDF_LABELS[language]`（chief_complaint / clinical_impression / summary
         等舊有版面標籤沿用同一份翻譯，不重複維護）
      3. 同兩張表的 zh-TW
      4. 原鍵名（底線換空白）

    最後一段是刻意的：LLM 若多吐了 schema 外的鍵，寧可印出無翻譯的鍵名，
    也不要靜默丟掉臨床內容。
    """
    for table in (
        _PDF_FIELD_LABELS.get(language),
        _PDF_LABELS.get(language),
        _PDF_FIELD_LABELS["zh-TW"],
        _PDF_LABELS["zh-TW"],
    ):
        if table and key in table:
            return table[key]
    return key.replace("_", " ")


def _enum_text(kind: str, value: str, language: str) -> str:
    """enum value → 可讀文字；對不上就原樣回傳（不吞未知值）。"""
    per_lang = _PDF_ENUM_LABELS.get(kind, {})
    table = per_lang.get(language) or per_lang.get("zh-TW") or {}
    return table.get(value, value)


def _render_pdf_value(value: Any, language: str, key: Optional[str] = None) -> str:
    """
    把 SOAP JSONB 的任意值轉成醫師可讀 HTML 片段。

    - None / 空字串 / 空 list / 空 dict → `_PDF_EMPTY`
    - urgency / likelihood 這類 enum 欄位 → 轉可讀文字（`er_now` → 「立即急診」）
    - list → `<ul>`；dict → 巢狀欄位表
    - 其餘 → 逃逸後的字串

    安全：所有葉節點一律 `html.escape`（值可能含病患語音 prompt-inject 的
    `<img src>` / CSS url()，未逃逸會經 WeasyPrint 觸發伺服器端資源抓取）。
    """
    if value is None:
        return _PDF_EMPTY
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return _PDF_EMPTY
        if key in _PDF_ENUM_LABELS:
            return _html.escape(_enum_text(key, stripped, language))
        return _html.escape(stripped)
    if isinstance(value, bool):
        return _html.escape(str(value))
    if isinstance(value, (int, float)):
        return _html.escape(str(value))
    if isinstance(value, (list, tuple)):
        if not value:
            return _PDF_EMPTY
        # key 往下傳：list-of-dict（differential_diagnoses / recommended_tests）
        # 的元素要沿用父鍵查已知欄位順序
        items = "".join(
            f"<li>{_render_pdf_value(v, language, key=key)}</li>" for v in value
        )
        return f"<ul>{items}</ul>"
    if isinstance(value, dict):
        if not value:
            return _PDF_EMPTY
        known = _KNOWN_FIELDS_BY_PARENT.get(key or "", ())
        return _render_field_table(value, known, language)
    # 未知型別：字串化後逃逸，絕不靜默丟
    return _html.escape(str(value))


def _ordered_fields(data: dict, known: tuple[str, ...]):
    """已知欄位依 schema 順序（缺值也產出），其餘鍵接在後面（不靜默丟棄）。"""
    for key in known:
        yield key, data.get(key)
    for key in data:
        if key not in known:
            yield key, data[key]


def _render_field_table(data: dict, known: tuple[str, ...], language: str) -> str:
    """把一個 SOAP 區段 dict 渲染成 label / value 欄位表。"""
    rows = "".join(
        f"<tr><th>{_html.escape(_pdf_label(key, language))}</th>"
        f"<td>{_render_pdf_value(value, language, key=key)}</td></tr>"
        for key, value in _ordered_fields(data, known)
    )
    return f"<table><tbody>{rows}</tbody></table>"


# 巢狀 dict / list-of-dict 的已知欄位順序，供 `_render_pdf_value` 依父鍵查表。
_KNOWN_FIELDS_BY_PARENT: dict[str, tuple[str, ...]] = {
    "hpi": _HPI_FIELDS,
    "differential_diagnoses": _DIFFERENTIAL_FIELDS,
    "recommended_tests": _RECOMMENDED_TEST_FIELDS,
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

    SO-5：四段內容全部欄位化排版（不再 json.dumps 整包 dump）。欄位鍵以
    `soap_generator` 的 prompt schema 為準，未登錄的鍵仍會印出（見 `_pdf_label`）。
    """
    from app.utils.datetime_utils import format_iso

    # 未支援的 language 一律 fallback 至 zh-TW，確保標籤一定有值。
    labels = _PDF_LABELS.get(language) or _PDF_LABELS["zh-TW"]
    # 欄位標籤／enum 文字用的語系（要與 labels 的 fallback 一致）
    field_language = language if language in _PDF_FIELD_LABELS else "zh-TW"

    subjective = report.subjective or {}
    objective = report.objective or {}
    assessment = report.assessment or {}
    plan = report.plan or {}

    # 安全：所有插入 HTML 的資料欄位一律逃逸。這些欄位源自 LLM 生成
    # （可被病患語音 prompt-inject）與醫師自由文字，未逃逸會讓注入的
    # <img src> / CSS url() 經 WeasyPrint 觸發伺服器端資源抓取。
    esc = _html.escape
    summary = esc(str(report.summary or "N/A"))
    icd10 = esc(", ".join(report.icd10_codes)) if report.icd10_codes else "N/A"

    # 四段內容：欄位化表格。非 dict（理論上不該發生）時退回 JSON dump，
    # 至少不讓資料消失。
    def _section(data: Any, known: tuple[str, ...]) -> str:
        if isinstance(data, dict):
            if not data:
                return "<p>N/A</p>"
            return _render_field_table(data, known, field_language)
        return _format_dict(data) if data else "<p>N/A</p>"

    subjective_html = _section(subjective, _SUBJECTIVE_FIELDS)
    objective_html = _section(objective, _OBJECTIVE_FIELDS)
    assessment_html = _section(assessment, _ASSESSMENT_FIELDS)
    plan_html = _section(plan, _PLAN_FIELDS)

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
            td, th {{ padding: 8px; border: 1px solid #e2e8f0; text-align: left; vertical-align: top; }}
            th {{ background: #edf2f7; width: 24%; font-weight: 600; }}
            /* 巢狀欄位表（hpi / 鑑別診斷 / 建議檢查；後兩者還多包一層 <li>）
               貼齊外層儲存格，故用後代選擇器而非 child 選擇器 */
            td table {{ margin: 0; }}
            td table th {{ background: #f7fafc; width: 30%; font-weight: 500; }}
            ul {{ margin: 0; padding-left: 18px; }}
            li {{ margin-bottom: 4px; }}
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
            {subjective_html}
            <p><strong>{labels["summary"]}:</strong> {summary}</p>
        </div>

        <div class="section">
            <h2>{labels["objective"]}</h2>
            {objective_html}
        </div>

        <div class="section">
            <h2>{labels["assessment"]}</h2>
            {assessment_html}
            <p><strong>ICD-10:</strong> {icd10}</p>
        </div>

        <div class="section">
            <h2>{labels["plan"]}</h2>
            {plan_html}
        </div>
        {transcript_section}
        <div class="section">
            <p class="meta">{labels["confidence"]}: {confidence}</p>
            {review_notes_html}
        </div>
    </body>
    </html>
    """


def _format_dict(d: Any) -> str:
    """
    將 dict 格式化為 HTML 段落（內容一律逃逸，值可能含 LLM 生成文字）。

    SO-5 後不再是 SOAP 四段的主要排版路徑（改走 `_render_field_table` 的
    醫師可讀欄位化排版）；僅保留為 **非 dict 內容的最後防線** ——
    若 objective / plan 因資料異常不是 dict，寧可 dump JSON 也不讓內容消失。
    """
    import json

    return f"<pre>{_html.escape(json.dumps(d, ensure_ascii=False, indent=2, default=str))}</pre>"


def _forbid_url_fetch(url: str) -> dict:
    """WeasyPrint url_fetcher：一律拒絕抓取任何資源。

    報告 HTML 樣式全為 inline CSS、不需任何外部資源；拒絕所有 URL
    （http/https/file/...）可阻斷經注入內容觸發的伺服器端 SSRF／本地檔讀取。
    WeasyPrint 對 fetch 失敗僅記 log 並略過該資源，不影響 PDF 產出。
    """
    raise ValueError(f"PDF 匯出禁止抓取外部資源: {url}")
