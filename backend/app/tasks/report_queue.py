"""
SOAP 報告生成 Celery 任務
- 從 Session + Patient + Conversation 取得完整上下文
- 依 session.language 呼叫 SOAPGenerator
- 將結果寫回 SOAPReport（含 language 欄位）
"""

import logging

from celery import Task

from app.tasks import celery_app

logger = logging.getLogger(__name__)


def _run_async(coro):
    """在同步 Celery worker context 內安全執行 async coroutine。

    與 generate_soap_report 的執行策略一致：優先沿用既有 event loop，
    若已在運行則改用 asyncio.run 新建一個 loop。
    """
    import asyncio

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            raise RuntimeError("event loop already running")
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


class _SOAPReportTask(Task):
    """
    自訂 Celery Task 基底，提供 on_failure 安全網。

    當任務在重試耗盡後仍最終失敗（或 task body 以非預期方式拋出），
    Celery 會呼叫 on_failure；此處將對應 SOAPReport 標記為 FAILED，
    確保報告不會永遠卡在 'generating' 狀態。
    """

    def on_failure(self, exc, task_id, args, kwargs, einfo):  # noqa: D401
        session_id = None
        if args:
            session_id = args[0]
        elif kwargs:
            session_id = kwargs.get("session_id")
        if not session_id:
            logger.error(
                "SOAP 報告任務最終失敗但無法解析 session_id，無法標記 FAILED: %s",
                exc,
            )
            return
        try:
            _run_async(_mark_report_failed(str(session_id)))
            logger.error(
                "SOAP 報告任務最終失敗，已將場次 %s 報告標記為 FAILED: %s",
                session_id,
                exc,
            )
        except Exception:  # noqa: BLE001 — on_failure 內不可再向上拋
            logger.exception(
                "SOAP 報告任務 on_failure 標記 FAILED 失敗: session=%s", session_id
            )


@celery_app.task(
    base=_SOAPReportTask,
    name="app.tasks.report_queue.generate_soap_report",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
    acks_late=True,
)
def generate_soap_report(self, session_id: str) -> dict:
    """
    生成 SOAP 報告（同步 Celery 任務，內部以同步方式執行 async 邏輯）

    Args:
        session_id: 場次 ID

    Returns:
        包含報告 ID 與狀態的字典
    """
    return _run_async(_async_generate(session_id))


async def _mark_report_failed(session_id: str) -> None:
    """獨立交易：把指定場次的 SOAPReport 標記為 FAILED 並 commit。

    供 on_failure 安全網使用——task body 內已有 except 路徑會處理多數情況，
    此函式為「最終失敗」時的兜底，獨立開一個 session 以免沿用已 rollback 的交易。
    """
    from app.core.database import async_session_factory
    from app.models.enums import ReportStatus

    async with async_session_factory() as db:
        await _update_report_status(db, session_id, ReportStatus.FAILED)
        await db.commit()


