# 產品全面稽核：問答水準 × 使用體驗（2026-07-06）

> 方法：3 個平行稽核 agent（問答品質 / 病患端 UX / 醫師端 UX），各自對原始碼與 40 batch + 15 對抗性真實逐字稿做證據性分析並複驗，主 session 再實查本地 DB 修正歸因。
> 素材：`scratchpad/e2e/batch_results/*.json`（40）、`adversarial_results/*.json`（15）、`frontend/src/screens/*`、`backend/app/pipelines/*`。
> 分級：**P0 安全/隱私 > P1 正確性/可用性阻斷 > P2 摩擦/體驗 > P3 細節**。標「✅已修/🟡部分修」者為本 session（PR#21）已處理。

---

## 0. 三大跨切面主題（最該優先）

1. **紅旗安全鏈全程有破口**——偵測層有誤報+漏報、送達層患者端與醫師端都可能漏看。這是本產品**核心安全功能**，卻是問題最密集處。詳 §1。
2. **Kiosk 隱私未把關**——無自動登出、結束問診不 logout、token 存 localStorage → 上一位病患姓名+泌尿主訴殘留給下一位。詳 §2。
3. **i18n「字典齊全但頁面沒接線」**——5 語 key 零缺漏（維護紀律好），但多個核心頁（含 SOAPReportPage、AlertListPage、PatientHistoryPage）整頁硬編繁中，且患者/醫師設定頁的語言切換都繞過「URL 為語言唯一權威」不變式。詳 §4。

---

## 1. P0 — 紅旗安全鏈（偵測 → 送達，患者+醫師+問答三面交叉）

### 1a. 偵測層：否定句誤觸紅旗（✅ 已修 2026-07-06 批1）
> **修復狀態**：`red_flag_detector.py` 新增否定幻覺後過濾 `_canonical_denied_in_text`（merge 後涵蓋規則+語意層）+ ja/ko 後置否定（`_clause_after`/`_POST_NEGATION_CUES`，含連用形「なく」）。安全設計：只抑制「canonical 關鍵字出現但全被否定、且無任一非否定出現」，規則層真命中與語意層情境推論（關鍵字不在文中）皆不受影響。量測：55 場歷史逐字稿**20 個否定誤觸抑制、0 真陽性誤殺**（critical torsion/真血尿全保留，c5 腰痛病患明確否認發燒的 urosepsis 正確抑制）；`test_red_flag_negation.py`+`test_red_flag_denial.py` 共 +15 例，全 backend 881 passed。⚠️ ja/ko 否定詞上線前建議母語者覆核。以下為原始問題描述：

- 病患明確**否認**症狀仍觸發紅旗，5 語言、多主訴大量重現。實例：`vi-VN_c1_vi02`「Không tiểu ra máu, sốt, sụt cân」→ 觸發尿路敗血症 critical + 血尿 + 體重減輕 3 筆；`en-US_c1_en01`「no blood clots」→ 觸發「大量血尿合併血塊」critical（**在真陽性上額外捏造未陳述的「血塊」**）。
- **主 session 實查 DB 歸因**：這些在 DB 皆 `alert_type=rule_based` → 是**規則層 substring** bug。本 session **A1 修復（`_keyword_present_non_negated`）已涵蓋 zh/en/vi 前置否定**（e2e 驗證修後該場 0 alert）。
- **仍未修的真 gap**：(a) **ja/ko 後置否定**（「血尿はありません」，`ja-JP_c9_ja08` 實證仍 rule_based 誤觸）——A1 只做前置；(b) **語意層獨立幻覺**——部分為 `combined`（規則+語意都中），A1 只壓規則層，`_merge_and_deduplicate` **沒有用否定邏輯反向抑制語意層**，語意-only 的否定誤觸仍會進 alert。
- **影響**：negation_heavy 對抗場**問診第 1 輪就被誤中止**（session `aborted_red_flag`），但同場 SOAP 卻判 `urgency=routine`、「無尿滯留感」——**同一病歷內部自相矛盾**。長期稀釋紅旗可信度→警示疲勞。
- **建議**：語意層每筆 alert 寫入前用否定邏輯交叉檢查、抑制或降級為「待人工複核」；ja/ko 加後置否定偵測。

