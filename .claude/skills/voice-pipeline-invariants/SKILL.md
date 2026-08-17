---
name: voice-pipeline-invariants
description: 列出 GU Voice 語音問診管線（VAD/靜音/TTS/紅旗偵測/§3b 風險因子/STT）的不變式與修改流程，防止改動時破壞已修復的行為。Use when modifying frontend/src/stores/conversationStore.ts、frontend/src/screens/patient/ConversationPage.tsx、**flutter_app/lib/features/voice/ 下任何檔案**（conversation_controller、vad_logic、tts_playback_controller、audio_stream_service、ws_manager）、backend/app/pipelines/ 下任何檔案（llm_conversation、red_flag_detector、supervisor、soap_generator、prompts/）、或任何影響問診對話行為的改動。**這條管線有兩份前端實作，改動要同時顧 React 與 Flutter。**
---

# 語音問診管線不變式

## Overview

這條管線的每一條不變式都對應一個修過的生產 bug 或 e2e 驗收（詳見 docs/archive/e2e_realopenai_audit_2026-06-28.md、docs/archive/product_audit_2026-07-06.md）。改動前先核對清單，改動後用 `e2e-real-openai` skill 驗證，否則回歸風險極高。

## When to Use

- 動到 `frontend/src/stores/conversationStore.ts` 或 `frontend/src/screens/patient/ConversationPage.tsx`
- 動到 `flutter_app/lib/features/voice/` 下任何檔案（同一條管線的第二份實作，2026-07-26 起）
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
18. **終態的 `session_status` 必須帶 `status`**：`send_localized_to_session` 的 canonical code 只夠拿來顯示文字，前端是靠 `extra` 裡的 `status` 才認得出「這場結束了」而導向感謝頁。`end_session` 曾漏填 → 後端場次 completed、SOAP 也生成了，但病患畫面停在對話頁、按鈕像壞掉（2026-07-27 由 Flutter 真跑抓到）。新增任何終端路徑都要帶。**對稱地，前端不得在送出 `end_session` 後本地搶先設 `completed`**：導頁會讓 autoDispose 拆掉 controller、`_ws.disconnect()` 早於指令送達，整場丟失。

**2026-07-27 §R 新增（見 `docs/TODO.md` §R 與 §R-lessons）**

19. **`patient_context.build_patient_info` 是 patient_info 的唯一來源**。WS 與 Celery SOAP 兩條路徑都必須走它。歷史教訓：兩份 builder 分岔，Celery 那份只放 name/gender/age、**完全不讀 `sessions.intake_data`**，導致 `soap_generator` 的病史/用藥/過敏/家族史四個分支在生產路徑是死碼，SOAP 對家族史寫「未提供」而 intake 明載父親膀胱癌。不得為了方便在任一端重新組裝。
20. **每一個終態都要有 SOAP**。會生成 SOAP 的路徑：手動 `end_session`、自動結束、critical 紅旗中止、硬上限前遲到 critical、遲到 critical 的 drain、閒置逾時。新增任何終態轉移時**同時**檢查這六件事：改 status、派 SOAP、送病患端 `session_status`（帶 `extra`）、廣播 dashboard、建醫師通知、設 `_terminated`。主 abort 分支做全套、drain 分支只做兩件，就是這樣漏掉的。
    ※ 病患直接關瀏覽器 → 60 分鐘後 cancelled、無 SOAP：那是**產品決策**（未完成場次要不要出報告），不是缺陷。
21. **紅旗規則層用「同句共現」不是相鄰字串比對**。裸關鍵字會 over-trigger（`eyeball hurts` 命中 `ball hurt`）、相鄰複合詞會 under-trigger（真人語序在部位詞與修飾詞之間插入時間/方位，zh/ja/ko/vi 四語 0 命中）。共現組（部位詞 × 急性/嚴重度詞，同句內距離上限）天生同時解掉兩個方向。新增紅旗或補關鍵字時**不要退回字串相鄰比對**。
22. **紅旗規則層偏誤報（2026-07-27 臨床拍板）**。誤中止＝病患白等、護理師走一趟，可逆；漏報不可逆。據此：
    - **每一條抑制守衛都是潛在漏報，舉證責任在保留方**。要留就要能說出「為什麼它不會造成漏報」。
    - 政策接受的誤報（第三人稱轉述、韓文無標點別部位、英文 `bladder is fine`）寫在 `test_red_flag_suppression_policy.py` 的**正向測試**裡，**不是 xfail**——xfail 的語意是「缺陷、暫時容忍」，會誘導後人修好它而開出漏報。要改成不觸發需臨床重新拍板。
    - severity 分級要照臨床定義。`gross_hematuria_heavy`(critical) 的判準是**量與血塊**不是顏色；把 `bright red`/`bloody` 收進去會讓血尿病患（主訴 c1）一講出自己的主訴就被中止。
