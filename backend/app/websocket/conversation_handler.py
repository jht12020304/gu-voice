"""
語音對話 WebSocket 處理器

處理完整的語音問診流程：
Client audio_chunk → STT → LLM → TTS → Client
同時在每次病患訊息後並行執行紅旗偵測。
"""

import asyncio
import base64
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from jose import JWTError
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.security import verify_access_token
from app.pipelines.llm_conversation import LLMConversationEngine
from app.pipelines.red_flag_detector import RedFlagDetector
from app.pipelines.stt_pipeline import STTPipeline
from app.pipelines.tts_pipeline import TTSPipeline
from app.pipelines.supervisor import SupervisorEngine
from app.websocket.connection_manager import manager

logger = logging.getLogger(__name__)

# ── Redis key 常數 ───────────────────────────────────────
_SESSION_CONTEXT_KEY = "gu:session:{session_id}:context"
_SESSION_STATE_KEY = "gu:session:{session_id}:state"
_SESSION_CONTEXT_TTL = 3600  # 1 小時
_SESSION_STATE_TTL = 1800  # 30 分鐘
_SESSION_SUPERVISOR_KEY = "gu:session:{session_id}:supervisor_guidance"


async def conversation_websocket(
    websocket: WebSocket,
    session_id: str,
    db: AsyncSession,
    redis: Redis,
    settings: Settings,
) -> None:
    """
    語音對話 WebSocket 主處理函式

    完整流程：
    1. 驗證 Token 並確認場次狀態
    2. 發送 connection_ack
    3. 監聽客戶端訊息並分派處理
    4. 每次病患訊息後並行執行紅旗偵測
    5. 斷線時儲存最終狀態

    Args:
        websocket: FastAPI WebSocket 實例
        session_id: 問診場次 ID
        db: 非同步資料庫 session
        redis: Redis 非同步客戶端
        settings: 應用程式設定
    """
    user_id: str | None = None
    stt_pipeline: STTPipeline | None = None
    conversation_history: list[dict[str, Any]] = []

    try:
        # ── 步驟 1：認證 ────────────────────────────────
        token = websocket.query_params.get("token")
        if not token:
            await websocket.close(code=4001, reason="缺少認證 Token")
            return

        try:
            payload = verify_access_token(token)
            user_id = payload.get("sub")
        except JWTError as exc:
            logger.warning(
                "WebSocket Token 驗證失敗 | session=%s, error=%s",
                session_id,
                str(exc),
            )
            await websocket.close(code=4001, reason="Token 無效或已過期")
            return

        # ── 步驟 2：驗證場次狀態 ────────────────────────
        session_data = await _validate_session(session_id, db)
        if session_data is None:
            await websocket.close(code=4004, reason="場次不存在")
            return

        session_status = session_data.get("status")
        if session_status not in ("waiting", "in_progress"):
            await websocket.close(
                code=4009,
                reason=f"場次狀態不正確：{session_status}",
            )
            return

        # ── 步驟 3：建立連線 ────────────────────────────
        await manager.connect_session(websocket, session_id)

        # 立即發送 connection_ack（在任何 I/O 初始化之前）
        await manager.send_to_session(
            session_id,
            {
                "type": "connection_ack",
                "payload": {
                    "sessionId": session_id,
                    "status": "connected",
                    "config": {
                        "audioFormat": "wav",
                        "sampleRate": settings.GOOGLE_STT_SAMPLE_RATE,
                        "maxChunkSizeBytes": 32768,  # 32KB
                    },
                },
            },
        )

        # 初始化 AI 管線（在 ack 之後，避免初始化延遲導致客戶端逾時）
        stt_pipeline = STTPipeline(settings)
        llm_engine = LLMConversationEngine(settings)
        tts_pipeline = TTSPipeline(settings)
        red_flag_detector = RedFlagDetector(settings, db)
        supervisor_engine = SupervisorEngine(settings)

        # 從 Redis 載入對話歷史（若有）
        conversation_history = await _load_conversation_history(
            redis, session_id
        )

        # 組合場次上下文
        session_context: dict[str, Any] = {
            "session_id": session_id,
            "user_id": user_id,
            "chief_complaint": session_data.get("chief_complaint", ""),
            "patient_info": session_data.get("patient_info", {}),
        }

        # 建構系統提示詞
        system_prompt = llm_engine.build_system_prompt(
            chief_complaint=session_context["chief_complaint"],
            patient_info=session_context["patient_info"],
        )

        # 更新場次狀態為進行中
        await _update_session_status(
            db, redis, session_id, "in_progress", session_status
        )

        # 通知儀表板
        await manager.broadcast_dashboard(
            {
                "type": "session_status_changed",
                "payload": {
                    "sessionId": session_id,
                    "status": "in_progress",
                    "previousStatus": session_status,
                    "reason": "WebSocket 連線建立",
                },
            }
        )

        logger.info(
            "問診 WebSocket 已就緒 | session=%s, user=%s",
            session_id,
            user_id,
        )

        # ── 步驟 4：主訊息迴圈 ─────────────────────────
        is_paused = False

        while True:
            raw_message = await websocket.receive_json()
            msg_type = raw_message.get("type", "")
            msg_payload = raw_message.get("payload", {})

            # ── ping / pong ────────────────────────────
            if msg_type == "ping":
                await manager.send_to_session(
                    session_id,
                    {
                        "type": "pong",
                        "payload": {
                            "serverTime": datetime.now(timezone.utc).isoformat()
                        },
                    },
                )
                continue

            # ── 控制指令 ───────────────────────────────
            if msg_type == "control":
                action = msg_payload.get("action", "")

                if action == "end_session":
                    logger.info("收到結束場次指令 | session=%s", session_id)
                    await _update_session_status(
                        db, redis, session_id, "completed", "in_progress"
                    )
                    await manager.send_to_session(
                        session_id,
                        {
                            "type": "session_status",
                            "payload": {
                                "sessionId": session_id,
                                "status": "completed",
                                "previousStatus": "in_progress",
                                "reason": "病患或助手結束場次",
                            },
                        },
                    )
                    await manager.broadcast_dashboard(
                        {
                            "type": "session_status_changed",
                            "payload": {
                                "sessionId": session_id,
                                "status": "completed",
                                "previousStatus": "in_progress",
                                "reason": "場次正常結束",
                            },
                        }
                    )
                    # 觸發 SOAP 報告非同步生成
                    asyncio.create_task(
                        _generate_soap_report_async(
                            session_id=session_id,
                            conversation_history=conversation_history,
                            session_context=session_context,
                            settings=settings,
                        )
                    )

                    break

                elif action == "pause_recording":
                    is_paused = True
                    logger.info("暫停錄音 | session=%s", session_id)
                    continue

                elif action == "resume_recording":
                    is_paused = False
                    logger.info("恢復錄音 | session=%s", session_id)
                    continue

                else:
                    logger.warning(
                        "未知控制指令 | session=%s, action=%s",
                        session_id,
                        action,
                    )
                    continue

            # ── 暫停中忽略音訊 ─────────────────────────
            if is_paused and msg_type == "audio_chunk":
                continue

            # ── 音訊片段處理 ───────────────────────────
            if msg_type == "audio_chunk":
                await _handle_audio_chunk(
                    session_id=session_id,
                    payload=msg_payload,
                    stt_pipeline=stt_pipeline,
                    llm_engine=llm_engine,
                    tts_pipeline=tts_pipeline,
                    red_flag_detector=red_flag_detector,
                    supervisor_engine=supervisor_engine,
                    system_prompt=system_prompt,
                    conversation_history=conversation_history,
                    session_context=session_context,
                    redis=redis,
                    db=db,
                )
                continue

            # ── 文字訊息處理（跳過 STT）─────────────────
            if msg_type == "text_message":
                text = msg_payload.get("text", "").strip()
                if text:
                    await _handle_text_message(
                        session_id=session_id,
                        text=text,
                        llm_engine=llm_engine,
                        tts_pipeline=tts_pipeline,
                        red_flag_detector=red_flag_detector,
                        supervisor_engine=supervisor_engine,
                        system_prompt=system_prompt,
                        conversation_history=conversation_history,
                        session_context=session_context,
                        redis=redis,
                        db=db,
                    )
                continue

            # ── 未知訊息類型 ───────────────────────────
            logger.warning(
                "收到未知訊息類型 | session=%s, type=%s",
                session_id,
                msg_type,
            )
            await manager.send_to_session(
                session_id,
                {
                    "type": "error",
                    "payload": {
                        "code": "UNKNOWN_MESSAGE_TYPE",
                        "message": f"不支援的訊息類型：{msg_type}",
                    },
                },
            )

    except WebSocketDisconnect:
        logger.info("WebSocket 連線已斷開 | session=%s", session_id)

    except Exception as exc:
        logger.error(
            "WebSocket 處理發生未預期錯誤 | session=%s, error=%s",
            session_id,
            str(exc),
            exc_info=True,
        )
        try:
            await manager.send_to_session(
                session_id,
                {
                    "type": "error",
                    "payload": {
                        "code": "INTERNAL_ERROR",
                        "message": "伺服器內部錯誤，連線即將關閉",
                    },
                },
            )
        except Exception:
            pass

    finally:
        # ── 清理與狀態儲存 ──────────────────────────────
        await manager.disconnect_session(session_id)

        # 儲存對話歷史至 Redis
        if conversation_history:
            await _save_conversation_history(redis, session_id, conversation_history)

        # 關閉 STT 管線
        if stt_pipeline is not None:
            await stt_pipeline.close()

        logger.info(
            "WebSocket 連線清理完成 | session=%s, history_length=%d",
            session_id,
            len(conversation_history),
        )