### 1b. 偵測層：淡化語氣 → 嚴重度降級 / 漏報（🟡 部分修，recall 未解）
- `adversarial downplay_zh01`（教科書睪丸扭轉但病患一直「應該還好」）→ 只判 `high`、**未 abort**；另一場 `downplay_zh02` → **0 偵測**。
- 本 session **A3（目錄 severity floor）已修「偵測到就 floor 回 critical」**（e2e downplay run1 已驗 high→critical→abort→er_now）。但**極度淡化下語意層 recall 不穩**（downplay 兩跑一次 critical、一次 0 偵測）——沒偵測到就無從 floor。這是最需要安全網的族群（隱私敏感部位病患最會淡化）。
- **建議**：需臨床決策——特定高風險主訴（年輕男性陰囊腫脹一律 torsion rule-out）強制篩查，或降低該類偵測門檻。

### 1c. 送達層（醫師）：新 critical 紅旗在多數頁面「零信號」→ 醫師極可能漏看（🟡 部分修 2026-07-06 批3c）
> **已修（低風險版）**：新增 `DoctorAlertPoller`（掛醫師 shell `MainLayout`）——每 20s 輪詢未處理紅旗數 → **Sidebar 徽章 app-wide 即時更新**、數字增加即**全域 toast**（5 語 `alert.newAlertToast`）+ 選配音效（接既有 `soundEnabled`，Web Audio beep 免音檔）。醫師在任何頁都會於 ≤20s 內收到新紅旗信號。**未採完整 WS 常駐**：因共用 singleton dashboard WS 的多消費者生命週期（`off(event)` 移除該事件所有 handler）在無 runtime 測試下風險高，留作後續（需 runtime QA）。以下為原始描述：

- 紅旗 WebSocket 只綁在 `AlertListPage`/`SessionListPage`（`useWebSocket.ts:132-165`，cleanup 即 disconnect）。醫師在審 SOAP、看病患、Dashboard、設定頁時**沒有任何開著的紅旗 WS**。Sidebar 未讀徽章只 mount 抓一次（無 WS/interval）。設定頁「聲音提示」開關的 `soundEnabled` **從未被讀取＝死設定**；全 repo 無 `new Audio`/`Notification`。
- **影響**：候診情境下，醫師審 A 病患 SOAP 時，B 病患的 er_now 紅旗**無徽章/聲音/toast/banner**，直到主動切 `/alerts` 且剛好重抓。**核心安全功能最大缺口。**
- **建議**：紅旗 WS 提升到 app-shell 常駐；critical 到來全域 toast/banner +（接上既有 soundEnabled）音效；Sidebar 徽章改 WS 驅動。

### 1d. 送達層（醫師）：session 抓取失敗**靜默隱藏**紅旗（✅ 已修 2026-07-06 批3a）
> **已修**：`SOAPReportPage` 加 `sessionLoadFailed` state；session 抓取失敗時紅旗徽章/卡片改顯示「⚠ 紅旗狀態載入失敗，切勿逕自當作無紅旗」（琥珀色警示）而非默默消失。tsc 0 錯。以下為原始描述：

- `SOAPReportPage.tsx:204-207` `getSession(...).catch(()=>setSession(null))`；頁面只 gate 在 `report`，故 `session` 抓失敗仍完整渲染，而紅旗徽章/紅旗註記卡都條件在 `session?.redFlag` → **一次網路抖動就讓有紅旗的病例顯示成沒紅旗**。
- **建議**：session 抓取失敗顯性化（錯誤條/重試）；紅旗區塊未載入成功時顯示「載入失敗」而非默默消失。

### 1e. 送達層（醫師）：紅旗清單無嚴重度排序 + 20 筆上限無 load-more（🟡 部分修 2026-07-06 批3a）
> **已修**：`AlertListPage` 日期分組內改以「未處理優先→severity(critical>high>medium)→較新」排序（critical 不再被當日較新 medium 推下）；`AlertItem` ack 按鈕加 `window.confirm`（5 語 `alert.acknowledgeConfirm`）防誤點不可復原。**仍未修**：20 筆上限的 `fetchMore`/無限捲動（超過 20 筆仍看不到）。以下為原始描述：

