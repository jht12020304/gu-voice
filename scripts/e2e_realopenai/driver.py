#!/usr/bin/env python
"""
真 OpenAI 本機 E2E 問診測試 driver。

流程：
  1. 對本機 backend 註冊病患帳號（register API；每情境一個帳號）
  2. POST /api/v1/sessions 建場次（chiefComplaintId + language + patientInfo）
  3. 連 WS ws://127.0.0.1:8000/api/v1/ws/sessions/{sid}/stream?token=...
     （legacy query-param 認證；全程 text_message，不用音訊）
  4. 病患模擬器（openai gpt-4o-mini）依 persona 生成每輪回答
  5. 每輪 AI 回應結束後輪詢 Redis gu:session:{id}:supervisor_guidance（附時間戳）
  6. 收 session_status completed / 病患回合達上限（18）即停，撈 DB 斷言
  7. 全部寫入 results/{scenario}.json

用法：
  cd backend && set -a && source <scratchpad>/e2e/local.env && set +a
  venv/bin/python <scratchpad>/e2e/driver.py dontknow_zh
"""

import asyncio
import json
import os
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
import psycopg2
import redis as redislib
import websockets
from dotenv import dotenv_values
from openai import AsyncOpenAI

E2E_DIR = Path(__file__).resolve().parent
RESULTS_DIR = E2E_DIR / "results"
# §E 驗收：E2E_BACKEND_DIR 可指向修復 worktree 的 backend（其 .env 已複製好，
# OPENAI_API_KEY 從該處讀）；預設原 repo。venv 一律共用主 repo 的 backend/venv。
BACKEND_DIR = Path(
    os.environ.get("E2E_BACKEND_DIR", "/Users/chun/Desktop/GU_0410/backend")
)

API_BASE = os.environ.get("E2E_API_BASE", "http://127.0.0.1:8000/api/v1")
WS_BASE = os.environ.get("E2E_WS_BASE", "ws://127.0.0.1:8000/api/v1/ws")
PG_DSN = os.environ.get(
    "E2E_PG_DSN", "postgresql://postgres:postgres@localhost:55432/gu_voice"
)
REDIS_URL = os.environ.get("E2E_REDIS_URL", "redis://localhost:56379/0")

SIM_MODEL = "gpt-4o-mini"
MAX_PATIENT_TURNS = 18
AI_RESPONSE_TIMEOUT = 240  # 單一 WS 訊息等待上限（LLM+逐句TTS 串起來可能很久）
GUIDANCE_POLL_TIMEOUT = 45  # supervisor timeout 30s + 緩衝
SOAP_POLL_TIMEOUT = 150  # SOAP 為結束後非同步生成（gpt-4o），多等一點

# §E 驗收參數（對齊 backend settings；worktree 若調整可用環境變數覆寫）
HARD_CAP = int(os.environ.get("E2E_HARD_CAP", "10"))  # MAX_PATIENT_TURNS_HARD_CAP
DRAIN_DEFERS = int(os.environ.get("E2E_DRAIN_DEFERS", "2"))  # MAX_HARD_CAP_DRAIN_DEFERS

