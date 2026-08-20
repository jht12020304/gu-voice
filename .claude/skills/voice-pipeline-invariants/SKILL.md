---
name: voice-pipeline-invariants
description: 列出 GU Voice 語音問診管線（VAD/靜音/TTS/紅旗偵測/§3b 風險因子/STT/終態收尾/病患面文字）的不變式與修改流程，防止改動時破壞已修復的行為。Use when modifying frontend/src/stores/conversationStore.ts、frontend/src/screens/patient/ConversationPage.tsx、**flutter_app/lib/features/voice/ 下任何檔案**（conversation_controller、vad_logic、tts_playback_controller、audio_stream_service、ws_manager）、backend/app/pipelines/ 下任何檔案（llm_conversation、red_flag_detector、supervisor、soap_generator、prompts/）、場次終態路徑（backend/app/websocket/conversation_handler.py、backend/app/services/session_service.py、backend/app/services/report_service.py）、兩份前端的 intake payload 組裝與病患面顯示頁、或任何影響問診對話行為的改動。**這條管線有兩份前端實作，改動要同時顧 React 與 Flutter。**
---

# 語音問診管線不變式

## Overview

這條管線的每一條不變式都對應一個修過的生產 bug 或 e2e 驗收（詳見 docs/archive/e2e_realopenai_audit_2026-06-28.md、docs/archive/product_audit_2026-07-06.md、2026-08-20 稽核修復戰役 commit 索引 `8e30bd3 931b9b7 116282d 6fc51e3 7e28d11 2daa82c c6938c8 24d3083 fb403d6`）。改動前先核對清單，改動後用 `e2e-real-openai` skill 驗證，否則回歸風險極高。

## ⚠️ 已知缺口（2026-08-21，修復中——別當成已保證的行為）

這份清單記的是**程式碼實際的樣子**，不是應該的樣子——**每一條都在 `6ecf10a` HEAD（＝目前生產跑的碼）上可以逐句重現**。以下五處不變式有已實測重現的破口：

| 缺口 | 影響 | 詳見 |
|---|---|---|
| **紅旗跨子句漏報**：`我今天小便，然後有很多血塊` → **零紅旗**（`6fc51e3` 把裸「血塊」降進 `urine_x_heavy_blood` 的回歸，該共現組沒開 `cross_clause`） | 大量血尿最自然的真人語序不再命中 critical | #30 的 ⚠️、TODO S7 |
| **SOAP prompt 完全沒過 `sanitize_for_prompt`**：D-1 只覆蓋對話路徑（`supervisor` / `llm_conversation`），`soap_generator.generate()` 直接 f-string 病患欄位進 prompt（其中三欄還吃 `patients` 表 fallback） | 攻擊面最大、含 PHI 最多的那條 prompt 可被偽區段注入 | #32 的 ⚠️、TODO S8 |
| **`sanitize_for_prompt` 的行首 `#` 只剝一次**：`'# ## Consultation Transcript'` → `'## Consultation Transcript'`（實測） | **消毒層自己漏**：過了消毒的值仍可能以 `##` 開頭 → 上一條修好也擋不住這個形狀 | #32 的 ⚠️⚠️、TODO S10 |
| **越南文 `tiểu` 假朋友**：`tôi bị tiểu đường và hôm qua tôi bị sốt`（我有糖尿病、昨天發燒）→ `urosepsis(critical)` | 糖尿病是 §3b 必問風險因子，vi 場次講到自己的病史就被中止問診 | #25 的 ⚠️、TODO S12 |
| **`is_dont_know` 對含數詞的固定語誤判**：`我不知道，一天到晚都在痛` → 判成「有回答」 | 真拒答**沒進** declined 清單 → 禁令沒下、過期的 `next_focus` 續指同欄 → **AI 會換句話重問該欄**（正是 R19 那個失效面） | #8 的 ⚠️、TODO S9 |

前四條有執行者正在修（工作區已有未 commit 的改動），**在 commit + e2e 驗收之前不要在別處記成已修**；`is_dont_know` 那條尚無人認領（已列進 TODO S9，別讓它只活在這張表裡）。

⚠️ **這張表的門檻是「在 HEAD 上重現得出來」**——只在某個未 commit 的中間態存在過的缺陷不列在這裡（那種東西讀者無從複驗，寫成現在式只會製造假情報）。終態 AST 跳閘器的 tuple 盲點就是這一類：它從來沒被 commit 過，見 #29 的設計說明。

⚠️ **編號對照**：紅旗跨子句漏報這條在文件叫 **S7**、在 `shared.py` 的碼內註解叫 **RF-5**——同一個缺陷。看到 RF-5 就是在講 S7。

另有兩處**單邊落實**（不是缺陷但常被讀成兩端通則）：#18 的四條結束流程行為 Flutter 只有一條；#28 的「純函式 + 精確 JSON 斷言」只有 Flutter 有。

## When to Use

- 動到 `frontend/src/stores/conversationStore.ts` 或 `frontend/src/screens/patient/ConversationPage.tsx`
- 動到 `flutter_app/lib/features/voice/` 下任何檔案（同一條管線的第二份實作，2026-07-26 起）
- 動到 `backend/app/pipelines/` 任何檔案（含 prompts/）
- 改 WebSocket 對話協議（`backend/app/websocket/conversation_handler.py`）
- 動到場次終態轉移（`app/services/session_service.py`、`app/services/report_service.py`、`app/tasks/session_timeout.py`）或兩份前端的 intake payload 組裝／病患面顯示頁
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
    ※ **「帶保留的有效回答」不算拒答**（2026-08-20 D-8）。標記詞比對是**裸子字串**，所以「我不確定，大概三天前吧」「不知道要打幾分，大概七分」整句被判成拒答 → `effective_next_focus` 把 pending 指導換成推進指令、`build_dont_know_ban` 再把該欄所有換句話句式列為本輪硬性禁令——**病患明明給了值，AI 卻連一次澄清（「所以是三天前開始的嗎」）都不能問**。現行判準：標記詞 **∧ 同句沒有「數值＋量詞」**。疑問數詞（幾／多少／how long／どのくらい／얼마나／bao lâu）在比對前先被挖除，所以「不知道幾天」「don't know how many days」**仍判拒答**——那是最常見的拒答句型，也是這個窄化最容易寫壞的一邊。量詞白名單只收時間／次數／程度分數，正好是 onset / duration / severity 三欄會拿到的值型別。證據 `next_focus_guard.py` 的 `_QUESTION_QUANTIFIERS` / `_CONCRETE_VALUE` 兩個常數（上方就是 #22 舉證段）與 `has_concrete_value` / `is_dont_know` 兩支函式；雙向語料 `test_dont_know_concrete_value_guard.py`（`MUST_FIRE` 收「不知道幾天」／`MUST_NOT_FIRE` 收「帶保留的有效回答」）與 `test_next_focus_reask_guard.py`（用的是 `MUST_REPLACE` / `MUST_KEEP` 兩張表，`:46`／`:112`，不是 FIRE/NOT_FIRE），e2e 回歸 `dontknow_zh` 的 `a2_no_duration_reask_after_dontknow`。
    ⚠️ **已知缺口（2026-08-21 實測，尚無人認領，TODO S9）：含數詞的固定語會讓真拒答被判成有回答。** `next_focus_guard.py` 的 `_CONCRETE_VALUE` 舉證段註解宣稱「不存在『病患拒答但被判成有回答』的路徑」，實測有反例——`is_dont_know('我不知道，反正一天比一天嚴重')`／`('我不知道，一天到晚都在痛')`／`('記不得了，反正一天到晚跑廁所')` **三句全回 `False`**（「一天」符合 `_NUMERAL + _UNIT`，但成語裡的「一天」不是可記錄的值）。文件原本只點名疑問數詞那一邊「最容易寫壞」，實際最容易漏的是這一邊。
    **後果是「重問」不是「不問」——別寫反了。** `is_dont_know` 全庫只有一個消費端：`declined_fields_from_history`（`next_focus_guard.py`）。回 `False` ＝ 該欄**不進** declined 集合 ＝ ①`build_dont_know_ban`（`llm_conversation.py` 組 system prompt 時呼叫）拿到空集合、**本輪不下換句話禁令**；②`effective_next_focus` 看到 `declined` 為空就**原封不動回傳過期的 `next_focus`**，而那份 guidance 是在拒答之前算的、仍指著同一欄。兩條合起來＝**AI 會換句話重問病患剛拒答的那一欄**，正是這整層（四層防線／R19）存在的理由。動這條窄化時要把上面三句補進 `MUST_FIRE`。
9. 紅旗偵測雙層：LLM 層 + 規則層 fallback（`red_flag_detector.py`），規則層不得被移除或繞過。
    ※ **否定幻覺後過濾只套在語意層**（2026-08-20 RF-1，P0 漏報）。這道過濾原本套在**所有** alert 上，但它的判準 `_CANONICAL_KEYWORDS` 只收 triggers／triggers_by_lang、**不認識共現組**，於是規則層靠共現組命中的 critical 被整筆丟掉：「我沒有高燒，但是我發燒到三十八度而且小便會痛」→ 規則層 urosepsis critical（發燒 × 小便），但 canonical 關鍵字只有被否認的「高燒」→ 整筆刪掉 → **漏報**（urinary_retention、cauda_equina_suspected 同型）。修法不是為了讓測試變綠：規則層自己的否定守衛對每個關鍵字位置、共現組的部位詞／急性詞／整段跨度三處都跑過 `_occurrence_negated`，**能產出 alert 就代表已經有一處非否定證據**；再拿一份看不到共現組的關鍵字表覆蓋它，只會刪掉正確命中。證據 `red_flag_detector.py:2186-2213`。
    ※ **DB 規則的 regex 路徑同樣要過 `_occurrence_negated`**（D-6）：關鍵字路徑早就有否定守衛，regex 路徑沒有 → 同一句「我沒有血尿」在兩條路徑得到相反結論。逐一 `finditer` 找第一個非否定 match，證據 `:1862-1902`。
    ※ **DB rule 的 `canonical_id` 為 NULL 要先用 name 反查目錄救回**（`red_flag_detector._resolve_db_canonical_id`；反查表是同檔的 `_TITLE_TO_CANONICAL`）。救不回要 log warning——canonical_id 缺席時共現組／severity floor／後過濾三張表對該規則**靜默失效**。
