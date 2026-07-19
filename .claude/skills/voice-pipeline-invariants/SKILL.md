---
name: voice-pipeline-invariants
description: 列出 GU Voice 語音問診管線（VAD/靜音/TTS/紅旗偵測/§3b 風險因子/STT）的不變式與修改流程，防止改動時破壞已修復的行為。Use when modifying frontend/src/stores/conversationStore.ts、frontend/src/screens/patient/ConversationPage.tsx、backend/app/pipelines/ 下任何檔案（llm_conversation、red_flag_detector、supervisor、soap_generator、prompts/）、或任何影響問診對話行為的改動。
---

# 語音問診管線不變式

## Overview

這條管線的每一條不變式都對應一個修過的生產 bug 或 e2e 驗收（詳見 docs/archive/e2e_realopenai_audit_2026-06-28.md、docs/archive/product_audit_2026-07-06.md）。改動前先核對清單，改動後用 `e2e-real-openai` skill 驗證，否則回歸風險極高。

## When to Use

- 動到 `frontend/src/stores/conversationStore.ts` 或 `frontend/src/screens/patient/ConversationPage.tsx`
- 動到 `backend/app/pipelines/` 任何檔案（含 prompts/）
- 改 WebSocket 對話協議（`backend/app/websocket/conversation_handler.py`）
- NOT for：純 UI 樣式、與對話流程無關的頁面

## 不變式清單

**前端（conversationStore.ts / ConversationPage.tsx）**

1. 靜音（mute）只擋 TTS 播放，不得影響辨識與對話流程。
2. unmute 一律走 `shouldUnmuteVAD` 決策矩陣，不得散落各處各自判斷。
3. AI 講話期間硬鎖麥克風（防自迴授），TTS 結束才依矩陣決定是否開麥。
4. `userPaused` 是獨立閘門：使用者手動暫停後，任何自動流程不得替他恢復。
5. `stopActiveTTS` 中斷播放時必須補呼 `onended` 回呼，否則狀態機卡死。
6. STT 幻覺過濾與空辨識可見提示：空結果要給使用者看得到的回饋，不得靜默吞掉。
7. 開場主訴選單在地化、含「其他」sentinel 選項，raw 主訴需與後續流程一致。

**後端（app/pipelines/）**

8. 自動結束判斷：紅旗優先；「不知道」是第三態（不重問、不當否認）。
9. 紅旗偵測雙層：LLM 層 + 規則層 fallback（`red_flag_detector.py`），規則層不得被移除或繞過。
10. §3b 高風險主訴風險因子必問：動態硬上限 + 軟門檻下限 + 極簡收尾 prompt（PR#29 設計，見 docs/archive/consultation_soap_improvement_tracking.md）。改 prompt 時不得破壞這組配額邏輯。
11. 病患面措辭遵守 kiosk 情境：「請稍候等看診」「請告知現場醫護」，禁用「盡速就醫」。
12. SOAP 報告語言固定 `SOAP_REPORT_LANGUAGE`（zh-TW，2026-07-19 產品決策）：問診對話與病患端訊息走場次語言，但報告生成與 `report.language` 一律中文（讀者是院內醫護）。
13. SOAP 生成單一路徑（2026-07-19 架構修復）：`_generate_soap_report_async` 只是「建 GENERATING row → 派 Celery」的觸發器，生成本體只在 `tasks/report_queue`。不得在 WS 路徑重新 inline 生成（會回歸行程重啟遺失＋雙路徑漂移）；本機 e2e 必須起 celery worker。
14. 問診 WS 必過 `_authorize_ws_session_access`（row-level 授權，與 REST 同模型）；未授權回 4004 與不存在同碼。不得移除或繞過。
15. 紅旗/場次狀態 dashboard 事件必走 `broadcast_dashboard_event`（Redis 橋接）：生產 4 個 uvicorn 行程，退回 in-memory `broadcast_dashboard` 會讓 3/4 醫師收不到即時紅旗。
16. 場次狀態機單一權威（2026-07-19）：合法轉移只定義在 `app/core/session_state.py`（`VALID_TRANSITIONS`/`is_valid_transition`），REST 與 WS 共用。改轉移規則只改這一處；WS `_update_session_status` 送 DB 前先過 `is_valid_transition(..., allow_noop=True)`（放行 resume 自轉移），不得繞過。
17. 自動結束政策與紅旗去重已抽到 `app/pipelines/conclusion_policy.py` 與 `app/pipelines/alert_dedup.py`——**這兩個新模組仍是問診保護區**，改動視同改管線、要 e2e。conversation_handler 以底線別名 re-import，不得把邏輯改回 inline。

## 修改流程

1. 讀本清單，找出改動會碰到哪幾條不變式。
2. 實作改動（最小 diff）。
3. 前端行為改動 → `npm run type-check` + 手動走一次對話流程；管線/prompt 改動 → 依 `e2e-real-openai` skill 跑至少一個相關情境（紅旗改動跑 torsion_critical_zh、結束邏輯改動跑 dontknow_zh）。
4. PR 描述註明驗證了哪些不變式。

## Common Rationalizations

| 藉口 | 現實 |
|---|---|
| 「只是小改 prompt，不用跑 e2e」 | §3b 與紅旗行為對 prompt 措辭極敏感，過去多次「小改」造成漏問/誤結束，全靠 e2e 抓到 |
| 「這個 unmute 情境很特殊，直接 setMuted 就好」 | 散落的 unmute 判斷正是當初重構成 shouldUnmuteVAD 矩陣的原因 |
| 「規則層紅旗和 LLM 重複，可以刪」 | 規則層是 LLM 漏判時的 fallback（E9 加固），刪了等於單點失效 |

## Verification

- [ ] 改動涉及的每條不變式都確認未被破壞（列在 PR 描述）
- [ ] 管線/prompt 改動有真 OpenAI e2e 結果 JSON 佐證
- [ ] 前端改動通過 `npm run type-check` 與 `npm run lint`