CC_HEMATURIA = "00000000-0000-4000-8000-0000000000c1"  # 血尿 / Hematuria
CC_FREQUENCY = "00000000-0000-4000-8000-0000000000c2"  # 頻尿 / Frequent urination
CC_SCROTAL = "00000000-0000-4000-8000-0000000000c7"    # 陰囊腫脹 / Scrotal swelling
CC_ED = "00000000-0000-4000-8000-0000000000c8"         # 勃起功能障礙 / ED


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _backend_git_head() -> str | None:
    """記錄受測 backend 的 git HEAD（worktree 驗收時能對上修復 commit）。唯讀操作。"""
    import subprocess

    try:
        out = subprocess.run(
            ["git", "-C", str(BACKEND_DIR), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return out.stdout.strip() or None
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# 情境定義
# ─────────────────────────────────────────────────────────────────────────────

DONTKNOW_ZH_PERSONA = """你是一位68歲男性病患，在泌尿科門診用打字方式做 AI 問診。你的主訴是「頻尿」。

你的病情事實（回答時保持一致）：
- 白天排尿約 10 到 12 次，每次尿量少
- 夜間起床上廁所約 3 次
- 排尿時沒有疼痛、沒有灼熱感
- 尿液顏色正常、沒有血、沒有混濁
- 沒有發燒、沒有腰痛、沒有下腹痛
- 覺得尿完還有殘尿感，尿流有變細變弱
- 喝水量正常，沒有喝特別多咖啡或茶，睡前沒有大量喝水
- 目前沒有服用任何藥物，也沒有在吃利尿劑
- 沒有藥物或食物過敏
- 症狀沒有特別會加重或緩解的因素，久坐後比較明顯
- 家族沒有攝護腺癌病史（如果被問到家族史就這樣答）

硬性規則（最重要，違反就是失敗）：
1. 只要 AI 問到「症狀什麼時候開始 / 開始多久了 / 何時出現 / 持續多久 / 多長時間」這類發生時間或持續時間的問題，你一律回答：「我真的不知道，不記得了。」絕對不要給出任何時間資訊（不要說幾天、幾週、幾個月、最近、以前）。
2. 只要 AI 問到「過去病史 / 以前生過什麼病 / 有沒有慢性病 / 開過刀 / 動過手術」，你一律回答：「不記得了，我真的不知道。」
3. 其他問題依照上面的病情事實正常、配合地回答。
4. 用口語繁體中文回答，每次 1 到 2 句話，不要反問問題，不要主動提供時間相關資訊。
5. 如果 AI 表示問診要結束、請你稍候或道謝，就簡短回「好的，謝謝。」"""

HEMATURIA_EN_PERSONA = """You are a cooperative 62-year-old male patient at a urology clinic doing a typed AI intake interview. Your chief complaint is visible blood in your urine (gross hematuria).

Your facts (stay consistent):
- For the past 3 days you have seen visible, bright red blood in your urine on most urinations.
- No blood clots, just red-tinted urine. It is painless.
- No pain or burning when urinating, no fever, no chills.
- No flank or back pain, no abdominal pain.
- Normal urinary frequency and stream, no urgency, no nighttime urination.
- You have smoked half a pack of cigarettes a day for about 30 years.
- No weight loss, appetite is normal, no fatigue.
- You take amlodipine 5mg daily for high blood pressure. No blood thinners. No other medications.
- No drug or food allergies.
- No previous urologic problems, no kidney stones, no surgeries.
- Nothing makes it better or worse; you have not done any strenuous exercise recently.
- No family history of kidney or bladder cancer.

Rules:
1. Answer every question clearly and cooperatively in English, 1-2 short sentences.
2. Do not ask questions back. Do not volunteer information beyond what was asked.
3. If the AI says the interview is ending or thanks you, reply briefly: "Thank you."
"""

TORSION_ZH_PERSONA = """你是一位30歲男性病患，在泌尿科門診用打字方式做 AI 問診。你的主訴是「陰囊腫脹」。

你的病情事實（回答時保持一致）：
- 大約兩小時前，左邊睪丸「突然」劇烈疼痛，痛到想吐、冒冷汗
- 左側陰囊明顯腫脹，碰到就更痛，走路困難
- 疼痛是持續性的，10 分裡有 9 分痛
- 沒有發燒、沒有排尿問題、沒有外傷、沒有被撞到
- 沒有慢性病、沒有開過刀、沒有在吃藥、沒有過敏

硬性規則：
1. 第一輪回答就要完整講出重點：「大約兩小時前左邊睪丸突然劇烈疼痛，
   陰囊腫起來，痛到想吐，走路都有困難。」不要拆散到後面幾輪才講。
2. 之後被問什麼就照上面事實回答，口語繁體中文，每次 1 到 2 句。
3. 如果 AI 表示要通知醫護、請你稍候或結束問診，就簡短回「好，麻煩快一點，真的很痛。」"""

ED_ZH_PERSONA = """你是一位55歲男性病患，在泌尿科門診用打字方式做 AI 問診。你的主訴是「勃起功能障礙」。

你的病情事實（回答時保持一致）：
- 大約一年前開始，勃起硬度逐漸變差，最近半年幾乎每次都不夠硬
- 晨勃明顯變少
- 性慾還在，但因為擔心表現，壓力大時更嚴重
- 沒有骨盆外傷、沒有開過刀
- 有高血壓，每天吃 amlodipine 5mg；健檢說血糖偏高（糖尿病前期）
- 抽菸一天半包，抽了 25 年；偶爾喝酒
- 沒有胸痛、沒有走路會喘；沒有藥物或食物過敏
- 和太太關係穩定，沒有伴侶因素

硬性規則：
1. 配合、誠實回答每一個問題，口語繁體中文，每次 1 到 2 句，不反問。
2. 不要主動一次講完全部，等被問到再回答對應的事實。
3. 如果 AI 表示問診要結束、請你稍候，就簡短回「好的，謝謝。」"""

SCENARIOS = {
    "dontknow_zh": {
        "language": "zh-TW",
        "chief_complaint_id": CC_FREQUENCY,
        # 前端一定會送 chiefComplaintText（complaintText || complaintName）。
        # 不送的話 _validate_session 會 fallback 到 ChiefComplaint ORM 物件 →
        # build_system_prompt TypeError → WS 直接 internal_error 斷線（已實測）。
        "chief_complaint_text": "頻尿",
        "patient_name": "E2E不知道先生",
        "gender": "male",
        "dob": "1958-03-15",
        "persona": DONTKNOW_ZH_PERSONA,
        "farewell_after_turn": None,
        "farewell_text": None,
    },
    "hematuria_coop_en": {
        "language": "en-US",
        "chief_complaint_id": CC_HEMATURIA,
        "chief_complaint_text": "Hematuria",
        "patient_name": "E2E Hematuria Baseline",
        "gender": "male",
        "dob": "1964-08-02",
        "persona": HEMATURIA_EN_PERSONA,
        # 第 12 回合之後（即第 13 回合起）每輪固定道別
        "farewell_after_turn": 12,
        "farewell_text": "I think we've covered everything, thank you.",
    },
    # ── §E 修復後驗收情境（等通知才跑）─────────────────────────────
    # hematuria 驗收版：同 baseline 情境，但斷言換成「修復後」預期
    # （≤ HARD_CAP+DRAIN_DEFERS 回合 completed、恰 1 SOAP、canonical 去重、
    #   soap.language=en-US、收尾輪 fullText 非空）。
    "hematuria_coop_en_fixed": {
        "language": "en-US",
        "chief_complaint_id": CC_HEMATURIA,
        "chief_complaint_text": "Hematuria",
        "patient_name": "E2E Hematuria Fixed",
        "gender": "male",
        "dob": "1964-08-02",
        "persona": HEMATURIA_EN_PERSONA,
        "farewell_after_turn": 12,
        "farewell_text": "I think we've covered everything, thank you.",
    },
    # §3b 驗收：血尿 cooperative，驗證 AI 收尾前必問 3 個惡性風險因子（吸菸 / 抗凝血 /
    # 泌尿癌家族史）→ 進 SOAP；且收尾輪不發問。farewell=None 讓病患全程配合，由後端
    # 自動收尾結束（動態硬上限 = 10 + 3 + 2 = 15，給 HPI 十欄問完後仍有回合問風險因子）。
    "hematuria_3b_en": {
        "language": "en-US",
        "chief_complaint_id": CC_HEMATURIA,
        "chief_complaint_text": "Hematuria",
        "patient_name": "E2E Hematuria 3b",
        "gender": "male",
        "dob": "1964-08-02",
        "persona": HEMATURIA_EN_PERSONA,
        "farewell_after_turn": None,
        "farewell_text": None,
        "max_patient_turns": 18,
    },
    # 睪丸扭轉 critical：預期第 1 輪 aborted_red_flag + SOAP +
    # sessions.red_flag=true 且 red_flag_reason 非空（A4）。
    # 上限收緊到 4 回合：若未在第 1 輪中止即為 FAIL，不必燒滿 18 輪。
    "torsion_critical_zh": {
        "language": "zh-TW",
        "chief_complaint_id": CC_SCROTAL,
        "chief_complaint_text": "陰囊腫脹",
        "patient_name": "E2E扭轉先生",
        "gender": "male",
        "dob": "1996-05-20",
        "persona": TORSION_ZH_PERSONA,
        "farewell_after_turn": None,
        "farewell_text": None,
        "max_patient_turns": 4,
        # E8-1 驗收：abort 後再送 2 則訊息，server 應回固定終止提示
        # （不跑 LLM、不重發 abort 事件）
        "post_terminal_probes": 2,
        "probe_text": "醫生，我還是很痛，還需要我補充什麼嗎？",
    },
    # ED 配合病患：預期 8-10 輪自動結束；SOAP icd10_codes 含 N52 開頭 +
    # icd10_verified=true（B1+B2）。
    "ed_zh": {
        "language": "zh-TW",
        "chief_complaint_id": CC_ED,
        "chief_complaint_text": "勃起功能障礙",
        "patient_name": "E2E黃先生",
        "gender": "male",
        "dob": "1971-02-11",
        "persona": ED_ZH_PERSONA,
        "farewell_after_turn": None,
        "farewell_text": None,
        "max_patient_turns": 12,
    },
    # §3b 驗收：ED cooperative，驗證 AI 收尾前必問心血管風險因子（心血管疾病史 / 糖尿病 /
    # 吸菸）→ 進 SOAP；且收尾輪不發問。動態硬上限 = 10 + 3 + 2 = 15。
    "ed_3b_zh": {
        "language": "zh-TW",
        "chief_complaint_id": CC_ED,
        "chief_complaint_text": "勃起功能障礙",
        "patient_name": "E2E心血管黃先生",
        "gender": "male",
        "dob": "1971-02-11",
        "persona": ED_ZH_PERSONA,
        "farewell_after_turn": None,
        "farewell_text": None,
        "max_patient_turns": 18,
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# HTTP：註冊 + 建場次
# ─────────────────────────────────────────────────────────────────────────────

async def register_and_create_session(scenario_name: str, sc: dict) -> dict:
    email = f"e2e-{scenario_name}-{uuid.uuid4().hex[:8]}@gmail.com"
    password = "E2eTest2026x"
    async with httpx.AsyncClient(base_url=API_BASE, timeout=30) as client:
        r = await client.post(
            "/auth/register",
            json={"email": email, "password": password, "name": sc["patient_name"]},
        )
        r.raise_for_status()
        token = r.json()["access_token"]

        r = await client.post(
            "/sessions",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept-Language": sc["language"],
            },
            json={
                "chiefComplaintId": sc["chief_complaint_id"],
                "chiefComplaintText": sc["chief_complaint_text"],
                "language": sc["language"],
                "patientInfo": {
                    "name": sc["patient_name"],
                    "gender": sc["gender"],
                    "dateOfBirth": sc["dob"],
                },
            },
        )
        r.raise_for_status()
        session = r.json()
    return {"email": email, "token": token, "session": session}


# ─────────────────────────────────────────────────────────────────────────────
# 病患模擬器
# ─────────────────────────────────────────────────────────────────────────────

class PatientSimulator:
    def __init__(self, persona: str, api_key: str):
        self._persona = persona
        self._client = AsyncOpenAI(api_key=api_key)

    async def reply(self, transcript: list[dict], next_turn_no: int) -> str:
        """依逐字稿產生病患下一句回答。transcript: [{role, content}]"""
        messages = [{"role": "system", "content": self._persona}]
        # 把問診對話映射成模擬器視角：AI 醫助的話 → user；病患自己說過的話 → assistant
        for entry in transcript:
            if entry["role"] == "assistant":
                messages.append({"role": "user", "content": entry["content"]})
            elif entry["role"] == "patient":
                messages.append({"role": "assistant", "content": entry["content"]})
        resp = await self._client.chat.completions.create(
            model=SIM_MODEL,
            messages=messages,
            temperature=0.4,
            max_tokens=200,
        )
        return (resp.choices[0].message.content or "").strip()


# ─────────────────────────────────────────────────────────────────────────────
# WS 對話主流程
# ─────────────────────────────────────────────────────────────────────────────

async def drive_conversation(session_id: str, token: str, sc: dict, sim: PatientSimulator) -> dict:
    max_turns = sc.get("max_patient_turns", MAX_PATIENT_TURNS)
    ws_url = f"{WS_BASE}/sessions/{session_id}/stream?token={token}"
    rds = redislib.from_url(REDIS_URL, decode_responses=True)
    guidance_key = f"gu:session:{session_id}:supervisor_guidance"

    transcript: list[dict] = []       # {role, content, patient_turn(僅patient), ts}
    events: list[dict] = []           # 非對話事件（red_flag_alert / session_status / error ...）
    guidance_timeline: list[dict] = []  # {ts, after_patient_turn, changed, guidance}
    patient_turns = 0
    completed_event: dict | None = None
    ws_close: dict | None = None
    last_guidance_raw: str | None = None
    post_terminal_probes: list[dict] = []  # E8-1：終結後補送訊息的觀察記錄

    # 當前累積中的 AI 回應
    ai_state = {"message_id": None, "chunks": [], "audio_bytes": 0}

    def record_event(t: str, payload):
        events.append({"ts": now_iso(), "type": t, "payload": payload})

    def is_terminal_session_status(payload: dict) -> bool:
        """session_status 事件是否代表場次已終結。

        兩種 payload 形態都要認：
        - completed 路徑（send_to_session）：帶 status 欄位
        - abort 路徑（send_localized_to_session）：只有 code，無 status
          （torsion 驗收實測：漏認 code 形態會讓 driver 對已中止場次繼續問下去）
        """
        if payload.get("status") in ("completed", "aborted_red_flag"):
            return True
        return payload.get("code") in (
            "events.session.aborted_red_flag",
            "events.session.completed_hpi",
            "events.session.ended_by_user",
            "events.session.idle_timeout",
        )

    async def poll_guidance(after_turn: int, wait_for_change: bool) -> None:
        nonlocal last_guidance_raw
        deadline = time.monotonic() + (GUIDANCE_POLL_TIMEOUT if wait_for_change else 5)
        raw = None
        changed = False
        while time.monotonic() < deadline:
            raw = rds.get(guidance_key)
            if raw is not None and raw != last_guidance_raw:
                changed = True
                break
            await asyncio.sleep(1.0)
        if raw is not None:
            last_guidance_raw = raw
        parsed = None
        if raw:
            try:
                parsed = json.loads(raw)
            except Exception:
                parsed = {"_unparsed": raw}
        guidance_timeline.append(
            {
                "ts": now_iso(),
                "after_patient_turn": after_turn,
                "changed_since_last": changed,
                "guidance": parsed,
            }
        )

    async with websockets.connect(ws_url, max_size=None, ping_interval=20, open_timeout=30) as ws:

        async def read_until_ai_end() -> str | None:
            """讀 WS 直到收到 ai_response_end；回傳 fullText。期間記錄其他事件。"""
            nonlocal completed_event
            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=AI_RESPONSE_TIMEOUT)
                data = json.loads(raw)
                t = data.get("type", "")
                payload = data.get("payload", {}) or {}
                if t == "ai_response_start":
                    ai_state["message_id"] = payload.get("messageId")
                    ai_state["chunks"] = []
                    ai_state["audio_bytes"] = 0
                elif t == "ai_response_chunk":
                    ai_state["chunks"].append(payload.get("text", ""))
                    b64 = payload.get("audioB64") or ""
                    ai_state["audio_bytes"] += len(b64) * 3 // 4
                elif t == "ai_response_end":
                    full = payload.get("fullText") or "".join(ai_state["chunks"])
                    transcript.append(
                        {
                            "role": "assistant",
                            "content": full,
                            "ts": now_iso(),
                            "tts_audio_bytes_approx": ai_state["audio_bytes"],
                        }
                    )
                    print(f"  [AI] {full}", flush=True)
                    return full
                elif t == "session_status":
                    record_event(t, payload)
                    if is_terminal_session_status(payload):
                        completed_event = {"ts": now_iso(), "payload": payload}
                        return None
                elif t in ("connection_ack", "pong"):
                    record_event(t, payload)
                else:
                    # red_flag_alert / supervisor_guidance / error / 其他
                    record_event(t, payload)
                    if t == "red_flag_alert":
                        print(
                            f"  [RED FLAG] {payload.get('severity')} {payload.get('title')}",
                            flush=True,
                        )

        async def drain(seconds: float) -> None:
            """短暫收尾：吸收 ai_response_end 之後立即送達的事件（completed 等）。"""
            nonlocal completed_event
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                remain = deadline - time.monotonic()
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=max(0.1, remain))
                except asyncio.TimeoutError:
                    return
                data = json.loads(raw)
                t = data.get("type", "")
                payload = data.get("payload", {}) or {}
                record_event(t, payload)
                if t == "session_status" and is_terminal_session_status(payload):
                    completed_event = {"ts": now_iso(), "payload": payload}
                    return
                if t == "red_flag_alert":
                    print(
                        f"  [RED FLAG] {payload.get('severity')} {payload.get('title')}",
                        flush=True,
                    )

        try:
            # 開場白（server 主動送）
            await read_until_ai_end()
            await drain(2)
            await poll_guidance(after_turn=0, wait_for_change=False)

            while completed_event is None and patient_turns < max_turns:
                turn_no = patient_turns + 1
                if (
                    sc["farewell_after_turn"] is not None
                    and turn_no > sc["farewell_after_turn"]
                ):
                    reply = sc["farewell_text"]
                else:
                    reply = await sim.reply(
                        [
                            {"role": e["role"], "content": e["content"]}
                            for e in transcript
                            if e["role"] in ("assistant", "patient")
                        ],
                        turn_no,
                    )
                transcript.append(
                    {
                        "role": "patient",
                        "content": reply,
                        "patient_turn": turn_no,
                        "ts": now_iso(),
                    }
                )
                patient_turns = turn_no
                print(f"[P{turn_no}] {reply}", flush=True)
                await ws.send(
                    json.dumps(
                        {"type": "text_message", "payload": {"text": reply}},
                        ensure_ascii=False,
                    )
                )
                full = await read_until_ai_end()
                if completed_event is not None:
                    break
                if full is not None:
                    await drain(3)
                # 每輪收完 AI 回應後撈一次 supervisor guidance（等它更新）
                await poll_guidance(after_turn=turn_no, wait_for_change=True)
                if completed_event is None:
                    await drain(1)

            # ── E8-1 驗收：場次終結後再送訊息，觀察 server 回什麼 ──────────
            # 預期（修復後）：回固定的 ai_response_start/chunk/end 終止提示
            # （i18n ws.session_terminated_*_notice），不跑紅旗/LLM、
            # 不重發 abort session_status。修復前：LLM 續答 + 重發 abort。
            n_probes = sc.get("post_terminal_probes", 0)
            if n_probes and completed_event is not None:
                probe_text = sc.get("probe_text") or "還需要我補充什麼嗎？"
                for i in range(n_probes):
                    rec: dict = {
                        "sent": probe_text,
                        "ts": now_iso(),
                        "responses": [],
                        "ai_fulltext": None,
                    }
                    try:
                        await ws.send(
                            json.dumps(
                                {"type": "text_message", "payload": {"text": probe_text}},
                                ensure_ascii=False,
                            )
                        )
                        deadline = time.monotonic() + 30
                        while time.monotonic() < deadline:
                            try:
                                raw = await asyncio.wait_for(
                                    ws.recv(),
                                    timeout=max(0.1, deadline - time.monotonic()),
                                )
                            except asyncio.TimeoutError:
                                break
                            data = json.loads(raw)
                            t = data.get("type", "")
                            payload = data.get("payload", {}) or {}
                            lite = {"ts": now_iso(), "type": t}
                            for k in ("text", "fullText", "code", "status", "severity", "title"):
                                if k in payload:
                                    lite[k] = payload[k]
                            if payload.get("audioB64"):
                                lite["audio_bytes_approx"] = (
                                    len(payload["audioB64"]) * 3 // 4
                                )
                            rec["responses"].append(lite)
                            if t == "ai_response_end":
                                rec["ai_fulltext"] = payload.get("fullText", "")
                                break
                    except websockets.exceptions.ConnectionClosed as exc:
                        rec["connection_closed"] = {
                            "code": exc.code,
                            "reason": str(exc.reason),
                        }
                        post_terminal_probes.append(rec)
                        print(
                            f"[PROBE{i+1}] connection closed code={exc.code}",
                            flush=True,
                        )
                        break
                    post_terminal_probes.append(rec)
                    print(f"[PROBE{i+1}] → {rec.get('ai_fulltext')!r}", flush=True)

        except websockets.exceptions.ConnectionClosed as exc:
            ws_close = {"code": exc.code, "reason": str(exc.reason), "ts": now_iso()}
            print(f"[WS CLOSED] code={exc.code} reason={exc.reason}", flush=True)
        except asyncio.TimeoutError:
            record_event("driver_timeout", {"note": f"no WS message within {AI_RESPONSE_TIMEOUT}s"})
            print("[DRIVER] timeout waiting for WS message", flush=True)

    # WS 關閉後補撈一次最終 guidance（斷線路徑可能沒跑到本輪 poll）
    try:
        final_raw = rds.get(guidance_key)
        final_guidance = json.loads(final_raw) if final_raw else None
    except Exception:
        final_guidance = None
    rds.close()
    return {
        "transcript": transcript,
        "events": events,
        "guidance_timeline": guidance_timeline,
        "patient_turns": patient_turns,
        "completed_event": completed_event,
        "ws_close": ws_close,
        "final_guidance": final_guidance,
        "post_terminal_probes": post_terminal_probes,
    }


# ─────────────────────────────────────────────────────────────────────────────
# DB / Redis 斷言
# ─────────────────────────────────────────────────────────────────────────────

def fetch_db_state(session_id: str, wait_soap: bool) -> dict:
    conn = psycopg2.connect(PG_DSN)
    conn.autocommit = True
    cur = conn.cursor()

    def q(sql, args=()):
        cur.execute(sql, args)
        return cur.fetchall()

    def table_columns(table: str) -> set[str]:
        return {
            r[0]
            for r in q(
                "select column_name from information_schema.columns "
                "where table_name = %s",
                (table,),
            )
        }

    # 欄位存在性偵測：修復 worktree 與 baseline schema 可能不同（如 soap.language
    # 已存在但語意修正、或新增欄位），查不到的欄位記為 None 而非炸掉。
    soap_cols = table_columns("soap_reports")
    session_cols = table_columns("sessions")
    alert_cols = table_columns("red_flag_alerts")

    opt_soap = [c for c in ("language", "icd10_codes", "icd10_verified") if c in soap_cols]
    soap_select = (
        "id, status, review_status, generated_at, "
        "left(coalesce(subjective::text,''), 300)"
        + "".join(f", {c}" for c in opt_soap)
    )

    soap_row = None
    soap_count = 0
    deadline = time.monotonic() + (SOAP_POLL_TIMEOUT if wait_soap else 15)
    while time.monotonic() < deadline:
        rows = q(
            f"select {soap_select} from soap_reports where session_id = %s",
            (session_id,),
        )
        if rows:
            soap_count = len(rows)
            r = rows[0]
            soap_row = {
                "id": str(r[0]),
                "status": str(r[1]),
                "review_status": str(r[2]),
                "generated_at": str(r[3]),
                "subjective_head": r[4],
            }
            for i, c in enumerate(opt_soap):
                val = r[5 + i]
                if c == "icd10_codes" and val is not None and not isinstance(val, (list, dict)):
                    try:
                        val = json.loads(val)
                    except Exception:
                        pass
                soap_row[c] = val
            break
        time.sleep(5)

    _sess_opt_names = (
        "red_flag", "red_flag_reason", "language", "started_at", "completed_at"
    )
    opt_sess = [c for c in _sess_opt_names if c in session_cols]
    sess_select = "status" + "".join(f", {c}" for c in opt_sess)
    status_rows = q(
        f"select {sess_select} from sessions where id = %s", (session_id,)
    )
    session_status = str(status_rows[0][0]) if status_rows else None
    session_extra: dict = {c: None for c in _sess_opt_names}
    if status_rows:
        for i, c in enumerate(opt_sess):
            val = status_rows[0][1 + i]
            if c in ("started_at", "completed_at") and val is not None:
                val = str(val)
            session_extra[c] = val

    alert_rows = q(
        "select severity, title, count(*) from red_flag_alerts "
        "where session_id = %s group by severity, title order by count(*) desc",
        (session_id,),
    )
    alerts_summary = [
        {"severity": str(r[0]), "title": r[1], "count": int(r[2])} for r in alert_rows
    ]
    total_alerts = sum(a["count"] for a in alerts_summary)

    # A5 去重驗收：同 canonical_id 應只剩 1 筆
    alerts_by_canonical = None
    if "canonical_id" in alert_cols:
        alerts_by_canonical = [
            {"canonical_id": r[0], "severity": str(r[1]), "count": int(r[2])}
            for r in q(
                "select canonical_id, severity, count(*) from red_flag_alerts "
                "where session_id = %s group by canonical_id, severity "
                "order by count(*) desc",
                (session_id,),
            )
        ]

    conv_rows = q(
        "select count(*) from conversations where session_id = %s", (session_id,)
    )
    conn.close()
    return {
        "session_status": session_status,
        "session_red_flag": session_extra["red_flag"],
        "session_red_flag_reason": session_extra["red_flag_reason"],
        "session_language": session_extra["language"],
        "session_started_at": session_extra["started_at"],
        "session_completed_at": session_extra["completed_at"],
        "soap_report": soap_row,
        "soap_report_count": soap_count,
        "red_flag_alerts_summary": alerts_summary,
        "red_flag_alerts_total": total_alerts,
        "red_flag_alerts_by_canonical": alerts_by_canonical,
        "db_conversation_rows": int(conv_rows[0][0]),
    }


# ── dontknow_zh 斷言 ────────────────────────────────────────────────────────

# onset 與 duration 是兩個獨立 HPI 欄位：病患對「什麼時候開始」說不知道後，
# AI 第一次問「持續多久」不算重問（persona 也會對 duration 說不知道，之後才不得再問）。
# 分析必須逐欄位切 cutoff，否則會把合法的 first-ask 誤判成 re-ask。
FIELD_ASK_PATTERNS: dict[str, list[str]] = {
    "onset": [
        "什麼時候開始", "何時開始", "什麼時候出現", "何時出現", "什麼時候發現",
        "從什麼時候", "開始的時間", "大概什麼時候", "幾時開始",
        "一下子才開始", "突然開始", "突然出現",
    ],
    "duration": [
        "持續多久", "持續多長", "多久了", "多長時間", "幾天了", "幾週了", "幾個月了",
    ],
    "history": [
        "病史", "以前有沒有", "過去有沒有", "以前生過", "慢性病", "開過刀",
        "動過手術", "過去健康", "以前健康", "以前看過", "過去就醫",
    ],
}
# guidance missing_hpi 對應的欄位 id
FIELD_HPI_IDS: dict[str, tuple[str, ...]] = {
    "onset": ("onset",),
    "duration": ("duration",),
    "history": (),  # 過去病史不在 HPI 十欄內
}
DONTKNOW_PATTERNS = ["不知道", "不記得", "不清楚", "想不起", "沒印象"]


def _matches(text: str, patterns: list[str]) -> list[str]:
    return [p for p in patterns if p in text]


def analyze_dontknow(result: dict, db_state: dict) -> dict:
    transcript = result["transcript"]

    # 每個欄位各自找「AI 問該欄 → 病患說不知道」的第一個 patient turn（cutoff）
    dontknow_turn: dict[str, int | None] = {f: None for f in FIELD_ASK_PATTERNS}
    for i, e in enumerate(transcript):
        if e["role"] != "patient" or not _matches(e["content"], DONTKNOW_PATTERNS):
            continue
        prev_ai = next(
            (t for t in reversed(transcript[:i]) if t["role"] == "assistant"), None
        )
        if prev_ai is None:
            continue
        for field, patterns in FIELD_ASK_PATTERNS.items():
            if dontknow_turn[field] is None and _matches(prev_ai["content"], patterns):
                dontknow_turn[field] = e.get("patient_turn")

    # (a) 各欄位說不知道之後，AI 是否又問同一欄（含換句話，以關鍵字掃描 + 人工判讀）
    def ai_reask_after(cutoff: int | None, patterns: list[str]) -> list[dict]:
        if cutoff is None:
            return []
        hits = []
        seen_turn = 0
        for e in transcript:
            if e["role"] == "patient":
                seen_turn = e.get("patient_turn", seen_turn)
            elif e["role"] == "assistant" and seen_turn >= cutoff:
                m = _matches(e["content"], patterns)
                if m:
                    hits.append(
                        {
                            "after_patient_turn": seen_turn,
                            "matched": m,
                            "ai_text": e["content"],
                        }
                    )
        return hits

    reasks = {
        f: ai_reask_after(dontknow_turn[f], FIELD_ASK_PATTERNS[f])
        for f in FIELD_ASK_PATTERNS
    }

    # (b) supervisor guidance：cutoff+1（容 supervisor 一輪時序誤差）之後，
    # missing_hpi 不得再含該欄、next_focus 不得再指向該欄
    gl = result["guidance_timeline"]
    guidance_checks = []
    max_hpi_after_dontknow = None
    missing_violations: dict[str, list] = {f: [] for f in FIELD_ASK_PATTERNS}
    next_focus_violations: dict[str, list] = {f: [] for f in FIELD_ASK_PATTERNS}
    earliest_cutoff = min(
        (t for t in dontknow_turn.values() if t is not None), default=None
    )
    for g in gl:
        guid = g.get("guidance") or {}
        turn = g.get("after_patient_turn", 0)
        missing = guid.get("missing_hpi") or []
        nf = str(guid.get("next_focus") or "")
        hpi = guid.get("hpi_completion_percentage")
        try:
            hpi_f = float(hpi)
        except (TypeError, ValueError):
            hpi_f = None
        if (
            earliest_cutoff is not None
            and turn >= earliest_cutoff
            and hpi_f is not None
        ):
            max_hpi_after_dontknow = max(max_hpi_after_dontknow or 0, hpi_f)
        for field, cutoff in dontknow_turn.items():
            if cutoff is None or turn <= cutoff + 1:  # grace：不知道當輪 + 下一輪
                continue
            if any(m in FIELD_HPI_IDS[field] for m in missing):
                missing_violations[field].append(
                    {"after_patient_turn": turn, "missing_hpi": missing}
                )
            if _matches(nf, FIELD_ASK_PATTERNS[field]):
                next_focus_violations[field].append(
                    {"after_patient_turn": turn, "next_focus": nf}
                )
        if earliest_cutoff is not None and turn >= earliest_cutoff:
            guidance_checks.append(
                {
                    "after_patient_turn": turn,
                    "missing_hpi": missing,
                    "next_focus": nf,
                    "hpi_completion_percentage": hpi,
                    "fallback": bool(guid.get("fallback")),
                }
            )

    completed = result["completed_event"] is not None and (
        result["completed_event"]["payload"].get("status") == "completed"
    )

    all_missing_violations = [v for vs in missing_violations.values() for v in vs]
    all_nf_violations = [v for vs in next_focus_violations.values() for v in vs]

    assertions = {
        "a_no_onset_reask_after_dontknow": {
            "pass": len(reasks["onset"]) == 0,
            "first_dontknow_onset_turn": dontknow_turn["onset"],
            "reask_hits": reasks["onset"],
        },
        "a2_no_duration_reask_after_dontknow": {
            "pass": len(reasks["duration"]) == 0,
            "first_dontknow_duration_turn": dontknow_turn["duration"],
            "reask_hits": reasks["duration"],
        },
        "a3_no_history_reask_after_dontknow": {
            "pass": len(reasks["history"]) == 0,
            "first_dontknow_history_turn": dontknow_turn["history"],
            "reask_hits": reasks["history"],
        },
        "b_missing_hpi_drops_refused_fields": {
            "pass": len(all_missing_violations) == 0,
            "dontknow_turns": dontknow_turn,
            "violations_by_field": missing_violations,
        },
        "b2_next_focus_not_refused_fields": {
            "pass": len(all_nf_violations) == 0,
            "violations_by_field": next_focus_violations,
        },
        "b3_hpi_reaches_80": {
            "pass": (max_hpi_after_dontknow or 0) >= 80,
            "max_hpi_after_dontknow": max_hpi_after_dontknow,
        },
        "c_completed_within_10_turns": {
            "pass": completed and result["patient_turns"] <= 10,
            "completed_event_received": completed,
            "patient_turns": result["patient_turns"],
        },
        "c2_soap_report_in_db": {
            "pass": db_state["soap_report"] is not None,
            "soap": db_state["soap_report"],
        },
    }
    assertions["overall_pass"] = all(
        v["pass"] for v in assertions.values() if isinstance(v, dict)
    )
    assertions["guidance_after_dontknow"] = guidance_checks
    return assertions


def analyze_hematuria_baseline(result: dict, db_state: dict) -> dict:
    completed = result["completed_event"] is not None
    dup_alerts = [
        a for a in db_state["red_flag_alerts_summary"] if a["count"] > 1
    ]

    # 紅旗事件時間 → 對應病患回合（alert 在該回合病患訊息後 ~2-4s 內發出）
    transcript = result.get("transcript", [])
    events = result.get("events", [])
    patient_ts = [
        (e["patient_turn"], e["ts"]) for e in transcript if e["role"] == "patient"
    ]
    turns_with_high_alert: list[int] = []
    for ev in events:
        if ev.get("type") != "red_flag_alert":
            continue
        sev = str(ev["payload"].get("severity", "")).lower()
        if sev not in ("critical", "high"):
            continue
        ev_ts = ev["ts"]
        turn = max((t for t, ts in patient_ts if ts <= ev_ts), default=None)
        if turn is not None and turn not in turns_with_high_alert:
            turns_with_high_alert.append(turn)

    # 收尾被紅旗 deferral 擋掉的證據：AI 已講出「請稍候/wrap up」道別語的回合 vs
    # 實際 completed 回合（若道別回合有 high alert，該輪 auto-conclude 被 skip）。
    wrapup_markers = ["請您在原處稍候", "原處稍候", "wait where you are", "physician will see you"]
    wrapup_turns: list[int] = []
    seen_turn = 0
    for e in transcript:
        if e["role"] == "patient":
            seen_turn = e.get("patient_turn", seen_turn)
        elif e["role"] == "assistant" and any(m in e["content"] for m in wrapup_markers):
            wrapup_turns.append(seen_turn)

    baseline = {
        "patient_turns_sent": result["patient_turns"],
        "completed_event_received": completed,
        "completed_event": result["completed_event"],
        "final_session_status_db": db_state["session_status"],
        "soap_report_exists": db_state["soap_report"] is not None,
        "red_flag_alerts_total": db_state["red_flag_alerts_total"],
        "red_flag_alerts_summary": db_state["red_flag_alerts_summary"],
        "duplicated_alert_titles": dup_alerts,
        "patient_turns_with_high_alert": turns_with_high_alert,
        "ai_wrapup_message_at_turns": wrapup_turns,
        # documented bug D1（2026-06-28 發現）：紅旗 deferral 每輪都觸發 →
        # auto-conclude 每輪被 skip → 問診跑滿 client 上限仍 in_progress、無 SOAP
        "bug_D1_reproduced": (
            not completed
            and db_state["session_status"] == "in_progress"
            and result["patient_turns"] >= MAX_PATIENT_TURNS
            and db_state["soap_report"] is None
        ),
        # D1 的機制面（非全有全無）：只要「AI 已道別的回合」剛好也有 high alert，
        # 該輪 auto-conclude 就被 skip（收尾被延後），deferral 機制仍在。
        "red_flag_deferral_observed": bool(
            wrapup_turns
            and completed
            and min(wrapup_turns) in turns_with_high_alert
        ),
        # 已知次生問題：同一 canonical 紅旗跨回合不冪等（重複 insert）
        "non_idempotent_alerts_reproduced": bool(dup_alerts),
    }
    return baseline


# ── §E 修復後驗收斷言 ────────────────────────────────────────────────────────

def _last_ai_fulltext(transcript: list[dict]) -> str:
    for e in reversed(transcript):
        if e["role"] == "assistant":
            return (e.get("content") or "").strip()
    return ""


def analyze_hematuria_fixed(result: dict, db_state: dict) -> dict:
    """hematuria_coop_en 修復後驗收（對照 baseline results/hematuria_coop_en.json）。"""
    completed = result["completed_event"] is not None and (
        result["completed_event"]["payload"].get("status") == "completed"
    )
    by_canonical = db_state.get("red_flag_alerts_by_canonical")
    dup_canonical = [
        a for a in (by_canonical or []) if a["count"] > 1
    ]
    soap = db_state.get("soap_report") or {}
    last_ai = _last_ai_fulltext(result.get("transcript", []))

    assertions = {
        # E1/E3：紅旗 deferral 不再無限推遲 → 硬上限 + 至多 DRAIN_DEFERS 輪內結束
        "h1_completed_within_cap_plus_defers": {
            "pass": completed and result["patient_turns"] <= HARD_CAP + DRAIN_DEFERS,
            "patient_turns": result["patient_turns"],
            "limit": HARD_CAP + DRAIN_DEFERS,
            "completed_event_received": completed,
            "final_session_status_db": db_state["session_status"],
        },
        "h2_exactly_one_soap": {
            "pass": db_state.get("soap_report_count") == 1,
            "soap_report_count": db_state.get("soap_report_count"),
        },
        # A5：同 canonical_id 僅 1 筆
        "h3_alerts_deduped_by_canonical": {
            "pass": by_canonical is not None and len(dup_canonical) == 0,
            "alerts_by_canonical": by_canonical,
            "duplicates": dup_canonical,
        },
        # B3：SOAP 語言跟場次語言
        "h4_soap_language_en": {
            "pass": soap.get("language") == "en-US",
            "soap_language": soap.get("language"),
        },
        # A1：收尾輪 AI fullText 非空（baseline 上最後一輪 fullText 是空字串）
        "h5_final_ai_fulltext_nonempty": {
            "pass": bool(last_ai),
            "final_ai_fulltext_head": last_ai[:120],
        },
        # E8-4：en-US 場次 alert title 應為英文（baseline 是中文「肉眼血尿」）
        "h6_alert_titles_localized": {
            "pass": bool(db_state["red_flag_alerts_summary"])
            and not any(
                re.search(r"[一-鿿]", a["title"] or "")
                for a in db_state["red_flag_alerts_summary"]
            ),
            "titles": [a["title"] for a in db_state["red_flag_alerts_summary"]],
        },
        # E8-3：started_at / completed_at 補寫
        "h7_timestamps_persisted": {
            "pass": bool(db_state.get("session_started_at"))
            and bool(db_state.get("session_completed_at")),
            "started_at": db_state.get("session_started_at"),
            "completed_at": db_state.get("session_completed_at"),
        },
    }
    assertions["overall_pass"] = all(
        v["pass"] for v in assertions.values() if isinstance(v, dict)
    )
    return assertions


def analyze_torsion(result: dict, db_state: dict) -> dict:
    """torsion_critical_zh：第 1 輪 aborted_red_flag + SOAP + A4（session.red_flag 持久化）。"""
    # abort 事件證據從 events 找（abort 的 session_status 是 localized 形態：
    # 只有 code、無 status 欄位），並以時間戳判定它落在第幾個病患回合之後。
    transcript = result.get("transcript", [])
    patient_ts = [
        (e["patient_turn"], e["ts"]) for e in transcript if e["role"] == "patient"
    ]
    abort_events = [
        ev
        for ev in result.get("events", [])
        if ev.get("type") == "session_status"
        and (
            ev["payload"].get("status") == "aborted_red_flag"
            or ev["payload"].get("code") == "events.session.aborted_red_flag"
        )
    ]
    abort_turn = None
    if abort_events:
        first_ts = min(ev["ts"] for ev in abort_events)
        abort_turn = max(
            (t for t, ts in patient_ts if ts <= first_ts), default=None
        )
    aborted = bool(abort_events) and db_state["session_status"] == "aborted_red_flag"
    critical_alerts = [
        a
        for a in db_state["red_flag_alerts_summary"]
        if a["severity"].lower() == "critical"
    ]
    reason = db_state.get("session_red_flag_reason")

    assertions = {
        "t1_aborted_on_first_turn": {
            "pass": aborted and abort_turn == 1,
            "aborted_event_received": bool(abort_events),
            "abort_after_patient_turn": abort_turn,
            "patient_turns_sent_total": result["patient_turns"],
            "final_session_status_db": db_state["session_status"],
        },
        "t2_critical_alert_persisted": {
            "pass": len(critical_alerts) >= 1,
            "critical_alerts": critical_alerts,
        },
        "t3_soap_report_in_db": {
            "pass": db_state["soap_report"] is not None,
            "soap": db_state["soap_report"],
        },
        # A4：sessions.red_flag=true 且 red_flag_reason 非空（修復前 false/空）
        "t4_session_red_flag_persisted": {
            "pass": db_state.get("session_red_flag") is True
            and bool((reason or "").strip()),
            "session_red_flag": db_state.get("session_red_flag"),
            "session_red_flag_reason": reason,
        },
    }

    # E8-1：abort 後補送訊息 → 回固定終止提示（ai_response_* 三段、內容為
    # ws.session_terminated_aborted_notice 模板），不跑紅旗/LLM、不重發 abort，
    # 且 server 隨後「結束主迴圈、關閉 WS」（實作規格）。因此合格樣態是：
    #   probe1 = 終止提示模板；probe2 = 同模板 或 乾淨 close（1000/1001）。
    probes = result.get("post_terminal_probes") or []
    probe_issues: list[dict] = []
    notice_texts: list[str] = []
    clean_close_after_notice = False
    for idx, p in enumerate(probes, 1):
        if "connection_closed" in p:
            code = p["connection_closed"].get("code")
            if idx >= 2 and notice_texts and code in (1000, 1001):
                # 已先收到過終止提示，之後 server 收掉連線 → 符合實作規格
                clean_close_after_notice = True
            else:
                probe_issues.append(
                    {"probe": idx, "issue": "connection_closed", "detail": p["connection_closed"]}
                )
            continue
        resp = p.get("responses", [])
        ft = (p.get("ai_fulltext") or "").strip()
        if any(r["type"] == "red_flag_alert" for r in resp):
            probe_issues.append({"probe": idx, "issue": "red_flag_rerun"})
        if any(
            r["type"] == "session_status"
            and (
                r.get("status") == "aborted_red_flag"
                or r.get("code") == "events.session.aborted_red_flag"
            )
            for r in resp
        ):
            probe_issues.append({"probe": idx, "issue": "abort_event_resent"})
        if not ft:
            probe_issues.append({"probe": idx, "issue": "no_reply"})
        elif "問診已經結束" not in ft or "現場" not in ft:
            probe_issues.append(
                {"probe": idx, "issue": "unexpected_text", "text": ft[:160]}
            )
        else:
            notice_texts.append(ft)
    # 模板穩定：收到的所有提示文字完全一致（非 LLM 續答的直接證據）
    template_stable = len(notice_texts) >= 1 and len(set(notice_texts)) == 1
    assertions["t5_post_abort_terminated_notice"] = {
        "pass": len(probes) == 2 and not probe_issues and template_stable,
        "probes_sent": len(probes),
        "notices_received": len(notice_texts),
        "server_closed_ws_after_notice": clean_close_after_notice,
        "issues": probe_issues,
        "template_stable": template_stable,
        "notice_text": notice_texts[0][:200] if notice_texts else None,
    }
    # E8-3：started_at / completed_at 補寫
    assertions["t6_timestamps_persisted"] = {
        "pass": bool(db_state.get("session_started_at"))
        and bool(db_state.get("session_completed_at")),
        "started_at": db_state.get("session_started_at"),
        "completed_at": db_state.get("session_completed_at"),
    }

    assertions["overall_pass"] = all(
        v["pass"] for v in assertions.values() if isinstance(v, dict)
    )
    return assertions


def analyze_ed(result: dict, db_state: dict) -> dict:
    """ed_zh：正常完診 + B1/B2（SOAP icd10 含 N52* 且 icd10_verified=true）。"""
    completed = result["completed_event"] is not None and (
        result["completed_event"]["payload"].get("status") == "completed"
    )
    soap = db_state.get("soap_report") or {}
    codes_raw = soap.get("icd10_codes") or []
    codes: list[str] = []
    for c in codes_raw:
        if isinstance(c, dict):
            code = str(c.get("code") or c.get("icd10") or "")
        else:
            code = str(c)
        if code:
            codes.append(code)
    n52 = [c for c in codes if c.upper().startswith("N52")]

    assertions = {
        "e1_completed": {
            "pass": completed,
            "patient_turns": result["patient_turns"],
            "final_session_status_db": db_state["session_status"],
        },
        "e2_soap_report_in_db": {
            "pass": db_state["soap_report"] is not None,
            "soap_id": soap.get("id"),
        },
        # B1：ICD-10 含 N52 開頭（勃起功能障礙）
        "e3_icd10_contains_n52": {
            "pass": len(n52) > 0,
            "icd10_codes": codes,
            "n52_hits": n52,
        },
        # B2：icd10_verified 旗標為 true
        "e4_icd10_verified_true": {
            "pass": soap.get("icd10_verified") is True,
            "icd10_verified": soap.get("icd10_verified"),
        },
    }
    assertions["overall_pass"] = all(
        v["pass"] for v in assertions.values() if isinstance(v, dict)
    )
    return assertions


def _ai_turns_joined(transcript: list[dict]) -> str:
    """把所有 AI（assistant）輪的全文串起來（小寫），供『AI 是否問到 X』掃描。"""
    return " ".join(
        (e.get("content") or "") for e in transcript if e.get("role") == "assistant"
    ).lower()


def _wrapup_has_no_question(transcript: list[dict]) -> bool:
    """收尾輪（最後一則 AI 全文）不含問號 → 恢復『收尾不發問』不變式。"""
    last = _last_ai_fulltext(transcript)
    return "?" not in last and "？" not in last


def analyze_hematuria_3b(result: dict, db_state: dict) -> dict:
    """§3b 血尿：AI 收尾前必問 3 惡性風險因子（吸菸 / 抗凝血 / 泌尿癌家族史）+ 收尾不發問。

    對照 Fable 首版 NO-GO（10 回合 hard cap 擠掉風險因子 + 收尾發問回歸）：
    重新設計後動態硬上限 = base(10)+K(3)+buffer(2)=15，讓 HPI 十欄問完後仍有回合問到。
    """
    completed = result["completed_event"] is not None and (
        result["completed_event"]["payload"].get("status") == "completed"
    )
    ai_text = _ai_turns_joined(result.get("transcript", []))
    soap = db_state.get("soap_report") or {}
    # 動態硬上限 15 + 至多 DRAIN_DEFERS 輪
    cap_limit = 10 + 3 + 2 + DRAIN_DEFERS
    asked_smoking = any(k in ai_text for k in ("smok", "cigarette", "tobacco"))
    asked_anticoag = any(
        k in ai_text
        for k in ("blood thinner", "thinner", "anticoagul", "warfarin", "aspirin", "clopidogrel")
    )
    asked_family = "family" in ai_text

    assertions = {
        "r1_completed_within_extended_cap": {
            "pass": completed and result["patient_turns"] <= cap_limit,
            "patient_turns": result["patient_turns"],
            "limit": cap_limit,
            "final_session_status_db": db_state["session_status"],
        },
        "r2_asked_smoking": {"pass": asked_smoking},
        "r3_asked_anticoagulant": {"pass": asked_anticoag},
        "r4_asked_family_cancer_history": {"pass": asked_family},
        "r5_wrapup_no_new_question": {
            "pass": _wrapup_has_no_question(result.get("transcript", [])),
            "last_ai_head": _last_ai_fulltext(result.get("transcript", []))[:160],
        },
        "r6_soap_exists_en": {
            "pass": db_state["soap_report"] is not None and soap.get("language") == "en-US",
            "soap_language": soap.get("language"),
            "subjective_head": db_state.get("soap_report", {}).get("subjective_head")
            if isinstance(db_state.get("soap_report"), dict)
            else None,
        },
    }
    assertions["overall_pass"] = all(
        v["pass"] for v in assertions.values() if isinstance(v, dict)
    )
    return assertions


def analyze_ed_3b(result: dict, db_state: dict) -> dict:
    """§3b ED：AI 收尾前必問心血管風險因子（心血管疾病史 / 糖尿病 / 吸菸）+ 收尾不發問。"""
    completed = result["completed_event"] is not None and (
        result["completed_event"]["payload"].get("status") == "completed"
    )
    ai_text = _ai_turns_joined(result.get("transcript", []))
    soap = db_state.get("soap_report") or {}
    cap_limit = 10 + 3 + 2 + DRAIN_DEFERS
    asked_cv = any(
        k in ai_text
        for k in ("心血管", "高血壓", "血壓", "心臟", "冠狀", "中風", "心肌")
    )
    asked_diabetes = any(k in ai_text for k in ("糖尿", "血糖"))
    asked_smoking = any(k in ai_text for k in ("菸", "煙", "抽菸", "吸菸", "抽煙"))

    assertions = {
        "r1_completed_within_extended_cap": {
            "pass": completed and result["patient_turns"] <= cap_limit,
            "patient_turns": result["patient_turns"],
            "limit": cap_limit,
            "final_session_status_db": db_state["session_status"],
        },
        "r2_asked_cardiovascular": {"pass": asked_cv},
        "r3_asked_diabetes": {"pass": asked_diabetes},
        "r4_asked_smoking": {"pass": asked_smoking},
        "r5_wrapup_no_new_question": {
            "pass": _wrapup_has_no_question(result.get("transcript", [])),
            "last_ai_head": _last_ai_fulltext(result.get("transcript", []))[:160],
        },
        "r6_soap_exists_zh": {
            "pass": db_state["soap_report"] is not None and soap.get("language") == "zh-TW",
            "soap_language": soap.get("language"),
        },
    }
    assertions["overall_pass"] = all(
        v["pass"] for v in assertions.values() if isinstance(v, dict)
    )
    return assertions


ANALYZERS = {
    "dontknow_zh": analyze_dontknow,
    "hematuria_3b_en": analyze_hematuria_3b,
    "ed_3b_zh": analyze_ed_3b,
    "hematuria_coop_en": analyze_hematuria_baseline,
    "hematuria_coop_en_fixed": analyze_hematuria_fixed,
    "torsion_critical_zh": analyze_torsion,
    "ed_zh": analyze_ed,
}


# ─────────────────────────────────────────────────────────────────────────────
# main
# ─────────────────────────────────────────────────────────────────────────────

def reanalyze(scenario_name: str) -> None:
    """離線重算已存 JSON 的 analysis 區塊（不重跑對話、不花 OpenAI 額度）。"""
    path = RESULTS_DIR / f"{scenario_name}.json"
    output = json.loads(path.read_text())
    result = {
        "transcript": output["transcript"],
        "guidance_timeline": output["guidance_timeline"],
        "completed_event": output["completed_event"],
        "patient_turns": output["patient_turns"],
        "events": output.get("events", []),
        "post_terminal_probes": output.get("post_terminal_probes", []),
    }
    db_state = output["db_state"]
    output["analysis"] = ANALYZERS[scenario_name](result, db_state)
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    print(json.dumps(output["analysis"], ensure_ascii=False, indent=2))


async def main() -> None:
    if len(sys.argv) == 3 and sys.argv[1] == "reanalyze" and sys.argv[2] in SCENARIOS:
        reanalyze(sys.argv[2])
        return
    if len(sys.argv) != 2 or sys.argv[1] not in SCENARIOS:
        print(f"usage: driver.py [{'|'.join(SCENARIOS)}] | driver.py reanalyze <scenario>")
        sys.exit(2)
    scenario_name = sys.argv[1]
    sc = SCENARIOS[scenario_name]

    env_vals = dotenv_values(BACKEND_DIR / ".env")
    api_key = env_vals.get("OPENAI_API_KEY")
    if not api_key or not api_key.startswith("sk-"):
        print("FATAL: backend/.env 沒有可用的 OPENAI_API_KEY")
        sys.exit(1)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    started = now_iso()
    print(f"=== scenario {scenario_name} start {started} ===", flush=True)

    setup = await register_and_create_session(scenario_name, sc)
    session = setup["session"]
    session_id = session["id"]
    print(
        f"session={session_id} language={session.get('language')} "
        f"chief_complaint={session.get('chief_complaint_text') or sc['chief_complaint_id']}",
        flush=True,
    )

    sim = PatientSimulator(sc["persona"], api_key)
    result = await drive_conversation(session_id, setup["token"], sc, sim)

    wait_soap = result["completed_event"] is not None
    db_state = fetch_db_state(session_id, wait_soap=wait_soap)

    analysis = ANALYZERS[scenario_name](result, db_state)

    output = {
        "scenario": scenario_name,
        "started_at": started,
        "finished_at": now_iso(),
        "backend_dir": str(BACKEND_DIR),
        "backend_head": _backend_git_head(),
        "session_id": session_id,
        "session_language": session.get("language"),
        "account_email": setup["email"],
        "patient_turns": result["patient_turns"],
        "completed_event": result["completed_event"],
        "ws_close": result["ws_close"],
        "db_state": db_state,
        "final_guidance": result.get("final_guidance"),
        "post_terminal_probes": result.get("post_terminal_probes", []),
        "analysis": analysis,
        "guidance_timeline": result["guidance_timeline"],
        "events": result["events"],
        "transcript": result["transcript"],
    }
    out_path = RESULTS_DIR / f"{scenario_name}.json"
    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    print(f"=== done → {out_path} ===", flush=True)
    print(
        json.dumps(
            {
                "patient_turns": result["patient_turns"],
                "completed": result["completed_event"] is not None,
                "db_status": db_state["session_status"],
                "soap": db_state["soap_report"] is not None,
                "alerts_total": db_state["red_flag_alerts_total"],
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