10. §3b 高風險主訴風險因子必問：動態硬上限 + 軟門檻下限 + 極簡收尾 prompt（PR#29 設計，見 docs/archive/consultation_soap_improvement_tracking.md）。改 prompt 時不得破壞這組配額邏輯。
11. 病患面措辭遵守 kiosk 情境：「請稍候等看診」「請告知現場醫護」，禁用「盡速就醫」。
12. SOAP 報告語言固定 `SOAP_REPORT_LANGUAGE`（zh-TW，2026-07-19 產品決策）：問診對話與病患端訊息走場次語言，但報告生成與 `report.language` 一律中文（讀者是院內醫護）。
    ※ **病患端另走 `soap_reports.patient_facing_localized`**（2026-08-20）。斷層在於 `summary` 與 `plan.patient_education` 這兩欄是**病患自己在畫面上讀的**：越南語病患全程講越南語，最後拿到一段中文摘要。現行作法是主報告 commit **之後**用一次小模型呼叫，把**已消毒的**中文 `summary` / `patient_education` 轉述成場次語言（TRANSLATE ONLY），輸出再過**目標語言**的消毒層（#11/#24）。三個「絕不」寫在碼裡：絕不在主報告 commit 前跑、絕不讓失敗往上冒（留 NULL）、絕不在 rollback 後留下髒 session。zh-TW 場次恆為 NULL。**這是附加欄位——`report.language` 與主報告仍是 zh-TW，不得為了病患端把主報告改成場次語言。** 五語 `_PATIENT_FACING_CLAUSE` 文案自此才真正活化。證據 `models/soap_report.py:55-63`、migration `alembic/versions/20260820_1000-soap_report_patient_facing_localized.py`、`soap_generator.py` 的 `_LOCALIZE_SYSTEM_PROMPT` 與 `localize_patient_facing`（**「輸出過目標語言消毒層」的證據是該函式尾端呼叫 `_sanitize_patient_facing_text(..., target_language)` 那兩段，在 `localize_patient_facing` 內、不在 `_LOCALIZE_SYSTEM_PROMPT` 附近**）、`tasks/report_queue.py:529-580`。前端接法見 #37。
13. SOAP 生成單一路徑（2026-07-19 架構修復）：`_generate_soap_report_async` 只是「建 GENERATING row → 派 Celery」的觸發器，生成本體只在 `tasks/report_queue`。不得在 WS 路徑重新 inline 生成（會回歸行程重啟遺失＋雙路徑漂移）；本機 e2e 必須起 celery worker。
    ※ **REST 路徑共用同一支觸發器**（2026-08-20 EM-2）：`session_service._after_status_transition` 刻意 import `conversation_handler._generate_soap_report_async`，而不是自建一份「建 row + delay」。派任務一律 `commit → delay()`（先 commit 才不會讓 worker 讀到還沒落地的 row）。
    ※ **可產報告的場次終態是 `REPORT_ELIGIBLE_SESSION_STATUSES` = {completed, aborted_red_flag}**（SO-2）。以前這裡是一行 `!= COMPLETED`，把 `aborted_red_flag` **整類排除在報告之外**——那正好是最需要報告的一類：問診被系統主動掐斷，醫師接手時最需要中止當下的臨床脈絡，沒有報告等於只能裸讀逐字稿。`cancelled` **刻意不派**（與 `tasks/session_timeout`、`_SOAP_ON_TERMINAL` 同政策：未完成場次不出報告是產品決策）——要改政策**三處一起改**。證據 `report_service.py:43-62`、`session_service.py:98-100`（「三處一起改」的理由註解）／`:101-103`（`_SOAP_ON_TERMINAL` 集合本身）。
    ※ **regenerate 語意**（`report_service.py:70-99`）：只對 GENERATED/FAILED 生效；GENERATING 一律 409（防醫師連點讓兩個 Celery 任務互相覆寫同一 row），但**逾 10 分鐘允許 stale 接手**——派任務是 `commit → delay()`，broker 掛掉時 row 已是 GENERATING 而任務沒送出，沒有時效的 409 會把「醫師手動 regenerate 補救」這條路徑永久堵死。
14. 問診 WS 必過 `_authorize_ws_session_access`（row-level 授權，與 REST 同模型）；未授權回 4004 與不存在同碼。不得移除或繞過。
15. 紅旗/場次狀態 dashboard 事件必走 `broadcast_dashboard_event`（Redis 橋接）：生產 4 個 uvicorn 行程，退回 in-memory `broadcast_dashboard` 會讓 3/4 醫師收不到即時紅旗。
16. 場次狀態機單一權威（2026-07-19）：合法轉移只定義在 `app/core/session_state.py`（`VALID_TRANSITIONS`/`is_valid_transition`），REST 與 WS 共用。改轉移規則只改這一處；WS `_update_session_status` 送 DB 前先過 `is_valid_transition(..., allow_noop=True)`（放行 resume 自轉移），不得繞過。
17. 自動結束政策與紅旗去重已抽到 `app/pipelines/conclusion_policy.py` 與 `app/pipelines/alert_dedup.py`——**這兩個新模組仍是問診保護區**，改動視同改管線、要 e2e。conversation_handler 以底線別名 re-import，不得把邏輯改回 inline。
    ※ `app/pipelines/next_focus_guard.py`（2026-08-18 新增，防 supervisor 換句話重問已拒答欄位的四層防線之一）**同屬保護區**，改動視同改管線、要 e2e（`dontknow_zh`）。
18. **終態的 `session_status` 必須帶 `status`**：`send_localized_to_session` 的 canonical code 只夠拿來顯示文字，前端是靠 `extra` 裡的 `status` 才認得出「這場結束了」而導向感謝頁。`end_session` 曾漏填 → 後端場次 completed、SOAP 也生成了，但病患畫面停在對話頁、按鈕像壞掉（2026-07-27 由 Flutter 真跑抓到）。新增任何終端路徑都要帶。**對稱地，前端不得在送出 `end_session` 後本地搶先設 `completed`**：導頁會讓 autoDispose 拆掉 controller、`_ws.disconnect()` 早於指令送達，整場丟失。
    ※ **「不搶先導頁」兩份前端都已落實；下面那四條是 React 專屬，Flutter 只做到第三條**（React 2026-08-20 EM-3 補上）。React 舊寫法在 `send()` 之後立刻 navigate：`websocket.ts` 的 `send()` 在 `readyState !== OPEN` 時只 `console.warn` 就 return（**靜默 no-op，違反 #6**），而導頁卸載本頁 → cleanup 走 `off()`/`disconnect()` → 那筆 `end_session` 永遠送不出去。症狀是後端卡在 `in_progress`、SOAP 不生成，病患卻已看到「問診完成」（重連中按結束鍵最容易踩到）。現行四條：連線非 OPEN → 不送並給**看得見的錯誤**、按鈕保持可按；已連線 → 送出後進 disabled + `aria-busy` 的「結束中」；**導頁一律由後端終態事件驅動**；12 秒 ACK 看門狗逾時解鎖可重試（kiosk 不能留死按鈕）。證據 `ConversationPage.tsx:55`（`END_SESSION_ACK_TIMEOUT_MS`）、`:935-975`；AST 防回歸 `frontend/src/screens/patient/__tests__/endSessionNoNavigate.test.mts`（釘住「`handleEndSession` 內不得出現 navigate」）。
    ⚠️ **Flutter 側只有第三條，其餘三條待補**（2026-08-21 核對）：`conversation_controller.dart:499` 全文就是 `void endSession() => _ws.send('control', {'action': 'end_session'});`——**沒有連線檢查、沒有錯誤回饋**；`ws_manager.dart:111` 的 `if (!_isOpen || _channel == null) return;` 是**靜默丟棄**（正是 #6 禁止的形狀，與 React 修掉的舊 `websocket.ts` 同型）；`conversation_page.dart:82-85` 的按鈕**沒有 disabled／「結束中」／看門狗**。所以 Flutter 在重連中按結束鍵仍會走進「後端卡 in_progress、病患毫無回饋」那條路徑。動 Flutter 結束流程時這是第一件要補的事。

**2026-07-27 §R 新增（見 `docs/TODO.md` §R 與 §R-lessons）**

19. **`patient_context.build_patient_info` 是 patient_info 的唯一來源**。WS 與 Celery SOAP 兩條路徑都必須走它。歷史教訓：兩份 builder 分岔，Celery 那份只放 name/gender/age、**完全不讀 `sessions.intake_data`**，導致 `soap_generator` 的病史/用藥/過敏/家族史四個分支在生產路徑是死碼，SOAP 對家族史寫「未提供」而 intake 明載父親膀胱癌。不得為了方便在任一端重新組裝。
    ⚠️ **它的四個 `no_*` 分支只有在前端真的送得出旗標時才活著**。`no_family_history`（`patient_context.py:115-119`；`:99-114` 是另外三個 `no_*`）曾經是**死碼**：兩份前端都沒有勾選框，Flutter 更把 `familyHistory` 硬寫 `[]`（TODO G13），後端看起來有支援、實際永遠收不到。2026-08-20 才由 Flutter（D-10，`intake_payload.buildIntakePayload` 裡的 `'noFamilyHistory'` 鍵，理由註解就在它上方三行——`:103-106`，`:102` 是上一個清單的 `],`）與 React（`MedicalInfoPage.tsx:168-173`、`:288-299`、`:715-722`）各自補上勾選框後活化。新增 intake 三態欄位時，**後端 schema、`patient_context` 分支、兩份前端 UI 要同輪一起做**。
