---
name: e2e-real-openai
description: 用真 OpenAI 在本機對 backend 跑端到端問診驗證（病患模擬器經 WebSocket 對話、撈 Redis guidance、DB 斷言）。Use when 問診管線、SOAP prompt、紅旗偵測、自動結束邏輯有任何改動需要合併前驗證，或需要批次多場景/多語言驗證時。
---

# 真 OpenAI 端到端問診驗證

## Overview

單元測試抓不到 LLM 行為回歸；這套工具用 gpt-4o-mini 病患模擬器與受測 backend 真實對話，逐輪撈 supervisor guidance、結束後做 DB 斷言，輸出 JSON 逐字稿。是所有管線/prompt 改動的合併前置驗證。

## When to Use

- `voice-pipeline-invariants` skill 要求驗證時（管線、prompt、紅旗、結束邏輯改動）
- 需要批次驗證（多情境 × 多語言）產出統計數據時
- NOT for：純前端 UI 改動（用 Playwright `npm run test:e2e`）

## 操作依據

**唯一權威文件：`scripts/e2e_realopenai/README.md`** — 完整啟動步驟、情境清單、環境覆寫都在那裡，照做即可。摘要：

1. `compose.override.yml` 疊在 repo docker-compose.yml 上起 postgres（:55432）+ redis（:56379）
2. source `local.env`（`REDIS_KEY_PREFIX=gu:` 必須）→ `alembic upgrade head`
3. `start_backend.sh` 起受測 backend（可用 `E2E_BACKEND_DIR` 指到 worktree 測分支）
4. `run_scenario.sh <scenario>` 跑情境，結果在 `results/{scenario}.json`
5. `driver.py reanalyze <scenario>` 可離線重算斷言，不重跑、不花額度

## 選哪個情境（依改動類型）

| 改了什麼 | 至少要跑 |
|---|---|
| 紅旗偵測 / 關鍵字 / 否定守衛 | `torsion_critical_zh` **＋ `torsion_wordorder_zh` 或 `torsion_critical_en`** |
| intake / §3b 風險因子 gating | `intake_wiring_zh`（含白箱斷言）＋ `ed_3b_zh`（**無 intake**，驗必問沒被跳過） |
| 自動結束 / don't-know | `dontknow_zh` |
| SOAP 生成 / 措辭 | 任一場都會驗，但 `intake_wiring_zh` 會逐欄比對 intake→SOAP |

⚠️ **只跑 `torsion_critical_zh` 驗不到規則層**。它的 persona 台詞「左邊睪丸突然劇烈疼痛」
曾經剛好與關鍵字互相配適，讓規則層 4/5 語漏偵測撐了三輪沒被發現——
**驗收套件證明的是「這句台詞會命中」，不是「這個臨床情境會命中」**。語序變體情境就是為此存在的。

## 斷言是多態的（2026-07-27 起）

`pass` / `fail` / `not_applicable` / `precondition_not_met`。
**`precondition_not_met` 不等於 pass**——它代表「這條根本沒驗到」，`overall_status` 會是 `INCOMPLETE`。
歷史教訓：AI 全場沒問過病史，「不重問病史」的斷言卻報 pass，空跑被當成驗過。
`not_applicable` 才是「本情境依設計不適用」（例如 cooperative persona 不會有紅旗事件）。

## 已知陷阱

- 每情境註冊新病患帳號，register rate limit **5/hour/IP**，短時間重跑會 429。
  清法：`docker exec gu_0410-redis-1 sh -c "redis-cli --scan --pattern 'gu:rl:register_ip:*' | xargs -r redis-cli DEL"`
- 本機原生 postgres/redis 佔 5432/6379，所以 override 用 55432/56379——別改回去
- **`results/` 已被 gitignore**（`scripts/e2e_realopenai/.gitignore`），逐字稿不進版控；
  要保留對照組請另存檔名（如 `*.baseline_pr29.json`）
- **provenance 檢查**：driver 會確認 `:8000` 上跑的是當前磁碟碼。本機若有別的專案容器
  也綁 `:8000`，早期版本會誤判成「伺服器跑舊碼」害整場 FAIL——已改成只看受測 backend 那個 process，
  但看到 provenance 相關 FAIL 時先 `lsof -nP -iTCP:8000 -sTCP:LISTEN` 確認是不是這回事
- 白箱探針（`intake_wiring_zh` 的 i1–i4）是在 driver 進程裡 import **磁碟上**的模組重算，
  **與 :8000 那個 uvicorn 載入的碼沒有綁定**——所以改完碼一定要重啟 backend 再跑
- 批次工具 `batch_runner.py`（40 場 × 5 語言，2026-07-06 research analytics 驗證用）原存於 session scratchpad，**已被系統清除**。需要批次時從 `driver.py` 重建（方法記錄於 docs/archive/consultation_soap_improvement_proposal.md §壓力測試、docs/research_analytics.md），重建後直接收進 `scripts/e2e_realopenai/` 入庫，別再放 scratchpad。

## Common Rationalizations

| 藉口 | 現實 |
|---|---|
| 「mock LLM 的測試過了就夠了」 | D1–D6、E 系列問題全是 mock 測不出、真 OpenAI e2e 才現形的 |
| 「跑一場太慢，先合併再說」 | 一場約幾分鐘；生產回歸的除錯成本是它的數十倍 |
| 「斷言全綠了就是通過」 | §R 四輪的起點就是「4 個情境全綠，但**斷言驗不到它宣稱驗的東西**」。看到綠先問這條斷言結構上有沒有可能失敗 |
| 「斷言紅了，把它放寬就好」 | 先分辨是**產品缺陷**還是**斷言過嚴**，兩者的修法相反。放寬前要能說出「為什麼這個行為其實是對的」 |
| 「SOAP 有 row 就是生成了」 | 那是場次結束當下 INSERT 的 GENERATING 空殼列。要等 `status='generated'` 且 `generated_at` 非空 |

## Verification

- [ ] 相關情境的 `results/{scenario}.json` 顯示斷言全過，且**沒有 `precondition_not_met`**
- [ ] SOAP 斷言看的是 `status='generated'` 不是「有沒有 row」
- [ ] 逐字稿人工掃過：無漏問必問風險因子、無誤觸結束、措辭符合 kiosk 情境
- [ ] 紅旗改動：`red_flag_alerts.confidence` 不是 `semantic_only`（否則規則層根本沒參與）
- [ ] 新增的驗證工具已入庫（不在 scratchpad）
