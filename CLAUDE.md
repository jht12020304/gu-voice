# GU_0410 — GU Voice 泌尿科語音問診系統

院內候診 Kiosk 的語音 AI 問診系統：病患已在現場、問診完成後等看診。FastAPI + Celery 後端、React + Vite 前端、5 語言（zh-TW / en-US / ja-JP / ko-KR / vi-VN）。

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
frontend/           → React + Vite + TS，**目前的生產前端**。src/i18n/locales/ 是翻譯源頭；
                      public/locales/ 是 build 鏡像
flutter_app/        → Flutter 單一碼庫前端（web+iOS+Android），要取代 frontend/。
                      **平台定位（2026-08-22 拍板，推翻 2026-08-20 的分工）：iOS 單一 App**——候診區 kiosk iPad 跑病患語音問診，醫師/管理員用自己的裝置跑同一顆 App（角色分流），**網頁版走向除役**（React 正式站在 App 驗證完成前暫時保留，Flutter Web 停止投資）。iOS 平台閘門已拆（route_guard.dart 只剩角色守衛；拆除前先修掉 `/patients` 前綴誤中的病患越權洞——閘門拆掉後那是唯一防線）。Web 的 Vercel 管道與預覽網址仍在，僅供過渡。**醫師＝管理員（2026-08-22 拍板）**：admin 四頁與 admin API 對醫師開放（`require_role("admin","doctor")`），醫師並可從病患詳情頁代病患發起語音問診（場次記在該病患名下；後端 create_session 僅對 doctor/admin 放行任意 patient_id）。LLM 模型 2026-08-22 起為 gpt-5.6 世代，**權威在 backend/app/core/config.py**，取樣參數一律走 `sampling_kwargs`（不變式 #33，手寫 temperature= 會在 gpt-5.6 上 400）
                      iOS 有 TestFlight 內部測試發佈管道（`tool/build_ios_testflight.sh`
                      ＋ `ios/ExportOptions.plist` ＋ `tool/gen_app_icons.py`）——**2026-08-21 首顆 build
                      已上傳，TestFlight 狀態「準備測試」**，待建內部測試群組／真機安裝／推播驗證（§V8）；
                      步驟見 docs/deployment_guide.md 二、，**設定值見 docs/ios_release_settings.md**
                      assets/locales/ 是同一份翻譯的第三份拷貝，
                      切換期要與 frontend 兩份同步。已知缺口見 docs/TODO.md §G；
                      病患端非語音全流程已真跑驗畢（2026-07-27，文字代替語音，§V2）；
                      ⚠️ **麥克風／VAD 路徑仍是零實測**（§V1），別因 analyze/test 全綠就當它可用
docs/               → 現行文件（入口 docs/README.md；docs/AGENTS.md 為部署細節指南；
                      docs/archive/ 為歷史 audit 與舊規格，勿當現行讀）