20. **每一個終態都要有 SOAP**（`cancelled` 除外，見下）。會生成 SOAP 的路徑：手動 `end_session`、自動結束、critical 紅旗中止、硬上限前遲到 critical、遲到 critical 的 drain、閒置逾時、**`PUT /sessions/{id}/status`（REST，2026-08-20 納入）**。
    ⚠️ **`end_for_language_switch` 不在這張清單裡**——它轉的是 `CANCELLED`，而 `_SOAP_ON_TERMINAL = {COMPLETED, ABORTED_RED_FLAG}` 不含它（`session_service.py:101-103`，該路徑的碼內註解 `:720-724` 逐字寫「**不派 SOAP**」（在 `:723`））。它 2026-08-20 納入的是**六件事矩陣**（`test_terminal_path_six_things_matrix.py` 的 `TERMINAL_PATHS` 裡 `fanout_key="session_service:end_for_language_switch"` 那一列，SOAP 那格是 `_CANCELLED_SOAP_SKIP`），不是 SOAP 清單。把它讀成「會生成 SOAP」會與下面那條產品決策、#13 SO-2 的「`cancelled` 刻意不派」、`REPORT_ELIGIBLE_SESSION_STATUSES` 三處直接衝突。
    新增任何終態轉移時**同時**檢查這六件事：改 status、派 SOAP、送病患端 `session_status`（帶 `extra`）、廣播 dashboard、建醫師通知、設 `_terminated`。主 abort 分支做全套、drain 分支只做兩件，就是這樣漏掉的。
    ※ 病患直接關瀏覽器 → 60 分鐘後 cancelled、無 SOAP：那是**產品決策**（未完成場次要不要出報告），不是缺陷。
    ※ **做不到的格子要在 docstring 逐格寫下理由**（2026-08-20）。REST 路徑送不到病患端 WS、也設不了行程內的 `_terminated`——那是**跨行程限制不是漏做**，`session_service._after_status_transition:124-229` 逐格實作＋逐格記載，`_finalize_idle_timeout`（`conversation_handler.py`，第 6 件事「不適用」的 docstring 在 `:1522-1526`）同樣入 docstring。這些註解錨點被測試釘住，刪掉註解會紅。REST `completed` 的 SESSION_COMPLETE 通知（`session_service.py:609-629`）與切語言 cancelled 的 dashboard 廣播（`:720-732`）都是這輪才補上的空格。
    ※ **三條時序鐵律（2026-08-20，各對應一個 P0）**：
    - **critical abort 收尾後必須 `return True`，不可 fall-through**（EM-1，`conversation_handler.py:2554-2561`）。`_finalize_red_flag_abort` 的 CAS 若因 DB 例外失敗（場次其實還停在 `in_progress`），fall-through 後下方的 `completed` CAS 就會命中 → **剛判定 critical 中止的場次被降級成 completed**，抹掉醫師端的紅旗分流訊號，病患還會收到一般感謝頁而不是「請告知現場醫護」。
    - **先標 `_terminated` 再送**（EM-5）：守衛與標記之間**不得有任何 await**。abort 分支的旗標從 CAS 之後移到 CAS 之前（`:2298-2310`），自動結束分支從三個 await 之後移到 transitioned 的第一行（`:2670-2680`）。舊順序留下的窗口讓背景 late-critical drain 插隊跑完整套 abort，**病患在同一秒收到 completed 與 aborted_red_flag 兩則終態**。
    - **CAS 回傳值必須被尊重**（EM-4，`:758-795`）：`end_session` 對齊三件套——先查 `_terminated`（病患連點／前端在終態事件抵達前送出，以前會再跑一整套收尾）→ CAS 未命中就**什麼都不送**（不送病患端、不廣播、不派 SOAP；以前忽略回傳值，於是早已 `aborted_red_flag` 的場次仍被廣播成 completed）→ 成功才先標後送。
    ※ **硬上限 inline drain 要等 late alerts persist+commit 完才派 SOAP**（SO-3，`:1976-1980` 的 `late_persist_done` `asyncio.Event`），否則報告會漏掉觸發中止的那面紅旗。等待逾時仍照常收尾——**保命線優先於報告完整性**。
    ※ 新增終態 fan-out 點必須登記進 `backend/tests/unit/test_terminal_path_six_things_matrix.py` 的 `TERMINAL_PATHS`，否則 AST 跳閘器直接紅（見 #29）。
21. **紅旗規則層用「同句共現」不是相鄰字串比對**。裸關鍵字會 over-trigger（`eyeball hurts` 命中 `ball hurt`）、相鄰複合詞會 under-trigger（真人語序在部位詞與修飾詞之間插入時間/方位，zh/ja/ko/vi 四語 0 命中）。共現組（部位詞 × 急性/嚴重度詞，同句內距離上限）天生同時解掉兩個方向。新增紅旗或補關鍵字時**不要退回字串相鄰比對**。
    ※ **critical 的否定回看有語意邊界**（2026-08-20 RF-2，`red_flag_detector.py:891-957` 的 `_clause_before`）。散文預算在每個頓號／逗號歸零，等於否定作用範圍實質無上限，於是加了 (a) 不歸零的總預算 `_NEG_CRITICAL_TOTAL_LOOKBACK_UNITS = 48`（`:265`）；但真正承重的是 (b) **list 分隔符之後若已經是帶「時間錨點」的新發作陳述就切斷**。「否認一串病史 ＋ 逗號 ＋ 真急症」是門診第一句話最常見的形狀（「我沒有糖尿病、沒有高血壓、沒有心臟病，昨晚睪丸突然劇痛」），五語 0/5 → 5/5。純長度上限對它完全無效：最近的否定詞只隔 5–7 個語素當量，收到 7 以下反而會把「沒有睪丸劇痛」這種真否認也放行（方向反了）。能分開兩者的不是距離而是**語意**——並列列舉每一項都是裸症狀名詞，而「，昨晚睪丸突然劇痛」帶時間錨點（沿用既有的 `_CURRENT_EPISODE_TIME_ANCHORS`，`_has_time_anchor` 在 `:824`）。**刻意不用急性伴隨症狀當切斷證據**：那組含「吐」，而嘔吐正是並列否認列舉裡最常見的項目，用它會把一整句「我都排除了」變成多個誤中止。ko 另補 `~는데/은데/인데` 連接語尾（字面收在同檔的 `_CONTRAST_MARKERS`，上方有整段理由註解）。方向性檢查：這兩道邊界只讓否定範圍**變短** → 抑制變少 → 紅旗更容易命中，是安全的一側。
22. **紅旗規則層偏誤報（2026-07-27 臨床拍板）**。誤中止＝病患白等、護理師走一趟，可逆；漏報不可逆。據此：
    - **每一條抑制守衛都是潛在漏報，舉證責任在保留方**。要留就要能說出「為什麼它不會造成漏報」。
    - 政策接受的誤報（第三人稱轉述、韓文無標點別部位、英文 `bladder is fine`）寫在 `test_red_flag_suppression_policy.py` 的**正向測試**裡，**不是 xfail**——xfail 的語意是「缺陷、暫時容忍」，會誘導後人修好它而開出漏報。要改成不觸發需臨床重新拍板。
    - severity 分級要照臨床定義。`gross_hematuria_heavy`(critical) 的判準是**量與血塊**不是顏色；把 `bright red`/`bloody` 收進去會讓血尿病患（主訴 c1）一講出自己的主訴就被中止。
    - **收窄「字面」是可以的，但舉證責任在提出方，而且要逐字面**（2026-08-20 RF-3/RF-4，臨床已拍板）。本輪動的是**兩張不同的表**，別混為一談（⚠️ **兩張表的條數會隨新發現增加，要用請去讀常數本身、不要引這裡的數字**——`blood clots` 就是 2026-08-21 才補進 RF-3 的第 10 條）：
      - **RF-3 從 `triggers` 移除裸 trigger、改由共現組接住**（只多要求一個臨床軸），逐條釘在 `test_red_flag_audit_2026_08.py` 的 `RF3_BARE_TRIGGERS_REMOVED`；`test_removed_bare_trigger_is_still_reachable_via_cooccurrence` 把「仍接得住」釘成斷言。2026-08-21 現況共 **10 條**：血塊族四語 `血塊`/`血の塊`/`혈전`/`blood clots`、發燒族五語 `高燒`/`高熱`/`고열`/`high fever`/`sốt cao`、以及 `意識不清`。⚠️ **「原封不動留在 `acuity_terms`」只對其中 7 條成立**——逐字留在共現組詞表裡的是 `血塊`/`血の塊`/`혈전`/`高燒`/`高熱`/`고열`/`意識不清` 這 **7 條**（數的時候別漏掉 `意識不清`），另外 **3 條根本不在 `acuity_terms`**：`high fever`／`sốt cao`／`blood clots` 是靠更短的 `fever`／`sốt`／`blood clot`（前緣詞邊界比對）**包含**進去的。碼內註解寫了這個限定（`urosepsis` 的 RF-3 註解區塊），SKILL 先前壓縮時把限定丟了；釘子測試用的也是子字串包含，與碼內註解一致而與「原封不動」不一致。**動 `fever`／`sốt`／`blood clot` 這三個短字面時要記得它們各自還扛著一條 RF-3 移除字面的覆蓋。**
        ※ **`blood clots` 是 RF-3 當初的實作漏網**（2026-08-21 RF-5 補）：RF-3 的臨床拍板針對的是「血塊這個臨床實體要伴隨泌尿軸」這個**概念**，本來就該五語一起適用，但英文版被留下 → `i have blood clots in my leg`（下肢 DVT）實測仍判 `gross_hematuria_heavy(critical)` 中止問診，與已修掉的 `다리에 혈전이 생겼대요` 同型。**逐字面收窄的舉證要逐語言各查一次，別假設「同一個概念」已經五語一起改到。**
      - **RF-4 從共現組的 `acuity_terms`／`site_terms` 移除 12 條短字面**（`塊`、`できない`/`できません`/`できていません`、`下腹`、`體溫`/`体温`/`temperature`、`떨리`/`震え`/`ふるえ`/`shaking`），釘在 `RF4_SHORT_LITERALS_REMOVED`。這 12 條是**直接從共現組刪掉**、另補長字面替代（`排尿できない` 相鄰片語、`三十八度/38도` 發熱域度數、`running a temperature`、`ぞくぞく`、`오슬오슬`、`shaking chills`），**不是**移進共現組。
      合格的舉證＝「這個字面**在別的軸**仍被共現組接住」或「真人講法一定伴隨另一個已收錄字面」，並附**實測仍命中**的句子（如「尿裡有血塊」「我發高燒而且小便會痛」五語）。**只守住 `triggers` 不等於安全——共現組的組詞表同樣被逐字面釘住。**
    - **不可整族移除**——但這兩族記在**兩個不同的常數**裡（`backend/tests/unit/pipelines/test_red_flag_audit_2026_08.py`）：
      - `KEPT_LITERALS`（**只有 4 個 key**）＝本輪刻意**沒動**的同類字面：`寒顫/chills/悪寒/오한/ớn lạnh`（同屬「單軸即 critical」但**不在本輪臨床覆核清單**）、`整個都是血/一大堆血`、`かたまり/덩어리`、`平熱`。**要動需重新臨床拍板。**
      - 四語意識改變詞（`altered consciousness`/`意識がもうろう`/`의식이 흐려짐`/`rối loạn ý thức`，共現組**接不住**、不在 acuity_terms，移除會真漏報）**不在 `KEPT_LITERALS`**，而是寫在 `REMOVED_LITERAL_JUSTIFICATION["意識不清（urosepsis.triggers）"]` 的 ⚠️ 段——因為被移除的是中文的「意識不清」，那段 ⚠️ 是在警告「別順手把其餘四語一起收掉」。去 `KEPT_LITERALS` 裡找它會找不到。（`prompts/shared.py` 裡 `urosepsis` 定義上方那段 RF-3 註解有同一個混淆，動到時一併修。）
      證據 `prompts/shared.py` 的 `gross_hematuria_heavy`（血塊舉證註解）與 `urosepsis`（發燒／保留清單理由註解）兩處定義。