- `AlertListPage.tsx:225-248` 只依 `createdAt` 倒序；`fetchAlerts` 固定 `limit:20`，**從未呼叫 `fetchMore`**（store 有但零呼叫點）→ **超過 20 筆的未處理 critical 永久無法從 UI 取得**。ack（`AlertItem.tsx:156-165`）一鍵無確認、不可復原、不可批次。
- **建議**：依 severity 置頂 critical/未處理；接 `fetchMore`；critical ack 加確認 + undo。

### 1f. 送達層（患者）：紅旗中止不導離 + 無語音（🟡 部分修 2026-07-06 批2）
> **已修**：後端 abort patient emit 帶 `extra={"status":"aborted_red_flag"}`（`send_localized_to_session` 加 `extra` 參數）→ 前端 `ConversationPage` 紅旗中止**導向感謝頁並帶 state**（元件 unmount 自然停止無限重連）；`SessionThankYouPage` 紅旗變體顯示現成 5 語文案「請立即告知現場醫護」+ **不自動跳轉**（順帶解 M1）；紅旗橫幅加 `role="alert" aria-live="assertive"`、title `truncate`→`line-clamp-2`。測試 881 passed + tsc 0 錯。**仍未修**：紅旗中止「當下主動播語音」(S4)、idle_timeout 導頁。以下為原始描述：

- 後端「正常結束」帶 `status:completed` 才導頁；但**紅旗中止/idle 逾時只送 `code` 不帶 `status`**（`conversation_handler.py:614-622/2104-2110`）→ 前端 `ConversationPage.tsx:669-677` 只 `setError` **不導頁**，麥克風圈/輸入框視覺仍「活著」，隨後斷線又無限重連疊在中止訊息上、無限轉圈。
- 紅旗中止**無語音提示**（payload 無音訊、handler 不呼 TTS）→ 語音為主的長者安靜等待時**永遠聽不到「請立即告知現場醫護」**。
- 紅旗橫幅本身**無 `aria-live`/`role="alert"`**（`ConversationPage.tsx:916-968`）→ 螢幕報讀不主動播報最關鍵臨床訊息；描述用 12px+opacity-90（全頁最關鍵訊息卻用次小字）。
- **建議**：紅旗中止/idle 的 `session_status` payload 也帶 `status` 走既有導頁；中止當下主動播固定語音；紅旗橫幅加 `role="alert" aria-live="assertive"`、描述提到 14px。

### 1g. 呈現層：紅旗 `description` 欄位永遠繁中（未在地化，未修）
- `title` 正確在地化，但 `description` 不論場次語言都是繁中（`shared.py URO_RED_FLAGS` 只有單一 `description`，merge 保留規則層中文版）。醫師端/儀表板若看到會語言混雜。

---

## 2. P0 — Kiosk 隱私（患者端，未修）

### 2a. 無自動登出、結束問診不 logout → 個資殘留給下一位（🟡 部分修 2026-07-06 批3b）
> **已修**：新增 `KioskIdleGuard`（掛 RootNavigator 內）——**env 開關 `VITE_KIOSK_IDLE_TIMEOUT_MS`（預設停用，不影響非 kiosk）**、限 patient 角色、排除 `/conversation`（問診閒置由後端處理），閒置逾時 → `resetSession()` + `logout()`，RequireAuth 自動導回 `/login`。kiosk 於 Vercel env 設如 180000（3 分）啟用。**仍可加強**：結束問診「換下一位」單鍵登出、logout 時一併清 report/complaint store。以下為原始描述：

- 全 repo 無 idle timeout/auto-logout；token 存 **localStorage**、`App.tsx` mount 自動復原登入；`SessionComplete`/`ThankYou` **零 logout 呼叫**（複驗）。→ 上一位 token 未過期時，下一位開同台平板即以上一位身份登入。`PatientHomePage.tsx:96,170-183` 首頁直接顯示 `user.name` + 最近主訴（如「血尿持續三天」）+ redFlagReason。
- **建議**：(a) 全域 idle timer → logout+清 store+回歡迎頁；(b) 結束流程主動 logout+清 conversation/complaint/report store；(c) 工作人員「結束並清空給下一位」單鍵。