scripts/            → check_translations.py、e2e_realopenai/（真 OpenAI E2E 工具，見其 README.md）
supabase/           → 本機 supabase CLI 設定（untracked）
.claude/skills/     → 專案技能（入庫，載入時機見各 skill description）
graphify-out/       → graphify 知識圖譜（untracked，可重建；graph.html 互動圖、GRAPH_REPORT.md）
```

## 常用指令

- Frontend（在 `frontend/`）：`npm run dev`、`npm run build`（tsc + vite，翻譯改動後必跑）、`npm run lint`、`npm run type-check`、`npm run test:e2e`（Playwright）、`npm run i18n:extract:check`
- Backend（在 `backend/`）：`venv/bin/pytest tests/`（unit / integration / e2e 分層）、`venv/bin/uvicorn app.main:app --reload`
- Flutter（在 `flutter_app/`）：`flutter analyze`（**info 級也 exit 1**）、`flutter test`（只跑 `test/`）、`flutter run -d chrome`。dart-define 是 `API_BASE`／`WS_BASE` 且值含 path 後綴（`/api/v1`、`/api/v1/ws`）、`KIOSK_IDLE_TIMEOUT_SECONDS`（預設 180，`0`＝停用閒置登出）。iOS simulator 與 `integration_test/`（打真後端、需真 simulator、不在 CI）用法見 `flutter_app/README.md`
- 本機全端：`docker compose up -d`（frontend :80、backend :8000、postgres :5432、redis :6379）
- 翻譯完整性：`python scripts/check_translations.py`
- 碼庫探索：`graphify query "<問題>"`／`graphify path A B`／`graphify explain <符號>`（對 `graphify-out/graph.json` 查詢，涵蓋 code＋docs；程式碼大幅改動後用 `/graphify . --update` 增量重建）

## 部署重點

**部署是手動的——merge 到 main 不會上線。** Railway 與 Vercel 的 GitHub App 雖裝在 repo 上，但 check suite 在每一次 main merge 都永遠卡在 `queued`（2026-07-26 對 #29/#30/#31/#32 逐一查證），從未真的觸發部署；歷史上所有生產部署的 `cliCaller` 都是手動 CLI。要上線必須自己跑：

- 後端：⚠️ CLI 5.41.2 起 `railway up` 一律上傳 git root（在 `backend/` 裡跑也一樣→FAILED），必須先 `git archive HEAD:backend | tar -x -C <非git臨時目錄>`，在該目錄 `railway link -p gu-voice-api -s gu-voice-app -e production && railway up --detach` → 驗 `curl <host>/api/v1/healthz/deep`（完整流程見 `docs/deployment_guide.md` 一、）
- React 前端：`cd frontend && npm run build && vercel --prod`，然後 **手動** `vercel alias set <新deployment網址> gu-voice-chuns-projects-068de742.vercel.app`（正式 alias 不會隨 --prod 自動移動）
- Flutter Web：`cd flutter_app && ./tool/build_vercel_output.sh && vercel deploy --prebuilt --prod --skip-domain --scope chuns-projects-068de742`；正式切換前照 `docs/flutter_web_cutover.md` 驗語音並保留 React rollback
- iOS TestFlight（Flutter 醫師端，只做內部測試）：`cd flutter_app && ./tool/build_ios_testflight.sh` → 產出已簽章 .ipa → 由人看過六關驗證結果後手動上傳（現行走 ASC API key ＋ `xcrun altool`，先 `--validate-app` 再 `--upload-app`；腳本刻意不代勞）。**所有設定值（Team ID、bundle ID、SKU、ExportOptions、金鑰位置、上傳指令、目前上線的 build）只留在 `docs/ios_release_settings.md`，別在其他地方重抄**；前置條件、驗收斷言、內部測試群組、90 天到期與「TestFlight 要 iOS 16+ 但本 App 目標 15.0」都在 `docs/deployment_guide.md` 二、。⚠️ 第一次跑第 5 關必定被 macOS **鑰匙圈授權對話框**擋一次（錯誤訊息會誤導成 codesign 壞了），按「允許」後 `xcodebuild -exportArchive -allowProvisioningUpdates` 即可；`flutter build ipa` export 失敗仍回 exit 0，**唯一判準是 `.ipa` 存不存在**。⚠️ 內測包打的是**生產後端**（無 staging），`report_ready` 推播 body 帶真實病患姓名且 fan-out 給全體在職醫師，測試者拿的又是真實醫師帳號（後端無 tenant/scope 隔離，登進去就讀得到全部病歷）——**加第 2 個測試人員之前先看 `docs/TODO.md` §V8 的兩條路，光遮推播文案不會降低 PHI 暴露**。`ExportOptions.plist` 的 `testFlightInternalTestingOnly=true` **已證實生效**（2026-08-21 上傳的 build 在 ASC 標「內部」），**但它擋散佈不擋資料、不是 PHI 護欄**——擋 PHI 的仍然只有「第一版只裝自己一台」這個拍板；且走 Xcode Organizer 上傳仍會整份繞過 ExportOptions

活後端域名 = `gu-voice-app-production.up.railway.app`（`api-` 是死域名）。正式 React 網址仍為 `gu-voice-chuns-projects-068de742.vercel.app`；Flutter Web 固定驗證網址為 `gu-voice-flutter-preview.vercel.app`（2026-08-17 已驗 build、78 tests、五語 deep link、CORS、病患測試登入，**實體麥克風/STT/TTS/VAD 尚待人工驗證，未通過前不得 promote**）。React rollback deployment 是 `gu-voice-ktox9rgon-chuns-projects-068de742.vercel.app`。測試登入按鈕只可使用無真實資料的 patient 帳號，禁止內嵌 doctor/admin 憑證。生產 DB = Supabase `gu-voice-prod`（ref `xobxnlvtilezridrekdm`，ap-southeast-1）；環境變數真相 = Railway。細節見 `docs/flutter_web_cutover.md`、`deploy-production` skill 與 [docs/AGENTS.md](docs/AGENTS.md)。

## 專案技能（.claude/skills/）

| Skill | 何時載入 |
|---|---|
| `voice-pipeline-invariants` | 動到問診對話流程（前端 conversationStore / ConversationPage、後端 app/pipelines/）之前 |
| `e2e-real-openai` | 需要用真 OpenAI 驗證問診行為改動時（管線/prompt 改動的合併前置條件） |
| `i18n-language-consistency` | 動到語言切換、翻譯檔、或顯示在地化資料的頁面時 |
| `deploy-production` | 部署、改部署設定、生產環境除錯（DB timeout、連線問題）時 |
| `research-analytics` | 動到 /research 分析頁或 /api/v1/research/analytics 時 |
| `ios-testflight` | 打 iOS TestFlight 包、處理簽章／上傳／內部測試群組，或動到 `flutter_app/ios/` 與打包腳本時 |
| `design-taste-frontend` | 改任何前端視覺（頁面、按鈕、配色、版面）之前——taste-skill 的反樣板規則（2026-08-22 引入；登入頁重設計與全頁面統一皆依它）。**共用元件一律用 `flutter_app/lib/shared/widgets/ui_kit.dart`**（IconTile/PillTag/GroupHeader/Empty/Error/Skeleton/StatCell/MonthStatsCard，檔頭載明兩形系統等規則），別在頁面裡手刻樣式 |

## 鐵律（Boundaries）

- Always：改 `frontend/src/i18n/locales/` 後執行 `npm run build` 重生 `public/locales/`，兩者一起 commit
- Always：改 `backend/scripts/start.sh` 後保留 executable bit（`git update-index --chmod=+x`），否則 Railway 部署失敗
- Always：動語音管線或 SOAP prompt 前先讀 `voice-pipeline-invariants`；改完跑 `e2e-real-openai` 驗證
- Always：病患面措辭用「請稍候等看診」「請告知現場醫護」——部署情境是院內 kiosk，病患已在現場，禁用含糊的「盡速就醫」
- Always：改 `frontend/src/i18n/locales/` 的 key 時，切換期要同步 `flutter_app/assets/locales/`（`check_translations.py` 不涵蓋 flutter 那份）
- Always：`flutter_app` 新增路由要用 `_lngKeyed()` 包住，否則只切語言時頁面文字不會變（`t()` 讀全域 `currentLng`，非 reactive）
- Always：`flutter_app` 的指令一律用 **`fvm flutter`**（`.fvmrc` 釘 3.41.3），不要用 PATH 上的裸 `flutter`（homebrew 3.47.0）——3.47 的 SPM 預設開，會把 `.flutter-plugins-dependencies` 翻成 `swift_package_manager_enabled=true` 並動到 `ios/Podfile.lock`。2026-08-21 為此誤判成「SPM／CocoaPods 半切換要做架構決策」，實際只是跑錯 SDK；改用 fvm 後 `pod install` 對 `Podfile.lock` 零變動
- Always：`patient_info` 一律走 `app/pipelines/patient_context.build_patient_info`——WS 與 Celery SOAP 兩條路徑共用。曾經各組一份，Celery 那份不讀 `sessions.intake_data`，SOAP 對家族史寫「未提供」而 intake 明載父親膀胱癌（TODO R1）
- Always：新增場次終態轉移時六件事一起做——改 status、派 SOAP、送病患端 `session_status`（**要帶 `extra`**）、廣播 dashboard、建醫師通知、設 `_terminated`。漏做的分支造成過「終態卻沒有 SOAP」（TODO R3）。**WS / REST / Celery 三條路徑都算**（REST 走 `session_service._after_status_transition`，共用同一支 SOAP 觸發器，不得另寫一份；Celery 是 `tasks/session_timeout` 的 60 分鐘逾時 → cancelled）；新的 fan-out 點要**先**登記進 `backend/tests/unit/test_terminal_path_six_things_matrix.py` 的 `TERMINAL_PATHS`，「刻意不做」的格子要在產品碼留註解錨點（2026-08-20 EM-2）。⚠️ **AST 跳閘器只擋它認得的呼叫形狀，繞過形狀就看不見。** `6ecf10a` HEAD 的舊版只認三種（`_update_session_status(..., "<字面值>")` / `.values(status=SessionStatus.X)` / `_after_status_transition(...)`），2026-08-21 實測出三個盲點：keyword arg、常數變數、以及在 session_service 直接寫 `session.status = ...` 而不呼叫 fan-out（**最後這個正是本條要防的「終態卻沒有 SOAP」樣態**，正面守衛是 `test_terminal_status_writes_route_through_the_fanout_entry`）。本輪新增的掃描器（`_terminal_writes`）把認得的形狀擴成一張清單：直接對 `.status` 賦值、**tuple／list 多重指派**（`session.status, session.completed_at = SessionStatus.COMPLETED, now`）、鏈式指派、`.values(status=…)` 與 `.values({"status": …})`、`setattr(obj, "status", …)`、低階寫入 helper 呼叫，狀態值解析不出來一律保守當終態；每一型都由 `_BLIND_SPOT_INJECTIONS` 的注入式自我測試釘住（tuple 那型在原型開發中曾漏過，那個中間態未 commit，注入測試就是防它漏回去）。⚠️ **但那仍然是一張清單不是「所有寫法」**：`.values(**payload)`（認了會讓寫入 helper 自己發假警報）與 `__dict__`／`object.__setattr__`／裸 SQL 這類刻意規避是**刻意不認**的。**登記進 `TERMINAL_PATHS` 是人的責任，跳閘器只是第二道網，別把「測試沒紅」當成「六件事做完了」**
- Always：病患自由輸入（intake 四欄、主訴自填文字、姓名）插進 LLM prompt（system **或** user）前要過 `app/pipelines/prompts/shared.sanitize_for_prompt`。prompt 用 markdown 標題分區，多行值 + 開頭 `#` 渲染後與真正的區段標題字面上無法區分＝偽區段注入（2026-08-20 D-1）。**目前的實際覆蓋範圍（不是齊頭的，別照「一律」讀）**：
  - **schema 層**（`app/schemas/session.py`）：intake 四欄由 `PromptSafeFreeText`（`:19`）的 `field_validator("*")` 覆蓋，四個 item class 繼承它；**主訴自填文字走另一支獨立 validator** `SessionCreate._sanitize_chief_complaint_text`（`:116-129`）——`SessionCreate` 繼承裸 `BaseModel`，**新欄位繼承 `PromptSafeFreeText` 不會覆蓋主訴**；**姓名沒有 schema 層**（`PatientInfoPayload` 是裸 `BaseModel`、`name: str` 零消毒）
  - **prompt 組裝層**：只有**對話路徑**有——`llm_conversation.py`（姓名/病史/用藥/過敏/家族史 + 主訴）與 `supervisor.py`。這一層是為了涵蓋不經 schema 的路徑（`patients` 表舊資料、e2e 裸 JSON）
  - ⚠️ **已知缺口（2026-08-21 發現，修復中、尚未 commit）：`app/pipelines/soap_generator.py` 完全沒有這道消毒**。`generate()` 把 name / medical_history / medications / allergies / family_history 直接 f-string 進 `## Patient Basic Information`，而其中**三欄**（medical_history／medications／allergies）在 intake 空白時會 fallback 到 `patients` 表舊資料（`patient_context.build_patient_info` 的回傳 dict，`patient_context.py:131-136`）——偽區段注入已實測重現。**攻擊面最大、含 PHI 最多的那條 prompt 是目前唯一沒被覆蓋的。改 SOAP prompt 前先確認 TODO S8 已結案**
    ⚠️ **是三欄不是四欄**：`family_history` 只有 `intake_summary["family_history"]` 一個來源、**沒有 fallback**（`patient_context.py:137`），因為 `app/models/patient.py` 根本沒有 `family_history` 欄位（只有 `medical_history` / `allergies` / `current_medications`，`:38-40`）。`patient_context.py` 那段「上面四個扁平欄位…會 fallback」的碼內註解與工作區 `soap_generator.py` 新加的 D-1b 註解**都照抄了這個錯**，動到時一併修
  - ⚠️ **消毒器自己也有缺口（2026-08-21 發現，修復中、尚未 commit）：行首 `#` 只剝一次**。在 `6ecf10a` HEAD 上 `sanitize_for_prompt` 末段的 `_LEADING_HEADING_MARKS` 是 `^[#＃]+[ \t　]*`——`^` 錨定＝單次 sub，第一段 `#` 連同其後空白被吃掉後**後面的 `##` 就遞補回行首**：實測 `sanitize_for_prompt('# ## Consultation Transcript')` → `'## Consultation Transcript'`（`'#\t## …'`／`'＃ ## …'` 同型）。所以「這個值過了消毒」**不等於**「這個值不會以 `##` 開頭」——剝除要跑到固定點為止。這條同時影響對話 prompt 與（修好後的）SOAP prompt，兩層都靠同一支函式。**驗收前別假設已修**：工作區雖已出現改動，未 commit 之前生產跑的仍是 HEAD 那版
