"""
語音對話 WebSocket 處理器

處理完整的語音問診流程：
Client audio_chunk → STT → LLM → TTS → Client
同時在每次病患訊息後並行執行紅旗偵測。
"""

import asyncio
import base64
import hashlib
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import RateLimitExceededException
from app.core.rate_limit import enforce_llm_per_user_rate_limit
from app.pipelines.llm_conversation import LLMConversationEngine
from app.pipelines.red_flag_detector import RedFlagDetector
from app.pipelines.stt_pipeline import STTPipeline, to_whisper_language
from app.pipelines.tts_pipeline import TTSPipeline
from app.pipelines.supervisor import SupervisorEngine
from app.websocket.auth import authenticate_websocket
from app.websocket.connection_manager import manager

logger = logging.getLogger(__name__)

# ── Redis key 常數 ───────────────────────────────────────
_SESSION_CONTEXT_KEY = "gu:session:{session_id}:context"
_SESSION_STATE_KEY = "gu:session:{session_id}:state"
_SESSION_CONTEXT_TTL = 3600  # 1 小時
_SESSION_STATE_TTL = 1800  # 30 分鐘
_SESSION_SUPERVISOR_KEY = "gu:session:{session_id}:supervisor_guidance"

# 句子邊界（中文句號、驚嘆號、問號、換行）— 用於串流時的增量切句
_SENTENCE_BOUNDARY_CHARS = "。！？\n"


# ── Audio magic-byte signatures（DoS hardening） ─────────
# WebM/Matroska: 0x1A 0x45 0xDF 0xA3
# WAV: "RIFF" + 4 bytes size + "WAVE"
# Ogg: "OggS"
# MP3: "ID3" or 0xFF 0xFB / 0xFF 0xF3 / 0xFF 0xF2
# MP4/M4A: [4-byte box size] + "ftyp" — Chrome 113+/Safari 下 MediaRecorder
#          會輸出 audio/mp4，前端已將其列為首選 MIME；backend 若不認 ftyp
#          會把整段丟棄（errors.ws.invalid_audio_format）。Whisper 本身支援 m4a。
_AUDIO_MAGIC_WEBM = b"\x1a\x45\xdf\xa3"
_AUDIO_MAGIC_OGG = b"OggS"
_AUDIO_MAGIC_WAV = b"RIFF"
_AUDIO_MAGIC_ID3 = b"ID3"
_AUDIO_MAGIC_MP4 = b"ftyp"


def _has_valid_audio_magic(buf: bytes) -> bool:
    """檢查音訊容器的 magic bytes（前 16 bytes 即可）。"""
    if not buf or len(buf) < 4:
        return False
    head = buf[:16]
    if head.startswith(_AUDIO_MAGIC_WEBM):
        return True
    if head.startswith(_AUDIO_MAGIC_OGG):
        return True
    if head.startswith(_AUDIO_MAGIC_WAV):
        return True
    if head.startswith(_AUDIO_MAGIC_ID3):
        return True
    # MP3 frame sync: 0xFF followed by 0xFB/0xF3/0xF2/0xFA/0xF1 etc.
    if head[0] == 0xFF and (head[1] & 0xE0) == 0xE0:
        return True
    # MP4/M4A：ISO base media file format — 第一個 box 的 type 位於 bytes[4:8]，
    # 值為 "ftyp"（後續 brand 可能是 isom/mp42/M4A /dash 等）。
    if len(head) >= 8 and head[4:8] == _AUDIO_MAGIC_MP4:
        return True
    return False


def _history_checksum(history: list[dict[str, Any]]) -> str:
    """計算 conversation_history 的 sha256 checksum（穩定序列化）。"""
    try:
        # 僅雜湊 role + content（忽略 timestamp）以利跨來源比對
        payload = [
            {"role": e.get("role", ""), "content": e.get("content", "")}
            for e in history
        ]
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    except Exception:
        raw = str(history)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def _summarize_history_segment(
    settings: Settings,
    segment: list[dict[str, Any]],
) -> str | None:
    """
    使用便宜模型（gpt-4o-mini）摘要一段對話，回傳摘要文字。
    失敗回傳 None，呼叫端可選擇硬丟棄。
    """
    if not segment:
        return None
    try:
        lines: list[str] = []
        for entry in segment:
            role = entry.get("role", "")
            role_label = {"patient": "病患", "user": "病患", "assistant": "AI", "ai": "AI"}.get(role, role)
            content = entry.get("content", "")
            if content:
                lines.append(f"{role_label}：{content}")
        transcript = "\n".join(lines)
        if not transcript.strip():
            return None

        from app.core.openai_client import get_openai_client
        client = get_openai_client()
        model = getattr(settings, "OPENAI_MODEL_SUMMARIZER", "gpt-4o-mini")
        resp = await asyncio.wait_for(
            client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "你是一位泌尿科問診摘要助手。請將下列病患與 AI 的對話"
                            "以繁體中文、不超過 200 字，摘要為重點的 HPI 進度（已問過什麼、"
                            "已收集哪些症狀細節、尚未釐清的部分）。僅輸出摘要文字本身。"
                        ),
                    },
                    {"role": "user", "content": transcript},
                ],
                temperature=0.2,
                max_tokens=400,
            ),
            timeout=15.0,
        )
        content = (resp.choices[0].message.content or "").strip()
        return content or None
    except Exception as exc:
        logger.warning(
            "對話歷史摘要失敗，將保留原始舊輪次以免遺失臨床脈絡 | error=%s",
            str(exc),
        )
        return None


