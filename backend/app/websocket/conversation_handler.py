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
import re
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
from app.pipelines.patient_context import build_patient_info
from app.pipelines.prompts.shared import count_critical_risk_factors_for_complaint
from app.pipelines.red_flag_detector import RedFlagDetector
from app.pipelines.stt_pipeline import STTPipeline, to_whisper_language
from app.pipelines.tts_pipeline import TTSPipeline
from app.pipelines.supervisor import SupervisorEngine
from app.utils.i18n_messages import get_message as _i18n_get
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

# fire-and-forget 背景任務的強參照集合（見 _spawn_background）
_BACKGROUND_TASKS: set["asyncio.Task[Any]"] = set()


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


def _spawn_background(coro: Any) -> "asyncio.Task[Any]":
    """派送 fire-and-forget 背景任務並持強參照到完成。

    `asyncio` 只對執行中的 task 持弱參照：派送者自己隨即結束時（例如遲到紅旗的
    `_drain_late_red_flags` 派完 SOAP 就返回），task 可能在真正跑起來之前就被 GC
    回收，SOAP 於是永遠不生成。加入模組級集合、完成時自動移除。
    """
    task = asyncio.create_task(coro)
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)
    return task


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


def _authorize_ws_session_access(
    session_data: dict[str, Any], user_id: Any, role: Any
) -> bool:
    """問診 WS 的 row-level 授權（純函式，與 REST _authorize_session_access 同模型）。

    - admin：放行
    - doctor：場次未指派醫師、或指派醫師即本人 → 放行
    - patient：場次病患的 user_id 即本人 → 放行
    - 其餘（含 role 缺失 / user_id 缺失）→ 拒絕（fail-closed）
    """
    if not user_id:
        return False
    role_value = getattr(role, "value", role)
    uid = str(user_id)
    if role_value == "admin":
        return True
    if role_value == "doctor":
        doctor_id = session_data.get("doctor_id")
        return doctor_id is None or str(doctor_id) == uid
    if role_value == "patient":
        patient_user_id = session_data.get("patient_user_id")
        return patient_user_id is not None and str(patient_user_id) == uid
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


# ── BLOCKER F：收尾輪「不得發問」的確定性 backstop ───────────────────
# 收尾輪（conclude=True）本來只有 prompt 一層防線：`build_wrap_up_prompt` 的極簡
# 收尾語境 + `format_messages(conclude=True)` 的前後夾擊。實測（2026-07-27 ED 場
# ed_3b_zh 連跑兩次：run1 紅、run2 綠，同一份碼）證明**遵從是機率性的**——
# 只要 LLM 那一輪不從，病患就會拿到一個懸空問句然後被導去感謝頁。
# 更糟：ED 場 effective_hard_cap 正好 15，收尾輪與硬上限重合、零餘裕，沒有下一輪
# 可以補救（DB 裡 2026-07-06 的 ED 場 a5b71326 有同樣的懸空結尾，是長期缺陷）。
#
# 對策：不再加強文案（prompt 靠 LLM 遵從不是結構性保證），改在收尾輪的**輸出路徑**
# 加確定性檢查——命中問句就整段換成制式收尾語，並記 WARNING 讓「LLM 又不從了」
# 可被觀察（可觀測性，不是掩蓋）。
#
# 判準設計（刻意偏向「寧可替換」）：收尾輪本來就不該有新資訊，替換的代價很低；
# 漏抓的代價是病患收到懸空問句。故：
#   1) 任何語言的問號（ASCII / 全形 / CJK 相容字元）→ 一律視為發問，
#      不區分修辭性問句與真發問（分不清時走安全側）。
#   2) 無問號時再比對各語言的疑問句式，但這組 pattern **刻意窄化**，
#      因為它們沒有問號當佐證、誤判成本較高：
#      - ja：`ですか/ますか/ましたか` 需排除接續助詞「〜から」（"大切な情報ですから"
#        是陳述句），故用 negative lookahead。
#      - vi：只留 `phải không / hay không / được không / có không`；
#        刻意不收 `khi nào`（"bác sĩ sẽ cho bạn biết khi nào" 是陳述句）與 `bao lâu`。
#      - en：只認**句首**的疑問助動詞／wh 詞，且刻意排除 have/will/shall
#        （"Have a seat."、"Will be seen shortly." 都是祈使／陳述句）。
#   3) pattern 一律全語言比對、不依 session language 分流：各語言的字元集互斥
#      （嗎／ですか／습니까／không／英文詞邊界），跨語言誤命中可忽略，而 LLM 偶爾
#      回錯語言時仍抓得到。
_WRAP_UP_QUESTION_MARKS = ("?", "？", "﹖", "⁇", "؟")
_WRAP_UP_QUESTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    # zh-TW：疑問語尾助詞與正反問句式
    re.compile(r"嗎|呢|請問|有沒有|是不是|要不要|能不能|可不可以"),
    # ja-JP：丁寧体の疑問形（「〜ですから」等の接続助詞は除外）
    re.compile(r"ますか(?!ら)|ですか(?!ら)|ましたか(?!ら)|でしょうか|いかがですか"),
    # ko-KR：해요体の의문형 어미（격식체 `-ㅂ니까` 는 `_has_korean_formal_question`）
    re.compile(r"나요|까요|인가요|신가요|는지요"),
    # vi-VN：câu hỏi dạng "…không"
    re.compile(r"phải không|hay không|được không|có không", re.IGNORECASE),
    # en-US：句首疑問助動詞／wh 詞（have/will/shall 刻意不收，見上方註解）
    re.compile(
        r"(?:^|[.!;\n]\s*)"
        r"(?:do|does|did|are|is|was|were|has|had|can|could|would|should"
        r"|may|might|any|what|when|where|why|how|which|who)\b",
        re.IGNORECASE,
    ),
)


_HANGUL_BASE = 0xAC00
_HANGUL_COUNT = 11172
_HANGUL_JONGSEONG_B = 17  # 終聲 ㅂ 在 28 個終聲表中的索引


def _has_korean_formal_question(text: str) -> bool:
    """韓文格式體疑問形 `-ㅂ니까`：「니까」前一個音節的終聲必須是 ㅂ。

    只比對「니까」會誤抓連結어미（「진행되니까」＝因為…，是陳述句）；
    只列舉「습니까／입니까」又會漏掉「계십니까／갑니까」這類（實測漏抓）。
    故用終聲判斷，兩個方向都準。
    """
    idx = text.find("니까")
    while idx > 0:
        code = ord(text[idx - 1]) - _HANGUL_BASE
        if 0 <= code < _HANGUL_COUNT and code % 28 == _HANGUL_JONGSEONG_B:
            return True
        idx = text.find("니까", idx + 1)
    return False