23. **§3b gating 是三態不是兩態**：明確的「無」（`no_*` 旗標）→ 不問；值**真的涵蓋**該風險因子 → 不問；**值不涵蓋或欄位空白 → 仍必問**。判不準一律歸「仍必問」。家族史要**逐筆**判定——整串當 haystack 會讓「母親：乳癌、父親：攝護腺肥大」被判成有泌尿癌家族史，而 prompt 還叫 LLM 直接寫進病史＝**捏造病歷**。gating 只吃本次場次 intake，不吃 `patients` 表舊資料。
    ※ **涵蓋判定詞庫是五語的**（2026-08-20 IN-2）。intake 是病患用**場次語言**自填的自由文字，舊詞庫只有 zh+en：ko「방광암」、vi「ung thư bàng quang」、ja「膀胱がん／ワーファリン」判不出涵蓋 → 該項退回必問 → §3b 必問優先序高於禁問清單 → **病患剛填過的家族史被口頭重問**。抗凝血／惡性／泌尿／高血壓／冠心／心梗／中風／糖尿病 與取消資格限定語全部補齊 ja/ko/vi。收詞判準已入碼（`llm_conversation.py:121-140`）：只收高確信詞、每個字面先照 #25 檢查在其他四語是不是高頻子字串、ja 漢字 ≠ zh 漢字必須並列、`血液サラサラ` 刻意排除（保健食品行銷語，收了＝誤跳過）、ko「암」可收（有另一個詞群把關）、vi「u」不收。**判不準就不收**（安全方向）。
    ※ **來源標籤是三態的**（IN-3，`supervisor.py:143-190`）。舊版把扁平值整批標成「（intake 已提供）」，配上 prompt 那條「不得要求病患重述這些已知項目」——結果**幾個月前的舊病歷把本次問診的口頭確認整個關掉**，而對話端早就只採信本次 intake，兩端判準靜默漂移。現行：`session_intake_fields()` 認得的 →「（intake 已提供）」受不得重述限制；其餘扁平非空值（`patients` 表 fallback）→「（病歷記載，過往）」，prompt 明文**不**套用該條款。**supervisor 與對話端必須用同一支函式。**
    ※ **配額 K 吃的是「intake 過濾後」的必問題數**（D-2，`conclusion_policy.py:108-133` → `llm_conversation.count_must_ask_risk_factors:743-762`），不是主訴的原始 K。prompt 端的必問清單早就被三態判定過濾過，配額卻仍吃未過濾 K：血尿場 K=3、intake 已涵蓋 2 項時，病患只剩 1 題要答卻被抬到 soft_min 12／hard cap 15＝**白綁 6–7 輪**（修後 10／13）。**方向護欄是雙層 `min()` 只降不升**，`patient_info` 型別不對就退回未過濾 K——「多綁幾輪」是保守側，**K 變大是絕不能引入的反方向**。
24. **SOAP 的 `plan.patient_education` 與 `summary` 是病患面欄位**（渲染在 React `PatientSessionDetailPage` 與 Flutter `patient_session_detail_page`），受 #11 kiosk 措辭鐵律約束，prompt 與出口消毒兩層都要有。`plan` 的其他欄位是醫師面，不受限制。判準是「**有沒有叫病患自行離場**」而不是「有沒有出現某個詞」——「醫師會為您安排急診評估」對候診中的病患不違規。
    ※ **時間窗就是急迫度，只是換了詞性**（2026-08-20 SO-1，`soap_generator.py` 的 `_ZH_DEADLINE` / `_ZH_SELF_CARE` / `_ZH_URGENT` 三個 regex 片段常數，**寫符號名不寫行號：S8 修復中，本檔正在位移**）。`plan.urgency` 的四個 enum 被 LLM 寫成自然語言後**整族穿透**消毒層：「請於 24 小時內就醫」「本週內就診」「當天就醫」6/6 全放行。修法是把時間窗**另立一組** `_ZH_DEADLINE`，且**只**與「病患自己去求醫」的動作 `_ZH_SELF_CARE` 共現（那組動作的施事者天生是病患本人）——**不可塞進寬鬆的 `_ZH_URGENT`**，那會誤殺「急診評估的結果會併入今天的病歷」「這項檢查在本院急診就能完成」。`_ZH_SELF_CARE` 刻意**不收**「回診／複診／看診／掛號」（「建議一個月內回診」「請稍候等待看診」在院內候診情境完全合規）。施事者豁免判準不變：「醫師會在 24 小時內完成報告」不違規。規則都在同檔的 `_leave_site_patterns()`，它回傳 HARD／EXEMPT／SOFT 三組已編譯規則。⚠️ **SO-1 的時間窗規則全部只在 SOFT**（五語各一對雙向，共 10 條）——`_ZH/_EN/_JA/_KO/_VI_DEADLINE` 五個常數在 **HARD 側是零個使用點**；HARD 裡與 SO-1 相關的只有中文那條**單條**「祈使詞 ＋ 0–10 字插入語 ＋ `_ZH_SELF_CARE`」，它**不含時間窗**。分組不是隨手放的：時間窗那組要吃施事者豁免（「醫師會在 24 小時內完成報告」不違規）所以必須在 SOFT，而祈使那條的 `_ZH_SELF_CARE` 動詞施事者只可能是病患本人、語意上沒有「院方會做什麼」的解讀空間，才放得進不吃豁免的 HARD。oracle 語料獨立維護在 `backend/tests/unit/pipelines/patient_facing_corpus.py`。**消毒層與 prompt 禁語清單要同輪同步。**
    ※ 病患語言版（#12）的轉述輸出要過**目標語言**的消毒規則，不是中文那組。

**2026-08-18 文字掃蕩新增（見 `docs/TODO.md` R22、G34／G35b 與該輪 commit 索引）**

25. **紅旗規則層是全語言聯集比對**。關鍵字掛在**任一**語言段，都會拿去比對**所有**語言的句子（`_collect_all_language_keywords` 與共現組詞表皆為聯集，W1 設計）。ja 段的裸「熱」因此把中文的「刺刺熱熱／灼熱」——排尿灼熱（dysuria，泌尿科最常見主訴之一）——判成 critical **尿路敗血症並中止問診**（實證 session `dda55701`；R22，2026-08-18 臨床拍板收斂為**全身性發燒語彙**）。
    - 新增或修改**任何語言**的關鍵字前，先確認該字面**在其他四語的常見句子裡不是高頻子字串**。短字面（1–2 個 CJK 字、去掉助詞的詞根）風險最高。
    - 判準與雙向語料見 `test_red_flag_urosepsis_fever_semantics.py`（57 條，含「把裸『熱』加回詞表」的注入式回歸）。
    - 這類修正是**語意修正不是抑制守衛**，不與 #22「偏誤報」政策衝突——但仍受 #22 的舉證責任約束：每個移除的字面都要能說出「為什麼它不會造成漏報」。
    - ※ **2026-08-20 RF-4 的每一條移除都是這條的實例**：`下腹` 打中文的「下腹脹」、`塊` 打中文量詞「一塊一塊」、`できない` 打「我慢できない」＝尿意切迫（本紅旗的臨床**反義**）。**臨床反義是聯集誤配最惡性的一種**——新字面除了頻率，還要先確認它在別的語言裡不是反義詞。
    - ※ **適用面不只逐字稿**：`llm_conversation` 的 §3b 涵蓋判定詞庫同樣是全語言聯集比對 intake 欄位值（IN-2 明文引用本條），新增詞前要跑同一道檢查。
    - ⚠️ **已知缺口（2026-08-21 發現，修復中——尚未 commit，別當成已保證的行為）：誤配不只跨語言，還有同語言內的多義。** `urosepsis` 共現組的 vi `site_terms` 收了裸 `tiểu`，但越南文的 `tiểu` 同時是「排尿」與「小／次要」：`tiểu đường`＝**糖尿病**、`tiểu phẫu`＝小手術、`tiểu sử`＝簡歷。實測（規則層）：

      | 輸入（vi-VN） | 規則層（`trigger_keywords`） |
      |---|---|
      | **`tôi bị tiểu đường và hôm qua tôi bị sốt`**（我有糖尿病、昨天發燒） | **`urosepsis(critical)`** ← 誤中止（`['tiểu','sốt']`） |
      | **`mẹ tôi bị tiểu đường, tôi hơi sốt`**（我媽有糖尿病、我有點發燒） | **`urosepsis(critical)`**（`['tiểu','sốt']`） |
      | **`tôi vừa làm tiểu phẫu và bị sốt nhẹ`**（剛做完小手術、有點低燒） | **`urosepsis(critical)`**（`['tiểu','sốt']`） |
      | **`bác sĩ hỏi tiểu sử bệnh, tôi đang sốt`**（醫師問病史、我正在發燒） | **`urosepsis(critical)`**（`['tiểu','sốt']`） |
      | `tôi sốt và tiểu buốt`（發燒＋排尿灼痛） | `urosepsis(critical)` ✅ 真陽性 |

      （上表刻意用 `sốt` 當急性詞：它只在共現組的 `acuity_terms` 裡，所以命中**一定**經過 `tiểu` 這個 site 軸。**別拿 `ớn lạnh` 造反例**——`tôi hơi ớn lạnh` 單獨一句就命中 critical，那是 S1 那族刻意保留的單軸裸 trigger，與 `tiểu` 無關。）
      **這不是可以聳肩帶過的「政策接受的誤報」**：糖尿病是 §3b 的必問風險因子（`llm_conversation._DIABETES_TERMS` 自己就收了 `tiểu đường`），所以越南語病患**照著問診流程講出自己的病史**就會撞上它——與 R22 那個「排尿灼熱一講出主訴就被中止」同型，只是換成 vi。#25 的新字面檢查清單要多一條：**短字面除了「在其他四語是不是高頻子字串」，還要查「在它自己的語言裡是不是多義詞根」**。裸 `tiểu` 出現在**四個**共現組的 `site_terms`（`void_x_obstruction` / `urine_x_heavy_blood` / `urinary_x_systemic_infection` / `urine_x_blood_present`），修的時候四處都要看。詳見 TODO S12。
      ⚠️ **修法（`_TERM_FALSE_FRIENDS` 位置排除法）結構上不可能封閉**：漢越詞「小」的構詞沒有上限，那張表是**開放式列舉**，未收錄的「小」義複合詞（`tiểu thương`／`tiểu bang`／`tiểu thư`…）仍會供給泌尿軸。這件事本身被 `RF6_VI_KNOWN_OPEN_TAIL` ＋ `test_rf6_false_friend_table_is_an_open_ended_list_not_a_closed_set` 釘住（**斷言誤報仍會發生**，把某條收進表裡就會紅，逼人同步更新）。**收到 vi 誤中止回報時的第一個假設是「又一個沒收錄的複合詞」，不是「這條路封死了」。**
