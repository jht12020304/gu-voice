"""
SOAP 報告生成 Celery 任務
- 從 Session + Patient + Conversation 取得完整上下文
- 依 session.language 呼叫 SOAPGenerator
- 將結果寫回 SOAPReport（含 language 欄位）
"""

import logging

from app.tasks import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
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
    import asyncio

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            raise RuntimeError("event loop already running")
        return loop.run_until_complete(_async_generate(session_id))
    except RuntimeError:
        return asyncio.run(_async_generate(session_id))


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

            language = session_obj.language
            generator = SOAPGenerator(settings)
            soap_data = await generator.generate(
                transcript=transcript,
                patient_info=patient_info,
                chief_complaint=chief_complaint_text,
                language=language,
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