async def _async_generate(session_id: str) -> dict:
    """非同步報告生成核心邏輯"""
    from datetime import date

    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.core.config import settings
    from app.core.database import async_session_factory
    from app.models.enums import ReportRevisionReason, ReportStatus
    from app.models.session import Session
    from app.models.soap_report import SOAPReport
    from app.pipelines.icd10_symptom_map import resolve_symptom_id
    from app.pipelines.soap_generator import SOAPGenerator
    from app.utils.datetime_utils import utc_now

    async with async_session_factory() as db:
        try:
            stmt = (
                select(Session)
                .options(
                    selectinload(Session.patient),
                    selectinload(Session.conversations),
                    selectinload(Session.chief_complaint),
                )
                .where(Session.id == session_id)
            )
            session_obj = (await db.execute(stmt)).scalar_one_or_none()

            if session_obj is None:
                logger.warning("場次 %s 不存在，無法生成報告", session_id)
                return {
                    "session_id": session_id,
                    "status": "failed",
                    "reason": "session_not_found",
                }

            conversations = list(session_obj.conversations or [])
            if not conversations:
                logger.warning("場次 %s 無對話紀錄，無法生成報告", session_id)
                await _update_report_status(db, session_id, ReportStatus.FAILED)
                await db.commit()
                return {
                    "session_id": session_id,
                    "status": "failed",
                    "reason": "no_conversations",
                }

            transcript: list[dict[str, object]] = []
            for conv in conversations:
                role_value = conv.role.value if hasattr(conv.role, "value") else str(conv.role)
                transcript.append(
                    {
                        "role": role_value,
                        "content": conv.content_text or "",
                        "timestamp": conv.created_at.isoformat() if conv.created_at else "",
                    }
                )

            patient_info: dict[str, object] = {}
            patient = session_obj.patient
            if patient is not None:
                if patient.name:
                    patient_info["name"] = patient.name
                if patient.gender:
                    patient_info["gender"] = (
                        patient.gender.value
                        if hasattr(patient.gender, "value")
                        else str(patient.gender)
                    )
                if patient.date_of_birth:
                    today = date.today()
                    dob = patient.date_of_birth
                    patient_info["age"] = (
                        today.year - dob.year
                        - ((today.month, today.day) < (dob.month, dob.day))
                    )

            chief_complaint_text = session_obj.chief_complaint_text or ""
            if not chief_complaint_text and session_obj.chief_complaint is not None:
                chief_complaint_text = getattr(session_obj.chief_complaint, "name", "") or ""

            # M3：symptom_id 供 ICD-10 validator 對映——優先取 ChiefComplaint.name_en
            # 正規化後的 snake_case slug（與 `icd10_symptom_map.SYMPTOM_TO_ICD10` 的 key 相容）。
            # B2：共用函式見 icd10_symptom_map.resolve_symptom_id（WS 路徑亦使用）。
            symptom_id = resolve_symptom_id(session_obj)

            # 取出本場次即時偵測並持久化的紅旗，注入 SOAP 生成（安全關鍵：
            # 避免 LLM 自逐字稿重新推導時把 critical 急症 under-triage）。
            from app.models.red_flag_alert import RedFlagAlert

            rf_rows = (
                await db.execute(
                    select(RedFlagAlert).where(RedFlagAlert.session_id == session_id)
                )
            ).scalars().all()
            red_flags = [
                {
                    "severity": (
                        rf.severity.value
                        if hasattr(rf.severity, "value")
                        else str(rf.severity)
                    ),
                    "canonical_id": getattr(rf, "canonical_id", None),
                    "trigger_reason": rf.trigger_reason or "",
                    "suggested_actions": rf.suggested_actions or [],
                }
                for rf in rf_rows
            ]

            language = session_obj.language
            generator = SOAPGenerator(settings)
            soap_data = await generator.generate(
                transcript=transcript,
                patient_info=patient_info,
                chief_complaint=chief_complaint_text,
                language=language,
                symptom_id=symptom_id,
                red_flags=red_flags,
            )

            raw_transcript = "\n".join(
                f"[{entry['role']}] {entry['content']}" for entry in transcript
            )

            report = (
                await db.execute(
                    select(SOAPReport).where(SOAPReport.session_id == session_id)
                )
            ).scalar_one_or_none()

            if report is None:
                logger.error("場次 %s 找不到對應的報告記錄", session_id)
                return {
                    "session_id": session_id,
                    "status": "failed",
                    "reason": "report_not_found",
                }

            report.subjective = soap_data.get("subjective")
            report.objective = soap_data.get("objective")
            report.assessment = soap_data.get("assessment")
            report.plan = soap_data.get("plan")
            report.raw_transcript = raw_transcript
            report.summary = soap_data.get("summary", "")
            report.icd10_codes = soap_data.get("icd10_codes", [])
            # M3：把 validator 輸出的驗證旗標同步寫入，支援前端顯示「需醫師確認」
            report.icd10_verified = bool(soap_data.get("icd10_verified", False))
            report.ai_confidence_score = soap_data.get("confidence_score")
            report.language = language
            report.status = ReportStatus.GENERATED
            report.generated_at = utc_now()

            # M15 append-only：把剛寫入的首版內容存成不可變快照
            await db.flush()
            from app.services.report_service import ReportService

            await ReportService._snapshot_revision(
                db,
                report,
                ReportRevisionReason.INITIAL,
            )

            await db.commit()
            logger.info(
                "場次 %s SOAP 報告生成完成 | language=%s",
                session_id,
                language,
            )

            # H-8：報告真正完成（已 commit）才是 report_generated 的正確語意完成點。
            # 本任務在 Celery worker 行程，與持有 dashboard WS 連線的 API 行程不同，
            # 故走 Redis publish（由 API 行程的 subscriber 收到後本地 fan-out）。
            # payload 一律 camelCase 以對齊前端 ``ReportGeneratedPayload``。
            # publish 失敗已於 helper 內 swallow + log；此處再包一層確保絕不影響任務回傳。
            try:
                patient_name = ""
                patient = session_obj.patient
                if patient is not None:
                    patient_name = getattr(patient, "name", "") or ""
                await _publish_report_generated(
                    report_id=str(report.id),
                    session_id=session_id,
                    patient_name=patient_name,
                    status="generated",
                )
            except Exception as exc:  # noqa: BLE001 — 推播失敗不可影響任務結果
                logger.warning(
                    "場次 %s report_generated 推播失敗（非致命） | error=%s",
                    session_id,
                    exc,
                )

            return {
                "session_id": session_id,
                "status": "generated",
                "report_id": str(report.id),
            }

        except Exception as exc:
            logger.exception("場次 %s SOAP 報告生成失敗: %s", session_id, exc)
            await _update_report_status(db, session_id, ReportStatus.FAILED)
            await db.commit()
            raise


async def _publish_report_generated(
    report_id: str,
    session_id: str,
    patient_name: str,
    status: str,
) -> None:
    """把 ``report_generated`` 事件 publish 到 Redis 儀表板頻道（跨行程）。

    在 Celery worker 行程觸發，無法用 in-memory 廣播觸及 API 行程的 WS 連線，
    故走 ``ConnectionManager.publish_dashboard_event``（內部已對 Redis 故障做韌性處理）。
    payload 鍵名為 camelCase 以對齊前端 ``ReportGeneratedPayload``。
    """
    from app.websocket.connection_manager import publish_dashboard_event

    await publish_dashboard_event(
        "report_generated",
        {
            "reportId": report_id,
            "sessionId": session_id,
            "patientName": patient_name or "",
            "status": status,
        },
    )


async def _update_report_status(db, session_id: str, status) -> None:
    """更新報告狀態"""
    from sqlalchemy import select

    from app.models.soap_report import SOAPReport

    report = (
        await db.execute(
            select(SOAPReport).where(SOAPReport.session_id == session_id)
        )
    ).scalar_one_or_none()
    if report is not None:
        report.status = status