26. **無麥克風降級路徑是保護區**。三者缺一不可，不得移除：
    - `openMic()` 進入 `startStream` **之前**的「先權限、再可用輸入」兩道檢查；
    - iOS 的 `ios/Runner/MicProbe.swift`——`AVAudioEngine.inputNode.inputFormat` 是**模擬器上唯一不謊報的訊號**。無音訊輸入的宿主機上 `record.listInputDevices()`／`AVAudioSession.availableInputs`／`currentRoute.inputs`／`isInputAvailable` **全部回報幽靈裝置**，只有 inputNode format 誠實地回 0Hz/0ch；
    - `ConversationState.voiceUnavailable` 降級旗標。
    麥克風失敗**不得寫 `state.error`**（那是阻斷性錯誤且無任何路徑會清除，會讓一場全程成功的純文字問診從頭到尾掛著紅色橫幅），**也不得擋住 `_ws.connect`**（文字輸入走同一條紅旗／LLM／TTS 管線，麥克風壞掉只是「不能用講的」，不是「不能問診」）。少了這條防線，無音訊輸入的機器一進問診頁**必定在原生層 SIGABRT**（`installTap` 拿到無效 format → NSException，**Dart 的 try/catch 攔不到**，整個 app 當場死掉，重現 6/6）。
27. **WS 事件的兩端訂閱清單要同步**。React 與 Flutter 是**手抄兩份、沒有 codegen**，所以後端加事件時漏掉任一端不會有任何編譯或型別訊號。`resume_failed` 就是這樣：後端有發、**兩端都沒訂**，病患畫面靜默停在斷線前的舊逐字稿，而後端其實已經拿伺服器端 history 繼續問診——之後的 AI 追問接在一份錯的上下文後面（違反 #6：不得靜默吞掉）。
    - 現行為：兩端收到後以 REST `GET /sessions/{id}/conversations` **整批重抓取代**本地列表（不用 id 合併——樂觀送出的氣泡與半截 streaming 訊息會變成永久殘影），並清掉 `isAIResponding`／`sttProcessing`。
    - 新增任何 WS 事件時，`conversationStore`／`ConversationPage`（React）與 `conversation_controller._registerWsHandlers`（Flutter）**要同輪補齊**，且 React 的 `off()` 清理清單也要一起加。

**2026-08-20 LLM 管線稽核修復戰役新增（commit 索引 `8e30bd3`…`fb403d6`）**

28. **前端的 `no_*` 旗標只能來自明確勾選（兩份前端都是）**。`noKnownAllergies` / `noCurrentMedications` / `noPastMedicalHistory` / `noFamilyHistory` **只有在病患把勾選框勾起來時才送 `true`**，絕不可從 `list.isEmpty` / `list.length === 0` 推斷。**空白必須維持空白——三態，不是兩態。**
    - 為什麼：後端把 `no_*` 當 `ANSWERED_NO`——該題進 §3b 禁問清單、SOAP 記「病患自述無」。把「沒填」偽造成「病患否認」＝**捏造病歷**，而且 §3b gate 會整個跳過該風險因子（違反 #23）。Flutter 舊碼正是 `_noAllergies || allergies.isEmpty`（IN-1，列為 Flutter Web promote blocker）。
    - payload 組裝要留在 widget **外面**的純函式，單元測試斷言「勾選 / 留白 / 填寫」三種輸入的精確 JSON 形狀：真 OpenAI e2e 自己 POST 裸 JSON，**永遠看不到前端偽造的 payload**（見「測試設計」第 5 點）。
      ⚠️ **這個形狀目前只有 Flutter 做到**：`intake_payload.dart` 是 widget 外的純函式，`intake_payload_test.dart` 的 `group('IN-1: no_* flags mean "the patient denied it", never "the box was blank"')` 真的斷言三態 JSON——三態分別是 `test('untouched form sends every no_* as FALSE with empty lists')`（留白）、`test('explicitly ticked boxes send true and an empty list')`（勾選）、`test('filled-in rows send false + the rows')`（填寫）。**寫測試名不寫行號**：三態不連續，先前引的 `:43-81` 只框到 helper 與前兩態，第三態落在框外。**React 的 payload 是寫在 component handler 裡的 inline literal**（`MedicalInfoPage.tsx:258-299`，沒有可獨立測試的純函式），守它的 `patientFacingSurface.test.mts:76-110` 是**原始碼正則掃描**（掃 `useState(false)`、`checked={noFamilyHistory}`、掃「不得出現 `familyHistory.length`」）而**不是 JSON 形狀斷言**——擋得住「從空清單推斷」這個具體回歸，擋不住其他形狀的 payload 漂移。React 端抽純函式是待補項。
    - 證據 `flutter_app/lib/features/patient/intake_payload.dart:1-19`（規則入碼的 header）、同檔的 `buildIntakePayload`（`:55-118`；docstring 在 `:49-54`，四個 `no_*` 鍵都在函式體內）；`frontend/src/screens/patient/MedicalInfoPage.tsx:259`／`:270`／`:279`／`:291`（四個 `no_*` 都直接讀勾選框 state）、`:168-173`、`:715-722`。守它的測試：`flutter_app/test/intake_payload_test.dart`、`flutter_app/test/medical_info_family_test.dart`、`frontend/src/screens/patient/__tests__/patientFacingSurface.test.mts`。
29. **終態路徑 × 六件事矩陣有 AST 跳閘器**。`backend/tests/unit/test_terminal_path_six_things_matrix.py` 把 #20 的矩陣寫成資料：`TERMINAL_PATHS` 列出每條路徑每一格的預期值（`DONE` / `VIA_STATUS_HELPER` / `Skip(理由, 程式碼註解錨點)`），`test_terminal_path_does_the_six_things` 逐格跑真路徑比對（**不是** `test_matrix_cell`，那個名字不存在），`test_skipped_cells_are_documented_in_code` 確認每個「刻意不做」在產品碼有對應註解（**刪註解會紅**，逼下一個人重新面對這個決定），`test_registry_covers_every_terminal_fanout_site` 用 AST 掃 `conversation_handler.py` / `session_service.py` / `tasks/session_timeout.py` 三個模組所有「把場次寫成終態」的呼叫點與註冊表比對——**新增終態路徑而沒登記 → 直接紅**。
    - ⚠️ **歷史（`6ecf10a` HEAD 上的舊跳閘器，本輪已重寫）**：舊版 `_terminal_fanout_sites()` 三格認的形狀**不同**——conversation_handler 認 `_update_session_status(..., "<終態字面值>")`＝寫終態（keyword arg 或常數變數就掃不到）、session_timeout 認 `.values(status=SessionStatus.X)`＝寫終態、session_service 認的是 `_after_status_transition(...)`＝**fan-out 呼叫入口**。三者一律叫「fan-out 點」會讓人以為 session_service 那格也守得住「寫了終態但沒 fan-out」——2026-08-21 實測**守不住**：直接寫 `session.status = SessionStatus.COMPLETED` 而不呼叫 fan-out，跳閘器不跳，而那正是這條鐵律要防的失敗樣態（`session_service.py:557`、`:684` 已有兩處直接寫狀態）。**留這段是因為教訓比修法重要**：跳閘器的名字要說出它實際掃的是什麼，「fan-out 點」這個共用命名讓三格不同的覆蓋面被讀成同一件事，缺口整整活了一輪。現行分工是 `test_registry_covers_every_terminal_fanout_site`（有沒有登記）＋ `test_terminal_status_writes_route_through_the_fanout_entry`（有沒有真的 fan-out）兩條分別問。**無論如何：新增終態路徑靠的是人先加註冊表，跳閘器只是第二道網，別把「測試沒紅」讀成「六件事做完了」。**
    - ⚠️ **掃描器認得的是一張形狀清單，不是「所有寫法」——這一點永遠成立，別因為清單變長就當它封閉了。** 本輪新增的掃描器（`_terminal_writes`）認得：直接對 `.status` 賦值、**tuple／list 多重指派**（`session.status, session.completed_at = SessionStatus.COMPLETED, now`）、鏈式指派、`AnnAssign`、`.values(status=…)` 與 **`.values({"status": …})` 位置引數 dict**、**`setattr(obj, "status", …)`**、以及低階狀態寫入 helper 呼叫（keyword／positional／常數變數都吃），狀態值解析不出來一律保守當終態。
      **每一種都由 `_BLIND_SPOT_INJECTIONS` 的注入式自我測試逐型釘住**（把該寫法真的接進產品碼副本再掃，證明掃得到且判定為未登記），目前 10 型；tuple 多重指派是其中一型——原型在開發中確實漏過它（只認 `ast.Attribute` 的 assign target），那個中間態從未 commit，注入測試就是為了不讓它再漏回去。
      **刻意留著不認**的兩類（成本判斷寫在該檔的設計原則段）：`.values(**payload)`（`_update_session_status` 自己就這樣寫，認了會讓寫入 helper 本身天天發假警報）、以及 `__dict__`／`object.__setattr__`／綁到別名再呼叫／裸 SQL 這些**刻意規避**的寫法（跳閘器防手滑，不防內鬼）。
    - ⚠️ 測試檔自己的檔頭 docstring 曾把 cell 測試寫成不存在的 `test_matrix_cell`（本 skill 先前是照抄它），已於本輪一併改成 `test_terminal_path_does_the_six_things`。**引測試名之前先 grep 一下它存不存在**——這一條就是「文件照抄文件、沒人回去對過碼」的樣本。
    - 為什麼：#20 過去純靠人肉記憶執行，於是每加一條路徑就漏幾格（主 abort 全套、drain 只兩件、硬上限 inline drain 漏 `extra`、閒置逾時整條沒 SOAP、REST 六件只做一件）。稽核的「測試缺口 #1」就是**沒有任何測試在看這張矩陣**——每個缺陷都各修各的，下一條新路徑照樣會漏。
    - 新增終態路徑的順序：**先在 `TERMINAL_PATHS` 加一列（含 `fanout_key`），再讓它綠。** 證據 `test_terminal_path_six_things_matrix.py:1-62`；配套 `test_terminal_ordering_and_no_downgrade.py`、`test_end_session_control_guards.py`、`test_rest_status_side_effects.py`、`test_update_session_status.py`。