23. **§3b gating 是三態不是兩態**：明確的「無」（`no_*` 旗標）→ 不問；值**真的涵蓋**該風險因子 → 不問；**值不涵蓋或欄位空白 → 仍必問**。判不準一律歸「仍必問」。家族史要**逐筆**判定——整串當 haystack 會讓「母親：乳癌、父親：攝護腺肥大」被判成有泌尿癌家族史，而 prompt 還叫 LLM 直接寫進病史＝**捏造病歷**。gating 只吃本次場次 intake，不吃 `patients` 表舊資料。
24. **SOAP 的 `plan.patient_education` 與 `summary` 是病患面欄位**（渲染在 React `PatientSessionDetailPage` 與 Flutter `patient_session_detail_page`），受 #11 kiosk 措辭鐵律約束，prompt 與出口消毒兩層都要有。`plan` 的其他欄位是醫師面，不受限制。判準是「**有沒有叫病患自行離場**」而不是「有沒有出現某個詞」——「醫師會為您安排急診評估」對候診中的病患不違規。

## ⚠️ 這些不變式現在有兩份實作

2026-07-26 起 `flutter_app/`（Dart，已入 main 未上生產）與 `frontend/`（React，生產在跑）
都實作這條管線，**改動要同時顧兩邊**。純函式核心（shouldUnmuteVAD 64 組矩陣、TTS epoch
世代取消、PCM ring buffer）是逐字 port 且有測試，但移植時漏掉的閘門造成過這些缺陷（皆已修）：

| 不變式 | Flutter 的移植缺口 |
|---|---|
| #3 AI 出聲硬鎖 | `onSpeechEnd` 漏掉 hard-mute → 麥克風整段 STT+LLM+TTS 都活著，AI 自己的喇叭回音被當成病患下一句 |
| #3/#5 | `onSpeechStart` 無硬鎖 re-assert；`stopActive()` 在 `await _player.stop()` **之後**才捕獲 `_activeStep` → 誤 complete 新 step，VAD 提前解鎖 + 舊 completer 洩漏 |
| #4 userPaused 獨立閘門 | `pause()` 先送 `pause_recording` 才 mute → flush 的 final chunk 被後端丟棄，病患半句症狀消失、狀態列永久卡「正在辨識」 |
| #11 kiosk 措辭 | 紅旗中止時 `ref.listen` 讀 build 期快照 → 病患拿到一般感謝頁 + 8 秒自動導回首頁，看不到「告知現場醫護」 |

⚠️⚠️ **Flutter 版的麥克風路徑仍未被真的跑過一次**（見 `docs/TODO.md` §V1）。
2026-07-27 用**文字代替語音**跑完了病患全流程（`integration_test/patient_text_flow_test.dart`，
真 OpenAI，normal → `completed`＋SOAP、redflag → `aborted_red_flag`，見 §V2），
所以 WS handshake、AI 追問、紅旗中止、#11 感謝頁變體、#12 SOAP 固定 zh-TW 都有實測了。
**但文字輸入繞過 VAD**——上表 #3／#4／#5 那三條（`onSpeechEnd` hard-mute、`pause()` 順序、
`onSpeechStart` re-assert）依然只有單元測試與讀碼推論撐著，**沒有一次真的對麥克風講過話**。
動 Flutter 語音碼後，除了跑 `flutter test`：
- 動到 VAD／靜音／TTS chain → 必須在 simulator 上真的講一輪（iOS Simulator 可用 Mac 麥克風）
- 動到 WS 協議／結束流程／紅旗 → 跑 `patient_text_flow_test.dart` 兩個情境就夠

⚠️ 跑 integration test 前一定要 `xcrun simctl privacy <udid> grant microphone com.guvoice.guVoice`
（`flutter test` 每次重裝都會重置 TCC）。沒授權時 `start()` 卡在 `await openMic()`，
`_ws.connect` 排在它後面 → 症狀是 WS 停在 `connecting`，很容易誤判成 WS 壞掉。

**改 Flutter 語音碼時額外注意**：`conversationControllerProvider` 必須維持 `autoDispose`
（否則跨病患 session 污染）；`tts_playback_controller` 目前**無回歸測試**（自己 `new AudioPlayer()`，
要測得先讓 player 可注入）——那是 #5 唯一沒有防護的地方。