### 2b. 對話 WS 無 auth-failure 續期 → refresh 過期時無限 4001 迴圈（✅ 已修 2026-07-06 批3b）
> **已修**：`useConversationWebSocket` 比照 dashboardWS 註冊 `setAuthFailureHandler`（4001→主動 refresh、單飛去重）+ `_auth_exhausted`→`logout()`（RequireAuth 導回 /login），不再無限重連「連線中斷」轉圈。tsc 0 錯。以下為原始描述：

- `useConversationWebSocket` **從未註冊 `setAuthFailureHandler`**（只有 dashboardWS 有，複驗）。長問診 access token 過期是常態；refresh 也失效時無限重連（`maxRetries:0`）每 30s 撞 4001，UI 只顯示「重新連線中…」**永不出現「請重新登入/洽工作人員」**。
- **建議**：conversationWS 比照註冊 authFailureHandler；徹底失敗 emit 終止事件、UI 明確文案 + `closeMic()`。

### 2c. 表單無 `autoComplete` + session 讀取前端無 ownership 檢查
- 姓名/生日/電話 input 無 `autoComplete`（前一位 PII 可能出現在自動完成）；`PatientSessionDetailPage.tsx:30` 直接 `getSession(id)` 未核對 `patientId===user.id`（**IDOR 需後端稽核佐證**）。

---

## 3. P1 — 問答/臨床品質（問答稽核，未修）

- **3a. 矛盾陳述被靜默覆蓋未標記**：`contradiction` 對抗場病患前段「10/10 劇痛、幾乎每次血尿」中途翻供「上個月、偶爾、不太痛」，SOAP **只採後段**、無任何「陳述前後不一致」標註（違反 soap prompt 自身第 5 條）。醫師不知病患曾矛盾。
- **3b. 關鍵風險因子問不到**：血尿 cooperative 場（5 語言）**全部沒問吸菸史/抗凝血劑/泌尿癌家族史**（無痛血尿最重要的惡性風險分層）；ED 場 4/5 語言未問心血管風險。根因：這些被 prompt 歸為「次要補問」只在 HPI 十欄達 7 成才問（`llm_conversation.py:145-159`），而 Supervisor 又「不因次要未問完壓低分數」（`supervisor.py:100-105`）→ 核心十欄快填滿就收尾，觸不到次要補問。
- **3c. HPI 十欄系統性偏空**（40 場統計）：`relieving_factors` ~60% 空、`context` ~52%、`aggravating_factors` ~48%、`location` ~42% 空（characteristics/associated_symptoms <5% 空）→ OPQRST 後段維度常被跳過。
- **3d. 危急升級後部分語言仍追問例行問題**：zh/ko 偵測危急後只說「請立即告知醫護」不再追問；en/ja/vi 卻在同句又追問一個 OPQRST 問題 → 稀釋緊急訊號、5 語言不一致。
- **3e. confidence_score 自評、無 grounding**（先前提案已列，未修）。

> **做得好（問答）**：一次一題規則全數遵守、don't-know 正確跳題不打轉、同理心不過度公式化（每場≤1次）、離題/答非所問有韌性、ja/ko/vi 問句自然無翻譯腔無中文洩漏、DDx reasoning 有引用對話、false-fact 正確標「病人自述」不誤列 objective、**kiosk 措辭 55 場零「盡速就醫」**、開場/收尾一致得體。

---

## 4. P1 — i18n 頁面未接線（醫師+患者，未修）

字典（common/auth/admin/dashboard/soap/session/ws/conversation/intake）**5 語 key 零缺漏**，但下列頁面元件本身硬編繁中，非中文醫護/病患看到整頁中文：
- **醫師端**：`SOAPReportPage`（核心審閱頁，含最安全相關的審閱指示句 :578）、`AlertListPage`（最安全關鍵頁之一）、`ReportListPage`、`SystemHealthPage`、`NotificationPage`。
- **病患端**：`PatientHistoryPage`（唯一無 `useTranslation` 的病患頁，複驗）。
- **語言切換破壞不變式**：`PatientSettingsPage.tsx:191` 與醫師 `SettingsPage.tsx:119-126` 的語言下拉都走 `settingsStore.setLanguage`→只 `i18n.changeLanguage` **不動 URL** → 與 `LanguageLayout` 的 URL-first 衝突、畫面與後端 Accept-Language desync；且都只列 zh/en 2 語（ja/ko/vi 選不到）。正解是複用 Header 的 `LanguageSwitcher`。
- **細節**：`SOAPReportPage:67-72 extractNegativeFindings` 正則只認中/英否定 → ja/ko/vi 場「重要陰性」框誤空；`SearchBar aria-label="清除搜尋"` 硬編中文（所有語言螢幕報讀念中文）；`AlertItem` 用 `toLocaleDateString('zh-TW')` 硬鎖中文日期。

