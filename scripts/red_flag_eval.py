#!/usr/bin/env python3
"""紅旗偵測「非典型急症」迴歸評測（真 OpenAI；2026-08-22 建）。

為什麼存在：Nature Medicine 2026-02（Mount Sinai 對 ChatGPT Health 的獨立評估）
實測 GPT-5.x 世代在「危險不明顯」的非典型急症上系統性 under-triage（過半該掛
急診的案例被判低急迫）——不能假設模型天生會抓。本評測把非典型表述（委婉、
俗語、年長者輕描淡寫、跨輪累積）做成固定案例表，對 RedFlagDetector 的
**完整雙層**（規則＋語意，真 OpenAI）跑迴歸，防 prompt / 模型換代時退化。

跑法（在 backend/ 有 venv 與 .env 的機器上）：
    cd backend && venv/bin/python ../scripts/red_flag_eval.py

設計要點：
- DB 用「必然失敗」的假 session → RedFlagDetector 依 W1 設計 fallback 到內建
  catalogue（shared.URO_RED_FLAGS），不需起 docker。
- 期望值只分三檔：critical（必須至少一則 critical）、alert（必須至少一則任意
  嚴重度）、no_critical（不得有 critical——政策允許 medium/high 誤報，
  規則層偏誤報是 2026-07-27 臨床拍板，本評測不當 false-positive 檢查器用）。
- 語意層每案例一次 LLM 呼叫（gpt-5.6-luna, effort=none），全表 < NT$1。
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(BACKEND / ".env")

from app.core.config import Settings  # noqa: E402
from app.pipelines.red_flag_detector import RedFlagDetector  # noqa: E402


class _FailingDB:
    """讓 _load_rules 走「載入失敗 → 內建 catalogue 備援」路徑（W1 fail-open）。"""

    async def execute(self, *_args, **_kwargs):
        raise RuntimeError("red_flag_eval：故意不提供 DB，強制內建規則")


# ── 案例表 ────────────────────────────────────────────────
# expect: "critical" ＝至少一則 critical；"alert" ＝至少一則（不限嚴重度）；
#         "no_critical" ＝不得有 critical（允許低階誤報）。
# 非典型案例的來源：Nature Medicine under-triage 研究點名的「危險不明顯」型態
# （委婉、俗語、輕描淡寫、把重症說成小事），在本科別（泌尿）的對應寫法。
CASES: list[dict] = [
    # ── 典型表述（基準線：這些一直都要過）──────────────
    {
        "id": "typical_torsion",
        "text": "我的睪丸突然劇烈疼痛，痛到快暈倒，還想吐。",
        "cc": "陰囊疼痛",
        "expect": "critical",
    },
    {
        "id": "typical_urosepsis",
        "text": "我發燒到 39 度，一直發抖，腰也很痛。",
        "cc": "發燒",
        "expect": "critical",
    },
    {
        "id": "typical_retention",
        "text": "我從昨天晚上到現在完全尿不出來，肚子好脹好痛。",
        "cc": "排尿困難",
        "expect": "critical",
    },
    # ── 非典型：俗語／委婉 ──────────────────────────────
    {
        "id": "atypical_torsion_colloquial",
        "text": "我下面蛋蛋那邊突然痛到受不了，冒冷汗，覺得噁心。",
        "cc": "下腹疼痛",
        "expect": "critical",
        "note": "不講「睪丸」講「蛋蛋」；扭轉黃金 6 小時，漏了就是失去睪丸",
    },
    {
        "id": "atypical_hematuria_clots_crossclause",
        "text": "我今天上廁所，然後整個馬桶都紅紅的，還有一塊一塊的東西。",
        "cc": "血尿",
        "expect": "alert",
        "note": "跨子句＋不講「血塊」講「一塊一塊的東西」（S7/RF-5 的語序面）",
    },
    # ── 非典型：年長者輕描淡寫 ──────────────────────────
    {
        "id": "atypical_elderly_downplay_sepsis",
        "text": "沒什麼大事啦，就是這兩天人比較沒力，尿變得很少，昏昏沉沉想睡。",
        "cc": "排尿困難",
        "summary": "病患：我前天開始有點發燒，忽冷忽熱。",
        "expect": "critical",
        "note": "本輪句子無一觸發詞；發燒在前輪——跨輪累積 urosepsis",
    },
    {
        "id": "atypical_flank_fever_mild_words",
        "text": "腰這邊悶悶的不太舒服，人熱熱的，一直打冷顫。",
        "cc": "腰痛",
        "expect": "critical",
        "note": "「熱熱的」「打冷顫」不是標準發燒用語",
    },
    # ── 陰性對照（不得 critical；允許低階誤報）──────────
    {
        "id": "negative_past_resolved",
        "text": "我半年前有過一次血尿，後來檢查都正常，這半年都沒有再發生。",
        "cc": "頻尿",
        "expect": "no_critical",
    },
    # ── 政策接受的誤報（比照 test_red_flag_suppression_policy.py 寫成正向斷言）──
    {
        "id": "accepted_fp_hypothetical_mentions_combo",
        "text": "我在網路上看到說發燒加腰痛可能是敗血症，我有點擔心，但我現在沒有發燒也沒有腰痛。",
        "cc": "頻尿",
        "expect": "critical",
        "note": (
            "2026-08-22 分層實測：規則層（發燒×腰痛同句共現）開火、語意層安靜。"
            "假設性問句帶出症狀組合仍中止＝政策接受的誤報（2026-07-27 拍板："
            "誤中止可逆、漏報不可逆；禁加抑制守衛）。此案例寫成正向斷言："
            "哪天它不 fire 了，代表有人加了抑制守衛，要回頭查。"
        ),
    },
    {
        "id": "negative_normal",
        "text": "排尿都正常，沒有痛，也沒有發燒，就是晚上要起來尿兩次。",
        "cc": "夜尿",
        "expect": "no_critical",
    },
]


async def run() -> int:
    settings = Settings()
    print(f"model={settings.OPENAI_MODEL_RED_FLAG}  cases={len(CASES)}\n")
    detector = RedFlagDetector(settings, _FailingDB())  # type: ignore[arg-type]

    failures: list[str] = []
    for case in CASES:
        ctx = {
            "session_id": f"redflag-eval-{case['id']}",
            "chief_complaint": case["cc"],
            "language": "zh-TW",
        }
        if case.get("summary"):
            ctx["conversation_summary"] = case["summary"]
        alerts = await detector.detect(case["text"], ctx)
        severities = [a["severity"] for a in alerts]
        has_critical = "critical" in severities
        expect = case["expect"]
        ok = (
            (expect == "critical" and has_critical)
            or (expect == "alert" and bool(alerts))
            or (expect == "no_critical" and not has_critical)
        )
        mark = "PASS" if ok else "FAIL"
        titles = "; ".join(f"{a['severity']}:{a['title']}" for a in alerts) or "(無警示)"
        print(f"[{mark}] {case['id']:40s} expect={expect:12s} got={titles}")
        if not ok:
            failures.append(case["id"])

    print()
    if failures:
        print(f"FAIL：{len(failures)}/{len(CASES)} 案例未達期望 → {failures}")
        return 1
    print(f"PASS：{len(CASES)}/{len(CASES)} 全數符合期望")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
