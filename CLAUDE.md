# GU_0410 — GU Voice 泌尿科語音問診系統

院內候診 Kiosk 的語音 AI 問診系統：病患已在現場、問診完成後等看診。FastAPI + Celery 後端、React + Vite 前端、5 語言（zh-TW / en-US / ja-JP / ko-KR / vi-VN）。

## 專案結構

```
backend/            → FastAPI + Celery。app/pipelines/ 問診管線（llm_conversation、red_flag_detector、
                      supervisor、soap_generator、prompts/）、app/websocket/、alembic/ migrations
frontend/           → React + Vite + TS，**目前的生產前端**。src/i18n/locales/ 是翻譯源頭；
                      public/locales/ 是 build 鏡像
flutter_app/        → Flutter 單一碼庫前端（web+iOS+Android），要取代 frontend/。
                      **平台分工（2026-08-20 拍板）：Web＝病患語音問診（院內 kiosk）；
                      iOS＝醫師端查看報告/通知（不做語音問診）**。Web 已有
                      Vercel staged production 部署管道與固定預覽網址，但尚未 promote 為正式前端。
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

活後端域名 = `gu-voice-app-production.up.railway.app`（`api-` 是死域名）。正式 React 網址仍為 `gu-voice-chuns-projects-068de742.vercel.app`；Flutter Web 固定驗證網址為 `gu-voice-flutter-preview.vercel.app`（2026-08-17 已驗 build、78 tests、五語 deep link、CORS、病患測試登入，**實體麥克風/STT/TTS/VAD 尚待人工驗證，未通過前不得 promote**）。React rollback deployment 是 `gu-voice-ktox9rgon-chuns-projects-068de742.vercel.app`。測試登入按鈕只可使用無真實資料的 patient 帳號，禁止內嵌 doctor/admin 憑證。生產 DB = Supabase `gu-voice-prod`（ref `xobxnlvtilezridrekdm`，ap-southeast-1）；環境變數真相 = Railway。細節見 `docs/flutter_web_cutover.md`、`deploy-production` skill 與 [docs/AGENTS.md](docs/AGENTS.md)。

## 專案技能（.claude/skills/）

| Skill | 何時載入 |
|---|---|
| `voice-pipeline-invariants` | 動到問診對話流程（前端 conversationStore / ConversationPage、後端 app/pipelines/）之前 |
| `e2e-real-openai` | 需要用真 OpenAI 驗證問診行為改動時（管線/prompt 改動的合併前置條件） |
| `i18n-language-consistency` | 動到語言切換、翻譯檔、或顯示在地化資料的頁面時 |
| `deploy-production` | 部署、改部署設定、生產環境除錯（DB timeout、連線問題）時 |
| `research-analytics` | 動到 /research 分析頁或 /api/v1/research/analytics 時 |

## 鐵律（Boundaries）

- Always：改 `frontend/src/i18n/locales/` 後執行 `npm run build` 重生 `public/locales/`，兩者一起 commit
- Always：改 `backend/scripts/start.sh` 後保留 executable bit（`git update-index --chmod=+x`），否則 Railway 部署失敗
- Always：動語音管線或 SOAP prompt 前先讀 `voice-pipeline-invariants`；改完跑 `e2e-real-openai` 驗證
- Always：病患面措辭用「請稍候等看診」「請告知現場醫護」——部署情境是院內 kiosk，病患已在現場，禁用含糊的「盡速就醫」
- Always：改 `frontend/src/i18n/locales/` 的 key 時，切換期要同步 `flutter_app/assets/locales/`（`check_translations.py` 不涵蓋 flutter 那份）
- Always：`flutter_app` 新增路由要用 `_lngKeyed()` 包住，否則只切語言時頁面文字不會變（`t()` 讀全域 `currentLng`，非 reactive）
- Always：`patient_info` 一律走 `app/pipelines/patient_context.build_patient_info`——WS 與 Celery SOAP 兩條路徑共用。曾經各組一份，Celery 那份不讀 `sessions.intake_data`，SOAP 對家族史寫「未提供」而 intake 明載父親膀胱癌（TODO R1）
- Always：新增場次終態轉移時六件事一起做——改 status、派 SOAP、送病患端 `session_status`（**要帶 `extra`**）、廣播 dashboard、建醫師通知、設 `_terminated`。漏做的分支造成過「終態卻沒有 SOAP」（TODO R3）
- Always：response schema 的 Decimal 欄位一律用 `app/schemas/common.py` 的 `JsonFloatDecimal`——pydantic v2 預設把 Decimal 序列化成 JSON 字串，會炸掉 Flutter 端 `as num?` 解析（2026-08-18 修過 `ai_confidence_score`／`stt_confidence`）
- Never：把 `conversationControllerProvider` 從 `autoDispose` 改回長生命週期——會造成同一 kiosk 跨病患 session 污染（TODO G2）
- Never：紅旗規則層用字串相鄰比對做臨床語意判斷——用**同句共現**（部位詞 × 急性詞）。裸關鍵字會 over-trigger、相鄰複合詞會 under-trigger，2026-07-27 為此擺盪三輪（TODO R8／§R-lessons）
- Never：為了擋掉某個紅旗誤報而加抑制守衛——**規則層偏誤報是 2026-07-27 臨床拍板**（誤中止可逆、漏報不可逆）。政策接受的誤報寫在 `test_red_flag_suppression_policy.py` 的正向測試裡，不是 xfail（TODO R21）
- Never：dashboard 事件 publish 前用本 worker 的 `dashboard_connection_count` 提前 return——那是行程本地計數，多 worker 下事件到不了 Redis 就消失（2026-08-18 修過三處）
- Never：commit `.env*`、`vercel_*.yml`（含 live secrets，.gitignore 已擋）
- Never：用 URL 以外的來源（cookie、navigator、後端偏好）當前端語言權威
- Never：research analytics 的比例指標讓分子不是分母的子集（Wilson CI 會 sqrt 負數 → 500）
