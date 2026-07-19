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

## 已知陷阱

- 每情境註冊新病患帳號，register rate limit **5/hour/IP**，短時間重跑會 429
- 本機原生 postgres/redis 佔 5432/6379，所以 override 用 55432/56379——別改回去
- 基線 results JSON（如 `hematuria_coop_en`）是對照組，**勿覆蓋**
- 批次工具 `batch_runner.py`（40 場 × 5 語言，2026-07-06 research analytics 驗證用）原存於 session scratchpad，**已被系統清除**。需要批次時從 `driver.py` 重建（方法記錄於 docs/archive/consultation_soap_improvement_proposal.md §壓力測試、docs/research_analytics.md），重建後直接收進 `scripts/e2e_realopenai/` 入庫，別再放 scratchpad。

## Common Rationalizations

| 藉口 | 現實 |
|---|---|
| 「mock LLM 的測試過了就夠了」 | D1–D6、E 系列問題全是 mock 測不出、真 OpenAI e2e 才現形的 |
| 「跑一場太慢，先合併再說」 | 一場約幾分鐘；生產回歸的除錯成本是它的數十倍 |

## Verification

- [ ] 相關情境的 `results/{scenario}.json` 顯示斷言全過
- [ ] 逐字稿人工掃過：無漏問必問風險因子、無誤觸結束、措辭符合 kiosk 情境
- [ ] 新增的驗證工具已入庫（不在 scratchpad）