---

## 5. P1 — 可用性阻斷（跨端，未修）

- **5a. 分頁實質壞掉**（醫師）：`ReportListPage`/`NotificationPage`/admin 三清單頁 store 有 `fetchMore`/`hasMore` 但零消費 → **超過 20（或 50/100）筆的資料永久看不到、無提示**。`ReportListPage` 還**完全無搜尋框**。範本：`PatientListPage` 的無限捲動+三態。
- **5b. MedicalInfo Step1「下一步」disabled 使逐欄錯誤變死碼**（患者）：按鈕 `disabled={!identityValid}` → 原生 disabled 不觸發 onClick → 想顯示「哪欄沒填」的邏輯永不執行，長者只看到灰按鈕不知錯在哪（`MedicalInfoPage.tsx:206-213,813`）。
- **5c. 中途返回無預警清空全部已填**（患者）：返回箭頭一律 `navigate('/patient/start')` 無確認、無回填 → 姓名/病史/主訴全清空。
- **5d. 可核准未完成/失敗的報告**（醫師）（✅ 已修 2026-07-06 批3a）：核准/退回行動列改 gate `!isReviewed && report.status === 'generated'`（與 PDF 匯出一致）+ `handleReview` 加 `status !== 'generated'` 防禦。
- **5e. 無法內嵌修正 AI 欄位**（醫師）：`SOAPCard` 100% 唯讀，改一個抽錯的欄位只能「接受錯誤」或「整份重生」二選一。
- **5f. 慢網路可能靜默丟失病患第一句話**（患者）：麥克風開啟看 REST status、與 WS 連線不互等；WS 未 open 時開口，`audio_chunk` 被靜默丟棄、UI 卡「正在辨識」永不回。
- **5g. isAIResponding 斷線重連後永久卡 true**（患者）：`_disconnected`/`_connected` 不清 → 思考中動畫不消失，長者誤以為還要等。

---

## 6. P2 — 摩擦與錯誤處理（跨端，未修）

- **多處錯誤被靜默吞掉**（兩端）：`SessionListPage`/`ReportListPage`/`UserManagementPage`/多個 store `catch{/*靜默*/}` → API 失敗顯示「無資料」空狀態、無法分辨真錯誤、無 retry。範本：`PatientListPage` 三態 + 軟 retry、`complaintStore.resolveErrorMessage`（後端在地化訊息優先）。
- **未存編輯無警告遺失**（醫師）：無 `beforeunload`/`useBlocker`；401 refresh 失敗即硬跳 `/login`，正在打的審閱理由整段消失。審閱送出失敗可能靜默（modal onClose 未擋 isSubmitting）、成功也無 toast。
- **VAD 視覺回饋不足**（患者）：「AI 回應中(硬鎖)」vs「輪到你說」淺色僅一階色差、**深色模式完全相同**、無 icon/動畫差異 → 病患分不清能否開口（男性泌尿族群紅綠色盲比例高）。
- **麥克風**：getUserMedia 前無說明卡（長者反射按封鎖）、失敗時無「改用打字」主動導引（輸入框恆在但沒串起來）、無病患可調靈敏度/無問診前麥克風測試。
- **ThankYouPage 8 秒強制自動導頁**、對紅旗案例無加強提示；TTS 無 unmount 清理（導航後 AI 語音可能續播，kiosk 下一位聽到）。
- **admin 高風險動作缺確認**：停用帳號/升 admin 單鍵無確認（對比刪主訴模板卻有確認 modal）。
- **共用 `Modal` 無 a11y**（無 `role=dialog`/focus trap）**與 dark mode**（無 `dark:` class → 暗底刺眼亮框）；`UserManagementPage` 表格 `overflow-hidden` 窄螢幕裁切。

