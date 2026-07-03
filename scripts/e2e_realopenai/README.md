# 真 OpenAI 本機 E2E 問診測試工具

對 GU_0410 backend 跑「真 OpenAI」文字問診 E2E：病患模擬器（gpt-4o-mini）經
WebSocket 全程用 `text_message` 與 backend 對話，逐輪撈 Redis supervisor_guidance、
結束後撈 DB 斷言。不修改 repo（含 worktree）任何檔案。

受測 backend 可切換：預設原 repo `/Users/chun/Desktop/GU_0410/backend`
（分支 fix/api-audit-remediation @ aa72d38）；§E 驗收時用
`E2E_BACKEND_DIR=<worktree>/backend`（分支 fix/e2e-audit-egroup）。

## 檔案

| 檔案 | 用途 |
|---|---|
| `compose.override.yml` | 疊在 repo docker-compose.yml 上，postgres→55432、redis→56379（本機 5432/6379 被原生服務佔用） |
| `local.env` | uvicorn / alembic / driver 的環境覆寫（本機 DB/Redis、`REDIS_KEY_PREFIX=gu:` 必須） |
| `driver.py` | 主 driver：註冊→建場次→WS 對話→模擬器→guidance 輪詢→DB 斷言→JSON；`reanalyze <scenario>` 離線重算斷言（不重跑、不花額度） |
| `run_scenario.sh` | 一鍵跑單一情境（吃 `E2E_BACKEND_DIR`） |
| `start_backend.sh` | 啟動受測 backend（前景執行；吃 `E2E_BACKEND_DIR`，venv 共用主 repo） |
| `results/*.json` | 逐字稿 + 事件 + guidance timeline（附時間戳）+ DB 斷言結果 |
| `uvicorn.log` | backend 日誌 |

## 啟動基礎設施

```bash
E2E=/private/tmp/claude-501/-Users-chun-Desktop-GU-0410/1337bb7a-da86-4a4c-b956-6e2350c1f83f/scratchpad/e2e

# 1. docker postgres + redis（project 名 gu_0410，沿用既有 volume）
docker compose -p gu_0410 \
  -f /Users/chun/Desktop/GU_0410/docker-compose.yml \
  -f $E2E/compose.override.yml up -d postgres redis

# 2. migrate（local.env 讓 alembic env.py 不啟用 Supabase SSL）
#    §E 驗收時 cd 到 worktree 的 backend（新 migration 才會套上），venv 共用主 repo：
cd /Users/chun/Desktop/GU_0410/backend        # 或 <worktree>/backend
set -a; source $E2E/local.env; set +a
/Users/chun/Desktop/GU_0410/backend/venv/bin/alembic upgrade head

# 3. 起受測 backend（背景跑）
nohup $E2E/start_backend.sh > $E2E/uvicorn.log 2>&1 &                     # 原 repo
# E2E_BACKEND_DIR=<worktree>/backend nohup $E2E/start_backend.sh > $E2E/uvicorn.log 2>&1 &  # §E worktree
curl -s http://127.0.0.1:8000/api/v1/healthz/deep   # 應回 {"status":"ok",...}
```

## 跑情境

```bash
$E2E/run_scenario.sh dontknow_zh          # 已跑：驗收 #2「不知道不再換句話重問」（40c2f42）
$E2E/run_scenario.sh hematuria_coop_en    # 已跑：D1 基線（對照組，勿覆蓋 results JSON）

# §E 修復後驗收（等通知才跑；跑之前先用 worktree 起 backend）：
export E2E_BACKEND_DIR=<worktree>/backend
$E2E/run_scenario.sh torsion_critical_zh
$E2E/run_scenario.sh hematuria_coop_en_fixed
$E2E/run_scenario.sh ed_zh
```

結果寫到 `results/{scenario}.json`。每情境會註冊一個新病患帳號
（register rate limit 5/hour/IP，短時間重跑多次會 429）。

## 情境與斷言

已跑（2026-07-03，baseline @ aa72d38）：

- **dontknow_zh**（zh-TW、頻尿 c2）：病患對 onset/duration 與過去病史一律「我真的不知道」。
  斷言：(a) 說不知道後 AI 不再問同欄位（逐欄位關鍵字掃描 + 人工判讀）；
  (b) guidance missing_hpi 丟棄已拒答欄位、next_focus 不指向、hpi 能到 80+；
  (c) ≤10 回合自動結束 + SOAP。結果：7/8 PASS（唯一 FAIL 是第一輪無指導時
  conversation LLM 換句話重問 onset 一次）。
- **hematuria_coop_en**（en-US、血尿 c1）：合作病患，第 12 回合後每輪道別。
  D1 主症狀未重現（10 回合硬上限收尾、有 SOAP），但 deferral 機制（第 9 輪道別被
  high alert 擋掉）與 alerts 不冪等（同 title 6 筆）都入鏡 → 為 §E 修復對照基線。

§E 修復後驗收（**先不要跑，等通知**）：

- **torsion_critical_zh**（zh-TW、陰囊腫脹 c7，上限 4 回合）：第一輪即典型睪丸扭轉描述。
  斷言：t1 第 1 輪 `aborted_red_flag`；t2 critical alert 入庫；t3 有 SOAP；
  **t4 `sessions.red_flag=true` 且 `red_flag_reason` 非空（A4；修復前 false/空）**。
- **hematuria_coop_en_fixed**（同 baseline 情境、換驗收斷言）：
  h1 ≤ HARD_CAP(10)+MAX_HARD_CAP_DRAIN_DEFERS(2)=12 回合 `completed`（E1/E3）；
  h2 恰好 1 份 SOAP；**h3 `red_flag_alerts` 同 canonical_id 僅 1 筆（A5）**；
  **h4 `soap_reports.language='en-US'`（B3）**；h5 收尾輪 AI fullText 非空（A1，
  baseline 上是空字串）。上限值可用 `E2E_HARD_CAP` / `E2E_DRAIN_DEFERS` 覆寫。
- **ed_zh**（zh-TW、勃起功能障礙 c8，上限 12 回合）：配合病患，預期 8-10 輪自動結束。
  斷言：e1 completed；e2 有 SOAP；**e3 `icd10_codes` 含 N52 開頭（B1）**；
  **e4 `icd10_verified=true`（B2）**。

DB 欄位（`soap_reports.language/icd10_codes/icd10_verified`、`sessions.red_flag`、
`red_flag_alerts.canonical_id`）都做了存在性偵測，worktree schema 變動不會炸 driver。

## 注意

- OPENAI_API_KEY 是真 key：情境照上表跑、不要加跑；torsion 上限 4 回合、ed 12 回合。
- `REDIS_KEY_PREFIX` 一定要是 `gu:`：conversation_handler 讀 guidance 時
  hardcode `gu:session:{id}:supervisor_guidance`，supervisor 寫入卻用
  settings.REDIS_KEY_PREFIX；prefix 不是 `gu:` 時 guidance 迴路整條斷掉。
- WS 路徑是 `/api/v1/ws/sessions/{session_id}/stream`（`?token=` legacy 認證仍可用）。
- 建場次一定要帶 `chiefComplaintText`（前端行為）；不帶會踩
  `_validate_session` fallback 到 ORM 物件的 TypeError，WS 直接斷線。
- 收尾：`pkill -f "uvicorn app.main:app"`；docker compose 服務留著重用。