# ── 音訊片段處理 ─────────────────────────────────────────
async def _handle_audio_chunk(
    *,
    session_id: str,
    payload: dict[str, Any],
    stt_pipeline: STTPipeline,
    llm_engine: LLMConversationEngine,
    tts_pipeline: TTSPipeline,
    red_flag_detector: RedFlagDetector,
    supervisor_engine: SupervisorEngine,
    system_prompt: str,
    conversation_history: list[dict[str, Any]],
    session_context: dict[str, Any],
    redis: Redis,
    db: AsyncSession,
) -> None:
    """
    處理音訊片段：解碼 base64 → STT 辨識 → LLM 回應 → TTS 合成

    Args:
        session_id: 場次 ID
        payload: 音訊片段 payload
        其他參數: 各管線與上下文
    """
    audio_b64 = payload.get("audio_data", "")
    if not audio_b64:
        return

    try:
        audio_bytes = base64.b64decode(audio_b64)
    except Exception as exc:
        logger.warning(
            "音訊 base64 解碼失敗 | session=%s, error=%s",
            session_id,
            str(exc),
        )
        await manager.send_to_session(
            session_id,
            {
                "type": "error",
                "payload": {
                    "code": "INVALID_AUDIO",
                    "message": "音訊資料格式無效",
                },
            },
        )
        return

    # 建立單一音訊片段的非同步產生器
    async def single_chunk_generator():
        yield audio_bytes

    # 執行 STT 串流辨識
    final_text = ""
    try:
        async for result in stt_pipeline.stream_recognize(single_chunk_generator()):
            if result["is_final"]:
                message_id = str(uuid.uuid4())
                final_text = result["text"]

                # 發送 STT 最終結果
                await manager.send_to_session(
                    session_id,
                    {
                        "type": "stt_final",
                        "payload": {
                            "messageId": message_id,
                            "text": result["text"],
                            "confidence": result["confidence"],
                            "isFinal": True,
                        },
                    },
                )
            else:
                # 發送 STT 中間結果
                await manager.send_to_session(
                    session_id,
                    {
                        "type": "stt_partial",
                        "payload": {
                            "text": result["text"],
                            "confidence": result["confidence"],
                            "isFinal": False,
                        },
                    },
                )

    except Exception as exc:
        logger.error(
            "STT 辨識失敗 | session=%s, error=%s",
            session_id,
            str(exc),
            exc_info=True,
        )
        await manager.send_to_session(
            session_id,
            {
                "type": "error",
                "payload": {
                    "code": "STT_ERROR",
                    "message": "語音辨識服務暫時不可用",
                },
            },
        )
        return

    # 若有最終辨識結果，進入 LLM 處理
    if final_text:
        await _handle_text_message(
            session_id=session_id,
            text=final_text,
            llm_engine=llm_engine,
            tts_pipeline=tts_pipeline,
            red_flag_detector=red_flag_detector,
            supervisor_engine=supervisor_engine,
            system_prompt=system_prompt,
            conversation_history=conversation_history,
            session_context=session_context,
            redis=redis,
            db=db,
        )