async def _cap_conversation_history(
    history: list[dict[str, Any]],
    settings: Settings,
) -> None:
    """
    若 conversation_history 超過上限（預設 50 輪 = 100 entries），
    將最舊的一半超額部分摘要為單一 system 訊息，其餘保留。
    就地修改 history。摘要失敗時保留原始舊輪次（不靜默丟棄），以免遺失紅旗臨床脈絡。
    """
    max_turns = getattr(settings, "CONVERSATION_HISTORY_MAX_TURNS", 50)
    # 一輪 = patient + assistant → 2 筆，list 長度上限 = max_turns * 2
    max_entries = max_turns * 2
    if len(history) <= max_entries:
        return

    # 僅保留最新 max_entries 筆；其餘送摘要
    over = len(history) - max_entries
    # 取最舊的一半超額 → 但規格要求「最舊半」；此處改為：全部超額都替換為一則摘要，
    # 保留最新 max_entries 筆；同時若已有先前的摘要 system 訊息，合併之。
    old_segment: list[dict[str, Any]] = history[:over]
    recent: list[dict[str, Any]] = history[over:]

    summary_text: str | None = await _summarize_history_segment(settings, old_segment)

    # 合併既有摘要（若最前面已經是 [前段對話摘要] system 訊息）
    existing_summary = ""
    if recent and recent[0].get("role") == "system":
        first_content = recent[0].get("content", "")
        if isinstance(first_content, str) and first_content.startswith("[前段對話摘要]"):
            existing_summary = first_content
            recent = recent[1:]

    history.clear()
    if summary_text:
        merged = summary_text
        if existing_summary:
            merged = existing_summary + "\n" + summary_text
        else:
            merged = f"[前段對話摘要] {summary_text}"
        history.append(
            {
                "role": "system",
                "content": merged,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
    elif existing_summary:
        # 摘要失敗但保留舊摘要
        history.append(
            {
                "role": "system",
                "content": existing_summary,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
    else:
        # 摘要失敗且沒有既有摘要：不可靜默丟棄舊輪次，否則可能遺失紅旗臨床脈絡。
        # 改為保留原始舊輪次（接受 token 成本），並注入 system 標記提示脈絡未壓縮。
        # log 在 _summarize_history_segment 內已記錄；此處再以 ERROR 強調未壓縮的後果。
        logger.error(
            "對話歷史摘要失敗且無既有摘要，保留原始舊輪次以免遺失臨床脈絡 | "
            "dropped_avoided=%d",
            len(old_segment),
        )
        history.append(
            {
                "role": "system",
                "content": "[前段對話摘要] 摘要暫時無法產生，以下保留原始較舊對話內容以維持臨床脈絡完整。",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
        history.extend(old_segment)
    # 若摘要失敗且沒有既有摘要：保留舊輪次（見上方 else 分支），不再硬丟棄
    history.extend(recent)


def _split_completed_sentences(buffer: str) -> tuple[list[str], str]:
    """
    將緩衝字串依句子邊界切分為 (已完成句子列表, 殘餘未完句)。

    規則：遇到 [。！？\n] 任一字元即視為一個句子結束；結束字元保留在句子尾端
    （換行會被 strip 掉以避免純空白句）。殘餘字串為尚未遇到邊界的尾段。
    """
    completed: list[str] = []
    start = 0
    for i, ch in enumerate(buffer):
        if ch in _SENTENCE_BOUNDARY_CHARS:
            sentence = buffer[start : i + 1].strip()
            if sentence:
                completed.append(sentence)
            start = i + 1
    remainder = buffer[start:]
    return completed, remainder


def _coerce_hpi_pct(value: Any) -> float | None:
    """把 Supervisor 的 hpi_completion_percentage 強制轉成數值。

    LLM 走 json_object 時偶爾把百分比輸出成字串（"85"）；不轉型會讓軟門檻永遠不
    觸發、只剩硬上限收尾，等於默默廢掉自動結束的核心。bool 是 int 子類，需排除。
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except (ValueError, AttributeError):
            return None
    return None


def _should_auto_conclude(
    supervisor_guidance: Any,
    patient_turns: int,
    settings: Settings,
) -> bool:
    """是否該自動結束問診（純函式，便於單元測試）。

    兩條獨立路徑、皆受 ENABLED 總開關控制：
      - 軟門檻：Supervisor HPI 完整度 >= THRESHOLD 且病患回合 >= MIN（且該指導非
        fallback 佔位 — 降級時 hpi 不可信）。
      - 硬上限：病患回合 >= HARD_CAP，不依賴 Supervisor（降級時的保命線）。
    紅旗/drain/compare-and-set 等 turn-state 守衛留在呼叫端，不在此函式。
    """
    if not getattr(settings, "HPI_COMPLETION_TERMINATION_ENABLED", True):
        return False
    hpi_pct: float | None = None
    if isinstance(supervisor_guidance, dict) and not supervisor_guidance.get("fallback"):
        hpi_pct = _coerce_hpi_pct(supervisor_guidance.get("hpi_completion_percentage"))
    soft_ready = (
        hpi_pct is not None
        and hpi_pct >= getattr(settings, "HPI_COMPLETION_TERMINATION_THRESHOLD", 80)
        and patient_turns >= getattr(settings, "MIN_PATIENT_TURNS_BEFORE_AUTO_END", 5)
    )
    hard_ready = patient_turns >= getattr(settings, "MAX_PATIENT_TURNS_HARD_CAP", 10)
    return bool(soft_ready or hard_ready)


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
    idle_watchdog_task: asyncio.Task[None] | None = None
    # 使用 list 包裝以利內層 closure 就地更新（asyncio 不需要 Lock）
    last_activity_ref: list[float] = [time.monotonic()]

    try:
        # ── 步驟 1：認證（handshake message 或 legacy ?token=） ──
        payload = await authenticate_websocket(
            websocket,
            context=f"conversation-ws session={session_id}",
        )
        if payload is None:
            return  # authenticate_websocket 已 close
        user_id = payload.get("sub")

        # ── 步驟 2：驗證場次狀態 ────────────────────────
        session_data = await _validate_session(session_id, db)
        if session_data is None:
            await websocket.close(code=4004, reason="errors.ws.session_not_found")
            return

        session_status = session_data.get("status")
        if session_status not in ("waiting", "in_progress"):
            # close frame reason 必須 < 123 bytes；送 canonical code 讓前端 i18n 渲染
            await websocket.close(
                code=4009,
                reason="errors.ws.session_wrong_status",
            )
            return

        # ── 步驟 3：建立連線（authenticate_websocket 已 accept） ──
        await manager.connect_session(websocket, session_id, already_accepted=True)

        # 立即發送 connection_ack（在任何 I/O 初始化之前）
        await manager.send_to_session(
            session_id,
            {
                "type": "connection_ack",
                "payload": {
                    "sessionId": session_id,
                    "status": "connected",
                    "config": {
                        "audioFormat": "webm",
                        "sampleRate": 16000,
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
            # #6：場次語言的主訴顯示名稱（給開場問診語；LLM/SOAP 仍用原 chief_complaint 全文）。
            "chief_complaint_display": session_data.get("chief_complaint_display"),
            "patient_info": session_data.get("patient_info", {}),
            "language": session_data.get("language"),
        }

        # 建構系統提示詞
        # 需把 session.language 傳進去,否則 LLM 會永遠回繁體中文
        # （即使 STT 判對語言、病患用英文講，回覆仍是中文 → M18 回報）。
        system_prompt = llm_engine.build_system_prompt(
            chief_complaint=session_context["chief_complaint"],
            patient_info=session_context["patient_info"],
            language=session_context.get("language"),
        )

        # 更新場次狀態為進行中
        await _update_session_status(
            db, redis, session_id, "in_progress", session_status
        )

        # 通知儀表板
        await manager.broadcast_localized_dashboard(
            msg_type="session_status_changed",
            code="events.session.ws_connected",
            params={},
            severity="info",
            extra={
                "sessionId": session_id,
                "status": "in_progress",
                "previousStatus": session_status,
            },
        )
        # H-8：場次狀態變更會改變排隊 / 統計數字，順帶推播 queue_updated +
        # stats_updated（非致命，內部已 swallow 例外）。
        await _broadcast_dashboard_queue_and_stats(db, redis)

        logger.info(
            "問診 WebSocket 已就緒 | session=%s, user=%s",
            session_id,
            user_id,
        )

        # ── 步驟 3.5：處理 resume / 初始開場白 ────
        # Fix 23: 若前端帶 resumeFrom=<checksum>，且與伺服器端 history 吻合，
        # 則跳過開場白（沿用既有對話）；不符則拒絕 resume，走全新開場流程。
        resume_from = websocket.query_params.get("resumeFrom")
        if resume_from:
            server_checksum = _history_checksum(conversation_history)
            if conversation_history and server_checksum == resume_from:
                logger.info(
                    "場次 resume 成功 | session=%s, history_len=%d",
                    session_id,
                    len(conversation_history),
                )
                await manager.send_localized_to_session(
                    session_id,
                    msg_type="session_status",
                    code="events.session.resumed",
                    params={},
                    severity="info",
                )
            else:
                logger.warning(
                    "場次 resume 失敗（checksum 不符或無歷史）| session=%s",
                    session_id,
                )
                await manager.send_localized_to_session(
                    session_id,
                    msg_type="resume_failed",
                    code="events.session.resume_failed",
                    params={"reason": "checksum_mismatch_or_empty"},
                    severity="warning",
                )
                # Fallback: 視為全新場次
                if not conversation_history:
                    await _send_initial_greeting(
                        session_id=session_id,
                        llm_engine=llm_engine,
                        tts_pipeline=tts_pipeline,
                        system_prompt=system_prompt,
                        conversation_history=conversation_history,
                        session_context=session_context,
                        redis=redis,
                        db=db,
                    )
        elif not conversation_history:
            await _send_initial_greeting(
                session_id=session_id,
                llm_engine=llm_engine,
                tts_pipeline=tts_pipeline,
                system_prompt=system_prompt,
                conversation_history=conversation_history,
                session_context=session_context,
                redis=redis,
                db=db,
            )

        # ── 步驟 4：主訊息迴圈 ─────────────────────────
        is_paused = False
        # 音訊緩衝區：累積片段直到 isFinal=true 才呼叫 Whisper
        audio_buffer: list[bytes] = []
        # 累積的總 byte 數（用於 10 分鐘上限判斷）
        audio_buffer_total_bytes: list[int] = [0]

        # ── 啟動閒置逾時看門狗 ─────────────────────────
        last_activity_ref[0] = time.monotonic()
        idle_timeout_seconds = getattr(settings, "SESSION_IDLE_TIMEOUT_SECONDS", 600)
        idle_check_interval = getattr(
            settings, "SESSION_IDLE_CHECK_INTERVAL_SECONDS", 30
        )

        async def _idle_watchdog() -> None:
            try:
                while True:
                    await asyncio.sleep(idle_check_interval)
                    idle_for = time.monotonic() - last_activity_ref[0]
                    if idle_for >= idle_timeout_seconds:
                        logger.warning(
                            "場次閒置逾時，準備關閉連線 | session=%s, idle_for=%.1fs",
                            session_id,
                            idle_for,
                        )
                        try:
                            await manager.send_localized_to_session(
                                session_id,
                                msg_type="session_status",
                                code="events.session.idle_timeout",
                                params={
                                    "minutes": int(idle_timeout_seconds // 60),
                                },
                                severity="warning",
                            )
                        except Exception:
                            pass
                        try:
                            await _update_session_status(
                                db, redis, session_id, "completed", "in_progress"
                            )
                        except Exception:
                            pass
                        try:
                            await websocket.close(code=4000, reason="idle_timeout")
                        except Exception:
                            pass
                        return
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.warning(
                    "閒置看門狗錯誤 | session=%s, error=%s", session_id, str(exc)
                )

        idle_watchdog_task = asyncio.create_task(_idle_watchdog())

        while True:
            raw_message = await websocket.receive_json()
            msg_type = raw_message.get("type", "")
            msg_payload = raw_message.get("payload", {})

            # 任何有意義的訊息都算活動（ping 也算，避免中間逾時）
            last_activity_ref[0] = time.monotonic()

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
                    await manager.send_localized_to_session(
                        session_id,
                        msg_type="session_status",
                        code="events.session.ended_by_user",
                        params={},
                        severity="info",
                    )
                    await manager.broadcast_localized_dashboard(
                        msg_type="session_status_changed",
                        code="events.session.completed_normal",
                        params={},
                        severity="info",
                        extra={
                            "sessionId": session_id,
                            "status": "completed",
                            "previousStatus": "in_progress",
                        },
                    )
                    # H-8：完成場次後排隊 / 統計數字改變，順帶推播 queue/stats。
                    await _broadcast_dashboard_queue_and_stats(db, redis)
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
                ended = await _handle_audio_chunk(
                    session_id=session_id,
                    payload=msg_payload,
                    audio_buffer=audio_buffer,
                    audio_buffer_total_bytes=audio_buffer_total_bytes,
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
                    settings=settings,
                )
                # 本輪 HPI 達標 / 回合達上限 → 場次已自動結束，結束主迴圈走 finally 清理
                # （取消閒置看門狗、斷線、存歷史），與 end_session 控制指令同路徑。
                if ended:
                    break
                continue

            # ── 文字訊息（打字輸入備援，語音收不到時用）──────────────
            # 不走 STT，直接進 _handle_text_message：紅旗篩檢 / LLM / TTS / auto-conclude
            # 與語音同一條路徑，醫療安全一致。每則文字一樣計一次 LLM 配額。
            if msg_type == "text_message":
                text_in = (msg_payload.get("text") or "").strip()
                if not text_in:
                    continue
                # 長度上限，防濫用（與前端 maxLength=2000 對齊；後端為權威）
                if len(text_in) > 2000:
                    text_in = text_in[:2000]
                try:
                    await enforce_llm_per_user_rate_limit(
                        redis, session_context.get("user_id")
                    )
                except RateLimitExceededException as rle:
                    logger.warning(
                        "LLM rate limit 擋住一則文字訊息 | session=%s user=%s",
                        session_id,
                        session_context.get("user_id"),
                    )
                    await manager.send_localized_to_session(
                        session_id,
                        msg_type="error",
                        code="errors.ws.rate_limit_exceeded",
                        params={"retryAfter": (rle.details or {}).get("retry_after")},
                        severity="warning",
                    )
                    continue
                ended = await _handle_text_message(
                    session_id=session_id,
                    text=text_in,
                    llm_engine=llm_engine,
                    tts_pipeline=tts_pipeline,
                    red_flag_detector=red_flag_detector,
                    supervisor_engine=supervisor_engine,
                    system_prompt=system_prompt,
                    conversation_history=conversation_history,
                    session_context=session_context,
                    redis=redis,
                    db=db,
                    settings=settings,
                )
                if ended:
                    break
                continue

            # ── 未知訊息類型 ───────────────────────────
            logger.warning(
                "收到未知訊息類型 | session=%s, type=%s",
                session_id,
                msg_type,
            )
            await manager.send_localized_to_session(
                session_id,
                msg_type="error",
                code="errors.ws.unknown_message_type",
                params={"type": msg_type},
                severity="warning",
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
            await manager.send_localized_to_session(
                session_id,
                msg_type="error",
                code="errors.ws.internal_error",
                params={},
                severity="critical",
            )
        except Exception:
            pass

    finally:
        # ── 清理與狀態儲存 ──────────────────────────────
        # 停止閒置看門狗
        if idle_watchdog_task is not None and not idle_watchdog_task.done():
            idle_watchdog_task.cancel()
            try:
                await idle_watchdog_task
            except (asyncio.CancelledError, Exception):
                pass

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


# ── 初始開場問診語 ───────────────────────────────────────
async def _send_initial_greeting(
    *,
    session_id: str,
    llm_engine: LLMConversationEngine,
    tts_pipeline: TTSPipeline,
    system_prompt: str,
    conversation_history: list[dict[str, Any]],
    session_context: dict[str, Any],
    redis: Redis,
    db: AsyncSession,
) -> None:
    """
    全新場次時，主動讓 AI 發出第一句問診語，引導病患開口。
    """
    message_id = str(uuid.uuid4())

    # 立即使用固定模板問診語，避免等待 LLM
    # #6：開場語優先用「場次語言」的主訴顯示名稱（英文場次顯示 Hematuria 而非「血尿」）；
    # 解析不到才退回原 chief_complaint（病患原輸入，含多選/自訂備註）。
    chief_complaint = (
        session_context.get("chief_complaint_display")
        or session_context.get("chief_complaint", "")
    )
    from app.utils.i18n_messages import get_message as _i18n_get
    full_greeting = _i18n_get(
        "ws.initial_greeting",
        session_context.get("language"),
        chief_complaint=chief_complaint,
    )

    # 告知前端 AI 開始回應 → 顯示 thinking dots，遮住 TTS 合成的等待時間
    await manager.send_to_session(
        session_id,
        {"type": "ai_response_start", "payload": {"messageId": message_id}},
    )

    # 初始問診語為短模板，直接逐句切分後以 ai_response_chunk 同時送出 text + audio
    sentences_init, _remain_init = _split_completed_sentences(full_greeting)
    if _remain_init.strip():
        sentences_init.append(_remain_init.strip())
    if not sentences_init:
        sentences_init = [full_greeting]

    for idx, sentence in enumerate(sentences_init):
        audio_b64: str | None = ""
        tts_failed = False
        try:
            audio_bytes = await tts_pipeline.synthesize(
                text=sentence,
                language=session_context.get("language"),
            )
            if audio_bytes:
                audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
        except Exception as exc:
            tts_failed = True
            audio_b64 = None
            logger.warning(
                "初始問診語 TTS 合成失敗 | session=%s, idx=%d, error=%s",
                session_id,
                idx,
                str(exc),
            )
        await manager.send_to_session(
            session_id,
            {
                "type": "ai_response_chunk",
                "payload": {
                    "messageId": message_id,
                    "text": sentence,
                    "chunkIndex": idx,
                    "audioB64": audio_b64,
                    "ttsFailed": tts_failed,
                },
            },
        )

    # 加入 AI 回應到歷史
    if full_greeting:
        conversation_history.append(
            {
                "role": "assistant",
                "content": full_greeting,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
        # 儲存至 DB
        try:
            from app.services.conversation_service import ConversationService
            from uuid import UUID as _UUID
            await ConversationService.create(db, _UUID(session_id), "assistant", full_greeting)
            await db.commit()
        except Exception as _e:
            logger.warning("初始問診語儲存失敗 | session=%s, error=%s", session_id, str(_e))
            try:
                await db.rollback()
            except Exception:
                pass

    await manager.send_to_session(
        session_id,
        {
            "type": "ai_response_end",
            "payload": {"messageId": message_id, "fullText": full_greeting, "ttsAudioUrl": ""},
        },
    )

    await _save_conversation_history(redis, session_id, conversation_history)
    logger.info("初始問診語發送完成 | session=%s", session_id)


# ── 音訊片段處理 ─────────────────────────────────────────
async def _handle_audio_chunk(
    *,
    session_id: str,
    payload: dict[str, Any],
    audio_buffer: list[bytes],
    audio_buffer_total_bytes: list[int],
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
    settings: Settings,
) -> bool:
    """
    處理音訊片段：累積 base64 chunks → 收到 isFinal=true 時呼叫 Whisper → LLM → TTS

    前端每 250ms 發送一個 audio_chunk（isFinal=false），
    停止錄音時發送一個空的 audio_chunk（isFinal=true）作為結束標記。
    所有片段累積完成後統一送 Whisper 轉錄，避免切碎音訊。
    """
    audio_b64: str = payload.get("audioData", "")
    is_final: bool = payload.get("isFinal", False)

    # 估計時長的 byte 上限：16kHz mono 16-bit PCM 約 32000 B/s，
    # 但實際為壓縮容器（WebM/Opus）約 4-6 KB/s。保守採用 PCM 上限以免誤殺。
    sample_rate = getattr(settings, "AUDIO_SAMPLE_RATE_HZ", 16000)
    max_seconds = getattr(settings, "AUDIO_MAX_DURATION_SECONDS", 600)
    # PCM16 mono: sample_rate * 2 bytes/sec
    max_total_bytes = sample_rate * 2 * max_seconds

    # 非空片段：解碼並加入緩衝區
    if audio_b64:
        try:
            chunk_bytes = base64.b64decode(audio_b64)
            audio_buffer.append(chunk_bytes)
            audio_buffer_total_bytes[0] += len(chunk_bytes)
        except Exception as exc:
            logger.warning(
                "音訊 base64 解碼失敗 | session=%s, error=%s",
                session_id,
                str(exc),
            )
            await manager.send_localized_to_session(
                session_id,
                msg_type="error",
                code="errors.ws.invalid_audio",
                params={},
                severity="error",
            )
            return False

        # 時長 / 大小上限檢查（DoS hardening）
        if audio_buffer_total_bytes[0] > max_total_bytes:
            logger.warning(
                "音訊累積超過上限，強制結束該段 | session=%s, total=%d bytes",
                session_id,
                audio_buffer_total_bytes[0],
            )
            audio_buffer.clear()
            audio_buffer_total_bytes[0] = 0
            await manager.send_localized_to_session(
                session_id,
                msg_type="error",
                code="errors.ws.audio_too_long",
                params={"maxSeconds": int(max_seconds)},
                severity="warning",
            )
            return False

    # 尚未收到結束標記，繼續等待
    if not is_final:
        return False

    # 收到 isFinal=true：準備轉錄
    if not audio_buffer:
        logger.debug("音訊緩衝區為空，略過 STT | session=%s", session_id)
        audio_buffer_total_bytes[0] = 0
        return False

    # 合併所有片段
    complete_audio = b"".join(audio_buffer)
    audio_buffer.clear()
    audio_buffer_total_bytes[0] = 0

    # Magic byte 驗證（拒絕非法/偽造容器）
    if not _has_valid_audio_magic(complete_audio):
        logger.warning(
            "音訊 magic bytes 驗證失敗 | session=%s, head=%s",
            session_id,
            complete_audio[:16].hex() if complete_audio else "",
        )
        await manager.send_localized_to_session(
            session_id,
            msg_type="error",
            code="errors.ws.invalid_audio_format",
            params={},
            severity="error",
        )
        return False

    # ── LLM per-user rate limit（P2 #14）──────────────────
    # 到這裡代表「一輪對話」即將啟動（STT → LLM → TTS）。每輪算一次配額。
    # 超過 20/min 直接回 RATE_LIMIT WS error、不呼叫任何 OpenAI API。
    try:
        await enforce_llm_per_user_rate_limit(redis, session_context.get("user_id"))
    except RateLimitExceededException as rle:
        logger.warning(
            "LLM rate limit 擋住一輪對話 | session=%s user=%s retry_after=%s",
            session_id,
            session_context.get("user_id"),
            (rle.details or {}).get("retry_after"),
        )
        await manager.send_localized_to_session(
            session_id,
            msg_type="error",
            code="errors.ws.rate_limit_exceeded",
            params={
                "retryAfter": (rle.details or {}).get("retry_after"),
            },
            severity="warning",
        )
        return False

    logger.info(
        "開始 STT 轉錄 | session=%s, total_bytes=%d",
        session_id,
        len(complete_audio),
    )

    # 呼叫 OpenAI Whisper 轉錄
    # 場次語言在 MedicalInfoPage 建 session 時用 i18n.resolvedLanguage 寫入
    # （BCP-47：zh-TW / en-US / ja-JP / ko-KR / vi-VN）。Whisper 只吃 ISO-639-1,
    # 不轉會讓它退回 STTPipeline._language（預設 "zh"）導致英文被強制轉中文。
    whisper_lang = to_whisper_language(session_context.get("language"))
    final_text = ""
    try:
        result = await stt_pipeline.transcribe(complete_audio, language=whisper_lang)
        final_text = result["text"]
        message_id = str(uuid.uuid4())

        await manager.send_to_session(
            session_id,
            {
                "type": "stt_final",
                "payload": {
                    "messageId": message_id,
                    "text": final_text,
                    "confidence": result["confidence"],
                    "isFinal": True,
                },
            },
        )

    except Exception as exc:
        logger.error(
            "STT 轉錄失敗 | session=%s, error=%s",
            session_id,
            str(exc),
            exc_info=True,
        )
        await manager.send_localized_to_session(
            session_id,
            msg_type="error",
            code="errors.ws.stt_error",
            params={},
            severity="error",
        )
        return False

    # 若有最終辨識結果，進入 LLM 處理；回傳是否本輪後場次已自動結束。
    if final_text:
        return await _handle_text_message(
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
            settings=settings,
        )

    return False


# ── Supervisor 指導 WS 推播（CONV-2 / CONV-3） ───────────
async def _emit_supervisor_guidance(
    session_id: str,
    guidance: dict[str, Any] | None,
) -> None:
    """
    CONV-2：將本輪可用的 Supervisor 指導以專屬事件推播給病患場次。

    只送結構化的 canonical 欄位（next_focus / missing_hpi / hpi_completion_percentage），
    前端依 code/params 與 missing_hpi id 自行 i18n 渲染。指導不存在或僅為 fallback
    佔位時不送（degradation 由 _emit_supervisor_degraded 另行通知）。
    本函式不可拋例外，避免阻塞主 turn 流程。
    """
    if not isinstance(guidance, dict):
        return
    # fallback 佔位指導（Supervisor 逾時時寫入）不視為可用指導，跳過。
    if guidance.get("fallback"):
        return
    next_focus = guidance.get("next_focus")
    missing_hpi = guidance.get("missing_hpi")
    hpi_completion = guidance.get("hpi_completion_percentage")
    # 完全沒有任何可呈現內容就不送（不阻塞、不雜訊）。
    if not next_focus and not missing_hpi and hpi_completion is None:
        return
    try:
        await manager.send_to_session(
            session_id,
            {
                "type": "supervisor_guidance",
                "payload": {
                    "nextFocus": next_focus or "",
                    "missingHpi": missing_hpi or [],
                    "hpiCompletionPercentage": hpi_completion,
                },
            },
        )
    except Exception as exc:
        logger.warning(
            "Supervisor 指導事件推播失敗（非致命） | session=%s, error=%s",
            session_id,
            str(exc),
        )


async def _emit_supervisor_degraded(session_id: str) -> None:
    """
    CONV-3：Supervisor 分析逾時 / 退回 fallback 時，送出低嚴重度警示事件，
    讓降級狀態可被前端觀察，而非靜默。canonical code 由前端 i18n 渲染。
    本函式不可拋例外。
    """
    try:
        await manager.send_localized_to_session(
            session_id,
            msg_type="supervisor_degraded",
            code="events.supervisor.degraded",
            params={},
            severity="warning",
        )
    except Exception as exc:
        logger.warning(
            "Supervisor 降級事件推播失敗（非致命） | session=%s, error=%s",
            session_id,
            str(exc),
        )


# ── 儀表板 queue/stats 順帶推播（H-8） ───────────────────
async def _broadcast_dashboard_queue_and_stats(
    db: AsyncSession,
    redis: Redis,
) -> None:
    """場次狀態變更後，順帶向儀表板推播最新 queue_updated + stats_updated。

    委派給 dashboard_handler.broadcast_queue_and_stats（lazy import 避免任何
    匯入順序問題）。本函式不可拋例外，避免阻塞對話主流程。
    """
    try:
        from app.websocket.dashboard_handler import broadcast_queue_and_stats

        await broadcast_queue_and_stats(db, redis)
    except Exception as exc:
        logger.warning(
            "順帶推播儀表板 queue/stats 失敗（非致命） | error=%s", str(exc)
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
    settings: Settings,
) -> bool:
    """
    處理文字訊息：加入歷史 → LLM 回應 → TTS → 紅旗偵測

    Returns:
        bool: True 表示本輪後場次已自動結束（呼叫端應結束主迴圈）；否則 False。

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

    # ── 是否本輪收尾（自動結束問診，避免無止盡發問）──────────────
    # 用「上一輪」Supervisor 寫進 Redis 的 hpi_completion_percentage（同步讀取、
    # 不和本輪 fire-and-forget 的 Supervisor 任務競態）。本輪剛收到的病患輸入仍會
    # 完整跑完 LLM 與紅旗偵測後，才在函式尾端真正結束（見尾端結束區塊）。
    #   - 軟門檻：HPI 完整度達標 + 已問滿最低題數（且該指導非 fallback 佔位）。
    #   - 硬上限：病患回合數達上限即收尾，不依賴 Supervisor（降級時的保命線）。
    # patient_turns 此時已含剛 append 的本輪病患訊息；硬上限(15) 遠小於歷史摘要門檻
    # (CONVERSATION_HISTORY_MAX_TURNS=50)，故由 conversation_history 計數準確。
    patient_turns = sum(
        1 for e in conversation_history if e.get("role") in ("patient", "user")
    )
    should_conclude = _should_auto_conclude(supervisor_guidance, patient_turns, settings)

    # 格式化訊息並呼叫 LLM
    messages = llm_engine.format_messages(
        conversation_history,
        system_prompt,
        supervisor_guidance,
        language=session_context.get("language"),
        conclude=should_conclude,
    )

    # 發送 AI 回應開始
    await manager.send_to_session(
        session_id,
        {
            "type": "ai_response_start",
            "payload": {"messageId": message_id},
        },
    )

    # 句級串流：LLM 一邊產生，一邊切出完整句子並預先啟動 TTS 合成。
    # TTS 結果仍需等紅旗偵測 gate 通過後才依序發送，以保留 critical 警示優先順序。
    full_response = ""
    sentence_buffer = ""
    # 已切出的句子列表（保留順序）
    pending_sentences: list[str] = []
    # 對應的 TTS 任務列表（與 pending_sentences 同序），每個 item 為 asyncio.Task[bytes]
    pending_tts_tasks: list[asyncio.Task[bytes]] = []

    session_language = session_context.get("language")

    def _spawn_tts_task(sentence: str) -> None:
        """將一個句子排入 TTS 合成任務佇列（順序保持）。"""
        pending_sentences.append(sentence)
        pending_tts_tasks.append(
            asyncio.create_task(
                tts_pipeline.synthesize(text=sentence, language=session_language)
            )
        )

    # 啟動紅旗偵測（背景執行）
    red_flag_task = asyncio.create_task(
        red_flag_detector.detect(text, session_context)
    )

    try:
        async for text_chunk in llm_engine.generate_response(
            messages, session_context
        ):
            full_response += text_chunk
            sentence_buffer += text_chunk
            completed, sentence_buffer = _split_completed_sentences(sentence_buffer)
            for s in completed:
                _spawn_tts_task(s)

        # LLM 結束：殘餘緩衝視為最後一句（處理無終止標點的情況）
        tail = sentence_buffer.strip()
        if tail:
            _spawn_tts_task(tail)
        sentence_buffer = ""

    except Exception as exc:
        logger.error(
            "LLM 回應生成失敗 | session=%s, error=%s",
            session_id,
            str(exc),
        )
        await manager.send_localized_to_session(
            session_id,
            msg_type="error",
            code="errors.ws.ai_service_unavailable",
            params={},
            severity="error",
        )
        # 取消紅旗偵測任務與所有尚未完成的 TTS 任務
        red_flag_task.cancel()
        for _tts_task in pending_tts_tasks:
            if not _tts_task.done():
                _tts_task.cancel()
        return False

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

    # 觸發 Supervisor 背景分析（含 30 秒逾時與 fallback 指導）
    supervisor_timeout = getattr(settings, "SUPERVISOR_TIMEOUT_SECONDS", 30)

    async def _run_supervisor_with_timeout() -> None:
        try:
            await asyncio.wait_for(
                supervisor_engine.analyze_next_step(
                    session_id=session_id,
                    conversation_history=conversation_history,
                    chief_complaint=session_context.get("chief_complaint", ""),
                    patient_info=session_context.get("patient_info", {}),
                    redis=redis,
                    language=session_context.get("language"),
                ),
                timeout=supervisor_timeout,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "Supervisor 分析逾時（%ds），寫入 fallback 指導 | session=%s",
                supervisor_timeout,
                session_id,
            )
            # 寫入 fallback 指導至 Redis，避免下一輪讀到過期資料
            try:
                fallback = {
                    "next_focus": "supervisor unavailable, continuing with default guidance",
                    "missing_hpi": [],
                    "hpi_completion_percentage": 0,
                    "fallback": True,
                }
                redis_key = (
                    f"{settings.REDIS_KEY_PREFIX}session:{session_id}:supervisor_guidance"
                )
                await redis.setex(
                    redis_key, 300, json.dumps(fallback, ensure_ascii=False)
                )
            except Exception as exc:
                logger.warning(
                    "Supervisor fallback 寫入失敗 | session=%s, error=%s",
                    session_id,
                    str(exc),
                )
            # CONV-3：降級可被觀察 — 額外推播低嚴重度警示事件給場次，而非靜默。
            await _emit_supervisor_degraded(session_id)
        except Exception as exc:
            logger.error(
                "Supervisor 背景任務失敗 | session=%s, error=%s",
                session_id,
                str(exc),
            )

    asyncio.create_task(_run_supervisor_with_timeout())

    # === 醫療安全：在 TTS/ai_response_end 之前，優先等待紅旗偵測結果 ===
    # 若為 CRITICAL/HIGH 嚴重度，必須在患者聽到 AI 回應前先送出警示
    # 較低嚴重度可以延後處理（ai_response_end 之後）以避免阻塞語音
    RED_FLAG_WAIT_TIMEOUT = 3.5
    red_flag_alerts: list[dict[str, Any]] = []
    red_flag_timed_out = False
    # 是否仍有「遲到紅旗」背景 drain 在跑；若有，本輪不可自動結束（會 break 主迴圈、
    # 關閉 WS db），必須讓場次多撐一輪，確保急症紅旗能被持久化（醫療安全）。
    red_flag_drain_in_flight = False
    try:
        red_flag_alerts = await asyncio.wait_for(
            asyncio.shield(red_flag_task), timeout=RED_FLAG_WAIT_TIMEOUT
        )
    except asyncio.TimeoutError:
        red_flag_timed_out = True
        logger.warning(
            "紅旗偵測逾時（%.1fs），延後處理偵測結果 | session=%s",
            RED_FLAG_WAIT_TIMEOUT,
            session_id,
        )
    except Exception as exc:
        logger.error(
            "紅旗偵測任務失敗 | session=%s, error=%s",
            session_id,
            str(exc),
        )
        red_flag_alerts = []

    # 依嚴重度切分：critical/high 必須在 ai_response_end 前送出
    critical_alerts = [
        a for a in red_flag_alerts
        if str(a.get("severity", "")).lower() in ("critical", "high")
    ]
    deferred_alerts = [
        a for a in red_flag_alerts
        if str(a.get("severity", "")).lower() not in ("critical", "high")
    ]

    async def _persist_and_emit_alert(
        alert: dict[str, Any],
        *,
        persist_db: AsyncSession | None = None,
    ) -> str | None:
        """儲存單一紅旗警示至資料庫，並發送 WS 通知前端與儀表板。

        儲存失敗時不可偽造 alert_id 給前端（否則醫師會誤以為警示已存在）。
        改為送出真正的 error 事件、以 ERROR level 記錄，並回傳 None 中止本次 emit。

        persist_db：寫入用的 DB session。預設用 WS 的 db；但「遲到紅旗」背景 drain
        在主迴圈已結束（自動結束/閒置/end_session）時 WS db 已關閉，必須傳入自有的
        獨立 session 才能持久化，否則急症紅旗會被靜默丟棄（under-triage）。
        """
        target_db = persist_db if persist_db is not None else db
        try:
            from app.services.alert_service import AlertService
            from app.models.enums import AlertSeverity, AlertType
            from uuid import UUID as _UUID
            _db_alert = await AlertService.create(target_db, {
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
                # TODO-E6 / TODO-M8：把 canonical_id + confidence 穿到 DB,
                # 供 serializer 按 Accept-Language 渲染、前端 banner 呈現信心層級。
                "canonical_id": alert.get("canonical_id"),
                "confidence": alert.get("confidence", "rule_hit"),
                "language": session_context.get("language"),
            })
            await target_db.commit()
            alert_id = str(_db_alert.id)
        except Exception as _e:
            logger.error(
                "紅旗警示儲存失敗，不對前端偽造 alert_id | session=%s, severity=%s, error=%s",
                session_id,
                alert.get("severity"),
                str(_e),
                exc_info=True,
            )
            try:
                await target_db.rollback()
            except Exception:
                pass
            # 送出真正的 error 事件，讓前端知道偵測到的警示「未能持久化」，
            # 不可送出帶有偽造 alertId 的 red_flag_alert 事件。
            await manager.send_localized_to_session(
                session_id,
                msg_type="error",
                code="errors.ws.red_flag_persist_failed",
                params={"severity": str(alert.get("severity", ""))},
                severity="critical",
            )
            return None

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

        await manager.broadcast_dashboard(
            {
                "type": "new_red_flag",
                "payload": {
                    "alertId": alert_id,
                    "sessionId": session_id,
                    # fallback 改成空字串而非中文「未知」,讓 dashboard 前端依 locale
                    # 決定顯示字樣（Unknown / 未知 / Inconnu …）,不要在後端送中文。
                    "patientName": session_context.get("patient_info", {}).get(
                        "name"
                    )
                    or "",
                    "severity": alert["severity"],
                    "title": alert["title"],
                    "description": alert["description"],
                },
            }
        )
        return alert_id

    # Step C：在任何 ai_response_chunk（含音訊）送出之前，先送 critical/high 警示
    for alert in critical_alerts:
        await _persist_and_emit_alert(alert)

    # Step D：依序等待每一句的 TTS 合成結果，並以 ai_response_chunk 同時夾帶 text + audio
    # （前端會把每個 chunk 的音訊排入序列播放，視覺上字幕與語音逐句推進）
    # 若 TTS 失敗，仍送出文字 chunk（audioB64=null, ttsFailed=true）讓前端提示。
    for idx, (sentence, tts_task) in enumerate(zip(pending_sentences, pending_tts_tasks)):
        audio_b64: str | None = ""
        tts_failed = False
        try:
            audio_bytes = await tts_task
            if audio_bytes:
                audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
        except Exception as exc:
            tts_failed = True
            audio_b64 = None
            logger.warning(
                "句級 TTS 合成失敗，仍送出文字 | session=%s, idx=%d, error=%s",
                session_id,
                idx,
                str(exc),
            )

        await manager.send_to_session(
            session_id,
            {
                "type": "ai_response_chunk",
                "payload": {
                    "messageId": message_id,
                    "text": sentence,
                    "chunkIndex": idx,
                    "audioB64": audio_b64,
                    "ttsFailed": tts_failed,
                },
            },
        )

    # 發送 AI 回應結束（音訊改由逐句 chunk 送出，end 不再承載 ttsAudioUrl）
    await manager.send_to_session(
        session_id,
        {
            "type": "ai_response_end",
            "payload": {
                "messageId": message_id,
                "fullText": full_response,
                "ttsAudioUrl": "",
            },
        },
    )

    # CONV-2：本輪 AI 回覆結束後，若有可用的 Supervisor 指導即推播專屬事件。
    # supervisor_guidance 於本輪開頭自 Redis 讀入（前一輪分析結果）。不阻塞主流程。
    await _emit_supervisor_guidance(session_id, supervisor_guidance)

    # Fix 13: 達到上限時 FIFO 摘要壓縮
    try:
        await _cap_conversation_history(conversation_history, settings)
    except Exception as exc:
        logger.warning(
            "對話歷史摘要壓縮失敗（非致命） | session=%s, error=%s",
            session_id,
            str(exc),
        )

    # 儲存對話歷史至 Redis
    await _save_conversation_history(redis, session_id, conversation_history)

    # 若先前逾時，TTS 期間偵測可能已完成；嘗試回收結果作為延後處理
    if red_flag_timed_out:
        if red_flag_task.done():
            try:
                late_alerts = red_flag_task.result()
                # 逾時後才抵達的 critical/high 也仍須送出（僅次序略晚於語音）
                for alert in late_alerts or []:
                    sev = str(alert.get("severity", "")).lower()
                    if sev in ("critical", "high"):
                        critical_alerts.append(alert)
                        await _persist_and_emit_alert(alert)
                    else:
                        deferred_alerts.append(alert)
            except Exception as exc:
                logger.error(
                    "逾時後紅旗偵測結果取得失敗 | session=%s, error=%s",
                    session_id,
                    str(exc),
                )
        else:
            # 仍未完成：於背景等待並於完成後處理（避免阻塞當前 turn）。
            red_flag_drain_in_flight = True

            async def _drain_late_red_flags() -> None:
                try:
                    late_alerts = await red_flag_task
                except Exception as exc:
                    logger.error(
                        "背景紅旗偵測任務失敗 | session=%s, error=%s",
                        session_id,
                        str(exc),
                    )
                    return
                if not late_alerts:
                    return
                # 用「自有」DB session：主迴圈此刻可能已結束（自動結束/閒置/end_session），
                # WS 的 db 已被 get_db 關閉；沿用會讓遲到的急症紅旗 insert 失敗而靜默丟棄。
                from app.core.database import get_db_session
                try:
                    async with get_db_session() as drain_db:
                        for alert in late_alerts:
                            try:
                                await _persist_and_emit_alert(alert, persist_db=drain_db)
                            except Exception as exc:
                                logger.warning(
                                    "背景紅旗警示發送失敗 | session=%s, error=%s",
                                    session_id,
                                    str(exc),
                                )
                        # 遲到的 critical 仍需把場次升級為 aborted_red_flag（compare-and-set
                        # 只在仍 in_progress 時生效，不會覆寫已是 completed/aborted 的終態）。
                        if any(
                            str(a.get("severity", "")).lower() == "critical"
                            for a in late_alerts
                        ):
                            await _update_session_status(
                                drain_db, redis, session_id, "aborted_red_flag", "in_progress"
                            )
                except Exception as exc:
                    logger.error(
                        "背景紅旗 drain 失敗 | session=%s, error=%s",
                        session_id,
                        str(exc),
                    )

            asyncio.create_task(_drain_late_red_flags())

    # Step E：處理非關鍵嚴重度紅旗（ai_response_end 之後送出即可）
    for alert in deferred_alerts:
        await _persist_and_emit_alert(alert)

    # 後續 critical session-abort 判斷沿用合併後的 red_flag_alerts
    red_flag_alerts = critical_alerts + deferred_alerts

    if red_flag_alerts:
        # 若有 critical 等級，中止場次並生成 SOAP 報告
        has_critical = any(
            str(a.get("severity", "")).lower() == "critical" for a in red_flag_alerts
        )
        if has_critical:
            logger.warning(
                "偵測到 critical 紅旗，中止場次 | session=%s", session_id
            )
            await _update_session_status(
                db, redis, session_id, "aborted_red_flag", "in_progress"
            )
            await manager.send_localized_to_session(
                session_id,
                msg_type="session_status",
                code="events.session.aborted_red_flag",
                params={},
                severity="critical",
            )
            await manager.broadcast_localized_dashboard(
                msg_type="session_status_changed",
                code="events.session.aborted_red_flag_dashboard",
                params={},
                severity="critical",
                extra={
                    "sessionId": session_id,
                    "status": "aborted_red_flag",
                    "previousStatus": "in_progress",
                },
            )
            # H-8：紅旗中止場次後排隊 / 統計數字改變，順帶推播 queue/stats。
            await _broadcast_dashboard_queue_and_stats(db, redis)
            # 觸發 SOAP 報告生成（紅旗中止場次同樣需要報告供醫師審閱）
            asyncio.create_task(
                _generate_soap_report_async(
                    session_id=session_id,
                    conversation_history=conversation_history,
                    session_context=session_context,
                    settings=settings,
                )
            )

    # ── 自動結束問診（HPI 達標或回合硬上限）──────────────────────
    # 醫療安全多重保護，本區塊刻意放在「紅旗 gate 之後、critical-abort 區塊之後」：
    #   (i) 本輪病患輸入一定先被紅旗篩檢；
    #   (ii) 本輪若偵測到 critical/high 紅旗 → 不在「剛冒出嚴重症狀的這一輪」自動收尾，
    #        讓對話多撐一輪由 AI 處理（critical 另已走 abort）；
    #   (iii) 仍有遲到紅旗 drain 在背景跑時不結束，避免 break 主迴圈關閉 WS db 導致
    #        急症紅旗無法持久化（drain 雖已改用自有 session，這裡多一層保險）；
    #   (iv) 真正改狀態用 compare-and-set：只有「確實從 in_progress → completed」成功
    #        才送 completed/推 SOAP，避免把已 aborted_red_flag 的終態降級成 completed。
    serious_red_flag_this_turn = bool(red_flag_alerts) and any(
        str(a.get("severity", "")).lower() in ("critical", "high")
        for a in red_flag_alerts
    )
    if should_conclude and not serious_red_flag_this_turn and not red_flag_drain_in_flight:
        transitioned = await _update_session_status(
            db, redis, session_id, "completed", "in_progress"
        )
        if transitioned:
            logger.info(
                "HPI 完整度達門檻或回合達上限，自動結束場次 | session=%s, turns=%s, guidance_hpi=%s",
                session_id,
                patient_turns,
                supervisor_guidance.get("hpi_completion_percentage")
                if isinstance(supervisor_guidance, dict)
                else None,
            )
            # 必須用 send_to_session 送原始 payload：send_localized_to_session 不帶 status，
            # 而前端 on('session_status') 只在 status==='completed' 時導向 thank-you 頁。
            await manager.send_to_session(
                session_id,
                {
                    "type": "session_status",
                    "payload": {
                        "status": "completed",
                        "code": "events.session.completed_hpi",
                        "params": {},
                        "severity": "info",
                    },
                },
            )
            await manager.broadcast_localized_dashboard(
                msg_type="session_status_changed",
                code="events.session.completed_normal",
                params={},
                severity="info",
                extra={
                    "sessionId": session_id,
                    "status": "completed",
                    "previousStatus": "in_progress",
                },
            )
            await _broadcast_dashboard_queue_and_stats(db, redis)
            asyncio.create_task(
                _generate_soap_report_async(
                    session_id=session_id,
                    conversation_history=conversation_history,
                    session_context=session_context,
                    settings=settings,
                )
            )
            return True

    return False


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

    from sqlalchemy import select
    from sqlalchemy.exc import IntegrityError

    from app.core.database import get_db_session
    from app.models.enums import ReportStatus, ReviewStatus
    from app.models.soap_report import SOAPReport
    from app.pipelines.soap_generator import SOAPGenerator

    logger.info("開始生成 SOAP 報告 | session=%s", session_id)

    try:
        # 冪等保護（早期檢查）：一場場次只能有一份 SOAP。多個結束路徑可能同時觸發本函式
        # （end_session 控制指令 / 閒置逾時 / critical 紅旗中止 / HPI 自動結束），
        # 早期就先查一次，重複時直接 return，連昂貴的 LLM 生成都不跑。
        async with get_db_session() as _check_db:
            _existing = await _check_db.execute(
                select(SOAPReport.id).where(SOAPReport.session_id == UUID(session_id))
            )
            if _existing.scalar_one_or_none() is not None:
                logger.info("SOAP 已存在，跳過重複生成（早期檢查） | session=%s", session_id)
                return

        generator = SOAPGenerator(settings)
        soap_data = await generator.generate(
            transcript=conversation_history,
            patient_info=session_context.get("patient_info", {}),
            chief_complaint=session_context.get("chief_complaint", ""),
            language=session_context.get("language"),
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
            # 冪等保護（race 關閉）：兩個結束路徑可能在早期檢查與此處之間都通過，
            # 故在 insert 前於同一 session 內再查一次，避免重複報告。
            _dup = await db.execute(
                select(SOAPReport.id).where(SOAPReport.session_id == UUID(session_id))
            )
            if _dup.scalar_one_or_none() is not None:
                logger.info("SOAP 已存在，跳過重複生成（insert 前） | session=%s", session_id)
                return
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

    except IntegrityError:
        # soap_reports.session_id 有 UNIQUE 約束：兩個結束路徑同時 insert 時，
        # 其中一個會撞約束。這不是錯誤，是冪等保護生效（DB 層保證單一報告），
        # 以 INFO 記錄即可，避免誤導性的 ERROR + stacktrace。
        logger.info("SOAP 已存在（UNIQUE 撞擊，冪等略過） | session=%s", session_id)
    except Exception as exc:
        logger.error(
            "SOAP 報告生成失敗 | session=%s, error=%s",
            session_id,
            str(exc),
            exc_info=True,
        )

def _resolve_chief_complaint_display(session_obj: Any) -> str | None:
    """#6：把場次主訴解析成「場次語言」的顯示名稱（給開場問診語用）。

    英文場次卻顯示中文「血尿」的根因是開場語直接用 chief_complaint_text（建場當下凍結的
    單一語言字串）。此處改從 ChiefComplaint.name_by_lang/fallback 字典按場次語言解析，
    解析不到（無主訴記錄/字典缺項）才回 None，讓呼叫端 fallback 回原 text。
    """
    from app.core.config import settings as _settings
    from app.services.complaint_service import _resolve_with_fallback
    from app.utils.complaint_fallback_i18n import fallback_translate_name

    cc = getattr(session_obj, "chief_complaint", None)
    if cc is None:
        return None
    lang = getattr(session_obj, "language", None) or _settings.DEFAULT_LANGUAGE
    try:
        return _resolve_with_fallback(
            getattr(cc, "name_by_lang", None),
            lang,
            getattr(cc, "name", None),
            fallback_translate_name,
        )
    except Exception:
        return None


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
            .options(
                selectinload(Session.patient),
                # #6：開場問診語要用「場次語言」的主訴名稱，需 eager-load 主訴記錄拿 name_by_lang。
                selectinload(Session.chief_complaint),
            )
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
            # #6：主訴在「場次語言」下的顯示名稱（給開場問診語）。解析不到時為 None，
            # 呼叫端 fallback 回 chief_complaint_text（保留病患原輸入，含多選/自訂備註）。
            "chief_complaint_display": _resolve_chief_complaint_display(session_obj),
            "patient_info": patient_info,
            "language": getattr(session_obj, "language", None),
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
) -> bool:
    """
    更新場次狀態（資料庫 + Redis 快取），採 compare-and-set。

    僅當 DB 目前狀態 == previous_status 時才會轉移；否則視為 no-op 不覆寫。
    這保護「aborted_red_flag（紅旗中止）」等終態不會被後續的自動結束/閒置等
    路徑悄悄降級成 completed（會抹掉醫師端的分流訊號）。

    Args:
        db: 資料庫 session
        redis: Redis 客戶端
        session_id: 場次 ID
        new_status: 新狀態
        previous_status: 前一狀態（compare-and-set 的條件）

    Returns:
        bool: True 表示確實發生狀態轉移；False 表示目前狀態不符（no-op）或失敗。
    """
    try:
        from app.models.session import Session
        from sqlalchemy import update

        stmt = (
            update(Session)
            .where(Session.id == session_id)
            .where(Session.status == previous_status)
            .values(status=new_status)
        )
        result = await db.execute(stmt)
        await db.commit()

        if not result.rowcount:
            # 目前狀態 != previous_status → 不轉移、不動 Redis（避免快取與 DB 不一致）。
            logger.info(
                "場次狀態未轉移（目前非 %s，略過 → %s） | session=%s",
                previous_status,
                new_status,
                session_id,
            )
            return False

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
        return True

    except Exception as exc:
        logger.error(
            "更新場次狀態失敗 | session=%s, error=%s",
            session_id,
            str(exc),
            exc_info=True,
        )
        return False


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
