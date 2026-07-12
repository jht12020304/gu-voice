---
name: voice-pipeline-invariants
description: 列出 GU Voice 語音問診管線（VAD/靜音/TTS/紅旗偵測/§3b 風險因子/STT）的不變式與修改流程，防止改動時破壞已修復的行為。Use when modifying frontend/src/stores/conversationStore.ts、frontend/src/screens/patient/ConversationPage.tsx、backend/app/pipelines/ 下任何檔案（llm_conversation、red_flag_detector、supervisor、soap_generator、prompts/）、或任何影響問診對話行為的改動。
---

# 語音問診管線不變式

## Overview

這條管線的每一條不變式都對應一個修過的生產 bug 或 e2e 驗收（詳見 docs/e2e_realopenai_audit_2026-06-28.md、docs/product_audit_2026-07-06.md）。改動前先核對清單，改動後用 `e2e-real-openai` skill 驗證，否則回歸風險極高。

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
10. §3b 高風險主訴風險因子必問：動態硬上限 + 軟門檻下限 + 極簡收尾 prompt（PR#29 設計，見 docs/consultation_soap_improvement_tracking.md）。改 prompt 時不得破壞這組配額邏輯。
11. 病患面措辭遵守 kiosk 情境：「請稍候等看診」「請告知現場醫護」，禁用「盡速就醫」。

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
