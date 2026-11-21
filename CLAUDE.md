# GU_0410 — GU Voice 泌尿科語音問診系統

This project's Baseline target is Baseline Newly available. The frontend uses Chrome Modern Web Guidance (MWG); use feature detection and `@supports` progressive enhancement with graceful fallbacks for unsupported browsers.

院內候診 Kiosk 的語音 AI 問診系統：病患已在現場、問診完成後等看診。FastAPI + Celery 共用後端、原生 SwiftUI iOS App（病患 kiosk＋醫師＋管理員）、React + Vite 網頁版（**只給醫師看報告**）、5 語言（zh-TW / en-US / ja-JP / ko-KR / vi-VN）。

## 專案結構

```
backend/            → FastAPI + Celery。app/pipelines/ 問診管線（llm_conversation、red_flag_detector、
                      supervisor、soap_generator、prompts/）、app/websocket/、alembic/ migrations。
                      ⚠️ `tests/unit/test_terminal_path_six_things_matrix.py` 是**跨模組跳閘器**
                      （AST 掃 conversation_handler / session_service / tasks.session_timeout 三個
                      模組的**終態轉移點**——三格認的形狀不同，session_service 那格認的是
                      `_after_status_transition` 呼叫入口，另兩格認的是「寫終態」本身）。
                      必須留在 tests/unit/ **根**：檔內用 `parents[2]` 硬推 `backend/`，
                      移進子目錄會讓路徑推導掉一層
frontend/           → 持續維護的 React + Vite + TS 網頁版。2026-11-08 起 React 網頁版只剩醫師看報告（登入 → 報告清單 → 報告頁：患者名稱、紅旗、SOAP、逐字稿、確認／退回、匯出 PDF、快速開單），病患問診與其餘醫師／管理頁只在 iOS App。
                      路由只有 /:lng/{login,forgot-password,reset-password,reports,reports/:sessionId}，
                      其餘路徑一律導回 /reports；病患帳號在網頁登入會被擋下並登出。
                      src/i18n/locales/ 是網頁翻譯來源；public/locales/ 是 build 鏡像。
ios_native/         → 唯一的 iOS App，病患 kiosk、醫師與管理員依角色分流。
                      App/Localizable.xcstrings 與 App/*.lproj/Kiosk.strings 是五語來源。
                      本機建置與測試見 ios_native/README.md。發佈設定見 docs/ios_release_settings.md。
docs/               → 現行文件（入口 docs/README.md；docs/AGENTS.md 為部署細節指南；
                      docs/archive/ 為歷史 audit 與舊規格，勿當現行讀）
scripts/            → check_translations.py、e2e_realopenai/（真 OpenAI E2E 工具，見其 README.md）
.claude/skills/     → 專案技能（入庫，載入時機見各 skill description）
graphify-out/       → graphify 知識圖譜（untracked，可重建；graph.html 互動圖、GRAPH_REPORT.md）
```

## 常用指令

- Frontend（在 `frontend/`）：`npm run dev`、`npm run build`（tsc + vite，翻譯改動後必跑）、`npm run lint`、`npm run type-check`、`npm test`（Node ≥ 22.17）、`npm run test:e2e`（Playwright）、`npm run i18n:extract:check`
- Backend（在 `backend/`）：`venv/bin/pytest tests/`（unit / integration / e2e 分層）、`venv/bin/uvicorn app.main:app --reload`
- iOS：用 Xcode 的 GUVoice scheme 或依 `ios_native/README.md` 執行 `xcodebuild`、單元測試與 kiosk 合成情境。
- 本機全端：`docker compose up -d`（frontend :80、backend :8000、postgres :5432、redis :6379）
- 翻譯完整性（repo 根目錄）：網頁 `python scripts/check_translations.py`；App `python scripts/check_translations.py --ios-app-dir ios_native/App`
- 碼庫探索：`graphify query "<問題>"`／`graphify path A B`／`graphify explain <符號>`（對 `graphify-out/graph.json` 查詢，涵蓋 code＋docs；程式碼大幅改動後用 `/graphify . --update` 增量重建）

## 部署重點