**離開對話頁的清理是保護區**：在飛的 mic frame 與 `_ws.disconnect()` 自己發出的
`_statechange` 都晚於 provider dispose 抵達，任何在回呼裡寫 `state` 的路徑都必須先過
`_disposed` 閘門（WS 回呼統一走 `_wsOn`），否則病患每問診完一次就 `UnmountedRefException`。

## ⚠️ 改偵測邏輯時的測試設計（2026-07-27 三次擺盪的教訓）

改紅旗偵測、否定守衛、§3b gating 這類**判斷邏輯**時，測試怎麼寫比改怎麼寫更容易出錯。
2026-07-27 連續三輪擺盪（over-trigger → under-trigger → 收斂），每次根因都在這裡：

1. **測試表必須雙向對稱。** `MUST_FIRE` 與 `MUST_NOT_FIRE` 要同時存在。
   第一輪只加「必須命中」→ 改出 over-trigger；第二輪只加「不該命中」→ 改出 under-trigger。
   只往單一方向加斷言 ＝ 在替下一次擺盪鋪路。
2. **反例措辭不得與 e2e persona 台詞雷同。** 這是最深的假象：`torsion_critical_zh` 的台詞
   「左邊睪丸突然劇烈疼痛」剛好讓 `睪丸突然` 相鄰，所以 e2e 全綠——**驗收套件證明的是
   「這句台詞會命中」，不是「這個臨床情境會命中」**。加語序變體（部位詞與修飾詞之間插入
   2–8 字），並確認至少 3 種不同措辭都命中。
3. **測試的 oracle 不能是實作自己的偵測器。** SOAP 消毒層曾用自己的 regex 當判準 →
   偵測器漏掉的句型測試也一定漏掉，結果 2804 個 unit test 全綠但 e2e FAIL。
   用獨立維護的違規句語料（從真跑結果檔收集）。
4. **注入式回歸測試**：把修復故意改壞，確認有測試會紅，再還原。這招在 §R 四輪抓到 6 個
   「修了但沒有測試保護」的地方。值得當成常規步驟。

## 修改流程

1. 讀本清單，找出改動會碰到哪幾條不變式。
2. 實作改動（最小 diff）。
3. 改偵測邏輯 → 先讀上一節的測試設計四點。
4. 前端行為改動 → `npm run type-check` + 手動走一次對話流程；管線/prompt 改動 → 依 `e2e-real-openai` skill 跑至少一個相關情境（紅旗改動跑 `torsion_critical_zh` **＋ `torsion_wordorder_zh` 或 `torsion_critical_en`**，結束邏輯改動跑 `dontknow_zh`，intake/§3b 改動跑 `intake_wiring_zh`）。
5. PR 描述註明驗證了哪些不變式。

## Common Rationalizations

| 藉口 | 現實 |
|---|---|
| 「只是小改 prompt，不用跑 e2e」 | §3b 與紅旗行為對 prompt 措辭極敏感，過去多次「小改」造成漏問/誤結束，全靠 e2e 抓到 |
| 「這個 unmute 情境很特殊，直接 setMuted 就好」 | 散落的 unmute 判斷正是當初重構成 shouldUnmuteVAD 矩陣的原因 |
| 「規則層紅旗和 LLM 重複，可以刪」 | 規則層是 LLM 漏判時的 fallback（E9 加固），刪了等於單點失效 |
| 「這個誤報很蠢，加條守衛擋掉」 | 偏誤報是臨床拍板（#22）。每條抑制都是潛在漏報——先問「它會不會擋到真症狀」，多半會 |
| 「補幾個關鍵字就能修這個漏報」 | 補關鍵字是 §R 前兩輪走過的死路。用共現組（#21），否則過幾天就換另一邊出事 |
| 「單元測試全綠了，e2e 可以跳過」 | 2804 個 unit test 全綠但 e2e FAIL 發生過——測試的 oracle 是實作自己 |
| 「intake 已經填了就不用問」 | 要看**值是否真的涵蓋**該風險因子（#23）。用藥欄填 amlodipine 不等於沒吃抗凝血劑 |

## Verification

- [ ] 改動涉及的每條不變式都確認未被破壞（列在 PR 描述）
- [ ] 管線/prompt 改動有真 OpenAI e2e 結果 JSON 佐證
- [ ] 改偵測邏輯：`MUST_FIRE` 與 `MUST_NOT_FIRE` 雙向都有新增案例，且措辭不同於 persona 台詞
- [ ] 新增抑制守衛：能說出「為什麼它不會造成漏報」
- [ ] 前端改動通過 `npm run type-check` 與 `npm run lint`
