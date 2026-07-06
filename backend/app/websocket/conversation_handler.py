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
    hard_ready = _hard_cap_reached(patient_turns, settings)
    return bool(soft_ready or hard_ready)


# A3：紅旗 gate 的同步等待秒數。原為 _handle_text_message 內局部常數 3.5，
# 抬升為模組常數以利單元測試 monkeypatch（值與行為不變）。
_RED_FLAG_WAIT_TIMEOUT: float = 3.5

# A5：跨輪去重的 Redis hash key 與嚴重度排序（升級判斷用）。
_SESSION_EMITTED_RED_FLAGS_KEY = "gu:session:{session_id}:emitted_red_flags"
_RED_FLAG_SEVERITY_RANK = {"medium": 0, "high": 1, "critical": 2}


def _hard_cap_reached(patient_turns: int, settings: Settings) -> bool:
    """A2 [D1]：硬上限是否已到（獨立於軟門檻的旗標；受總開關控制）。"""
    if not getattr(settings, "HPI_COMPLETION_TERMINATION_ENABLED", True):
        return False
    return patient_turns >= getattr(settings, "MAX_PATIENT_TURNS_HARD_CAP", 10)


def _should_conclude_now(
    should_conclude: bool,
    hard_cap_reached: bool,
    soft_defer: bool,
    drain_unresolved: bool,
) -> bool:
    """A2 [D1+D5]：收尾閘門（純函式，便於矩陣測試）。

    - should_conclude 為 False → 一律不收尾。
    - drain_unresolved（遲到紅旗仍未解析）→ 一律延後；硬上限時呼叫端須先做
      有界 inline 解析 + MAX_HARD_CAP_DRAIN_DEFERS 絕對保命線後才傳入。
    - 軟門檻路徑（未達硬上限）被 soft_defer（本輪 critical/high 紅旗或空回應
      fallback）否決；**硬上限不被 soft_defer 否決**（D1 修復核心）。
    """
    if not should_conclude:
        return False
    if drain_unresolved:
        return False
    if hard_cap_reached:
        return True
    return not soft_defer


def _alert_dedup_identity(alert: dict[str, Any]) -> str | None:
    """A5 [D3] 去重身份：優先 canonical_id（跨語言穩定），fallback lowercase title；
    都沒有回 None（不去重，fail-open）。"""
    cid = alert.get("canonical_id")
    if cid:
        return str(cid)
    title = str(alert.get("title", "")).strip().lower()
    return title or None


async def _should_suppress_duplicate_alert(
    redis: Redis, session_id: str, alert: dict[str, Any]
) -> bool:
    """A5 [D3]：跨輪去重判斷（只抑制「持久化+廣播」，絕不影響 abort 判斷用的 list）。

    Redis hash session:{id}:emitted_red_flags 存 canonical_id→severity：
    - 同 canonical_id 且 severity 未升級（同級或降級）→ True（抑制）。
    - 升級（high→critical）→ False（放行，critical 照常觸發 abort）。
    - Redis 失效 / 身份不明 / severity 不明 → False（fail-open：寧重複不可漏急症）。
    """
    identity = _alert_dedup_identity(alert)
    if identity is None:
        return False
    new_rank = _RED_FLAG_SEVERITY_RANK.get(str(alert.get("severity", "")).lower())
    if new_rank is None:
        return False
    try:
        key = _SESSION_EMITTED_RED_FLAGS_KEY.format(session_id=session_id)
        prev = await redis.hget(key, identity)
        if prev is None:
            return False
        if isinstance(prev, (bytes, bytearray)):
            prev = prev.decode("utf-8", errors="replace")
        prev_rank = _RED_FLAG_SEVERITY_RANK.get(str(prev).lower())
        if prev_rank is None:
            return False
        return new_rank <= prev_rank
    except Exception as exc:
        logger.warning(
            "紅旗去重查詢失敗，fail-open 照常送出 | session=%s, error=%s",
            session_id,
            str(exc),
        )
        return False


async def _record_emitted_alert(
    redis: Redis, session_id: str, alert: dict[str, Any]
) -> None:
    """A5 [D3]：record-on-success — 僅在持久化+廣播成功後呼叫；
    自身吞例外（記錄失敗頂多下一輪重複 emit，不可拋、不可阻斷主流程）。"""
    identity = _alert_dedup_identity(alert)
    if identity is None:
        return
    try:
        key = _SESSION_EMITTED_RED_FLAGS_KEY.format(session_id=session_id)
        await redis.hset(key, identity, str(alert.get("severity", "")).lower())
        await redis.expire(key, _SESSION_CONTEXT_TTL)
    except Exception as exc:
        logger.warning(
            "紅旗去重記錄失敗（下一輪可能重複 emit，可接受） | session=%s, error=%s",
            session_id,
            str(exc),
        )


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
                    patient_metadata={"input_source": "text"},
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
        # 儲存至 DB（metadata.message_id 對應開場的 ai_response_* WS 事件）
        try:
            from app.services.conversation_service import ConversationService
            from uuid import UUID as _UUID
            await ConversationService.create(
                db,
                _UUID(session_id),
                "assistant",
                full_greeting,
                metadata={"message_id": message_id, "greeting": True},
            )
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