30. **紅旗的裸 trigger 也要自帶臨床軸**。`URO_RED_FLAGS` 的 `triggers` / `triggers_by_lang` 裡，**單獨一個詞就足以判 critical 的字面，必須自帶該紅旗的臨床軸**。臨床實體是兩軸的（尿路敗血症＝泌尿＋全身感染；大量血尿＝尿＋血/血塊），就不能有只命中其中一軸的裸 trigger——那些字面該**降進 `trigger_cooccurrence`**，由共現組去要求另一個軸。
    - 為什麼：`高燒` 單詞判 urosepsis → 「我上個月因為流感發高燒」被中止問診；`血塊` 單詞判大量血尿 → 「我腳上有一塊血塊瘀青」「다리에 혈전이 생겼대요」（下肢 DVT，是**別的**急症）被判成血尿 critical。這是本輪誤中止最大的一類。
    - 降進共現組不等於放寬舉證：#22 的逐字面舉證與 `KEPT_LITERALS` 保留清單照樣適用。證據 `prompts/shared.py` 的 `gross_hematuria_heavy` 與 `urosepsis`（`urinary_x_systemic_infection`）兩處定義上方的 RF-3 註解區塊（**本檔刻意不寫行號：S7／S8 修復中，這幾區正在位移**）；守它的測試 `backend/tests/unit/pipelines/test_red_flag_audit_2026_08.py`（含雙向對稱、語料獨立性結構測試、常駐注入測試與 `KEPT_LITERALS`）。
    - ⚠️ **已知缺口（2026-08-21 發現，修復中——尚未 commit，別當成已保證的行為；碼內註解編號為 RF-5＝TODO S7，同一缺陷）：`血塊` 降進共現組後產生跨子句漏報，是 `6fc51e3` 的回歸。** `trigger_cooccurrence.urine_x_heavy_blood` 當時**沒有宣告 `cross_clause`**（預設 False）。
      ※ **「哪些共現組開了 `cross_clause`」的權威是 `prompts/shared.py` 的組定義本身**（那個 key 在不在），**不是** `red_flag_detector._pairing_scope_ok` 的 docstring。那段 docstring 曾把判準寫成「site×acuity 型紅旗（睪丸扭轉／尿滯留／血尿）維持不開」，而 `urinary_retention` 的 `void_x_obstruction` **早在 2026-07-27 就是 `cross_clause: True`**（為英文語序開的，`shared.py` 有理由註解）——那句話在寫下時就已經與資料互斥。判準應該讀成「**兩個軸是不是兩個不同的觀察**」而不是紅旗的臨床分類名：兩個不同的觀察就開（urosepsis／cauda_equina／urinary_retention，RF-5 後加上 gross_hematuria_heavy，共四組），「同一部位 × 該部位的嚴重度」不開（`site_x_acuity`）。docstring 已於 RF-5 同輪訂正並改成明說「去查資料」。
      實測（`6ecf10a` HEAD）：

      | 輸入 | 規則層 |
      |---|---|
      | `尿裡有血塊` / `我剛去上廁所，馬桶裡有血塊` / `小便有很多血塊` | `gross_hematuria_heavy(critical)` ✅ |
      | **`我今天小便，然後有很多血塊`** | **`[]` ← 零紅旗** |
      | **`小便的時候，血塊一直出來`** | **`[]` ← 零紅旗** |
      | `我發燒到三十九度，而且小便的時候很痛` | `urosepsis(critical)`（那條才是 `cross_clause=True`） |

      這兩句是真人講大量血尿最自然的語序，**降級前會命中、降級後不會**——正是 #22 舉證要求的「為什麼它不會漏報」沒守住的一面。RF-3 在 `shared.py` 的舉證註解當時寫「多要求同一/**相鄰子句**裡有尿液詞」，與 `_pairing_scope_ok` 的實際行為互斥（TODO S2 也照抄了這句），該註解要與修復同輪對齊。**教訓：降級的舉證必須連跨子句語序一起實測，只測同句會漏掉整個漏報面。** 動這一區前先確認 TODO S7 已結案。
31. **探針／測試 oracle 自己也會壞掉，而且壞得沒有訊號**。三條本輪學到的守則：(a) **不要把「其中一種合格樣態」寫死成唯一樣態**（EM-1 之後 critical abort 有兩種合法收尾樣態，舊 `t5` 只認其中一種 → 同一份碼一場紅一場綠）；(b) **探針腳本的環境假設要自我證明**（中文 locale 下的 `ps` 解析＝假性 FAIL、`grep -c` 的退出碼＝假性 PASS）；(c) **driver 的回合上限是產品行為的函數**（§3b 動態硬上限上線後 K=3 場景需 15+ 輪，`max_patient_turns=12` 會讓 driver 先收手）。細節與證據見下方「改偵測邏輯時的測試設計」第 6–8 點；判準改版記在 `scripts/e2e_realopenai/README.md:366-371`（守則 #16）與 `:410-434`（`t5` 判準改版）。
32. **病患自由輸入進 prompt 前要消毒，而且是兩層**。intake 四欄（各 100 字）、主訴自填文字（200 字）、姓名——插進 LLM prompt 前必須過 `prompts/shared.sanitize_for_prompt`（控制字元／零寬／BiDi 移除＋換行摺疊＋行首 `#` 剝除）。**schema validator 與 prompt 組裝層兩層都要**：前者擋髒值落進 `sessions.intake_data`，後者涵蓋 `patients` 表舊資料與 e2e 裸 JSON 這些**不經 schema** 的路徑。臨床數值（`38度`、`50%`、`PSA 4.5`）原樣保留。
    - 為什麼：prompt 用 markdown 標題分區，多行值 + `##` 開頭在渲染後與**真正的區段標題字面上無法區分**＝偽區段注入。
    - **schema 層的覆蓋不是齊頭的**（2026-08-21 核對，`app/schemas/session.py`）：intake 四欄由 `PromptSafeFreeText`（`:19`）的 `field_validator("*")` 覆蓋，四個 item class 都繼承它（`:39/48/55/63`）；**主訴自填文字走的是 `SessionCreate` 上的另一支獨立 validator** `_sanitize_chief_complaint_text`（`:116-129`）——`SessionCreate` 繼承的是裸 `BaseModel`（`:99`），**讓新欄位繼承 `PromptSafeFreeText` 並不會覆蓋主訴**；**姓名完全沒有 schema 層**——`PatientInfoPayload`（`:88-96`）是裸 `BaseModel`、`name: str`（`:91`）零消毒，姓名只有組裝層那一道（`llm_conversation.py:876`）。
    - ⚠️ **已知缺口（2026-08-21 發現，修復中——尚未 commit，別當成已保證的行為）：SOAP 生成 prompt 完全沒過 `sanitize_for_prompt`。** D-1 只覆蓋了**對話路徑**——在 `6ecf10a` HEAD 上，全 backend `sanitize_for_prompt` 只出現在 `supervisor.py` / `llm_conversation.py` / `prompts/shared.py` / `schemas/session.py`，**`soap_generator.py` 不在其中**。`soap_generator.generate()` 把 `name` / `medical_history` / `medications` / `allergies` / `family_history` 直接 f-string 進 `## Patient Basic Information` 區塊，而 `patient_context.build_patient_info`（`patient_context.py:131-136`）對其中**三欄**在 intake 空白時會 fallback 到 **`patients` 表舊資料**——正是「組裝層那道要涵蓋」的那條路徑。實測可重現偽區段注入：病患欄位值渲染成真正的 `## Consultation Transcript` 標題，**該 prompt 的 line-initial `##` 從 3 個變 4 個**（乾淨基線本來就有三個區段標題：`## Patient Basic Information` / `## Chief Complaint` / `## Consultation Transcript`；換個講法，`## Consultation Transcript` 這一行從 1 個變 2 個）。
      ⚠️ **fallback 是三欄不是四欄**：`medical_history` / `medications` / `allergies` 各自寫成 `intake_summary[...] or format_jsonb_list(getattr(patient, ...))`（`patient_context.py:131-136`），而 `family_history` 是光桿的 `intake_summary["family_history"]`（`:137`）——**`app/models/patient.py` 根本沒有 `family_history` 欄位**（只有 `medical_history` / `allergies` / `current_medications`，`:38-40`），沒有東西可以 fallback。`patient_context.py` 那段「上面四個扁平欄位…會 fallback」的碼內註解、以及工作區 `soap_generator.py` 新加的 D-1b 註解 **(b)**，都照抄了這個錯，動到時一併修。**這條 prompt 攻擊面最大、含 PHI 最多，卻是唯一沒被覆蓋的一條。** 附帶教訓：規則原本寫「插進 LLM **system** prompt 前」，而這段是 **user message**，照字面讀規則**不覆蓋它**——規則的字面把最危險的那條排除在外。動 SOAP prompt 前先確認 TODO S8 已結案。
    - ⚠️⚠️ **消毒器自己也有缺口（2026-08-21 實測，修復中——尚未 commit）：行首 `#` 只剝一次。** 在 `6ecf10a` HEAD 上，`sanitize_for_prompt` 末段的 `_LEADING_HEADING_MARKS` 是 `^[#＃]+[ \t　]*`——`^` 錨定＝**單次** sub，第一段 `#` 連同其後空白被吃掉之後，**後面的 `##` 就遞補到行首**：

      | 輸入 | `sanitize_for_prompt` 輸出 |
      |---|---|
      | `'## Consultation Transcript'` | `'Consultation Transcript'` ✅ |
      | **`'# ## Consultation Transcript'`** | **`'## Consultation Transcript'`** ← 仍是標題 |
      | **`'#\t## Consultation Transcript'`** / **`'＃ ## Consultation Transcript'`** | 同上 |

      所以 **「這個值過了消毒」不等於「這個值不會以 `##` 開頭」**——S8 把 `soap_generator` 接上消毒之後，這個形狀照樣穿得過去。剝除要跑到**固定點**（loop until no change）為止。這條同時影響對話 prompt 與 SOAP prompt，兩層共用同一支函式。詳見 TODO S10。
    - 證據 `prompts/shared.sanitize_for_prompt` 與同檔的 `_LEADING_HEADING_MARKS` / `_PROMPT_UNSAFE_CHARS`（**本檔刻意不寫行號：S7／S8 修復中，正在位移**）、`schemas/session.py:19-38`（`PromptSafeFreeText` + `field_validator("*")`）、`llm_conversation.py:706-730`／`:788-795`／`:845-895`、`supervisor.py:180-190`。守它的測試 `test_prompt_injection_sanitization.py`、`tests/unit/schemas/test_session_intake_sanitization.py`——它們的 oracle 是**區段結構比對**而不是關鍵詞比對（避免重蹈「oracle 是實作自己」，見測試設計第 3 點）；**兩份測試都不涵蓋 `soap_generator`，也都沒有「剝一次不夠」的案例**。