**2026-11-15 起自架在使用者那台常開的 Mac，Railway／Vercel 已刪除。** 對外網址只有一個：`https://gu.zymomed.com`（Cloudflare Tunnel `gu-voice` → `127.0.0.1:8005` → nginx：React 報告網頁＋`/api/`、`/api/v1/ws/` 轉給 backend）。部署設定與金鑰都在 repo 外的 `~/Services/gu-voice/`（`compose.yml`、`.env`、`nginx.conf`、`deploy.sh`、`backup.sh`、`README.md`），因為 repo 是公開的。merge 到 main 不會上線：

- 後端＋React 網頁：`~/Services/gu-voice/deploy.sh`（拉 main → 先備份 → `docker compose up -d --build backend web`，`start.sh` 自跑 alembic → 驗 `/api/v1/healthz/deep`）
- 生產 DB＝該 Mac 上 compose 專案 `gu-voice-host` 的 Postgres 17（volume `gu-voice-host_db_data`），不再是 Supabase；每日 03:40 `backup.sh`（launchd `com.gu-voice.backup`）。⚠️ repo 根的 `docker-compose.yml` 是**本機開發用**、專案名 `gu-voice`，別拿它碰正式環境
- client IP：nginx 只把 `CF-Connecting-IP` 寫進 `X-Forwarded-For`，後端 `TRUST_PROXY_HEADERS=true` 取最後一段；改 nginx 時別換回 `$proxy_add_x_forwarded_for`（會讓全院共用 docker gateway IP、登入限流一起鎖）
- iOS TestFlight（內部測試）：用 `ios_native/tool/build_ios_testflight.sh` 從 `origin/main` 打包。發佈人審閱驗證日誌、核對 SHA-256，依序對同一顆 IPA 手動執行 `altool --validate-app` 與 `--upload-app`。正式端點在 `ios_native/Config/Production.xcconfig`。
- 正式環境只供獲授權人員。醫師與臨床 admin 只讀自己獲指派的資料，system admin 保留全院稽核。舊未指派報告通知仍有在職醫護 fallback。驗收用合成資料。
- 發佈與回滾見 `docs/deployment_guide.md`、`docs/ios_release_settings.md` 和 `docs/runbook/ios_rollback.md`。2026-11-15 前的 Railway、Vercel 與 Supabase 文件位於 `docs/archive/cloud_2026-11/`。

## 專案技能（.claude/skills/）

| Skill | 何時載入 |
|---|---|
| `voice-pipeline-invariants` | 動到問診對話流程（`ios_native/App/Kiosk*.swift`、後端 app/pipelines/）之前；React 的問診前端已於 2026-11-08 移除 |
| `e2e-real-openai` | 需要用真 OpenAI 驗證問診行為改動時（管線/prompt 改動的合併前置條件） |
| `i18n-language-consistency` | 動到語言切換、翻譯檔、或顯示在地化資料的頁面時（網頁及 iOS 各自檢查翻譯） |
| `deploy-production` | 部署、改部署設定、生產環境除錯（DB timeout、連線問題）時 |
| `research-analytics` | 動到 `ios_native/App/ResearchScreen.swift`或 /api/v1/research/analytics 時（React /research 頁已於 2026-11-08 移除） |
| `ios-testflight` | 打 iOS TestFlight 包、處理簽章／上傳／內部測試群組，或動到 `ios_native/Config/` 與打包腳本時 |
| `design-taste-frontend` | 改前端視覺時。iOS 優先重用 `ios_native/App/ClinicalRows.swift`、`ClinicalNavigation.swift` 與 kiosk 已有的元件 |

## 鐵律（Boundaries）