def _looks_like_question(text: str) -> bool:
    """收尾輪輸出是否含問句（各語言問號 + 窄化的疑問句式）。

    純函式，供 `_handle_text_message` 的收尾 backstop 使用；判不準時偏向回 True
    （替換成制式收尾語的代價遠低於讓病患收到懸空問句）。
    """
    if not text:
        return False
    if any(mark in text for mark in _WRAP_UP_QUESTION_MARKS):
        return True
    if any(p.search(text) for p in _WRAP_UP_QUESTION_PATTERNS):
        return True
    return _has_korean_formal_question(text)


# A3：紅旗 gate 的同步等待秒數。原為 _handle_text_message 內局部常數 3.5，
# 抬升為模組常數以利單元測試 monkeypatch（值與行為不變）。
_RED_FLAG_WAIT_TIMEOUT: float = 3.5

# ── 紅旗語意層用的跨輪對話摘要（session_context["conversation_summary"]）─────
# red_flag_detector._semantic_detect 會把它以「先前對話（依時間排序）：」放進 LLM
# 的病患背景（消費端的正規化／截斷見該檔 `_format_conversation_summary`），
# 但這個 key 過去從來沒有人寫入 → 語意層永遠只看得到「本輪單句 + 主訴字串」，
# 跨輪累積型急症（前輪講發燒、本輪講腰痛＝urosepsis）偵測不到。
# 長度必須有上限：整場逐字稿塞進紅旗 prompt 會燒 token，也會稀釋最新症狀。
_CONVERSATION_SUMMARY_MAX_TURNS: int = 4  # 最近 4 組來回（病患＋AI 各算一則 → 8 則）
_CONVERSATION_SUMMARY_MAX_CHARS: int = 1200  # 摘要總長度上限
_CONVERSATION_SUMMARY_ENTRY_MAX_CHARS: int = 200  # 單則發言長度上限
_PATIENT_ROLES = ("patient", "user")


def _build_conversation_summary(
    history: list[dict[str, Any]],
    *,
    max_turns: int = _CONVERSATION_SUMMARY_MAX_TURNS,
    max_chars: int = _CONVERSATION_SUMMARY_MAX_CHARS,
    entry_max_chars: int = _CONVERSATION_SUMMARY_ENTRY_MAX_CHARS,
) -> str:
    """把最近幾輪對話壓成紅旗語意層可讀的多行摘要字串。

    格式（每則一行，最舊在上、最新在下）::

        病患：早上開始發燒到三十九度
        AI：發燒有多久了？
        病患：現在右邊腰很痛

    取最後 ``max_turns * 2`` 則（病患／AI 各算一則），單則超過 ``entry_max_chars``
    截斷並補「…」；組完若總長超過 ``max_chars`` 就從最舊那端逐則丟掉（保留最新，
    因為紅旗判斷的是「現在」的急症風險）。沒有可用內容時回空字串，呼叫端據此
    決定不要寫入這個 key（`_semantic_detect` 對空字串會略過整行）。

    不含摘要壓縮後的 system/summary 角色：`_cap_conversation_history` 會把舊輪
    壓成單則 role="system" 的摘要，那是給主 LLM 的，塞進紅旗 prompt 只會混淆。
    """
    if not history:
        return ""
    dialog = [
        e
        for e in history
        if isinstance(e, dict)
        and e.get("role") in (*_PATIENT_ROLES, "assistant", "ai")
        and str(e.get("content") or "").strip()
    ]
    if not dialog:
        return ""

    lines: list[str] = []
    for entry in dialog[-(max_turns * 2) :]:
        speaker = "病患" if entry.get("role") in _PATIENT_ROLES else "AI"
        content = " ".join(str(entry.get("content")).split())
        if len(content) > entry_max_chars:
            content = content[:entry_max_chars] + "…"
        lines.append(f"{speaker}：{content}")

    # 總長度上限：從最舊那端丟，保留最新的輪次。
    while lines and sum(len(x) for x in lines) + len(lines) - 1 > max_chars:
        lines.pop(0)
    return "\n".join(lines)


