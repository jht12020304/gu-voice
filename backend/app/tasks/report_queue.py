"""
SOAP 報告生成 Celery 任務
- 從對話紀錄取得完整逐字稿
- 呼叫 SOAP 生成 pipeline
- 將結果寫回資料庫
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
        result = asyncio.get_event_loop().run_until_complete(
            _async_generate(session_id)
        )
        return result
    except Exception:
        # 若事件迴圈不存在，建立新的
        result = asyncio.run(_async_generate(session_id))
        return result


async def _async_generate(session_id: str) -> dict:
    """非同步報告生成核心邏輯"""
    from sqlalchemy import select

    from app.core.database import async_session_factory
    from app.models.conversation import Conversation
    from app.models.soap_report import SOAPReport
    from app.models.enums import ReportStatus

    async with async_session_factory() as db:
        try:
            # 1. 取得場次所有對話紀錄
            result = await db.execute(
                select(Conversation)
                .where(Conversation.session_id == session_id)
                .order_by(Conversation.sequence_number.asc())
            )
            conversations = result.scalars().all()

            if not conversations:
                logger.warning("場次 %s 無對話紀錄，無法生成報告", session_id)
                # 更新報告狀態為 failed
                await _update_report_status(db, session_id, ReportStatus.FAILED)
                return {"session_id": session_id, "status": "failed", "reason": "no_conversations"}

            # 2. 組合逐字稿
            transcript_lines: list[str] = []
            for conv in conversations:
                transcript_lines.append(f"[{conv.role}] {conv.content_text}")
            raw_transcript = "\n".join(transcript_lines)

            # 3. 呼叫 SOAP 生成 pipeline
            try:
                from app.pipelines.soap_generator import generate_soap

                soap_data = await generate_soap(
                    transcript=raw_transcript,
                    conversations=conversations,
                )
            except ImportError:
                logger.error("SOAP pipeline 尚未實作，使用空白報告")
                soap_data = {
                    "subjective": {},
                    "objective": {},
                    "assessment": {},
                    "plan": {},
                    "summary": "",
                    "icd10_codes": [],
                    "ai_confidence_score": 0.0,
                }

            # 4. 更新報告內容
            from app.services.report_service import ReportService

            report_result = await db.execute(
                select(SOAPReport).where(SOAPReport.session_id == session_id)
            )
            report = report_result.scalar_one_or_none()

            if report:
                from app.utils.datetime_utils import utc_now

                report.subjective = soap_data.get("subjective")
                report.objective = soap_data.get("objective")
                report.assessment = soap_data.get("assessment")
                report.plan = soap_data.get("plan")
                report.raw_transcript = raw_transcript
                report.summary = soap_data.get("summary", "")
                report.icd10_codes = soap_data.get("icd10_codes", [])
                report.ai_confidence_score = soap_data.get("ai_confidence_score")
                report.status = ReportStatus.GENERATED
                report.generated_at = utc_now()

                await db.commit()
                logger.info("場次 %s SOAP 報告生成完成", session_id)
                return {"session_id": session_id, "status": "generated", "report_id": str(report.id)}

            logger.error("場次 %s 找不到對應的報告記錄", session_id)
            return {"session_id": session_id, "status": "failed", "reason": "report_not_found"}

        except Exception as exc:
            logger.exception("場次 %s SOAP 報告生成失敗: %s", session_id, exc)
            await _update_report_status(db, session_id, ReportStatus.FAILED)
            await db.commit()
            raise


async def _update_report_status(db, session_id: str, status) -> None:
    """更新報告狀態"""
    from sqlalchemy import select

    from app.models.soap_report import SOAPReport

    result = await db.execute(
        select(SOAPReport).where(SOAPReport.session_id == session_id)
    )
    report = result.scalar_one_or_none()
    if report:
        report.status = status
        await db.commit()