- Always：改 `frontend/src/i18n/locales/` 後執行 `npm run build` 重生 `public/locales/`，兩者一起 commit
- Always：改 `backend/scripts/start.sh` 後保留 executable bit（`git update-index --chmod=+x`），否則 backend 容器起不來
- Always：動語音管線或 SOAP prompt 前先讀 `voice-pipeline-invariants`；改完跑 `e2e-real-openai` 驗證
- Always：病患面措辭用「請稍候等看診」「請告知現場醫護」——部署情境是院內 kiosk，病患已在現場，禁用含糊的「盡速就醫」
- Always：iOS 與 React 都持續維護；共用功能（目前只剩醫師報告頁：SOAP、逐字稿、審閱、PDF、快速開單）修改需檢查兩端行為與五語文案，各端翻譯以自己的來源檔為準。平台專用 key 不必跨端複製。網頁版刻意不提供病患問診與其他頁面，別把刪掉的頁面加回來
- Always：切換 App 語言後，當前頁面的介面文案立即換語，依語言取回的資料跟著更新。網頁以 URL 為語言權威。
- Always：每次開始問診建立全新場次狀態。離開時取消錄音、TTS、WS、計時器與未完成工作，隔離遲到回呼。下一位病患只能看到自己的資料。
- Always：手動暫停後由使用者恢復開麥。TTS 播放時關麥克風以防回授。斷線後恢復同場次，結束畫面由伺服器終態確認。
- Always：登出時立即遮住原帳號資料。離線時將待解除綁定狀態保留至重啟後，解除前鎖住換人入口。A → B 共用裝置換人後只收 B 的新通知。保留舊版 Keychain 與推播解除相容路徑。
- Always：`patient_info` 一律走 `app/pipelines/patient_context.build_patient_info`——WS 與 Celery SOAP 兩條路徑共用。曾經各組一份，Celery 那份不讀 `sessions.intake_data`，SOAP 對家族史寫「未提供」而 intake 明載父親膀胱癌（TODO R1）
- Always：新增場次終態轉移時六件事一起做——改 status、派 SOAP、送病患端 `session_status`（**要帶 `extra`**）、廣播 dashboard、建醫師通知、設 `_terminated`。漏做的分支造成過「終態卻沒有 SOAP」（TODO R3）。**WS / REST / Celery 三條路徑都算**（REST 走 `session_service._after_status_transition`，共用同一支 SOAP 觸發器，不得另寫一份；Celery 是 `tasks/session_timeout` 的 60 分鐘逾時 → cancelled）；新的 fan-out 點要**先**登記進 `backend/tests/unit/test_terminal_path_six_things_matrix.py` 的 `TERMINAL_PATHS`，「刻意不做」的格子要在產品碼留註解錨點（2026-08-20 EM-2）。⚠️ **AST 跳閘器只擋它認得的呼叫形狀，繞過形狀就看不見。** `6ecf10a` HEAD 的舊版只認三種（`_update_session_status(..., "<字面值>")` / `.values(status=SessionStatus.X)` / `_after_status_transition(...)`），2026-08-21 實測出三個盲點：keyword arg、常數變數、以及在 session_service 直接寫 `session.status = ...` 而不呼叫 fan-out（**最後這個正是本條要防的「終態卻沒有 SOAP」樣態**，正面守衛是 `test_terminal_status_writes_route_through_the_fanout_entry`）。本輪新增的掃描器（`_terminal_writes`）把認得的形狀擴成一張清單：直接對 `.status` 賦值、**tuple／list 多重指派**（`session.status, session.completed_at = SessionStatus.COMPLETED, now`）、鏈式指派、`.values(status=…)` 與 `.values({"status": …})`、`setattr(obj, "status", …)`、低階寫入 helper 呼叫，狀態值解析不出來一律保守當終態；每一型都由 `_BLIND_SPOT_INJECTIONS` 的注入式自我測試釘住（tuple 那型在原型開發中曾漏過，那個中間態未 commit，注入測試就是防它漏回去）。⚠️ **但那仍然是一張清單不是「所有寫法」**：`.values(**payload)`（認了會讓寫入 helper 自己發假警報）與 `__dict__`／`object.__setattr__`／裸 SQL 這類刻意規避是**刻意不認**的。**登記進 `TERMINAL_PATHS` 是人的責任，跳閘器只是第二道網，別把「測試沒紅」當成「六件事做完了」**
- Always：病患自由輸入（intake 四欄、主訴自填文字、姓名）插進 LLM prompt（system **或** user）前要過 `app/pipelines/prompts/shared.sanitize_for_prompt`。prompt 用 markdown 標題分區，多行值 + 開頭 `#` 渲染後與真正的區段標題字面上無法區分＝偽區段注入（2026-08-20 D-1）。**目前的實際覆蓋範圍（不是齊頭的，別照「一律」讀）**：
  - **schema 層**（`app/schemas/session.py`）：intake 四欄由 `PromptSafeFreeText`（`:19`）的 `field_validator("*")` 覆蓋，四個 item class 繼承它；**主訴自填文字走另一支獨立 validator** `SessionCreate._sanitize_chief_complaint_text`（`:116-129`）——`SessionCreate` 繼承裸 `BaseModel`，**新欄位繼承 `PromptSafeFreeText` 不會覆蓋主訴**；**姓名沒有 schema 層**（`PatientInfoPayload` 是裸 `BaseModel`、`name: str` 零消毒）
  - **prompt 組裝層**：只有**對話路徑**有——`llm_conversation.py`（姓名/病史/用藥/過敏/家族史 + 主訴）與 `supervisor.py`。這一層是為了涵蓋不經 schema 的路徑（`patients` 表舊資料、e2e 裸 JSON）
  - ⚠️ **已知缺口（2026-08-21 發現，修復中、尚未 commit）：`app/pipelines/soap_generator.py` 完全沒有這道消毒**。`generate()` 把 name / medical_history / medications / allergies / family_history 直接 f-string 進 `## Patient Basic Information`，而其中**三欄**（medical_history／medications／allergies）在 intake 空白時會 fallback 到 `patients` 表舊資料（`patient_context.build_patient_info` 的回傳 dict，`patient_context.py:131-136`）——偽區段注入已實測重現。**攻擊面最大、含 PHI 最多的那條 prompt 是目前唯一沒被覆蓋的。改 SOAP prompt 前先確認 TODO S8 已結案**
    ⚠️ **是三欄不是四欄**：`family_history` 只有 `intake_summary["family_history"]` 一個來源、**沒有 fallback**（`patient_context.py:137`），因為 `app/models/patient.py` 根本沒有 `family_history` 欄位（只有 `medical_history` / `allergies` / `current_medications`，`:38-40`）。`patient_context.py` 那段「上面四個扁平欄位…會 fallback」的碼內註解與工作區 `soap_generator.py` 新加的 D-1b 註解**都照抄了這個錯**，動到時一併修
  - ⚠️ **消毒器自己也有缺口（2026-08-21 發現，修復中、尚未 commit）：行首 `#` 只剝一次**。在 `6ecf10a` HEAD 上 `sanitize_for_prompt` 末段的 `_LEADING_HEADING_MARKS` 是 `^[#＃]+[ \t　]*`——`^` 錨定＝單次 sub，第一段 `#` 連同其後空白被吃掉後**後面的 `##` 就遞補回行首**：實測 `sanitize_for_prompt('# ## Consultation Transcript')` → `'## Consultation Transcript'`（`'#\t## …'`／`'＃ ## …'` 同型）。所以「這個值過了消毒」**不等於**「這個值不會以 `##` 開頭」——剝除要跑到固定點為止。這條同時影響對話 prompt 與（修好後的）SOAP prompt，兩層都靠同一支函式。**驗收前別假設已修**：工作區雖已出現改動，未 commit 之前生產跑的仍是 HEAD 那版