- Always：response schema 的 Decimal 欄位一律用 `app/schemas/common.py` 的 `JsonFloatDecimal`——pydantic v2 預設把 Decimal 序列化成 JSON 字串，會炸掉 Flutter 端 `as num?` 解析（2026-08-18 修過 `ai_confidence_score`／`stt_confidence`）
- Never：把 `conversationControllerProvider` 從 `autoDispose` 改回長生命週期——會造成同一 kiosk 跨病患 session 污染（TODO G2）
- Never：為了「讓 TestFlight 收得到推播」去改 `flutter_app/ios/Runner/Runner.entitlements` 的 `aps-environment: development`——**改了完全沒作用**，該值由簽章時的 provisioning profile 決定（Apple TN2265），distribution profile 一律給 production，Flutter 專案躺著 `development` 是正確狀態。真因是 Apple Developer 後台的 App ID 沒勾 Push Notifications capability（症狀＝上傳吃 ITMS-90078、線上收不到推播）；驗法是對 export 出的 .ipa 跑 `codesign -d --entitlements :- <Runner.app>` 看實際簽進去的值。同理不要動 `project.pbxproj` 的 `CODE_SIGN_IDENTITY[sdk=iphoneos*]`（與 Flutter 官方 template 一字不差，automatic signing 會覆寫它）
- Never：紅旗規則層用字串相鄰比對做臨床語意判斷——用**同句共現**（部位詞 × 急性詞）。裸關鍵字會 over-trigger、相鄰複合詞會 under-trigger，2026-07-27 為此擺盪三輪（TODO R8／§R-lessons）
- Never：為了擋掉某個紅旗誤報而加**抑制守衛**——**規則層偏誤報是 2026-07-27 臨床拍板**（誤中止可逆、漏報不可逆）。政策接受的誤報寫在 `test_red_flag_suppression_policy.py` 的正向測試裡，不是 xfail（TODO R21）。把「單軸就判 critical」的裸 trigger 降進 `trigger_cooccurrence`（多要求一個臨床軸）不是抑制而是**語意修正**，允許——但舉證責任在提出方、要逐字面寫「為什麼它不會漏報」並補上替代字面，且 `test_red_flag_audit_2026_08.py` 的 `KEPT_LITERALS`（4 個 key：寒顫族／`整個都是血`+`一大堆血`／`かたまり`+`덩어리`／`平熱`）保留清單要重新臨床拍板才能動（2026-08-20 RF-3/RF-4）。⚠️ **四語意識改變詞不在 `KEPT_LITERALS`**，在同檔的 `REMOVED_LITERAL_JUSTIFICATION["意識不清（urosepsis.triggers）"]`。⚠️ 守它的 `test_every_kept_literal_of_the_same_class_has_a_reason` 只斷言「dict 非空 ＋ 每筆理由 ≥60 字」——**把某一筆整個刪掉不會紅**（只要還剩一筆），這條靠人不靠跳閘器。⚠️ **降進共現組也可能開出漏報**：`6fc51e3` 把裸「血塊」降進 `urine_x_heavy_blood` 後，`我今天小便，然後有很多血塊` 變成**零紅旗**（該共現組沒開 `cross_clause`，2026-08-21 實測，TODO S7＝碼內註解編號 **RF-5**，同一缺陷，修復中、尚未 commit）——**降級的舉證要連跨子句語序一起實測，只測同句會漏掉整個漏報面**。⚠️ 另一個方向的同輪缺口（TODO S12，修復中、尚未 commit）：**越南文 `tiểu` 是假朋友**——它同時是「排尿」與「小/次要」，`tiểu đường`＝糖尿病、`tiểu phẫu`＝小手術，而糖尿病正是 §3b 必問風險因子（`llm_conversation._DIABETES_TERMS` 收了 `tiểu đường`）。實測 `tôi bị tiểu đường và hôm qua tôi bị sốt`（我有糖尿病、昨天發燒）→ `urosepsis(critical)` 中止問診。**新增短字面前的 #25 檢查不只要跨語言查，還要查同語言內的多義**
- Never：critical 紅旗 abort 收尾後 fall-through 進自動結束區塊——**必須 `return`**。abort 的 CAS 若因 DB 例外失敗，下方 `completed` 的 CAS 就會命中，把紅旗中止場次**降級成 completed**，抹掉醫師端分流訊號、還讓病患看到一般感謝頁（2026-08-20 EM-1，錨點：`conversation_handler._handle_text_message` 裡標著 `EM-1：必須 return` 的註解區塊，`return True` 在其下方）
- Never：前端從「清單是空的」推斷 intake 的 `no_*` 旗標——後端把 `no_*` 當 ANSWERED_NO（該題進 §3b 禁問清單、送進 SOAP prompt 的該欄值被寫成 `"無"`——`patient_context.py:101/106/111/116`，不是任何更長的字串），把「沒填」偽造成「病患否認」＝捏造病歷。空白必須維持空白，是三態不是兩態（2026-08-20 IN-1，React 與 Flutter 兩份前端都修過）
- Never：dashboard 事件 publish 前用本 worker 的 `dashboard_connection_count` 提前 return——那是行程本地計數，多 worker 下事件到不了 Redis 就消失（2026-08-18 修過三處）
- Never：commit `.env*`、`vercel_*.yml`（含 live secrets，.gitignore 已擋）
- Never：用 URL 以外的來源（cookie、navigator、後端偏好）當前端語言權威
- Never：research analytics 的比例指標讓分子不是分母的子集（Wilson CI 會 sqrt 負數 → 500）