---

## 7. P2/P3 — 無障礙與一致性（患者端為主，未修）

- 多處關鍵狀態缺 `aria-live`/`role`（紅旗橫幅、狀態列、錯誤 banner）；表單 label 無 `htmlFor/id`；icon-only 按鈕缺 `aria-label` 且觸控目標 <44px（結束問診鈕/確認鈕/checkbox）；字級偏小 + 低對比（`ink-muted` 2.95:1、`red-500` 3.76:1 皆 < WCAG AA 4.5:1）用於必填星號/錯誤/紅旗描述；紅旗在歷史清單只靠 **3px 紅色左邊條**（無文字/icon）→ completed+redFlag 時色盲看不出。
- 清單頁三套分頁策略、兩套 filter-tab 樣式、無共用元件；只有 Patient 用 store 故只有它返回保留篩選；篩選未寫入 URL（無法書籤/分享）。
- 術語漂移：「主訴模**版**」vs「模**板**」、「系統狀態」vs「系統健康監控」；`SystemHealthPage` 卡片標題「AI 服務配額」實渲染 DB/Redis 假進度條、未讀後端已提供的 openai 配額。
- Dashboard 誤解：`DashboardPage` **不是即時佇列/紅旗頁**而是月度摘要（無 WS）；`QueueCard`/`StatCard` 為死碼。

---

## 8. 做得好的（平衡，已複驗）

- **語音管線醫療安全骨幹**：AI 講話硬鎖麥 + 多路徑保證解鎖 + `shouldUnmuteVAD` 矩陣 + userPaused 獨立閘；打字斷線防呆（可打字/草稿不清/不假造氣泡）；麥克風 unmount 清理完整。
- **WS manager**：指數退避、4001 靠共享 `refreshAccessToken` 單飛去重、resume token；`client.ts` 單一 refreshPromise 去重。
- **紅旗偵測規則層**：否定邏輯嚴謹（列舉/轉折/句尾/5 語）+ 完整單元測試；典型危急劇本 5 語言都正確 critical+abort；跨語言聯集比對抓得到 code-switch 關鍵字。
- **i18n key parity 零缺漏**、路由級 `RoleGuard` 真重導、`SeverityBadge`/`StatusBadge` 色+圖示+文字（色盲友善、reduced-motion 停動畫）、`TranscriptPanel`（角色過濾+搜尋+校準低 STT 信心標記+逐句紅旗）、`SOAPCard` 正規化防 schema 漂移、`PatientListPage` 三態+無限捲動範本、重生/退回的確認+不可復原守則。
- **kiosk 措辭合規**：患者面 55 場 + locale 逐字核對，零「盡速就醫/去急診」。

---

## 9. 建議優先修復順序

1. **P0 紅旗鏈**（安全，影響全體）：
   - 醫師端 §1c 紅旗 WS 常駐 app-shell + 醒目提示/音效、§1d session 抓取失敗別隱藏紅旗、§1e 排序+分頁+ack 確認。
   - 患者端 §1f 紅旗中止導離+語音+aria-live。
   - 偵測層 §1a 語意層/ja-ko 否定交叉抑制、§1b downplay recall（需臨床決策）。
2. **P0 kiosk 隱私** §2：idle 登出 + 結束 logout + WS authFailureHandler。
3. **P1 正確性**：§5d 核准加 status gate、§3a 矛盾標記、§3b 關鍵風險因子提前、§1g/§4 紅旗描述+核心頁 i18n（字典已齊，純接線）。
4. **P1 可用性**：§5a 分頁、§5b 逐欄錯誤、§5c 返回保留、§5f/§5g 連線邊界。
5. **P2/P3**：錯誤三態化、a11y（aria-live/觸控/對比/色盲）、共用元件收斂。

> 標「需實機確認」：色彩對比實測值、kiosk 螢幕字級可讀性、觸控誤觸率、斷線重連/紅旗中止手動實測、S5 IDOR 後端授權、autoComplete 是否被裝置 kiosk-mode 緩解。