# ── 自動結束政策與紅旗去重已抽到 app/pipelines/{conclusion_policy,alert_dedup}.py ──
# 這裡以底線別名 re-import，保持既有呼叫端與測試（ch._should_auto_conclude 等）相容。
from app.pipelines.conclusion_policy import (  # noqa: E402
    coerce_hpi_pct as _coerce_hpi_pct,
    effective_hard_cap as _effective_hard_cap,
    hard_cap_reached as _hard_cap_reached,
    session_risk_factor_count as _session_risk_factor_count,
    should_auto_conclude as _should_auto_conclude,
    should_conclude_now as _should_conclude_now,
)
from app.pipelines.alert_dedup import (  # noqa: E402
    RED_FLAG_SEVERITY_RANK as _RED_FLAG_SEVERITY_RANK,
    SESSION_EMITTED_RED_FLAGS_KEY as _SESSION_EMITTED_RED_FLAGS_KEY,
    alert_dedup_identity as _alert_dedup_identity,
    record_emitted_alert as _record_emitted_alert,
    should_suppress_duplicate_alert as _should_suppress_duplicate_alert,
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

        # ── 步驟 2.5：row-level 授權（與 REST _authorize_session_access 同模型）──
        # 未授權回與「不存在」相同的 close code，避免場次存在性洩漏。
        if not _authorize_ws_session_access(
            session_data, user_id, payload.get("role")
        ):
            logger.warning(
                "問診 WS 授權拒絕 | session=%s, user=%s", session_id, user_id
            )
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
            # BLOCKER #2：紅旗警示要不要 fan-out 給全體在職醫師，取決於本場次
            # 有沒有指派醫師（kiosk 恆為 NULL）。`_validate_session` 已撈回來，
            # 帶進 context 免得 `_persist_and_emit_alert` 每則警示再 SELECT 一次。
            "doctor_id": session_data.get("doctor_id"),
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
                            await _finalize_idle_timeout(
                                db=db,
                                redis=redis,
                                session_id=session_id,
                                idle_timeout_seconds=idle_timeout_seconds,
                            )
                        except Exception:
                            logger.warning(
                                "閒置逾時收尾失敗 | session=%s",
                                session_id,
                                exc_info=True,
                            )
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
                    # EM-4：與其他終態路徑（`_finalize_red_flag_abort`／自動結束／
                    # `_finalize_idle_timeout`）對齊三件事：
                    #   (1) 先查 `_terminated` 前置守衛：紅旗中止／自動結束已收尾的
                    #       場次再收到一則 end_session（病患連點、或前端在收到終態
                    #       事件前就送出），以前會再跑一整套 —— 重複 dashboard
                    #       `session_status_changed`、重複推 queue/stats、重複派 SOAP。
                    if session_context.get("_terminated"):
                        logger.info(
                            "場次已終止（%s），end_session 指令略過重複收尾 | session=%s",
                            session_context.get("_terminated"),
                            session_id,
                        )
                        break
                    #   (2) 尊重 CAS 回傳：以前完全忽略，於是「場次早已是
                    #       aborted_red_flag / cancelled（REST 取消、逾時清理）」時，
                    #       仍照樣對病患端送 completed、對 dashboard 廣播 completed
                    #       —— 醫師端排隊清單看到的是一場「已完成」的紅旗中止場次。
                    #       CAS 未命中就什麼都不送（終態的 fan-out 屬於真正完成轉移
                    #       的那條路徑）。
                    transitioned = await _update_session_status(
                        db, redis, session_id, "completed", "in_progress"
                    )
                    if not transitioned:
                        logger.info(
                            "end_session CAS 未命中（場次已是終態或轉移失敗），"
                            "不送 completed、不廣播、不派 SOAP | session=%s",
                            session_id,
                        )
                        break
                    #   (3) 成功轉移才設 `_terminated`，且**先標再送**（與紅旗中止
                    #       分支同一理由）：下面三個 await 期間背景 late-critical
                    #       drain 可能插隊，看不到旗標就會再跑一套 abort 收尾。
                    session_context["_terminated"] = "completed"
                    await manager.send_localized_to_session(
                        session_id,
                        msg_type="session_status",
                        code="events.session.ended_by_user",
                        params={},
                        severity="info",
                        # 少了 status，病患端的 session_status handler 認不出這是終態，
                        # 按「結束問診」畫面不會有反應。其他終態路徑都有帶（見 extra 的用途說明）。
                        extra={"status": "completed", "previousStatus": "in_progress"},
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
                    # 觸發 SOAP 報告非同步生成（必須持強參照：下一行就 break 出
                    # 主迴圈，裸 create_task 可能在跑起來前被 GC 掉）
                    _spawn_background(
                        _generate_soap_report_async(session_id=session_id)
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
    message_id = str(uuid.uuid4())
    session_language = session_context.get("language")
    notice_key = _SESSION_TERMINATED_NOTICE_KEYS.get(
        terminated_status, "ws.session_terminated_completed_notice"
    )
    # BLOCKER #2：aborted_red_flag 的版本明說「已通知現場醫護人員」。只有在本場次
    # 真的建立過 RED_FLAG 通知（`_persist_and_emit_alert` 的 fan-out 回傳 > 0）時
    # 才可以這樣講；fan-out 建了 0 筆（查無在職醫師 / 寫入失敗）就退到只陳述
    # 「已標記在紀錄中」的版本。kiosk 情境病患就在現場，這句話他會當真。
    if notice_key == "ws.session_terminated_aborted_notice" and not session_context.get(
        "_red_flag_notified_titles"
    ):
        notice_key = "ws.session_terminated_aborted_notice_unnotified"
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


# ── 閒置逾時收尾 ─────────────────────────────────────────
async def _finalize_idle_timeout(
    *,
    db: AsyncSession,
    redis: Redis,
    session_id: str,
    idle_timeout_seconds: int,
) -> bool:
    """閒置逾時的場次收尾：告知病患 → 轉 completed →（轉成功才）通知＋派 SOAP。

    回傳是否真的把場次從 in_progress 轉成 completed（compare-and-set 命中）。

    以前這裡只做「送 idle 提示 + 改狀態」兩件事，於是：
    - **沒有 SOAP**。會生成報告的路徑只有 end_session、自動結束、critical 中止、
      硬上限前遲到 critical 四條，閒置是漏掉的第五條 —— 場次終態是 completed，
      soap_reports 卻永遠沒有那一列，醫師端等不到報告。
    - 病患端那則 `session_status` 不帶 `status`（`connection_manager` 只在有 extra
      時才把 status 併進 payload），前端 `on('session_status')` 認不出終態；WS 隨即
      被 4000 關掉 → 畫面停在對話頁並不斷重連。
    - 儀表板收不到 `session_status_changed` / queue / stats，醫師端排隊清單留著一
      筆早已結束的場次。

    每一步各自 try/except：任何一步失敗都不可讓看門狗死掉（後面還要關 WS）。

    不變式 #20「六件事」在本路徑的第 6 件（**設 `_terminated`**）：**不適用**。
    本函式跑在閒置看門狗 task 裡，拿不到主迴圈的 `session_context`（那是
    `conversation_websocket` 的區域變數，只傳給 `_handle_*` 系列）；而且收尾完
    下一步就是 `websocket.close(4000)`，主迴圈會直接以 WebSocketDisconnect 收工，
    沒有「下一輪訊息」需要被旗標攔下。刻意省略，不是漏做。
    """
    try:
        await manager.send_localized_to_session(
            session_id,
            msg_type="session_status",
            code="events.session.idle_timeout",
            params={"minutes": int(idle_timeout_seconds // 60)},
            severity="warning",
        )
    except Exception:
        logger.warning("閒置逾時提示送出失敗 | session=%s", session_id, exc_info=True)

    try:
        transitioned = await _update_session_status(
            db, redis, session_id, "completed", "in_progress"
        )
    except Exception:
        logger.error("閒置逾時狀態轉移失敗 | session=%s", session_id, exc_info=True)
        return False

    if not transitioned:
        # CAS 未命中＝場次早已是終態（紅旗中止 / 已完成），該路徑已派過 SOAP。
        return False

    try:
        # 病患端終態訊號（帶 status 前端才會導離對話頁）。
        await manager.send_localized_to_session(
            session_id,
            msg_type="session_status",
            code="events.session.idle_timeout",
            params={"minutes": int(idle_timeout_seconds // 60)},
            severity="warning",
            extra={"status": "completed", "previousStatus": "in_progress"},
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
    except Exception:
        logger.warning(
            "閒置逾時通知推播失敗（非致命） | session=%s", session_id, exc_info=True
        )

    # 派 SOAP —— 這是本函式存在的主因，不可被上面任何非致命失敗擋掉。
    _spawn_background(_generate_soap_report_async(session_id=session_id))
    return True


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
    # patient_turns 此時已含剛 append 的本輪病患訊息；硬上限（一般 10、§3b 高風險主訴
    # 最多約 15）遠小於歷史摘要門檻(CONVERSATION_HISTORY_MAX_TURNS=50)，故由
    # conversation_history 計數準確。
    patient_turns = sum(
        1 for e in conversation_history if e.get("role") in ("patient", "user")
    )
    # §3b：高風險主訴（血尿/PSA/ED）把 cap 動態抬高，讓 HPI 十欄問完後仍有回合問到
    # 關鍵風險因子；一般主訴 K=0、cap 不變。
    risk_factor_count = _session_risk_factor_count(session_context)
    should_conclude = _should_auto_conclude(
        supervisor_guidance, patient_turns, settings, risk_factor_count
    )

    # 格式化訊息並呼叫 LLM。收尾輪改用「極簡收尾 prompt」——移除 HPI/次要補問/風險因子
    # 等 questioning 框架，避免它們在收尾輪與收尾指示競爭而讓 LLM 硬問一題（實測 ED 場
    # 反覆問次要用藥問題）。收尾規則由 format_messages(conclude=True) 前後夾擊注入。
    active_system_prompt = (
        llm_engine.build_wrap_up_prompt(session_context.get("language"))
        if should_conclude
        else system_prompt
    )
    messages = llm_engine.format_messages(
        conversation_history,
        active_system_prompt,
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
    # 先把「前幾輪」壓成摘要寫進 session_context，語意層才看得到跨輪累積的急症線索
    # （前輪發燒 + 本輪腰痛＝urosepsis）。本輪這句已由 detect(text, …) 單獨帶入，
    # 故摘要刻意排除剛 append 的最後一則，避免同一句在 prompt 裡重複兩次。
    _summary = _build_conversation_summary(conversation_history[:-1])
    if _summary:
        session_context["conversation_summary"] = _summary
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
            # （`_i18n_get` 已在模組層 import；這裡再 import 一次會讓它變成
            #   `_handle_text_message` 的區域變數，`_persist_and_emit_alert`
            #   閉包引用時就 NameError。）

            used_empty_fallback = True
            full_response = _i18n_get("ws.ai_empty_retry_fallback", session_language)
            _spawn_tts_task(full_response)
    # 不可 early-return：後續歷史寫入 / 紅旗 gate / TTS chunk / ai_response_end 照走。

    # ── BLOCKER F：收尾輪「不得發問」的確定性 backstop ────────────────
    # prompt（極簡收尾 system prompt + 前後夾擊的收尾規則）只是機率性防線：實測同一
    # 份碼跑兩次，一次收尾輪硬問了一題、病患留下懸空問句就被導去感謝頁。ED 場的
    # effective_hard_cap 與收尾輪重合（15）→ 零餘裕，沒有下一輪能補救。
    # 這裡在輸出路徑做確定性攔截：命中問句就整段換成制式收尾語（5 語齊全、符合
    # kiosk 措辭「請依現場人員的安排稍候看診」），並記 WARNING 讓不遵從可被觀察。
    #
    # 刻意排除 `used_empty_fallback`：那條路徑的 fallback 文案本身就是一句「請您再說
    # 一次」的提問（A1 [D5] 的設計），且 used_empty_fallback 會讓軟門檻收尾被
    # soft_defer 否決（場次多半不會在本輪結束）——替換掉會讓病患收到「已經結束」卻
    # 又被繼續問。兩條 fallback 各自負責，不互相覆寫。
    #
    # 換掉 full_response 前必須連同 in-flight TTS 一起作廢並整句重排（與空回應
    # fallback 同一套處理）：否則病患會「聽到」原本那句問句，只是螢幕文字被換掉。
    # 整句 _spawn_tts_task 不走切句 —— _SENTENCE_BOUNDARY_CHARS 是 CJK-only。
    if should_conclude and not used_empty_fallback and _looks_like_question(full_response):
        logger.warning(
            "收尾輪 LLM 仍發問，改送制式收尾語 | session=%s, patient_turns=%s, "
            "hard_cap=%s, llm_output=%r",
            session_id,
            patient_turns,
            _effective_hard_cap(settings, risk_factor_count),
            full_response[:200],
        )
        for _t in pending_tts_tasks:
            if not _t.done():
                _t.cancel()
        pending_sentences.clear()
        pending_tts_tasks.clear()
        full_response = _i18n_get(
            "ws.session_terminated_completed_notice", session_language
        )
        _spawn_tts_task(full_response)

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
    # SO-3：背景 drain 的「持久化階段已跑完」訊號。硬上限 inline drain 解析出
    # late-critical 時要等它 set 之後才收尾派 SOAP，否則 SOAP 會在 red_flag_alerts
    # 尚未 commit 時就開始生成（報告漏掉觸發中止的那面紅旗）。
    late_persist_done: asyncio.Event | None = None
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
                # 語意層在 red_flag_detector 產出的 LLM 原判（model / raw_title /
                # raw_severity / matched_catalogue / description），是 severity floor
                # 與 title 重解析「之前」的值。AlertService.create 與 red_flag_alerts
                # 都早就支援這一欄，只有這裡沒帶 → DB 該欄永遠 NULL、事後無從覆核
                # 「LLM 本來判什麼、被規則層改成什麼」。
                "llm_analysis": alert.get("llm_analysis"),
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

        # ── BLOCKER #2：先讓「已通知醫護」變成真的，再決定要對病患講哪一句 ──
        # `AlertService.create` 附帶的那則 RED_FLAG 通知只在 `sessions.doctor_id`
        # 有值時才建，而院內 kiosk 場次恆為 NULL → 實測 notifications 表 0 筆。
        # 未指派時改 fan-out 給所有在職醫師（沿用 critical 中止路徑已採用的模型）。
        #
        # 為什麼「每一則」警示都通知，而不只 critical/high：病患端橫幅對任何嚴重度
        # 都會顯示同一段提示，只補 critical/high 會讓 medium/low 那幾則繼續說謊；
        # 且 `AlertService.create` 對「已指派醫師」的場次本來就是每則都通知，這裡
        # 只是把未指派場次補回同一語意。跨輪去重（上方 `_should_suppress_duplicate_alert`）
        # 已擋掉同一 canonical 紅旗重覆 emit，通知量＝每場次的相異紅旗數，不是每輪。
        notified_count = 0
        _session_doctor_id = session_context.get("doctor_id")
        try:
            if _session_doctor_id is not None:
                # 已指派：`AlertService.create` 在同一交易內建過了（上面 commit 成功
                # 才走到這裡），再建一次會變成同一事件兩則通知。
                notified_count = 1
            else:
                notified_count = await _notify_doctors_red_flag(
                    target_db,
                    session_id=session_id,
                    doctor_id=None,
                    language=session_context.get("language"),
                    red_flag_reason=resolved_title,
                    extra_data={"alert_id": alert_id, "severity": alert["severity"]},
                )
                await target_db.commit()
        except Exception:
            notified_count = 0
            logger.warning(
                "紅旗醫師通知建立失敗（非致命，警示已持久化） | session=%s, alert=%s",
                session_id,
                alert_id,
                exc_info=True,
            )
            try:
                await target_db.rollback()
            except Exception:
                pass
        if notified_count:
            # 供 `_finalize_red_flag_abort` 去重（同一紅旗不重複 fan-out）與
            # `_notify_session_already_terminated` 選擇終止提示文案用。
            session_context.setdefault("_red_flag_notified_titles", set()).add(
                resolved_title
            )

        # BLOCKER #3：病患端 payload 結構性只送病患需要的欄位。
        # `description` / `suggestedActions` 是 LLM 自由生成的醫師向臨床內容
        # （真跑 t8 實測 suggestedActions[4]＝「立即安排急診評估」），不是靠禁字
        # 黑名單過濾——換個講法就繞過去了——而是**根本不送**。醫師端（dashboard
        # 廣播）與 DB（red_flag_alerts）保留完整內容，資訊沒有變少。
        # patientNotice 依「有沒有真的建立醫師通知」二選一（見 i18n_messages 註解）。
        await manager.send_to_session(
            session_id,
            {
                "type": "red_flag_alert",
                "payload": {
                    "alertId": alert_id,
                    "severity": alert["severity"],
                    "title": resolved_title,
                    "patientNotice": _i18n_get(
                        "ws.red_flag_patient_notice_notified"
                        if notified_count
                        else "ws.red_flag_patient_notice_flagged",
                        session_context.get("language"),
                    ),
                },
            },
        )

        # P0-1（2026-07-19 架構修復）：改走 Redis pub/sub 橋接——生產 4 個 uvicorn
        # worker 行程，in-memory broadcast 只送得到同行程的 dashboard 連線（3/4
        # 機率醫師收不到即時紅旗）。橋接與 queue_updated/report_generated 同一條路。
        await manager.broadcast_dashboard_event(
            "new_red_flag",
            {
                "alertId": alert_id,
                "sessionId": session_id,
                # fallback 改成空字串而非中文「未知」,讓 dashboard 前端依 locale
                # 決定顯示字樣（Unknown / 未知 / Inconnu …）,不要在後端送中文。
                "patientName": session_context.get("patient_info", {}).get("name")
                or "",
                "severity": alert["severity"],
                "title": resolved_title,
                "description": alert["description"],
            },
        )
        # A5 [D3]：record-on-success — DB 持久化 + 廣播皆未拋例外才記錄去重身份。
        # send_to_session 回 False（病患 WS 已關，drain 情境常見）仍記錄：
        # 去重目的在防重複 DB row / 儀表板轟炸，DB 已寫成功即記。
        await _record_emitted_alert(redis, session_id, alert)
        return alert_id

    async def _finalize_red_flag_abort(
        *,
        status_db: AsyncSession,
        red_flag_reason: str | None,
    ) -> None:
        """critical 紅旗中止場次的收尾——五件事，缺一不可，三條路徑共用。

        呼叫者有三條：
        1. 主 abort 分支（本輪 3.5s 內就等到 critical）；
        2. `_drain_late_red_flags`（偵測慢於 gate，主迴圈可能已結束）；
        3. 硬上限收尾前的 inline drain 解析出 late-critical。

        以前是三份手抄，於是各漏各的：drain 那份只改 DB 狀態＋設 `_terminated`，
        **不生成 SOAP、不通知病患端、不廣播 dashboard**——場次停在 aborted_red_flag
        卻連一列 soap_reports 都沒有（主迴圈 finally 不生；病患下一則訊息撞
        `_terminated` 守衛直接 return 也不生），醫師端永遠等不到報告；inline drain
        那份則漏了 `extra`，`connection_manager` 只在有 extra 時才把 status 併進
        payload，病患端 `on('session_status')` 認不出終態 → 卡在對話頁 + 無限重連。

        `status_db`：寫狀態／查 queue-stats 用的 session。drain 情境 WS 的 db 已被
        `get_db` 關閉，必須傳 drain 自有的那個。

        **CAS 回傳值必須被尊重**（覆核指出本函式原本忽略它，與同批新增的
        `_finalize_idle_timeout` 不一致）：三條路徑競態時（例如主 abort 已收尾、
        背景 drain 隨後又解析出同一則 critical），第二次呼叫的 CAS 必然 miss，
        此時再廣播一次就是 dashboard 重複 `session_status_changed`、重複推 queue/
        stats、重複派 SOAP。只有「確實由本次呼叫完成 in_progress → aborted_red_flag」
        才做那三件事。

        病患端的 `session_status` 例外：它在 CAS miss 時仍會送，因為
        `_update_session_status` 回 False 也可能是 DB 例外（場次其實還停在
        in_progress）——那時不告知病患會讓 kiosk 畫面卡在對話頁。重複送出由
        下方的 `_terminated` 前置守衛擋掉（同一連線只會走到這裡一次）。
        """
        # in-process 去重：三條路徑共用同一個 `session_context`，第一次收尾就會把
        # `_terminated` 標起來。這道守衛讓「重複病患端 abort 事件」在同一連線內
        # 結構性不可能發生（不倚賴 DB 狀態，DB 掛掉時也成立）。
        if session_context.get("_terminated"):
            logger.info(
                "紅旗中止收尾已由其他路徑完成，略過重複收尾 | session=%s, terminated=%s",
                session_id,
                session_context.get("_terminated"),
            )
            return

        # E8-1：標記本連線場次已終止（不論下面 CAS 是否真的轉移成功——即使因競態
        # 已被別的路徑轉走，場次現在也一定是終態），讓「下一輪」訊息進
        # _handle_text_message / _handle_audio_chunk 時被開頭的守衛攔下，不再重新
        # 跑一次紅旗/LLM/重發 abort 事件。
        #
        # 先標再做，**含 `_update_session_status` 這個 await 在內**：上面的守衛與
        # 這行之間不能有任何 await，否則兩條路徑（背景 late-critical drain vs 硬
        # 上限 inline drain）可以同時通過守衛，各自跑一整套收尾 —— 病患收到兩則
        # 終態、dashboard 兩則 session_status_changed。以前這行在 CAS 之後，那段
        # await 就是那個窗口；SO-3 讓 inline drain 改為等 drain 持久化完成之後才
        # 收尾，兩者的交會時間點正好落在這裡。
        session_context["_terminated"] = "aborted_red_flag"
        transitioned = await _update_session_status(
            status_db,
            redis,
            session_id,
            "aborted_red_flag",
            "in_progress",
            red_flag_reason=red_flag_reason,
            # BLOCKER #2 去重：這則 critical 若已在 `_persist_and_emit_alert`
            # fan-out 過（同場次、同 title、同一批醫師），不要再建第二則通知。
            notify_doctors=red_flag_reason
            not in session_context.get("_red_flag_notified_titles", ()),
        )
        await manager.send_localized_to_session(
            session_id,
            msg_type="session_status",
            code="events.session.aborted_red_flag",
            params={},
            severity="critical",
            # 帶終態 status → 前端導離對話頁（不再卡在「使用中」+ 無限重連）。
            extra={"status": "aborted_red_flag"},
        )
        # 紅旗中止場次同樣需要報告供醫師審閱。刻意放在 CAS 判斷「之前」：
        # `_update_session_status` 回 False 也可能是 DB 例外（場次仍 in_progress），
        # 那時把 SOAP 一起跳過會讓醫師端永遠等不到報告。重複派送無害——冪等由
        # `_generate_soap_report_async` 的存在性檢查 + soap_reports UNIQUE 保護。
        _spawn_background(_generate_soap_report_async(session_id=session_id))
        if not transitioned:
            # CAS 未命中＝場次早已是終態（另一條 abort/結束路徑先到），那條路徑
            # 已經廣播過 dashboard、推過 queue/stats。這兩件事沒有冪等保護，
            # 重複做就是醫師端排隊清單抖動 + 重複的 session_status_changed。
            logger.info(
                "紅旗中止 CAS 未命中（場次已是終態或轉移失敗），略過重複 dashboard 廣播 | session=%s",
                session_id,
            )
            return
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
        await _broadcast_dashboard_queue_and_stats(status_db, redis)

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
            late_persist_done = asyncio.Event()
            _persist_done_signal = late_persist_done

            async def _drain_late_red_flags() -> None:
                # SO-3：不論走哪個 return / 例外路徑，離開時一定要放行等在
                # `late_persist_done` 上的硬上限 inline drain（否則它只能靠逾時
                # fallback 才會繼續，白等一段）。
                try:
                    await _drain_late_red_flags_inner()
                finally:
                    _persist_done_signal.set()

            async def _drain_late_red_flags_inner() -> None:
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
                        # SO-3：持久化階段（含 commit）到此結束——先放行硬上限 inline
                        # drain，再做自己的收尾。放在 `_finalize_red_flag_abort` 之前
                        # 是刻意的：兩條路徑誰先收尾都行（`_terminated` 去重擋掉第二次），
                        # 但「SOAP 派送時 red_flag_alerts 已 commit」必須先成立。
                        _persist_done_signal.set()
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
                            logger.warning(
                                "遲到的 critical 紅旗，中止場次 | session=%s",
                                session_id,
                            )
                            # 與主 abort 分支同一組收尾（狀態＋病患端終態＋dashboard
                            # ＋queue/stats＋SOAP＋_terminated）。過去這裡只做了狀態
                            # 與 _terminated 兩件，導致場次 aborted 卻無 SOAP。
                            await _finalize_red_flag_abort(
                                status_db=drain_db,
                                red_flag_reason=late_critical_title,
                            )
                except Exception as exc:
                    logger.error(
                        "背景紅旗 drain 失敗 | session=%s, error=%s",
                        session_id,
                        str(exc),
                    )

            # 強參照：本輪 return 後主迴圈可能立刻結束，裸 create_task 的 drain
            # 有機會在跑起來前被 GC 掉 → 遲到的急症紅旗連持久化都不會發生。
            _spawn_background(_drain_late_red_flags())

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
            await _finalize_red_flag_abort(
                status_db=db, red_flag_reason=critical_title
            )
            # EM-1：**必須 return**，不可 fall-through 進下方自動結束區塊。
            # `_finalize_red_flag_abort` 的 CAS 若因 DB 例外失敗（場次其實還停在
            # in_progress），fall-through 後下方 `_update_session_status(completed,
            # in_progress)` 的 CAS 就會命中 → 剛判定 critical 中止的場次被**降級成
            # completed**，抹掉醫師端的紅旗分流訊號，還會對病患端送一則 completed
            # （紅旗中止的病患該看到的是「請告知現場醫護」而不是一般感謝頁）。
            # 回 True＝呼叫端結束主迴圈（與其他終態路徑同語意）。
            return True

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
    hard_cap_reached = _hard_cap_reached(patient_turns, settings, risk_factor_count)
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
                # SO-3：**先等 drain 把 late alerts persist + commit 完，再收尾**。
                # 本路徑刻意不自己 persist（交給已在跑的 `_drain_late_red_flags`，
                # 避免 double-persist 競態），但 `_finalize_red_flag_abort` 會立刻
                # `generate_soap_report.delay()`——以前沒有這道等待，Celery worker
                # 常在 alert 那筆 INSERT commit 之前就 SELECT 完 red_flag_alerts，
                # 生出來的 SOAP 少掉「觸發本次中止的那面 critical 紅旗」。順序對齊
                # 主 abort 分支與背景 drain 的「先持久化再派 SOAP」。
                #
                # 有界等待：drain 端不論成功/失敗/無 alert 都會在 finally set 這個
                # Event，正常情況幾乎立刻返回。逾時仍照舊收尾——保命線（硬上限一定
                # 要出得了 SOAP）優先於報告完整性，`asyncio.shield` 也不受影響。
                if late_persist_done is not None:
                    try:
                        await asyncio.wait_for(
                            late_persist_done.wait(),
                            timeout=float(
                                getattr(
                                    settings, "HARD_CAP_DRAIN_AWAIT_SECONDS", 5.0
                                )
                            ),
                        )
                    except asyncio.TimeoutError:
                        logger.error(
                            "等待遲到紅旗持久化逾時，仍照常收尾（SOAP 可能少一面紅旗） | session=%s",
                            session_id,
                        )
                # 與主 abort 分支完全相同的收尾組（含病患端終態 extra——這裡以前
                # 漏帶，病患會卡在對話頁）。
                await _finalize_red_flag_abort(
                    status_db=db, red_flag_reason=late_critical_title
                )
                return True
            # late_alerts 不併入 red_flag_alerts：非 critical 由 _drain_late_red_flags
            # 持久化/廣播，避免重跑上方 abort 區塊或 double-persist。

    if _should_conclude_now(should_conclude, hard_cap_reached, soft_defer, drain_unresolved):
        transitioned = await _update_session_status(
            db, redis, session_id, "completed", "in_progress"
        )
        if transitioned:
            # EM-5：**先標再送**（與 `_finalize_red_flag_abort` :「先標再送，避免下方
            # 任一 await 期間有其他路徑插隊重入」同一理由）。以前這行放在下面三個
            # await（病患端 session_status → dashboard 廣播 → queue/stats）之後，
            # 那段窗口內背景 late-critical drain 可以插隊：它看不到 `_terminated`，
            # 於是跑完整套 abort 收尾（含病患端 aborted 訊息與第二份 SOAP 派送），
            # 病患在同一秒收到 completed 與 aborted_red_flag 兩則終態。
            session_context["_terminated"] = "completed"
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
            # 強參照：下一行 return True 會結束主迴圈（見 _spawn_background）。
            _spawn_background(
                _generate_soap_report_async(session_id=session_id)
            )
            return True

    return False


# ── 輔助函式 ─────────────────────────────────────────────

async def _generate_soap_report_async(*, session_id: str) -> None:
    """問診結束後的 SOAP 生成觸發（P0-2 架構修復，2026-07-19）。

    舊版在 API 行程內 inline 跑 LLM 生成：Railway 重新部署／行程回收會讓生成中
    的報告無聲消失，且失敗只記 log、無 retry、無 FAILED 標記。改為
    「建 GENERATING row → 派既有 Celery generate_soap_report 任務」：
    - 生成本體由 tasks/report_queue 執行（acks_late + retry ×2 + on_failure 標
      FAILED + report_generated 儀表板事件 + REPORT_READY 通知），行程重啟不遺失。
    - 同時消滅 WS／Celery 雙路徑的內容漂移（transcript／red_flags／summary／
      symptom_id／language 全部單一來源＝report_queue._async_generate）。

    冪等：早期存在性檢查 + soap_reports.session_id UNIQUE。撞 UNIQUE＝另一條
    結束路徑（end_session／閒置逾時／critical 中止／自動結束）已觸發，略過即可。
    """
    from uuid import UUID

    from sqlalchemy import select
    from sqlalchemy.exc import IntegrityError

    from app.core.database import get_db_session
    from app.models.enums import ReportStatus, ReviewStatus
    from app.models.soap_report import SOAPReport
    from app.utils.datetime_utils import utc_now

    try:
        async with get_db_session() as db:
            _existing = await db.execute(
                select(SOAPReport.id).where(SOAPReport.session_id == UUID(session_id))
            )
            if _existing.scalar_one_or_none() is not None:
                logger.info(
                    "SOAP 已存在或生成中，跳過重複觸發 | session=%s", session_id
                )
                return
            now = utc_now()
            db.add(
                SOAPReport(
                    session_id=UUID(session_id),
                    status=ReportStatus.GENERATING,
                    review_status=ReviewStatus.PENDING,
                    created_at=now,
                    updated_at=now,
                )
            )
            # get_db_session() 於 context 結束時自動 commit
    except IntegrityError:
        logger.info("SOAP 已存在（UNIQUE 撞擊，冪等略過） | session=%s", session_id)
        return
    except Exception:
        logger.error(
            "SOAP GENERATING row 建立失敗 | session=%s", session_id, exc_info=True
        )
        return

    try:
        from app.tasks.report_queue import generate_soap_report

        generate_soap_report.delay(session_id)
        logger.info("已派送 SOAP 生成任務 | session=%s", session_id)
    except Exception:
        # broker 不可用：row 已標 GENERATING（狀態可見），醫師端可手動 regenerate 補救
        logger.error(
            "SOAP 任務派送失敗（row 已標 GENERATING） | session=%s",
            session_id,
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

        # 組合病患資訊（含完整欄位）。組裝邏輯集中在 app/pipelines/patient_context，
        # 與 Celery SOAP 路徑（tasks/report_queue）共用同一份——過去兩邊各有一份、
        # Celery 那份只給 name/gender/age，讓 soap_generator 的病史/用藥/過敏/家族史
        # 四個分支在生產路徑成為死碼（SOAP 家族史恆寫「未提供」）。
        patient = getattr(session_obj, "patient", None)
        patient_info: dict[str, Any] = build_patient_info(
            patient, getattr(session_obj, "intake_data", None)
        )

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
            # WS row-level 授權用（與 REST _authorize_session_access 同一權限模型）
            "patient_user_id": (
                str(patient.user_id)
                if patient is not None and getattr(patient, "user_id", None)
                else None
            ),
            "doctor_id": (
                str(session_obj.doctor_id)
                if getattr(session_obj, "doctor_id", None)
                else None
            ),
        }

    except Exception as exc:
        logger.error(
            "載入場次資料失敗 | session=%s, error=%s",
            session_id,
            str(exc),
            exc_info=True,
        )
        return None



async def _notify_doctors_red_flag(
    db: AsyncSession,
    *,
    session_id: str,
    doctor_id: Any,
    language: str | None,
    red_flag_reason: str | None,
    extra_data: dict[str, Any] | None = None,
) -> int:
    """紅旗事件 → 建立 RED_FLAG 站內通知給醫師，回傳**實際建立**的筆數。

    回傳值是「病患端要不要說『已通知現場醫護人員』」的唯一依據（BLOCKER #2）：
    呼叫端一律以此值挑文案，不可假設通知一定成功。

    為什麼要獨立一條而不是靠 `AlertService.create` 附帶的那則：那則只在
    `sessions.doctor_id` 有值時才建，而院內 kiosk 的場次在問診當下**通常還沒指派
    醫師**（實測 DB 內 sessions.doctor_id 全為 NULL）——結果是病患被告知「已通知
    現場醫護人員」，notifications 表卻 0 筆。

    因此：有指派醫師就通知他；沒有就發給所有在職醫師（未指派佇列的 fan-out）。
    紅旗是病安事件，寧可多人看到也不能沒人看到。`NotificationType.RED_FLAG` 在
    `NotificationService` 不受使用者偏好抑制（病安關鍵，恆送）。

    標題語言沿用 `sessions.language`（與 `AlertService` 既有的紅旗推播一致），
    不另外查每位醫師的 preferred_language —— 避免 N+1 查詢，且兩處紅旗通知
    對同一事件顯示同一語言。

    `extra_data`：併進 notification.data 的額外欄位（如 alert_id / severity），
    讓醫師端可以從通知直接跳到該則警示。

    呼叫端負責 commit；本函式只 flush（沿用 NotificationService 慣例）。
    """
    from uuid import UUID as _UUID

    from sqlalchemy import select

    from app.models.enums import NotificationType, UserRole
    from app.models.user import User
    from app.services.notification_service import NotificationService
    from app.utils.i18n_messages import get_message as _i18n_get

    targets: list[Any] = []
    if doctor_id is not None:
        # `session_context["doctor_id"]` 是字串（`_validate_session` 轉過），
        # `_update_session_status` 的 RETURNING 則是 UUID —— 統一成 UUID 再進 ORM。
        if isinstance(doctor_id, str):
            try:
                doctor_id = _UUID(doctor_id)
            except ValueError:
                logger.warning(
                    "doctor_id 不是合法 UUID，紅旗通知略過 | session=%s, doctor_id=%r",
                    session_id,
                    doctor_id,
                )
                return 0
        targets = [doctor_id]
    else:
        # 未指派醫師 → 發給所有在職醫師。查詢自帶 try/except：查不到不可讓
        # 已 commit 的狀態轉移連帶被外層 except 回滾稽核紀錄。
        try:
            result = await db.execute(
                select(User.id).where(
                    User.role == UserRole.DOCTOR,
                    User.is_active.is_(True),
                )
            )
            targets = list(result.scalars().all())
        except Exception:
            logger.warning(
                "查詢在職醫師失敗，紅旗通知略過 | session=%s",
                session_id,
                exc_info=True,
            )
            return 0

    if not targets:
        logger.error(
            "紅旗事件但沒有任何可通知的醫師（場次未指派且無在職醫師） | session=%s",
            session_id,
        )
        return 0

    reason_text = red_flag_reason or _i18n_get("alert.unknown_title", language)
    title = _i18n_get("alert.push_notification_title", language, title=reason_text)
    payload: dict[str, Any] = {
        "type": "red_flag",
        "session_id": str(session_id),
        "unassigned_fanout": doctor_id is None,
    }
    if extra_data:
        payload.update(extra_data)
    created = 0
    for target_id in targets:
        notification = await NotificationService.create(
            db,
            user_id=target_id,
            type=NotificationType.RED_FLAG,
            title=title,
            body=reason_text,
            data=dict(payload),
        )
        if notification is not None:
            created += 1
    logger.info(
        "紅旗醫師通知已建立 | session=%s, doctors=%d, created=%d",
        session_id,
        len(targets),
        created,
    )
    return created


async def _update_session_status(
    db: AsyncSession,
    redis: Redis,
    session_id: str,
    new_status: str,
    previous_status: str,
    *,
    red_flag_reason: str | None = None,
    notify_doctors: bool = True,
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
        notify_doctors: 轉 aborted_red_flag 時要不要建立醫師 RED_FLAG 通知。
            預設 True。呼叫端在「同一則 critical 已於 `_persist_and_emit_alert`
            fan-out 過」時傳 False，避免同一事件對同一批醫師產生兩則通知。
            其他轉移忽略此參數。

    Returns:
        bool: True 表示確實發生狀態轉移；False 表示目前狀態不符（no-op）或失敗。
    """
    try:
        from app.core.session_state import is_valid_transition
        from app.models.enums import SessionStatus
        from app.models.session import Session
        from sqlalchemy import Integer, func, update

        # 單一權威狀態機（與 REST update_status_static 共用 VALID_TRANSITIONS）：
        # 先前 WS 只靠 compare-and-set 的 WHERE 擋，不查合法轉移表 → 可執行表外轉移。
        #
        # EM-6：`allow_noop` 收斂成「只放行 in_progress 自轉移」。它存在的唯一理由
        # 是 resume 重連的 `in_progress → in_progress` 冪等補寫 started_at
        # （`is_valid_transition` 的 docstring 也只宣稱這一條），但以前無條件傳
        # True，等於連 `completed → completed`、`aborted_red_flag →
        # aborted_red_flag`、`cancelled → cancelled` 都算合法轉移而放行進 UPDATE
        # ——終態表是空 list（`VALID_TRANSITIONS`），任何從終態出發的轉移都該在
        # 這裡就被擋掉。實務上 CAS 的 WHERE 會讓終態自轉移變成無害的 no-op
        # UPDATE，但那是「靠第二道防線兜住第一道的破口」，且會白寫一次 Redis
        # 快取與稽核路徑；宣稱與實作對齊後這個窗口結構性不存在。
        # 非法轉移不 raise（fire-and-forget，不可炸主迴圈），記 warning 後 no-op。
        _in_progress = (SessionStatus.IN_PROGRESS, SessionStatus.IN_PROGRESS.value)
        _noop_allowed = (
            previous_status in _in_progress and new_status in _in_progress
        )
        if not is_valid_transition(
            previous_status, new_status, allow_noop=_noop_allowed
        ):
            logger.warning(
                "非法場次狀態轉移，略過 | %s → %s | session=%s",
                previous_status,
                new_status,
                session_id,
            )
            return False

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
            elif new_status == "aborted_red_flag" and notify_doctors:
                # 病患收到的終止提示原文明說「系統已將…通知現場醫護人員」
                # （ws.session_terminated_aborted_notice），但這條路徑以前一則通知
                # 都不建 —— 實測 notifications 表 0 筆，等於對病患說謊。
                await _notify_doctors_red_flag(
                    db,
                    session_id=session_id,
                    doctor_id=row.doctor_id,
                    language=row.language,
                    red_flag_reason=red_flag_reason,
                    extra_data={"status": "aborted_red_flag"},
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