# ── 文字訊息處理 ─────────────────────────────────────────
async def _handle_text_message(
    *,
    session_id: str,
    text: str,
    llm_engine: LLMConversationEngine,
    tts_pipeline: TTSPipeline,
    red_flag_detector: RedFlagDetector,
    supervisor_engine: SupervisorEngine,
    system_prompt: str,
    conversation_history: list[dict[str, Any]],
    session_context: dict[str, Any],
    redis: Redis,
    db: AsyncSession,
) -> None:
    """
    處理文字訊息：加入歷史 → LLM 回應 → TTS → 紅旗偵測

    Args:
        session_id: 場次 ID
        text: 病患文字訊息
        其他參數: 各管線與上下文
    """
    # 加入對話歷史
    conversation_history.append(
        {
            "role": "patient",
            "content": text,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )

    # 儲存病患訊息至資料庫（持久化，不依賴 Redis TTL）
    patient_conv_id: uuid.UUID | None = None
    try:
        from app.services.conversation_service import ConversationService
        from uuid import UUID as _UUID
        _conv = await ConversationService.create(db, _UUID(session_id), "patient", text)
        await db.commit()
        patient_conv_id = _conv.id
    except Exception as _e:
        logger.warning("病患訊息儲存失敗 | session=%s, error=%s", session_id, str(_e))
        try:
            await db.rollback()
        except Exception:
            pass

    message_id = str(uuid.uuid4())

    # 從 Redis 取得 Supervisor 指導
    import json
    supervisor_guidance = None
    try:
        raw_guidance = await redis.get(f"gu:session:{session_id}:supervisor_guidance")
        if raw_guidance:
            supervisor_guidance = json.loads(raw_guidance)
    except Exception as exc:
        logger.warning("讀取 Supervisor 指導失敗 | session=%s, error=%s", session_id, str(exc))

    # 格式化訊息並呼叫 LLM
    messages = llm_engine.format_messages(conversation_history, system_prompt, supervisor_guidance)

    # 發送 AI 回應開始
    await manager.send_to_session(
        session_id,
        {
            "type": "ai_response_start",
            "payload": {"messageId": message_id},
        },
    )

    # 串流生成 AI 回應，同時並行偵測紅旗
    full_response = ""
    chunk_index = 0

    # 啟動紅旗偵測（背景執行）
    red_flag_task = asyncio.create_task(
        red_flag_detector.detect(text, session_context)
    )

    try:
        async for text_chunk in llm_engine.generate_response(
            messages, session_context
        ):
            full_response += text_chunk
            await manager.send_to_session(
                session_id,
                {
                    "type": "ai_response_chunk",
                    "payload": {
                        "messageId": message_id,
                        "text": text_chunk,
                        "chunkIndex": chunk_index,
                    },
                },
            )
            chunk_index += 1

    except Exception as exc:
        logger.error(
            "LLM 回應生成失敗 | session=%s, error=%s",
            session_id,
            str(exc),
        )
        await manager.send_to_session(
            session_id,
            {
                "type": "error",
                "payload": {
                    "code": "AI_SERVICE_UNAVAILABLE",
                    "message": "AI 回應生成失敗，請重試",
                },
            },
        )
        # 取消紅旗偵測任務
        red_flag_task.cancel()
        return

    # 加入 AI 回應到對話歷史
    conversation_history.append(
        {
            "role": "assistant",
            "content": full_response,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )

    # 儲存 AI 回應至資料庫
    try:
        from app.services.conversation_service import ConversationService
        from uuid import UUID as _UUID
        await ConversationService.create(db, _UUID(session_id), "assistant", full_response)
        await db.commit()
    except Exception as _e:
        logger.warning("AI 回應記錄儲存失敗 | session=%s, error=%s", session_id, str(_e))
        try:
            await db.rollback()
        except Exception:
            pass

    # 觸發 Supervisor 背景分析
    asyncio.create_task(
        supervisor_engine.analyze_next_step(
            session_id=session_id,
            conversation_history=conversation_history,
            chief_complaint=session_context.get("chief_complaint", ""),
            patient_info=session_context.get("patient_info", {}),
            redis=redis,
        )
    )

    # TTS 合成（背景執行，不阻塞回應結束通知）
    tts_url = ""
    try:
        tts_url = await tts_pipeline.synthesize_to_url(
            text=full_response,
            session_id=session_id,
            message_id=message_id,
        )
    except Exception as exc:
        logger.warning(
            "TTS 合成失敗，仍發送文字回應 | session=%s, error=%s",
            session_id,
            str(exc),
        )

    # 發送 AI 回應結束
    await manager.send_to_session(
        session_id,
        {
            "type": "ai_response_end",
            "payload": {
                "messageId": message_id,
                "fullText": full_response,
                "ttsAudioUrl": tts_url,
            },
        },
    )

    # 儲存對話歷史至 Redis
    await _save_conversation_history(redis, session_id, conversation_history)

    # 等待紅旗偵測結果
    try:
        red_flag_alerts = await red_flag_task
    except Exception as exc:
        logger.error(
            "紅旗偵測任務失敗 | session=%s, error=%s",
            session_id,
            str(exc),
        )
        red_flag_alerts = []

    # 處理紅旗警示
    if red_flag_alerts:
        for alert in red_flag_alerts:
            alert_id = str(uuid.uuid4())

            # 儲存紅旗警示至資料庫
            try:
                from app.services.alert_service import AlertService
                from app.models.enums import AlertSeverity, AlertType
                from uuid import UUID as _UUID
                _db_alert = await AlertService.create(db, {
                    "session_id": _UUID(session_id),
                    "conversation_id": patient_conv_id or uuid.uuid4(),
                    "alert_type": AlertType(alert.get("alert_type", "semantic")),
                    "severity": AlertSeverity(alert["severity"]),
                    "title": alert["title"],
                    "description": alert.get("description", ""),
                    "trigger_reason": alert.get("trigger_reason", ""),
                    "trigger_keywords": alert.get("trigger_keywords"),
                    "suggested_actions": alert.get("suggested_actions", []),
                    "matched_rule_id": _UUID(alert["matched_rule_id"]) if alert.get("matched_rule_id") else None,
                })
                await db.commit()
                alert_id = str(_db_alert.id)
            except Exception as _e:
                logger.warning("紅旗警示儲存失敗 | session=%s, error=%s", session_id, str(_e))
                try:
                    await db.rollback()
                except Exception:
                    pass

            # 發送紅旗警示給前端
            await manager.send_to_session(
                session_id,
                {
                    "type": "red_flag_alert",
                    "payload": {
                        "alertId": alert_id,
                        "severity": alert["severity"],
                        "title": alert["title"],
                        "description": alert["description"],
                        "suggestedActions": alert.get("suggested_actions", []),
                    },
                },
            )

            # 通知儀表板
            await manager.broadcast_dashboard(
                {
                    "type": "new_red_flag",
                    "payload": {
                        "alertId": alert_id,
                        "sessionId": session_id,
                        "patientName": session_context.get("patient_info", {}).get(
                            "name", "未知"
                        ),
                        "severity": alert["severity"],
                        "title": alert["title"],
                        "description": alert["description"],
                    },
                }
            )

        # 若有 critical 等級，中止場次並生成 SOAP 報告
        has_critical = any(
            a["severity"] == "critical" for a in red_flag_alerts
        )
        if has_critical:
            logger.warning(
                "偵測到 critical 紅旗，中止場次 | session=%s", session_id
            )
            await _update_session_status(
                db, redis, session_id, "aborted_red_flag", "in_progress"
            )
            await manager.send_to_session(
                session_id,
                {
                    "type": "session_status",
                    "payload": {
                        "sessionId": session_id,
                        "status": "aborted_red_flag",
                        "previousStatus": "in_progress",
                        "reason": "偵測到危急紅旗症狀，場次已中止，請立即就醫",
                    },
                },
            )
            await manager.broadcast_dashboard(
                {
                    "type": "session_status_changed",
                    "payload": {
                        "sessionId": session_id,
                        "status": "aborted_red_flag",
                        "previousStatus": "in_progress",
                        "reason": "偵測到 critical 紅旗症狀",
                    },
                }
            )
            # 觸發 SOAP 報告生成（紅旗中止場次同樣需要報告供醫師審閱）
            asyncio.create_task(
                _generate_soap_report_async(
                    session_id=session_id,
                    conversation_history=conversation_history,
                    session_context=session_context,
                    settings=settings,
                )
            )


# ── 輔助函式 ─────────────────────────────────────────────

async def _generate_soap_report_async(
    *,
    session_id: str,
    conversation_history: list[dict[str, Any]],
    session_context: dict[str, Any],
    settings: Settings,
) -> None:
    """
    在問診結束後非同步生成 SOAP 報告並存入資料庫
    （使用獨立 DB session，避免 WebSocket session 關閉後無法操作）
    """
    from datetime import datetime, timezone
    from uuid import UUID

    from app.core.database import get_db_session
    from app.models.enums import ReportStatus, ReviewStatus
    from app.models.soap_report import SOAPReport
    from app.pipelines.soap_generator import SOAPGenerator

    logger.info("開始生成 SOAP 報告 | session=%s", session_id)

    try:
        generator = SOAPGenerator(settings)
        soap_data = await generator.generate(
            transcript=conversation_history,
            patient_info=session_context.get("patient_info", {}),
            chief_complaint=session_context.get("chief_complaint", ""),
        )

        # 格式化對話逐字稿
        transcript_lines = []
        for entry in conversation_history:
            role = entry.get("role", "unknown")
            role_label = {"patient": "病患", "assistant": "AI 助手"}.get(role, role)
            content = entry.get("content", "")
            transcript_lines.append(f"{role_label}：{content}")
        raw_transcript = "\n".join(transcript_lines)

        # 建立 SOAPReport 記錄（使用獨立 session，不依賴 WebSocket 的 db）
        async with get_db_session() as db:
            report = SOAPReport(
                session_id=UUID(session_id),
                status=ReportStatus.GENERATED,
                review_status=ReviewStatus.PENDING,
                subjective=soap_data.get("subjective"),
                objective=soap_data.get("objective"),
                assessment=soap_data.get("assessment"),
                plan=soap_data.get("plan"),
                summary=soap_data.get("summary"),
                icd10_codes=soap_data.get("icd10_codes", []),
                ai_confidence_score=soap_data.get("confidence_score"),
                raw_transcript=raw_transcript,
                generated_at=datetime.now(timezone.utc),
            )
            db.add(report)
            # get_db_session() 會在 context 結束時自動 commit

        logger.info(
            "SOAP 報告生成完成並儲存 | session=%s, confidence=%.2f",
            session_id,
            soap_data.get("confidence_score", 0),
        )

    except Exception as exc:
        logger.error(
            "SOAP 報告生成失敗 | session=%s, error=%s",
            session_id,
            str(exc),
            exc_info=True,
        )

async def _validate_session(
    session_id: str, db: AsyncSession
) -> dict[str, Any] | None:
    """
    從資料庫驗證並載入場次資料（含病患完整資訊）

    Args:
        session_id: 場次 ID
        db: 資料庫 session

    Returns:
        場次資料字典，或 None（不存在時）
    """
    try:
        from app.models.patient import Patient
        from app.models.session import Session
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        stmt = (
            select(Session)
            .options(selectinload(Session.patient))
            .where(Session.id == session_id)
        )
        result = await db.execute(stmt)
        session_obj = result.scalar_one_or_none()

        if session_obj is None:
            return None

        # 組合病患資訊（含完整欄位）
        patient_info: dict[str, Any] = {}
        patient = getattr(session_obj, "patient", None)
        if patient is not None:
            # 計算年齡
            age = None
            if getattr(patient, "date_of_birth", None):
                from datetime import date
                today = date.today()
                dob = patient.date_of_birth
                age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))

            def format_jsonb_list(items: Any) -> str | None:
                if not items:
                    return None
                if isinstance(items, list):
                    parts = []
                    for item in items:
                        if isinstance(item, dict):
                            name = (
                                item.get("name")
                                or item.get("medication")
                                or item.get("condition")
                                or item.get("allergen")
                                or str(item)
                            )
                            parts.append(name)
                        else:
                            parts.append(str(item))
                    return "、".join(parts) if parts else None
                return str(items)

            def format_family_history(items: Any) -> str | None:
                if not items or not isinstance(items, list):
                    return None
                parts: list[str] = []
                for item in items:
                    if not isinstance(item, dict):
                        parts.append(str(item))
                        continue
                    relation = item.get("relation")
                    condition = item.get("condition")
                    if relation and condition:
                        parts.append(f"{relation}：{condition}")
                    elif condition:
                        parts.append(str(condition))
                return "、".join(parts) if parts else None

            intake = getattr(session_obj, "intake_data", None) or {}
            intake_summary = {
                "medical_history": (
                    "無"
                    if intake.get("no_past_medical_history")
                    else format_jsonb_list(intake.get("medical_history"))
                ),
                "medications": (
                    "無"
                    if intake.get("no_current_medications")
                    else format_jsonb_list(intake.get("current_medications"))
                ),
                "allergies": (
                    "無"
                    if intake.get("no_known_allergies")
                    else format_jsonb_list(intake.get("allergies"))
                ),
                "family_history": format_family_history(intake.get("family_history")),
            }

            patient_info = {
                "name": getattr(patient, "name", None),
                "age": age,
                "gender": getattr(patient, "gender", None),
                "medical_history": intake_summary["medical_history"]
                or format_jsonb_list(getattr(patient, "medical_history", None)),
                "medications": intake_summary["medications"]
                or format_jsonb_list(getattr(patient, "current_medications", None)),
                "allergies": intake_summary["allergies"]
                or format_jsonb_list(getattr(patient, "allergies", None)),
                "family_history": intake_summary["family_history"],
            }

        return {
            "id": str(session_obj.id),
            "status": session_obj.status,
            "chief_complaint": session_obj.chief_complaint_text or getattr(session_obj, "chief_complaint", ""),
            "patient_info": patient_info,
        }

    except Exception as exc:
        logger.error(
            "載入場次資料失敗 | session=%s, error=%s",
            session_id,
            str(exc),
            exc_info=True,
        )
        return None