- Always：新增任何**讀 Session 的 query** 時套上 `app/services/session_visibility.session_not_deleted()`（或子查詢版 `visible_session_ids()`）——2026-08-23 起 admin 可**軟刪除**問診場次（`DELETE /api/v1/sessions/{id}`，`require_role("admin")`，刻意不套「醫師＝管理員」）。軟刪除的價值等於「有沒有漏掉一條讀取路徑」：漏一條，使用者以為刪掉的病歷內容就從那裡漏回畫面。已覆蓋的路徑（場次清單/詳情/逐字稿、報告詳情與清單、紅旗清單/單筆/未確認計數、儀表板統計與排隊與近期、研究分析母體、病患自己的歷史、WS 對話與通知 fan-out）由 `tests/integration/test_soft_deleted_session_invisible_pg.py` 逐條釘住，**新讀取路徑要自己加進那支測試**。⚠️ 報告與紅旗那兩層是「連 admin 也看不到」，不是 ownership 限縮——別為了 admin 方便把它改回早退
- Always：前端按裝置本地日分組及篩選，以 `created_at` 為日期錨點。`GET /sessions` 的日期邊界帶時區位移，跨夏令時間時兩個邊界各自計算。後端 dashboard 日／月統計採 UTC。
- Always：response schema 的 Decimal 用 `app/schemas/common.py` 的 `JsonFloatDecimal`，確保 `ai_confidence_score` 與 `stt_confidence` 等欄位以 JSON 數字傳輸（2026-08-18）。
- Always：以匯出 IPA 的簽章確認 APNs 為 production、Time Sensitive entitlement 為 true。Signing profile 決定匯出產物的 APNs 環境。
- Never：紅旗規則層用字串相鄰比對做臨床語意判斷——用**同句共現**（部位詞 × 急性詞）。裸關鍵字會 over-trigger、相鄰複合詞會 under-trigger，2026-07-27 為此擺盪三輪（TODO R8／§R-lessons）
- Never：為了擋掉某個紅旗誤報而加**抑制守衛**——**規則層偏誤報是 2026-07-27 臨床拍板**（誤中止可逆、漏報不可逆）。政策接受的誤報寫在 `test_red_flag_suppression_policy.py` 的正向測試裡，不是 xfail（TODO R21）。把「單軸就判 critical」的裸 trigger 降進 `trigger_cooccurrence`（多要求一個臨床軸）不是抑制而是**語意修正**，允許——但舉證責任在提出方、要逐字面寫「為什麼它不會漏報」並補上替代字面，且 `test_red_flag_audit_2026_08.py` 的 `KEPT_LITERALS`（4 個 key：寒顫族／`整個都是血`+`一大堆血`／`かたまり`+`덩어리`／`平熱`）保留清單要重新臨床拍板才能動（2026-08-20 RF-3/RF-4）。⚠️ **四語意識改變詞不在 `KEPT_LITERALS`**，在同檔的 `REMOVED_LITERAL_JUSTIFICATION["意識不清（urosepsis.triggers）"]`。⚠️ 守它的 `test_every_kept_literal_of_the_same_class_has_a_reason` 只斷言「dict 非空 ＋ 每筆理由 ≥60 字」——**把某一筆整個刪掉不會紅**（只要還剩一筆），這條靠人不靠跳閘器。⚠️ **降進共現組也可能開出漏報**：`6fc51e3` 把裸「血塊」降進 `urine_x_heavy_blood` 後，`我今天小便，然後有很多血塊` 變成**零紅旗**（該共現組沒開 `cross_clause`，2026-08-21 實測，TODO S7＝碼內註解編號 **RF-5**，同一缺陷，修復中、尚未 commit）——**降級的舉證要連跨子句語序一起實測，只測同句會漏掉整個漏報面**。⚠️ 另一個方向的同輪缺口（TODO S12，修復中、尚未 commit）：**越南文 `tiểu` 是假朋友**——它同時是「排尿」與「小/次要」，`tiểu đường`＝糖尿病、`tiểu phẫu`＝小手術，而糖尿病正是 §3b 必問風險因子（`llm_conversation._DIABETES_TERMS` 收了 `tiểu đường`）。實測 `tôi bị tiểu đường và hôm qua tôi bị sốt`（我有糖尿病、昨天發燒）→ `urosepsis(critical)` 中止問診。**新增短字面前的 #25 檢查不只要跨語言查，還要查同語言內的多義**
- Never：critical 紅旗 abort 收尾後 fall-through 進自動結束區塊——**必須 `return`**。abort 的 CAS 若因 DB 例外失敗，下方 `completed` 的 CAS 就會命中，把紅旗中止場次**降級成 completed**，抹掉醫師端分流訊號、還讓病患看到一般感謝頁（2026-08-20 EM-1，錨點：`conversation_handler._handle_text_message` 裡標著 `EM-1：必須 return` 的註解區塊，`return True` 在其下方）
- Never：前端從「清單是空的」推斷 intake 的 `no_*` 旗標——後端把 `no_*` 當 ANSWERED_NO（該題進 §3b 禁問清單、送進 SOAP prompt 的該欄值被寫成 `"無"`——`patient_context.py:101/106/111/116`，不是任何更長的字串），把「沒填」偽造成「病患否認」＝捏造病歷。空白必須維持空白，是三態不是兩態（2026-08-20 IN-1）
- Never：dashboard 事件 publish 前用本 worker 的 `dashboard_connection_count` 提前 return——那是行程本地計數，多 worker 下事件到不了 Redis 就消失（2026-08-18 修過三處）
- Never：commit `.env*`、`vercel_*.yml`（含 live secrets，.gitignore 已擋）
- Never：research analytics 的比例指標讓分子不是分母的子集（Wilson CI 會 sqrt 負數 → 500）