33. **跨行程的身份字串一律正規化**。紅旗去重身份（`canonical_id` / title）寫進 Redis hash 或當 dedup key 之前一律過 `normalize_canonical_id`（lowercase + strip + 內部空白摺疊）；`red_flag_detector._dedup_key` 與 `alert_dedup.alert_dedup_identity` **共用同一支函式，兩處不得漂移**。
    - 為什麼：語意層對**不在內建目錄裡**的紅旗（LLM 自創命名）是拿 `raw_title` 當 canonical_id，而 LLM 每輪的大小寫／前後空白／內部空白都可能不同（`"Testicular Torsion Suspected"` / `"testicular torsion suspected"` / `" Testicular  Torsion Suspected "`）→ 同輪兩層合不起來、跨輪 Redis 去重**靜默失效** → 同一紅旗每輪重寫一筆 alert、重新廣播一次（護理站警示疲勞、research analytics 紅旗計數灌水）。對內建目錄的 snake_case id 是恆等變換，既有行為不受影響；顯示用的 title 仍是 raw_title。
    - 證據 `prompts/shared.normalize_canonical_id`（**本檔刻意不寫行號：S7／S8 修復中，正在位移**）、`alert_dedup.py:41-56`（`alert_dedup_identity`）、`red_flag_detector.py:2338-2349`（`_dedup_key`——本條主張的主體；`:2018-2036` 是語意層 title→canonical 反查，是它的上游）。
34. **Redis key 的前綴，讀取端與寫入端必須同源**。**同源才是不變式，「一律讀 settings」不是。**
    - 為什麼：`supervisor.analyze_next_step` 用 `settings.REDIS_KEY_PREFIX` 寫、`conversation_handler` 硬寫 `gu:` 讀 → 只要環境把前綴改掉（多環境共用一台 Redis 就會），supervisor 整條指導管線**靜默失效**：AI 從此沒有 next_focus，也沒有 `hpi_completion_percentage` 可觸發軟門檻收尾。**不報錯、不降級、沒有任何訊號。** 這個缺陷的形狀是**兩端寫法不一致**，不是「有人硬寫了 `gu:`」。
    - ⚠️ **碼庫裡仍有大量硬寫 `"gu:"` 且正在使用的 key，那些不是缺陷、不要順手改**：`conversation_handler.py:44,45`（`_SESSION_CONTEXT_KEY` / `_SESSION_STATE_KEY`，用於 `:3152,:3252,:3281`，並被 `session_service.py:114,119` import 共用）、`dashboard_handler.py:32-34`、`connection_manager.py:23`、`alert_dedup.py:21`、`core/rate_limit.py:36-42`、`core/dependencies.py:34`、`routers/sessions.py:230`。它們讀寫共用同一個模組層常數，**沒有漂移風險**。照「一律讀 settings」的字面執行會變成一場無謂的大改。
    - ⚠️ **`conversation_handler.py:48` 的 `_SESSION_SUPERVISOR_KEY = "gu:session:{session_id}:supervisor_guidance"` 現在是死常數**（全庫 0 個引用，2026-08-21 核對）。它是修復前那條硬寫路徑的殘骸——下一個人「順手」拿它去取代 `:1680` 的 settings 寫法就會把整個 D-8 修復回退。**這個常數該刪。**
    - 證據 `conversation_handler.py:1671-1684`；守它的測試 `backend/tests/unit/websocket/test_guidance_key_prefix_and_history_summary.py`（含 `staging:` 前綴的反向釘子）。
35. **壓縮的歷史摘要必須真的進得了 LLM**。`_cap_conversation_history` 產生的摘要 content 必須以共用常數 `HISTORY_SUMMARY_PREFIX`（`[前段對話摘要]`）起頭，`format_messages` 靠它放行**且只放行這一則** role=system 歷史。
    - 為什麼：`format_messages` 原本無條件跳過所有 system 歷史 → 摘要**從來沒有進過 LLM**，「壓縮」實際上等於丟棄，長場次的前段病史對 AI 完全消失（而壓縮的初衷正是「不靜默丟棄舊輪次，以免遺失紅旗臨床脈絡」）。放行這一則比改 `_cap_conversation_history` 的 role 侵入更小：改成 assistant 會讓摘要漏進紅旗語意層的 `_build_conversation_summary`。**前綴不得兩邊各寫一份字面值。**
    - 證據 `llm_conversation.py:90-93`（常數）、`:1133-1142`（放行）、`conversation_handler.py:206-250`；測試同 #34。
36. **病患端不得渲染未經醫師確認的 ICD-10 與 AI 信心分數**。React `PatientSessionDetailPage` / `SessionCompletePage` 與 Flutter `patient_session_detail_page` / `session_complete_page` 都不得渲染 `icd10_codes` 與 `ai_confidence_score`；醫師端不受限。
    - 為什麼：ICD-10 未經醫師 review 就會被病患讀成「診斷」；信心分數則讓病患拿一個百分比去衡量還沒審閱過的 AI 判斷。
    - 證據 `flutter_app/lib/features/patient/patient_session_detail_page.dart:12-14`（header 註解逐字寫 `no ICD-10/confidence`；`:79-84` 是 `resolvePatientFacingSummary` 呼叫，那是 #37 的材料不是本條的）、`session_complete_page.dart:170-182`（註解在 `:179-180`）；React 兩頁（commit `2daa82c`）。守它的測試 `flutter_app/test/patient_facing_summary_test.dart`（**靜態守衛**：讀原始碼、去註解後掃禁用識別字）、`frontend/src/screens/patient/__tests__/patientFacingSurface.test.mts`。
37. **病患面摘要的三態 resolver 是唯一判斷點**。兩頁共用一支純函式（Flutter `resolvePatientFacingSummary`、React `resolvePatientFacing`），三態：(1) `patient_facing_localized.language` 與**場次語言**相符且有內容 → 用它；(2) 場次語言是 zh-TW → 用報告本體的 `summary` / `plan.patientEducation`；(3) 其餘（非中文場次、沒有可用的在地化文字）→ **五語通用訊息**（`session.patientFacing.notice`，kiosk 措辭）。
    - 為什麼：非中文場次的病患全程講自己的語言，最後看到一段中文病歷摘要——讀不懂，也像系統壞掉。**分支 (3) 結構性地不把報告原文帶出函式**，避免日後有人在 UI 端「順手」退回中文。語言比對走主語言子標籤正規化（後端可能寫 `en` / `zh-Hant`），判不準一律退回通用訊息——與 §3b「判不準歸保守側」同一原則。
    - 證據 `flutter_app/lib/features/patient/patient_facing_summary.dart:1-103`、`frontend/src/utils/patientFacingReport.ts:1-109`（全檔；呼叫端 `SessionCompletePage.tsx:87`、`PatientSessionDetailPage.tsx:61`）。守它的測試 `flutter_app/test/patient_facing_summary_test.dart`、`frontend/src/utils/__tests__/patientFacingReport.test.mts`。
    - ⚠️ e2e driver 目前**沒撈** `patient_facing_localized`（`scripts/e2e_realopenai/driver.py` 的 `soap_select` 只取 S/O/A/P + summary），所以非 zh-TW 場次病患**實際看到的那份文字**沒有任何 e2e 措辭鐵律覆蓋，只有 unit test 撐著。改這一區時別把「e2e 綠」當成措辭有驗過。

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
| #28 `no_*` 旗標 | `_noAllergies \|\| allergies.isEmpty` 把「沒填」送成「病患否認」（IN-1）；`familyHistory` 更是硬寫 `[]`（G13）。2026-08-20 兩端都改成純函式投影 + 明確勾選 |

**2026-08-20 之後的兩端對稱狀態**（本輪把三條病患面不變式一次補到兩端）：

| 不變式 | React | Flutter |
|---|---|---|
| #18 對稱條款（`end_session` 不搶先導頁） | **四條齊全**：不導頁 + 非 OPEN 給可見錯誤 + disabled/「結束中」 + 12 秒看門狗（EM-3），AST 測試釘住 | **只有「不導頁」這一條**（`conversation_controller.dart:495-499` 的註解就是 React 照著改的來源）。**非 OPEN 靜默丟棄**（`ws_manager.dart:111`）、**無 disabled**、**無看門狗** → **待補** |
| #28 `no_family_history` 勾選框 | 本輪補上（`MedicalInfoPage.tsx:715-722`） | 本輪補上（D-10；同輪修掉 IN-1 與 G13） |
| #36 / #37 病患面顯示（下架 ICD-10/信心分數、三態 resolver） | `patientFacingReport.ts` + 兩頁 | `patient_facing_summary.dart` + 兩頁 |