async def _update_session_status(
    db: AsyncSession,
    redis: Redis,
    session_id: str,
    new_status: str,
    previous_status: str,
) -> None:
    """
    更新場次狀態（資料庫 + Redis 快取）

    Args:
        db: 資料庫 session
        redis: Redis 客戶端
        session_id: 場次 ID
        new_status: 新狀態
        previous_status: 前一狀態
    """
    try:
        from app.models.session import Session
        from sqlalchemy import update

        stmt = (
            update(Session)
            .where(Session.id == session_id)
            .values(status=new_status)
        )
        await db.execute(stmt)
        await db.commit()

        # 更新 Redis 快取
        state_key = _SESSION_STATE_KEY.format(session_id=session_id)
        await redis.hset(state_key, "status", new_status)
        await redis.expire(state_key, _SESSION_STATE_TTL)

        logger.info(
            "場次狀態已更新 | session=%s, %s → %s",
            session_id,
            previous_status,
            new_status,
        )

    except Exception as exc:
        logger.error(
            "更新場次狀態失敗 | session=%s, error=%s",
            session_id,
            str(exc),
            exc_info=True,
        )


async def _load_conversation_history(
    redis: Redis, session_id: str
) -> list[dict[str, Any]]:
    """
    從 Redis 載入對話歷史

    Args:
        redis: Redis 客戶端
        session_id: 場次 ID

    Returns:
        對話歷史列表
    """
    import json

    context_key = _SESSION_CONTEXT_KEY.format(session_id=session_id)
    try:
        raw = await redis.hget(context_key, "conversation_history")
        if raw:
            return json.loads(raw)
    except Exception as exc:
        logger.warning(
            "載入對話歷史失敗 | session=%s, error=%s",
            session_id,
            str(exc),
        )
    return []


async def _save_conversation_history(
    redis: Redis,
    session_id: str,
    history: list[dict[str, Any]],
) -> None:
    """
    將對話歷史儲存至 Redis

    Args:
        redis: Redis 客戶端
        session_id: 場次 ID
        history: 對話歷史列表
    """
    import json

    context_key = _SESSION_CONTEXT_KEY.format(session_id=session_id)
    try:
        await redis.hset(
            context_key,
            "conversation_history",
            json.dumps(history, ensure_ascii=False),
        )
        await redis.expire(context_key, _SESSION_CONTEXT_TTL)
    except Exception as exc:
        logger.warning(
            "儲存對話歷史失敗 | session=%s, error=%s",
            session_id,
            str(exc),
        )