# ── E8-1：場次已終止後仍收到訊息的唯一回覆 ──────────────────
# _SESSION_TERMINATED_NOTICE_KEYS：終態 → i18n key 的對照表；場次已終止
# （aborted_red_flag / completed）後若還收到訊息（前端競態、殘留的緩衝片段
# 等），不可再重跑紅旗/LLM/auto-conclude（會重發 abort 事件洪流、浪費 LLM
# 配額 — e2e_realopenai_findings 2026-06-28 實測），只送這一則提示。
_SESSION_TERMINATED_NOTICE_KEYS: dict[str, str] = {
    "aborted_red_flag": "ws.session_terminated_aborted_notice",
    "completed": "ws.session_terminated_completed_notice",
}


async def _notify_session_already_terminated(
    *,
    session_id: str,
    terminated_status: str,
    tts_pipeline: TTSPipeline,
    session_context: dict[str, Any],
) -> None:
    """場次已終止（aborted_red_flag / completed）後仍收到訊息時的唯一回覆。

    刻意重用 ai_response_start / ai_response_chunk / ai_response_end 三段序列
    （而非另開新訊息型別）：前端「AI 講話時硬鎖麥克風」與 VAD 解鎖都掛在這條
    既有鏈上（每分支唯一 ai_response_end 不變式），沿用此序列可保證 VAD 不
    卡死，且不需要改動前端 payload 契約 / 新增前端 i18n key。
    """
    from app.utils.i18n_messages import get_message as _i18n_get

    message_id = str(uuid.uuid4())
    session_language = session_context.get("language")
    notice_key = _SESSION_TERMINATED_NOTICE_KEYS.get(
        terminated_status, "ws.session_terminated_completed_notice"
    )
    notice_text = _i18n_get(notice_key, session_language)

    await manager.send_to_session(
        session_id,
        {"type": "ai_response_start", "payload": {"messageId": message_id}},
    )

    audio_b64: str | None = ""
    tts_failed = False
    try:
        audio_bytes = await tts_pipeline.synthesize(
            text=notice_text, language=session_language
        )
        if audio_bytes:
            audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
    except Exception as exc:
        tts_failed = True
        audio_b64 = None
        logger.warning(
            "場次已終止提示 TTS 合成失敗，仍送出文字 | session=%s, error=%s",
            session_id,
            str(exc),
        )

    await manager.send_to_session(
        session_id,
        {
            "type": "ai_response_chunk",
            "payload": {
                "messageId": message_id,
                "text": notice_text,
                "chunkIndex": 0,
                "audioB64": audio_b64,
                "ttsFailed": tts_failed,
            },
        },
    )

    await manager.send_to_session(
        session_id,
        {
            "type": "ai_response_end",
            "payload": {
                "messageId": message_id,
                "fullText": notice_text,
                "ttsAudioUrl": "",
            },
        },
    )


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
    # E8-1：場次已終止（前一輪紅旗 abort / 已完成）→ 拒收後續音訊，不進 STT。
    # 放在最前面（先於任何 buffer 累積），避免對已終止場次浪費 Whisper 額度；
    # 只要收到任何片段（不論 isFinal）就立刻回一則提示並結束主迴圈，
    # 不會像舊行為一樣每 250ms 的殘留片段都重跑一次。
    terminated_status = session_context.get("_terminated")
    if terminated_status:
        logger.info(
            "場次已終止（%s），忽略音訊片段、不進 STT | session=%s",
            terminated_status,
            session_id,
        )
        audio_buffer.clear()
        audio_buffer_total_bytes[0] = 0
        await _notify_session_already_terminated(
            session_id=session_id,
            terminated_status=terminated_status,
            tts_pipeline=tts_pipeline,
            session_context=session_context,
        )
        return True

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
    stt_confidence: float | None = None
    try:
        result = await stt_pipeline.transcribe(complete_audio, language=whisper_lang)
        final_text = result["text"]
        # 真實信心分數（segments avg_logprob 估算）；None＝未知。
        # 未知時「不帶 confidence 鍵」而非送 null：前端 ChatBubble 以
        # `sttConfidence !== undefined` 判斷是否顯示百分比，null 會渲染成 0%。
        stt_confidence = result.get("confidence")
        message_id = str(uuid.uuid4())

        stt_payload: dict[str, Any] = {
            "messageId": message_id,
            "text": final_text,
            "isFinal": True,
        }
        if stt_confidence is not None:
            stt_payload["confidence"] = stt_confidence

        await manager.send_to_session(
            session_id,
            {
                "type": "stt_final",
                "payload": stt_payload,
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
            stt_confidence=stt_confidence,
            patient_metadata={
                "input_source": "voice",
                "stt_language": whisper_lang,
            },
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
    stt_confidence: float | None = None,
    patient_metadata: dict[str, Any] | None = None,
) -> bool:
    """
    處理文字訊息：加入歷史 → LLM 回應 → TTS → 紅旗偵測

    Returns:
        bool: True 表示本輪後場次已自動結束（呼叫端應結束主迴圈）；否則 False。

    Args:
        session_id: 場次 ID
        text: 病患文字訊息
        stt_confidence: 語音路徑的 STT 信心分數（0~1）；文字輸入 / 未知時 None
        patient_metadata: 病患對話輪的 metadata（input_source 等），落
            conversations.metadata JSONB
        其他參數: 各管線與上下文
    """
    # E8-1：場次已終止（前一輪紅旗 abort / 已完成）→ 拒收後續訊息。
    # session_context 是本連線唯一、跨輪共用的同一份參照（由 conversation_websocket
    # 建立一次、每輪都原樣傳入）；一旦本連線任何一輪（含背景 late-critical drain）
    # 把場次判定為終態就會設下面這個旗標，之後任何一輪都會在這裡攔下——不再跑紅旗
    # /LLM/auto-conclude、不再重發 abort 事件洪流，只回一則在地化提示並結束主迴圈
    # （e2e_realopenai_findings 2026-06-28：critical abort 後 server 對已中止場次
    # 續答 3 輪、每輪重發 abort 事件並照跑 LLM）。
    terminated_status = session_context.get("_terminated")
    if terminated_status:
        logger.info(
            "場次已終止（%s），忽略本則訊息、不重跑紅旗/LLM | session=%s",
            terminated_status,
            session_id,
        )
        await _notify_session_already_terminated(
            session_id=session_id,
            terminated_status=terminated_status,
            tts_pipeline=tts_pipeline,
            session_context=session_context,
        )
        return True

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
        _conv = await ConversationService.create(
            db,
            _UUID(session_id),
            "patient",
            text,
            stt_confidence=stt_confidence,
            metadata=patient_metadata or {"input_source": "text"},
        )
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

    # ── A1 [D5] 空回應守衛：LLM 正常結束但無內容 → 單次 retry → 仍空送在地化 fallback ──
    used_empty_fallback = False
    if not full_response.strip():
        logger.warning(
            "LLM 回傳空回應 | session=%s, retry_enabled=%s",
            session_id,
            getattr(settings, "LLM_EMPTY_RESPONSE_RETRY", True),
        )
        # 先清 in-flight TTS + reset（空/純空白回應理論上切不出句子，防禦性清理）
        for _t in pending_tts_tasks:
            if not _t.done():
                _t.cancel()
        pending_sentences.clear()
        pending_tts_tasks.clear()
        full_response = ""
        sentence_buffer = ""
        if getattr(settings, "LLM_EMPTY_RESPONSE_RETRY", True):
            try:
                async for text_chunk in llm_engine.generate_response(
                    messages, session_context
                ):
                    full_response += text_chunk
                    sentence_buffer += text_chunk
                    completed, sentence_buffer = _split_completed_sentences(sentence_buffer)
                    for s in completed:
                        _spawn_tts_task(s)
                tail = sentence_buffer.strip()
                if tail:
                    _spawn_tts_task(tail)
                sentence_buffer = ""
            except Exception as exc:
                # retry「全程吞例外」：後面的 ai_response_end 必須照送（VAD 不卡死不變式）
                logger.error(
                    "空回應 retry 失敗 | session=%s, error=%s", session_id, str(exc)
                )
                for _t in pending_tts_tasks:
                    if not _t.done():
                        _t.cancel()
                pending_sentences.clear()
                pending_tts_tasks.clear()
                full_response = ""
                sentence_buffer = ""
        if not full_response.strip():
            # 仍空：送在地化 fallback，「直接」整句 _spawn_tts_task —— 不可走切句：
            # _SENTENCE_BOUNDARY_CHARS 是 CJK-only，en/ko/vi 的 ASCII '?' 切不出句子
            # → 會變成 0 個 chunk 的空泡泡（D5 根因之一）。
            from app.utils.i18n_messages import get_message as _i18n_get

            used_empty_fallback = True
            full_response = _i18n_get("ws.ai_empty_retry_fallback", session_language)
            _spawn_tts_task(full_response)
    # 不可 early-return：後續歷史寫入 / 紅旗 gate / TTS chunk / ai_response_end 照走。

    # 加入 AI 回應到對話歷史
    conversation_history.append(
        {
            "role": "assistant",
            "content": full_response,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )

    # 儲存 AI 回應至資料庫（metadata.message_id 對應本輪 ai_response_* WS 事件）
    try:
        from app.services.conversation_service import ConversationService
        from uuid import UUID as _UUID
        await ConversationService.create(
            db,
            _UUID(session_id),
            "assistant",
            full_response,
            metadata={"message_id": message_id},
        )
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
    red_flag_alerts: list[dict[str, Any]] = []
    red_flag_timed_out = False
    # 是否仍有「遲到紅旗」背景 drain 在跑；若有，本輪不可自動結束（會 break 主迴圈、
    # 關閉 WS db），必須讓場次多撐一輪，確保急症紅旗能被持久化（醫療安全）。
    red_flag_drain_in_flight = False
    try:
        red_flag_alerts = await asyncio.wait_for(
            asyncio.shield(red_flag_task), timeout=_RED_FLAG_WAIT_TIMEOUT
        )
    except asyncio.TimeoutError:
        red_flag_timed_out = True
        logger.warning(
            "紅旗偵測逾時（%.1fs），延後處理偵測結果 | session=%s",
            _RED_FLAG_WAIT_TIMEOUT,
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

    def _resolve_alert_display_title(alert: dict[str, Any]) -> str:
        """依場次語言防禦性重解析單一紅旗 alert 的顯示用 title（E8-4 防線）。

        對「內建 catalogue（shared.URO_RED_FLAGS）」的紅旗，不論上游傳入的 title
        實際語言為何，一律以 get_display_title 依當前場次語言重新解析一次；
        非內建 catalogue（DB 自訂規則／LLM 自創）維持原樣，避免被覆寫成醜陋的
        canonical_id slug（詳見 `_persist_and_emit_alert` docstring 的完整理由）。

        供 `_persist_and_emit_alert`（DB／WS／dashboard 廣播用）與
        critical_title／late_critical_title（寫入 session.red_flag_reason）
        共用同一份重解析邏輯，避免兩者對同一急症事件顯示不同語言的 title。
        """
        from app.pipelines.prompts.shared import URO_RED_FLAGS, get_display_title

        _canonical_id = alert.get("canonical_id")
        _is_builtin_catalog_flag = any(
            f.get("canonical_id") == _canonical_id for f in URO_RED_FLAGS
        )
        resolved = (
            get_display_title(_canonical_id, session_context.get("language"))
            if _canonical_id and _is_builtin_catalog_flag
            else alert.get("title")
        )
        return resolved or alert.get("title")

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

        A5 [D3]：跨輪去重 — 同 canonical 紅旗未升級時抑制重複持久化/廣播；
        僅抑制此處的 emit，不影響呼叫端組裝 abort 判斷用的 red_flag_alerts list。

        E8-4：title 依場次語言防禦性重解析 — red_flag_detector 偵測時已依
        session.language 解析 title（規則層 `_rule_based_detect` / 語意層
        `_semantic_detect` 皆已本地化），這裡是持久化/廣播前的最後把關，
        只針對「內建 catalogue（shared.URO_RED_FLAGS）」的紅旗做二次防禦性
        重解析：不論上游傳進來的 title 實際語言為何，一律以
        get_display_title 依當前場次語言重新解析一次。

        刻意排除「canonical_id 存在但不在內建 catalogue」的情況（DB 管理員
        自訂規則、或 LLM 自創的新型紅旗）：get_display_title 只認得內建
        catalogue，對這類 canonical_id 只會回傳 canonical_id 原始字串
        （如 "acute_epididymitis_suspected"），若在此無條件覆寫會讓 DB
        自訂規則原本已透過自身 display_title_by_lang 正確解析好的 title
        被替換成醜陋的 snake_case slug——反而製造新的在地化 regression。
        """
        if await _should_suppress_duplicate_alert(redis, session_id, alert):
            logger.info(
                "紅旗跨輪去重：同紅旗未升級，抑制重複持久化/廣播 | session=%s, canonical_id=%s, severity=%s",
                session_id,
                alert.get("canonical_id"),
                alert.get("severity"),
            )
            return None
        resolved_title = _resolve_alert_display_title(alert)
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
                "title": resolved_title,
                "description": alert.get("description", ""),
                "trigger_reason": alert.get("trigger_reason", ""),
                "trigger_keywords": alert.get("trigger_keywords"),
                "suggested_actions": alert.get("suggested_actions", []),
                "matched_rule_id": _UUID(alert["matched_rule_id"]) if alert.get("matched_rule_id") else None,
                # E8-4（原 TODO-E6 / TODO-M8）：把 canonical_id + confidence 穿到 DB,
                # title 已依場次語言解析(見上方 resolved_title),confidence 供
                # 前端 banner 呈現信心層級。
                "canonical_id": alert.get("canonical_id"),
                "confidence": alert.get("confidence", "rule_hit"),
                "language": session_context.get("language"),
            })
            await target_db.commit()
            alert_id = str(_db_alert.id)

            # 把觸發本警示的病患對話輪標記 red_flag_detected=true。
            # 僅在有真實 conversation row 時標（drain 情境 patient_conv_id 可能為
            # None，alert.conversation_id 是佔位 uuid、無列可標）。獨立小交易：
            # 標記失敗絕不可影響已提交的警示（病安優先）。
            if patient_conv_id is not None:
                try:
                    from sqlalchemy import update as _sa_update
                    from app.models.conversation import Conversation as _Conversation

                    await target_db.execute(
                        _sa_update(_Conversation)
                        .where(_Conversation.id == patient_conv_id)
                        .values(red_flag_detected=True)
                    )
                    await target_db.commit()
                except Exception:
                    logger.warning(
                        "紅旗對話輪標記失敗（非致命） | session=%s, conversation=%s",
                        session_id,
                        patient_conv_id,
                        exc_info=True,
                    )
                    try:
                        await target_db.rollback()
                    except Exception:
                        pass
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
                    "title": resolved_title,
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
                    "title": resolved_title,
                    "description": alert["description"],
                },
            }
        )
        # A5 [D3]：record-on-success — DB 持久化 + 廣播皆未拋例外才記錄去重身份。
        # send_to_session 回 False（病患 WS 已關，drain 情境常見）仍記錄：
        # 去重目的在防重複 DB row / 儀表板轟炸，DB 已寫成功即記。
        await _record_emitted_alert(redis, session_id, alert)
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
                            late_critical_title = next(
                                (
                                    _resolve_alert_display_title(a)
                                    for a in late_alerts
                                    if str(a.get("severity", "")).lower() == "critical"
                                ),
                                None,
                            )
                            await _update_session_status(
                                drain_db,
                                redis,
                                session_id,
                                "aborted_red_flag",
                                "in_progress",
                                red_flag_reason=late_critical_title,
                            )
                            # E8-1：遲到的 critical 常在 _handle_text_message 這輪已
                            # 結束（本輪 return False）之後才落地；沒有這個旗標，
                            # 病患下一輪訊息仍會被當成場次還活著、整套紅旗/LLM 重跑。
                            session_context["_terminated"] = "aborted_red_flag"
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
            # A4 [D2]：帶 critical 紅旗 title 作為 red_flag_reason（title 已由偵測器
            # 按場次語言在地化；_resolve_alert_display_title 再做一次 E8-4 防禦性
            # 重解析，與 _persist_and_emit_alert 對 DB/WS 廣播用的 title 保持一致，
            # 避免 session.red_flag_reason 與 alerts 表語言不一致），供醫師端分流顯示。
            critical_title = next(
                (
                    _resolve_alert_display_title(a)
                    for a in red_flag_alerts
                    if str(a.get("severity", "")).lower() == "critical"
                ),
                None,
            )
            await _update_session_status(
                db,
                redis,
                session_id,
                "aborted_red_flag",
                "in_progress",
                red_flag_reason=critical_title,
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
            # E8-1：標記本連線場次已終止（不論上面 CAS 是否真的轉移成功——即使
            # 因競態已被別的路徑轉走，場次現在也一定是終態），讓「下一輪」訊息
            # 進 _handle_text_message / _handle_audio_chunk 時被開頭的守衛攔下，
            # 不再重新跑一次紅旗/LLM/重發 abort 事件。
            session_context["_terminated"] = "aborted_red_flag"

    # ── 自動結束問診（HPI 達標或回合硬上限）──────────────────────
    # 醫療安全多重保護，本區塊刻意放在「紅旗 gate 之後、critical-abort 區塊之後」：
    #   (i) 本輪病患輸入一定先被紅旗篩檢；
    #   (ii) 軟門檻收尾被 soft_defer（本輪 critical/high 紅旗、或空回應 fallback 輪）
    #        否決 → 對話多撐一輪由 AI 處理（critical 另已走 abort）。但「硬上限」不受
    #        soft_defer 否決（A2 [D1]：持續 high 的主訴如肉眼血尿，否則永不結束）；
    #   (iii) 仍有遲到紅旗 drain 未解析時：軟門檻延後一輪；硬上限改做有界 inline 解析
    #        （A3 [D1]：late-critical 先 abort，偵測器真卡死累計 MAX_HARD_CAP_DRAIN_DEFERS
    #        輪後強制收尾 — 絕對保命線）；
    #   (iv) 真正改狀態用 compare-and-set：只有「確實從 in_progress → completed」成功
    #        才送 completed/推 SOAP，避免把已 aborted_red_flag 的終態降級成 completed。
    serious_red_flag_this_turn = bool(red_flag_alerts) and any(
        str(a.get("severity", "")).lower() in ("critical", "high")
        for a in red_flag_alerts
    )
    hard_cap_reached = _hard_cap_reached(patient_turns, settings)
    # A2：soft_defer 只否決軟門檻收尾；空回應 fallback 輪也不軟收尾（病患還沒真的被
    # 問到問題）。硬上限不受 soft_defer 否決（D1 修復核心：持續 high 紅旗的主訴
    # 如肉眼血尿，不可再把硬上限「永久延後」）。
    soft_defer = serious_red_flag_this_turn or used_empty_fallback
    drain_unresolved = red_flag_drain_in_flight

    # A3 [D1]：硬上限 + 遲到紅旗未解析 → 有界 inline 解析，偵測器真卡死才走絕對保命線
    if hard_cap_reached and drain_unresolved:
        try:
            # 必須 shield：wait_for 逾時會 cancel 內層 task，會連帶殺掉正在 await
            # 同一 red_flag_task 的 _drain_late_red_flags（遲到紅旗就永遠無法持久化）。
            late_alerts = await asyncio.wait_for(
                asyncio.shield(red_flag_task),
                timeout=float(getattr(settings, "HARD_CAP_DRAIN_AWAIT_SECONDS", 5.0)),
            )
        except asyncio.TimeoutError:
            defers = int(session_context.get("_hard_cap_drain_defers", 0)) + 1
            session_context["_hard_cap_drain_defers"] = defers
            if defers > int(getattr(settings, "MAX_HARD_CAP_DRAIN_DEFERS", 2)):
                # 絕對保命線（E7 決策 2）：偵測器真卡死，強制收尾出 SOAP。
                # 接受極罕見 late-critical race：偵測若日後完成，_drain_late_red_flags
                # 仍會持久化警示供醫師審閱；其 abort CAS 對已 completed 終態為 no-op。
                logger.error(
                    "紅旗偵測器連續 %d 輪未解析，硬上限強制收尾 | session=%s",
                    defers,
                    session_id,
                )
                drain_unresolved = False
        except Exception:
            # 偵測任務本身失敗（drain 端已記 log）：沒有結果可等 → 視為已解析
            drain_unresolved = False
        else:
            drain_unresolved = False
            session_context.pop("_hard_cap_drain_defers", None)
            if any(
                str(a.get("severity", "")).lower() == "critical"
                for a in late_alerts or []
            ):
                # 紅旗優先：先 abort（CAS，永不覆寫終態），持久化/廣播交給已在跑的
                # _drain_late_red_flags（避免與其 double-persist 競態），再結束主迴圈。
                late_critical_title = next(
                    (
                        _resolve_alert_display_title(a)
                        for a in late_alerts or []
                        if str(a.get("severity", "")).lower() == "critical"
                    ),
                    None,
                )
                logger.warning(
                    "硬上限收尾前解析出遲到 critical 紅旗，中止場次 | session=%s",
                    session_id,
                )
                await _update_session_status(
                    db,
                    redis,
                    session_id,
                    "aborted_red_flag",
                    "in_progress",
                    red_flag_reason=late_critical_title,
                )
                # 與既有 critical-abort 區塊相同的通知組（行為一致）。
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
                await _broadcast_dashboard_queue_and_stats(db, redis)
                # SOAP 冪等由 _generate_soap_report_async 雙重存在性檢查 + UNIQUE 保護。
                asyncio.create_task(
                    _generate_soap_report_async(
                        session_id=session_id,
                        conversation_history=conversation_history,
                        session_context=session_context,
                        settings=settings,
                    )
                )
                # E8-1：與其他終態分支一致地標記（雖然下面立刻 return True 結束
                # 主迴圈，這輪不會再進 handler，但保持所有終態出口一致，避免
                # 未來重構誤刪 return True 時失去這道保護）。
                session_context["_terminated"] = "aborted_red_flag"
                return True
            # late_alerts 不併入 red_flag_alerts：非 critical 由 _drain_late_red_flags
            # 持久化/廣播，避免重跑上方 abort 區塊或 double-persist。

    if _should_conclude_now(should_conclude, hard_cap_reached, soft_defer, drain_unresolved):
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
            # E8-1：正常收尾同樣標記終態（見上方 aborted_red_flag 分支同註解）。
            session_context["_terminated"] = "completed"
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
    from sqlalchemy.orm import selectinload

    from app.core.database import get_db_session
    from app.models.enums import ReportStatus, ReviewStatus
    from app.models.session import Session
    from app.models.soap_report import SOAPReport
    from app.pipelines.icd10_symptom_map import resolve_symptom_id
    from app.pipelines.soap_generator import SOAPGenerator

    logger.info("開始生成 SOAP 報告 | session=%s", session_id)

    try:
        # 冪等保護（早期檢查）：一場場次只能有一份 SOAP。多個結束路徑可能同時觸發本函式
        # （end_session 控制指令 / 閒置逾時 / critical 紅旗中止 / HPI 自動結束），
        # 早期就先查一次，重複時直接 return，連昂貴的 LLM 生成都不跑。
        symptom_id: str | None = None
        async with get_db_session() as _check_db:
            _existing = await _check_db.execute(
                select(SOAPReport.id).where(SOAPReport.session_id == UUID(session_id))
            )
            if _existing.scalar_one_or_none() is not None:
                logger.info("SOAP 已存在，跳過重複生成（早期檢查） | session=%s", session_id)
                return
            # B2：同一趟連線順便查 session（eager-load 主訴）解析 symptom_id，
            # 供 ICD-10 驗證層做 symptom↔code 對映；解析不到（無主訴/「其他」
            # sentinel/查無 session）→ None，validator 會回 unverified（graceful）。
            _session_obj = (
                await _check_db.execute(
                    select(Session)
                    .options(selectinload(Session.chief_complaint))
                    .where(Session.id == UUID(session_id))
                )
            ).scalar_one_or_none()
            symptom_id = resolve_symptom_id(_session_obj)

            # 安全關鍵（修死代碼）：取本場次即時偵測並持久化的紅旗注入 SOAP 生成，
            # 讓 _enforce_red_flag_urgency 能把 critical/high 紅旗強制反映到
            # plan.urgency（只升不降），避免 LLM 自逐字稿重新推導時 under-triage。
            # 先前此路徑未傳 red_flags → generate() red_flags=None → 安全底線恆 no-op
            # （即時生成路徑漏接；Celery 重生路徑 report_queue.py 已正確傳，此處對齊）。
            from app.models.red_flag_alert import RedFlagAlert

            _rf_rows = (
                await _check_db.execute(
                    select(RedFlagAlert).where(
                        RedFlagAlert.session_id == UUID(session_id)
                    )
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
                for rf in _rf_rows
            ]

        generator = SOAPGenerator(settings)
        soap_data = await generator.generate(
            transcript=conversation_history,
            patient_info=session_context.get("patient_info", {}),
            chief_complaint=session_context.get("chief_complaint", ""),
            language=session_context.get("language"),
            symptom_id=symptom_id,
            red_flags=red_flags,
        )

        # 格式化對話逐字稿——與 Celery 重生路徑（report_queue._async_generate）
        # 共用單一來源 format_raw_transcript（中性 `[patient]` 標籤，
        # 修掉舊版寫死中文「病患：/AI 助手：」的漂移問題）。
        from app.utils.transcript import format_raw_transcript

        raw_transcript = format_raw_transcript(conversation_history)

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
                # D6/B2：validator 的 symptom↔code 對映驗證結果（供前端「需醫師確認」顯示）
                icd10_verified=bool(soap_data.get("icd10_verified", False)),
                # D4/B3：SOAP 語言必須跟 session 語言（先前漏設 → 落 server_default 恆 zh-TW）。
                # 「or DEFAULT_LANGUAGE」是承重的：欄位 nullable=False，若把 None 傳進去會
                # IntegrityError，被下方 except IntegrityError 誤當 UNIQUE 冪等撞擊 →
                # SOAP 靜默消失。絕對不可拿掉 fallback。
                language=session_context.get("language") or settings.DEFAULT_LANGUAGE,
                ai_confidence_score=soap_data.get("confidence_score"),
                raw_transcript=raw_transcript,
                generated_at=datetime.now(timezone.utc),
            )
            db.add(report)

            # M15 append-only：WS 路徑與 Celery 路徑一致——首版內容也留快照
            # （舊版只有 Celery regenerate 路徑會寫 INITIAL revision）。
            await db.flush()
            from app.models.enums import ReportRevisionReason
            from app.services.report_service import ReportService

            await ReportService._snapshot_revision(
                db, report, ReportRevisionReason.INITIAL
            )

            # REPORT_READY 站內通知（有負責醫師才發；失敗不可影響報告寫入）。
            try:
                from app.services.notification_service import NotificationService

                await NotificationService.notify_report_ready(
                    db, session_id=session_id, report_id=report.id
                )
            except Exception:
                logger.warning(
                    "REPORT_READY 通知建立失敗（非致命） | session=%s",
                    session_id,
                    exc_info=True,
                )
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

# 「其他」主訴 sentinel：與 alembic seed（20260704_1000-seed_other_chief_complaint）的固定
# UUID 同步，unit test 交叉驗證兩處一致。病患選「其他」時 FK 指向此筆，實際主訴內容
# 在 chief_complaint_text（病患自述）。
OTHER_CHIEF_COMPLAINT_ID = "00000000-0000-4000-8000-0000000000ff"


def _resolve_chief_complaint_display(session_obj: Any) -> str | None:
    """#6：把場次主訴解析成「場次語言」的顯示名稱（給開場問診語用）。

    英文場次卻顯示中文「血尿」的根因是開場語直接用 chief_complaint_text（建場當下凍結的
    單一語言字串）。此處改從 ChiefComplaint.name_by_lang/fallback 字典按場次語言解析，
    解析不到（無主訴記錄/字典缺項）才回 None，讓呼叫端 fallback 回原 text。

    #5：主訴為「其他」sentinel 時，名稱只是佔位詞，改回傳 chief_complaint_text
    （病患自述）；自述為空才落回一般解析（至少顯示在地化的「其他」）。
    """
    from app.core.config import settings as _settings
    from app.services.complaint_service import _resolve_with_fallback
    from app.utils.complaint_fallback_i18n import fallback_translate_name

    cc = getattr(session_obj, "chief_complaint", None)
    if cc is None:
        return None
    # 「其他」sentinel：名稱只是佔位詞，開場語若念「關於您的『其他』」毫無資訊量，
    # 優先改用病患自述（chief_complaint_text）；自述為空（前端已擋，防禦舊 client /
    # 直接打 API）才落回一般解析，至少顯示在地化的「其他」而不是壞字串。
    if str(getattr(cc, "id", "")) == OTHER_CHIEF_COMPLAINT_ID:
        text = (getattr(session_obj, "chief_complaint_text", None) or "").strip()
        if text:
            return text
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

        # #6：主訴在「場次語言」下的顯示名稱（給開場問診語）。解析不到時為 None，
        # 呼叫端 fallback 回 chief_complaint_text（保留病患原輸入，含多選/自訂備註）。
        resolved_chief_complaint_display = _resolve_chief_complaint_display(session_obj)

        return {
            "id": str(session_obj.id),
            "status": session_obj.status,
            # E8-2：舊版在 chief_complaint_text 為空時 fallback 成
            # `getattr(session_obj, "chief_complaint", "")`——那其實是 ChiefComplaint
            # ORM 關聯物件（selectinload 整個 model instance），不是字串。之後
            # shared.py 的 get_red_flags_for_complaint 對它做 `cc in chief_complaint`
            # substring 比對會直接 TypeError，導致「建場次不帶 chief_complaint_text」
            # 時整個 WS 開場直接 internal_error 掛掉。改成沿用 #6 的場次語言解析
            # （name_by_lang → name），fallback 鏈最終保證是字串（含空字串）。
            "chief_complaint": (
                session_obj.chief_complaint_text
                or resolved_chief_complaint_display
                or ""
            ),
            "chief_complaint_display": resolved_chief_complaint_display,
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
    *,
    red_flag_reason: str | None = None,
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
        red_flag_reason: 轉 aborted_red_flag 時的紅旗原因（critical 紅旗 title，
            已按場次語言在地化）；其他轉移忽略此參數。

    Returns:
        bool: True 表示確實發生狀態轉移；False 表示目前狀態不符（no-op）或失敗。
    """
    try:
        from app.models.session import Session
        from sqlalchemy import Integer, func, update

        values: dict[str, Any] = {"status": new_status}
        if new_status == "aborted_red_flag":
            # E2 [D2]（E7 決策 3）：session.red_flag 語意＝「因紅旗中止」。
            # 僅 aborted_red_flag 轉移時寫入；completed（含 high-only 撐到硬上限收尾）
            # 不設 true —「曾有紅旗」請查 red_flag_alerts 表。
            values["red_flag"] = True
            if red_flag_reason:
                values["red_flag_reason"] = red_flag_reason
        # E8-3：sessions.started_at / completed_at 補寫。這兩欄過去只有 REST 端點
        # （SessionService.update_status_static）會寫，但實際問診幾乎全程走 WS
        # 這條路徑（本函式），從未被寫過 → 恆為 NULL，dashboard 平均時長只能退回
        # 同樣沒人寫的 duration_seconds（等於恆缺值）。
        #   - started_at：問診真正開始（轉 in_progress，含首次連線與斷線 resume
        #     重連）時寫一次；用 COALESCE 保留既有值達成冪等 —— 不可用額外 WHERE
        #     擋（下面 compare-and-set 的 WHERE 條件不可動），resume 重連時
        #     previous_status 常已是 in_progress，加 WHERE 會讓整條 UPDATE 連
        #     status 都轉不了。
        #   - completed_at：轉任一終態（completed / aborted_red_flag）時寫入；
        #     CAS 本身保證同一場次只會成功轉移一次，天然冪等，不需額外保護。
        if new_status == "in_progress":
            values["started_at"] = func.coalesce(Session.started_at, func.now())
        elif new_status in ("completed", "aborted_red_flag"):
            values["completed_at"] = func.now()
            # WS 終態同步補寫 duration_seconds（REST 路徑本來就會寫，補齊對稱）。
            # started_at 為 NULL 時 interval 運算結果為 NULL —— 保持缺值不硬塞 0，
            # dashboard 端本就以 completed_at − started_at 為優先來源。
            values["duration_seconds"] = func.cast(
                func.extract("epoch", func.now() - Session.started_at), Integer
            )
        stmt = (
            update(Session)
            .where(Session.id == session_id)
            .where(Session.status == previous_status)
            .values(**values)
            # RETURNING：轉移成功時順帶取回稽核/通知所需欄位，免第二趟 SELECT。
            .returning(Session.language, Session.doctor_id, Session.patient_id)
        )
        result = await db.execute(stmt)
        row = result.first()
        await db.commit()

        if row is None:
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

        # ── SESSION_START / SESSION_END 稽核 + 完成通知（第二段交易）────────
        # 刻意放在狀態轉移 commit 之後：稽核 / 通知任何失敗都絕不可回滾
        # 已生效的轉移（狀態機正確性 > 附屬記錄）。失敗僅記 warning。
        try:
            from app.models.enums import AuditAction
            from app.services.audit_log_service import AuditLogService

            audit_action: AuditAction | None = None
            if new_status == "in_progress":
                audit_action = AuditAction.SESSION_START
            elif new_status in ("completed", "aborted_red_flag"):
                audit_action = AuditAction.SESSION_END
            if audit_action is not None:
                details: dict[str, Any] = {
                    "previous_status": previous_status,
                    "new_status": new_status,
                    "via": "websocket",
                }
                if red_flag_reason:
                    details["red_flag_reason"] = red_flag_reason
                await AuditLogService.log(
                    db,
                    user_id=None,  # WS 轉移由系統驅動（kiosk 病患無獨立操作者）
                    action=audit_action,
                    resource_type="session",
                    resource_id=str(session_id),
                    details=details,
                    language=row.language,
                )
            if new_status == "completed" and row.doctor_id is not None:
                from app.services.notification_service import NotificationService

                await NotificationService.notify_session_complete(
                    db,
                    session_id=session_id,
                    doctor_id=row.doctor_id,
                    patient_id=row.patient_id,
                )
            await db.commit()
        except Exception as exc:
            logger.warning(
                "場次狀態稽核/通知寫入失敗（非致命，轉移已生效） | session=%s, error=%s",
                session_id,
                str(exc),
            )
            try:
                await db.rollback()
            except Exception:
                pass

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