**仍不對稱、動到時要留意**：
- **#18 的其餘三條**（非 OPEN 可見錯誤／disabled 結束中／12 秒看門狗）React 有、**Flutter 沒有**，見上表。
- **#28 的「純函式 + 精確 JSON 形狀斷言」** Flutter 有、**React 是 inline literal + 原始碼正則掃描**，見 #28 的 ⚠️。
- Flutter 的 family relation 送**在地化字串**（D-3）與主訴→基本資料走 **URL query 參數**（D-5）是本輪 Flutter 端才做的。
  ✅ **React 這兩格早就對稱，不是待辦**：relation 本來就送 `t()`（`MedicalInfoPage.tsx:297`）；主訴路由本來就是 URL query（`SelectComplaintPage.tsx:239` `navigate('/patient/medical-info?' + params)` → `MedicalInfoPage.tsx:137-141` `useSearchParams()`），重整／深連結不會 422。

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

## ⚠️ 改偵測邏輯時的測試設計（2026-07-27 三次擺盪 + 2026-08-20 稽核的教訓）

改紅旗偵測、否定守衛、§3b gating 這類**判斷邏輯**時，測試怎麼寫比改怎麼寫更容易出錯。
2026-07-27 連續三輪擺盪（over-trigger → under-trigger → 收斂），每次根因都在這裡；
2026-08-20 稽核又多學到三條「**探針／oracle 自己壞掉**」的教訓（5–7）：

1. **測試表必須雙向對稱。** `MUST_FIRE` 與 `MUST_NOT_FIRE` 要同時存在。
   第一輪只加「必須命中」→ 改出 over-trigger；第二輪只加「不該命中」→ 改出 under-trigger。
   只往單一方向加斷言 ＝ 在替下一次擺盪鋪路。
2. **反例措辭不得與 e2e persona 台詞雷同。** 這是最深的假象：`torsion_critical_zh` 的台詞
   「左邊睪丸突然劇烈疼痛」剛好讓 `睪丸突然` 相鄰，所以 e2e 全綠——**驗收套件證明的是
   「這句台詞會命中」，不是「這個臨床情境會命中」**。加語序變體（部位詞與修飾詞之間插入
   2–8 字），並確認至少 3 種不同措辭都命中。
3. **測試的 oracle 不能是實作自己的偵測器。** SOAP 消毒層曾用自己的 regex 當判準 →
   偵測器漏掉的句型測試也一定漏掉，結果 2804 個 unit test 全綠但 e2e FAIL。
   用獨立維護的違規句語料（從真跑結果檔收集，如 `patient_facing_corpus.py`），
   或改成**結構性 oracle**（`test_prompt_injection_sanitization.py` 比對的是 prompt
   的區段結構，不是關鍵詞）。
4. **注入式回歸測試**：把修復故意改壞，確認有測試會紅，再還原。這招在 §R 四輪抓到 6 個
   「修了但沒有測試保護」的地方。值得當成常規步驟。
5. **e2e 自己 POST 裸 JSON ＝ 對前端 payload 組裝完全失明。** 真 OpenAI e2e 的 driver
   直接送它自己組的 intake JSON，所以前端把「沒填」偽造成「病患否認」（#28 IN-1）
   **在 e2e 是永遠看不到的**——場次照跑、SOAP 照生、全綠。凡是「前端投影出來的資料形狀」
   都要用**前端自己的**單元測試斷言精確 JSON（`intake_payload_test.dart` 就是為此把投影
   抽成 widget 外的純函式）。同理，e2e driver 沒撈的欄位（如 `patient_facing_localized`，#37）
   等於沒有 e2e 覆蓋。
6. **探針腳本的環境假設要自我證明。** `ps` 解析在中文 locale 下讓觀測欄位恆為 null →
   **假性 FAIL**（必須 `LC_ALL=C`）；`grep -c` 的退出碼在「沒命中」時非 0，包在
   `set -e`／`&&` 裡會被判成命中 → **假性 PASS**。探針的每個環境假設都要有一個
   「假設不成立時回 `precondition_not_met`」的分支，而不是靜靜落在 pass/fail 的某一側。
   相關的還有既有兩條：`_wrapup_has_no_question` 舊寫法 `"?" not in last_ai_text` 在
   文字為空時**恆真**（凡「某文字不含 X」型斷言都要先確認那段文字存在）；
   `reanalyze` 只讀結果檔 ＝ 對產品碼變動失明，要嘛真的重跑要嘛標 `stale`。
7. **不要把「其中一種合格樣態」寫死成唯一樣態。** EM-1（#20）之後 critical abort 有**兩種
   合法樣態**：inline 判定 → 主迴圈當場 break、WS 立刻關閉、**收不到任何提示**（A）；
   背景 drain 判定 → 下一則訊息被 `_terminated` 守衛接住、送固定 i18n 提示後關閉（B）。
   舊 `t5` 只認 B，於是**同一份碼會一場紅一場綠**（兩場 torsion 真跑各中一次）。
   判準要寫在**不變的實質**上（這裡是「終止後不得有任何 LLM 產物」），把各樣態列成合法
   分支，並記進 `post_abort_shape` 這種觀測欄位讓覆核者看得見走了哪條。
   證據：`scripts/e2e_realopenai/README.md:366-371`（守則 #16）、`:410-434`（t5 判準改版）。
8. **driver 的回合上限是產品行為的函數。** §3b 動態硬上限（#23 的配額）上線後，K=3 的場景
   需要 15+ 輪才收得了尾，`max_patient_turns=12` 會讓 driver 先收手 → **假性 FAIL**。
   改配額邏輯時要回頭檢查各情境的 `max_patient_turns`（`ed_zh` 本輪 12→18）。

## 修改流程

1. 讀本清單，找出改動會碰到哪幾條不變式。
2. 實作改動（最小 diff）。
3. 改偵測邏輯 → 先讀上一節的測試設計八點（尤其 5–8：改前端 payload／探針腳本／終態樣態／配額時，見 #31）。
4. 動到終態轉移 → 先在 `tests/unit/test_terminal_path_six_things_matrix.py` 的
   `TERMINAL_PATHS` 加一列再讓它綠（#29），並確認 #20 的三條時序鐵律與 `_SOAP_ON_TERMINAL` /
   `REPORT_ELIGIBLE_SESSION_STATUSES` / `tasks/session_timeout` 三處政策一致（#13）。
5. 動到 intake 三態欄位或病患面顯示 → 後端 schema、`patient_context` 分支、**兩份前端 UI**
   同輪一起做（#19／#28），病患面文字兩端都要走同一支 resolver（#37）。
6. 前端行為改動 → `npm run type-check` + 手動走一次對話流程；管線/prompt 改動 → 依
   `e2e-real-openai` skill 跑至少一個相關情境（紅旗改動跑 `torsion_critical_zh`
   **＋ `torsion_wordorder_zh` 或 `torsion_critical_en`**，結束邏輯改動跑 `dontknow_zh`，
   intake/§3b 改動跑 `intake_wiring_zh`）。
7. PR 描述註明驗證了哪些不變式。

## Common Rationalizations

| 藉口 | 現實 |
|---|---|
| 「只是小改 prompt，不用跑 e2e」 | §3b 與紅旗行為對 prompt 措辭極敏感，過去多次「小改」造成漏問/誤結束，全靠 e2e 抓到 |
| 「這個 unmute 情境很特殊，直接 setMuted 就好」 | 散落的 unmute 判斷正是當初重構成 shouldUnmuteVAD 矩陣的原因 |
| 「規則層紅旗和 LLM 重複，可以刪」 | 規則層是 LLM 漏判時的 fallback（E9 加固），刪了等於單點失效 |
| 「這個誤報很蠢，加條守衛擋掉」 | 偏誤報是臨床拍板（#22）。每條抑制都是潛在漏報——先問「它會不會擋到真症狀」，多半會 |
| 「那就把這個字面從詞表刪掉」 | 收窄字面可以，但要**逐字面**舉證＋臨床拍板，多半是降進共現組而不是消失（#22／#30）。`KEPT_LITERALS` 裡的更不能動 |
| 「補幾個關鍵字就能修這個漏報」 | 補關鍵字是 §R 前兩輪走過的死路。用共現組（#21），否則過幾天就換另一邊出事 |
| 「單元測試全綠了，e2e 可以跳過」 | 2804 個 unit test 全綠但 e2e FAIL 發生過——測試的 oracle 是實作自己 |
| 「e2e 全綠了，前端那段不用測」 | e2e 自己 POST 裸 JSON，看不到前端偽造的 payload（#28）、也撈不到它沒 select 的欄位（#37） |
| 「intake 已經填了就不用問」 | 要看**值是否真的涵蓋**該風險因子（#23）。用藥欄填 amlodipine 不等於沒吃抗凝血劑 |
| 「清單是空的，就是病患沒有」 | 空白＝沒填，不是否認。後端把 `no_*` 當 ANSWERED_NO 寫進 SOAP＝捏造病歷（#28） |
| 「終態就是把 status 改掉而已」 | 是六件事＋三條時序鐵律（#20），漏一格就是「終態沒有 SOAP」或「病患收到兩則終態」 |

## Verification

- [ ] 改動涉及的每條不變式都確認未被破壞（列在 PR 描述）
- [ ] 管線/prompt 改動有真 OpenAI e2e 結果 JSON 佐證
- [ ] 改偵測邏輯：`MUST_FIRE` 與 `MUST_NOT_FIRE` 雙向都有新增案例，且措辭不同於 persona 台詞
- [ ] 新增抑制守衛：能說出「為什麼它不會造成漏報」；**移除／收窄字面**：逐字面舉證 + 附實測仍命中的句子 + 未動到 `KEPT_LITERALS`
- [ ] 新增終態路徑：已登記進 `test_terminal_path_six_things_matrix.py` 的 `TERMINAL_PATHS`，六格皆 DONE 或有 docstring 理由 + 程式碼註解錨點
- [ ] 動到 intake 三態或病患面文字：兩份前端都改了，且有斷言 payload 形狀／resolver 三態的單元測試
- [ ] 新增探針斷言：環境假設有自我證明分支，且沒有把單一合格樣態寫死（`post_abort_shape` 型的觀測欄位）
- [ ] 前端改動通過 `npm run type-check` 與 `npm run lint`
