# REFACTORING_TRACKER — 唯一進度追蹤（2026-10-24 起）

狀態：PENDING／IN_PROGRESS／TESTING／DONE／BLOCKED／UNVERIFIED／NOT_APPLICABLE。
驗收通則（適用每一項）：修改後跑該區域完整套件（backend：`pytest tests` + ruff F 規則；frontend：lint／type-check／`npm test`／build／Playwright；flutter：`fvm flutter analyze`／`fvm flutter test`）；OpenAPI 契約快照測試必須維持綠（或在 commit message 說明為何刻意更新）。每項的 file:line 證據見 `evidence/audit_*.md`。
授權邊界（直接標 BLOCKED）：正式資料／不可逆操作／部署／重要對外 API 契約／權限驗證安全政策／無法確認是否使用的功能／付費外部服務（含真 OpenAI e2e）。

## Backend

| ID | 問題 | 檔案 | 風險/優先 | 修法 | 驗收標準 | 測試 | 狀態 | 結果 |
|---|---|---|---|---|---|---|---|---|
| B01 | 46 個未用 import／dead binding | app/、tests/ | 低/高 | 逐一驗證後移除；2 個測試用 re-export 加 noqa | ruff F401/F841 = 0、全套綠 | pytest tests | DONE | 4,922 綠；ruff 0 |
| B02 | 13 個無呼叫者符號 | exceptions/openai_client/tts_pipeline/alert_service/complaint_service/connection_manager/schemas.auth/conversation_handler | 低/高 | 刪除 | grep 零引用、全套綠 | pytest | DONE | 243 行刪除 |
| B03 | 無讀取者 Settings 欄位 ×4 | core/config.py、.env.example | 低/中 | 刪除並註明 shell 變數 | config 測試綠 | pytest | DONE | |
| B04 | 逾時任務漏 `session_not_deleted()`（鐵律違反） | tasks/session_timeout.py:105 | 中/高 | 加過濾 | 軟刪場次不被取消、不廣播 | 新 unit + integration（真 PG） | DONE | 先紅後綠 |
| B05 | WeasyPrint 同步阻塞 event loop | services/report_service.py:740 | 高/高 | to_thread + 鎖 | PDF 期間 /health < 150 ms | test_report_pdf_offloop + 實測 | DONE | 956 → ≤142 ms |
| B06 | `BLACKLIST_KEY_PREFIX` 定義兩處 | core/dependencies.py、services/auth_service.py | 中/高 | 單一來源 | AST 測試 | 新測試 | DONE | |
| B07 | admin 同步 bcrypt ×2 | services/admin_service.py:128,293 | 中/中 | to_thread | 全套綠 | pytest | DONE | 未另量測 |
| B08 | 每則 dashboard 事件新開 Redis 連線 | websocket/connection_manager.py、cache/redis_client.py | 中/中 | loop-aware 池重用 | 同 loop 用池、異 loop 短命 client | 新測試 ×2 + microbench | DONE | 0.73 → 0.21 ms |
| B09 | 在職臨床人員查詢重複兩份 | conversation_handler._notify_doctors_red_flag | 中/中 | 共用 `_doctor_targets` | 相關 4 測試檔綠 | pytest | DONE | |
| B10 | alembic SSL 看 DB_HOST | alembic/env.py:37 | 中/中 | 解析 DATABASE_URL host | pooler URL → SSL | `alembic current` + 表達式驗算 | DONE | 生產 URL 未實跑（UNVERIFIED 面） |
| B11 | `tests/integration` 不在 CI | .github/workflows/ci.yml | 中/高 | 加 `alembic upgrade head` + `pytest tests/integration` 步驟 | 本機以全新 PG 容器模擬 CI 流程通過 | 本機模擬 | DONE | ci.yml 加 `alembic upgrade head` + `pytest tests/integration`（TEST_DATABASE_URL）；本機以全新 postgres:15 容器模擬：migrations + 13 integration 綠。GitHub 上首跑＝UNVERIFIED |
| B12 | 17 條兩端未呼叫路由 | routers/{dashboard,alerts,notifications,patients,complaints,reports,audit_logs}.py | 中/中 | 刪路由+service | 契約快照刻意更新 | — | BLOCKED | 對外 API 契約，需授權 |
| B13 | keyset cursor 述詞複製 ×6 | report/alert/notification/admin/patient services vs session_service._apply_cursor_keyset | 中/中 | 抽到 utils/pagination、參數化 id 欄 | 分頁測試 + smoothness integration 綠 | pytest + integration | DONE | `utils/pagination.keyset_after()`；session/report/alert×2/notification/admin/patient×2 共 8 處改走；4,926 綠 |
| B14 | `has_more/next_cursor` 收尾 ×11 | 同上 | 低/低 | `page_slice()` helper | 同上 | 同上 | DONE | `page_slice()` 取代 11 處收尾；next_cursor 一致 |
| B15 | `REDIS_KEY_PREFIX` 只有 3/20 key 遵守；`conversation_handler.py:53-54` 硬編 | 多檔 | 高/中 | 一律套或拆掉設定 | — | — | BLOCKED | 改 key 名會讓生產既有黑名單／限流 key 失效＝安全政策影響；需確認 Railway 的 REDIS_KEY_PREFIX 值 |
| B16 | 未讀通知 cache key 字面 ×2 | notification_service.py:496,799 | 低/低 | 常數 | 全套綠 | pytest | DONE | `_unread_cache_key()` |
| B17 | dashboard stats cache key 形狀不一致（handler vs service） | dashboard_handler.py:32 vs dashboard_service.py:237 | 中/中 | 查證生產者/消費者；共用常數或修失效 | 失效路徑有測試 | pytest | NOT_APPLICABLE | handler key `gu:dashboard:stats:{doctor_id}` 落在 service 失效 glob `gu:dashboard:stats:*` 之內，失效已覆蓋；形狀不同但無漏失效 |
| B18 | 授權編排 ×3 重複 | session/report/patient services | 中/低 | 抽 `patient_owned_by()` 到 authz | authz 測試綠 | pytest | DONE | `core/authz.patient_owned_by()` 取代 session／report 兩份病患擁有權查詢；authz 測試 46 綠；三支編排刻意不整併（report 拋 NotFound、軟刪除先於 admin 早退） |
| B19 | 一行 wrapper／alias（`_is_admin`、`_doctor_scope_id`、`_get_user_role` ×4、`_extract_client_ip` ×2） | 多檔 | 低/低 | 直接呼叫 authz／net | 全套綠 | pytest | DONE | `_doctor_scope_id`、4 個 `_get_user_role` alias、2 個 `_extract_client_ip` 移除；`_is_admin` 保留（`test_auth_service_security` 直接釘它的真值表，刪了＝弱化測試） |
| B20 | UUID 轉型 ×4 | middleware/notification/admin/auth services | 低/低 | `utils.pagination.parse_cursor`／一個 `coerce_uuid` | 全套綠 | pytest | DONE | `utils.pagination.coerce_uuid`；middleware／notification／admin 改用；auth reset-token 路徑語意不同保留 |
| B21 | 健康探針 ×2 | main.py:330 vs admin_service.py:357 | 低/低 | main 重用 admin 探針 | health 測試綠 | pytest | DONE | `core/health.py` probe_db/probe_redis；main.py 與 admin_service 共用；health 測試綠 |
| B22 | `_validate_language` 與 `_validate_to_language` 同體 | schemas/session.py | 低/低 | 模組層 validator fn | schema 測試綠 | pytest | DONE | `_validated_supported_language()` |
| B23 | 錯誤回應語言忽略 `?lng`/`X-Language` | core/exceptions.py:297 | 中/中 | 先用 `request.state.language` | 新測試：帶 X-Language 的 4xx body 語言 | pytest | DONE | 優先 `request.state.language`；新測試 2 案 |
| B24 | `i18n_messages._resolve_lang` 忽略 disabled languages | utils/i18n_messages.py:1076 | 低 | — | — | — | NOT_APPLICABLE | 錯誤文案仍應在地化，與 kill-switch 語意無衝突 |
| B25 | `datetime.now(timezone.utc)` 散落 12 處 | conversation/dashboard handlers 等 | 低/低 | `utc_now()` | 全套綠 | pytest | DONE | 12 處改 `utc_now()` |
| B26 | `enums.SupportedLanguage` 與 `LANGUAGE_MAP` 重複 | models/enums.py、scripts/tests/test_locale_lists_in_sync.py | 低/低 | 測試改讀 LANGUAGE_MAP 後刪 enum | scripts tests 綠 | pytest scripts/tests | DONE | scripts 測試改讀 `LANGUAGE_MAP`；enum 刪除；scripts/tests 21 綠 |
| B27 | `risk_factor_intake_field` 只有測試用 | pipelines/llm_conversation.py:545 | 低/低 | 移進測試檔 | 該測試綠 | pytest | DONE | helper 搬進 `test_intake_risk_coverage.py` |
| B28 | `stt_partial` 只在 docstring | connection_manager.py:490 | 低 | 刪字 | — | — | DONE | |
| B29 | redis `close()` deprecation | cache/redis_client.py | 低 | aclose | 無 warning | pytest -W | DONE | |
| B30 | 通知 fan-out N+1（每位醫師 2 round trip） | notification_service.py:194-270、conversation_handler | 中/中 | 一次查 preferred_language + 批次建立 | SQL 語句數以事件計數器量測前後 | 新測試計 statement | DONE | `_preferred_languages()` 一次查；新測試釘「語言查詢 = 1 次」（N=5）；既有 push dispatch 16 案的假 DB 序列同步改成批次形狀 |
| B31 | `/dashboard/queue` 無 LIMIT | dashboard_service.py:393 | 中/中 | `.limit(50)` 對齊 WS 版 | 契約不變、測試綠 | pytest | DONE | `.limit(50)` 對齊 WS 版；契約快照不變 |
| B32 | `/research/analytics` 無日期過濾、拉全部 JSONB | research_service.py:257-374 | 中/中 | 預設時間窗＝契約變更 | — | — | BLOCKED | 需決定預設窗口（API 語意）；本機 17 場次無法量測 |
| B33 | 無索引：`sessions(status, created_at)`、`red_flag_alerts(acknowledged_by IS NULL)` | alembic/versions | 中/高 | 新 migration（CONCURRENTLY） | 本機 10k 列 EXPLAIN 前後 | 真 PG | DONE | migration `audit_20261024_idx`（CONCURRENTLY + INVALID 自癒）；100k 列：queue 5.65→1.08 ms、今日計數 4.72→1.05 ms；alert partial index 低待確認比時 0.20→0.05 ms、33% 待確認時無變化（見 evidence/perf_backend_round2） |
| B34 | `func.date(created_at) == today` 不可用索引 | dashboard_handler.py:521-538、dashboard_service.py:551-565 | 中/中 | 改範圍述詞（語意相同） | 既有 dashboard 測試綠 + EXPLAIN | pytest + 真 PG | DONE | `func.date()` 改範圍述詞 + `acknowledged_by`；舊式 6.6 ms 不吃索引、新式 1.05 ms |
| B35 | Celery `run_async` 每 task 新 loop/engine | tasks/__init__.py:63 | 中/低 | — | — | — | BLOCKED | 需 Celery worker + pooler 連線數觀測環境；設計已文件化 |
| B36 | 歷史 JSON 每輪整包重寫、問候 TTS 逐句 | conversation_handler | 低 | — | — | — | NOT_APPLICABLE | KB 級、語音路徑；收益小於 e2e 驗證成本 |
| B37 | `_handle_text_message` 1,202 行／CC 81、紅旗規則層／SOAP 複雜度 | conversation_handler、red_flag_detector、soap_generator | 高 | 拆分 | 真 OpenAI e2e | — | BLOCKED | 受 AST 跳閘器與臨床拍板保護；驗收需付費 e2e |
| B38 | `ResearchService._assemble` CC 104 | services/research_service.py:392 | 中/低 | 拆子函式 | research 測試綠 | pytest | DONE | `_assemble` 拆成 8 個模組層 `_*_section`；最高 CC 104 → 21；research 測試 21 綠 |
| B39 | Dockerfile 3.11 vs CI/venv 3.12 | backend/Dockerfile | 中/中 | 改 3.12-slim，本機 docker build | build 成功、容器 /health 200 | docker | UNVERIFIED | Dockerfile 3.11→3.12-slim；本機 `docker build` 成功、容器內 `import app.main` OK（3.12.15）；未在 Railway 實跑 |
| B40 | railway worker/beat 套件描述未部署拓樸 | railway-*.toml、start_*.sh、docs/railway_celery_runbook.md | 低 | 留作拆分套件 | — | — | NOT_APPLICABLE | 四檔+runbook 一起保留，TODO.md:209 更正（B42） |
| B41 | compose `APP_DEBUG` 非 Settings 欄位；docs `APP_LOG_LEVEL` 不存在 | docker-compose.yml:52、docs/system_overview.md:295 | 低 | 刪／改 | — | — | DONE | compose 移除 `APP_DEBUG`；docs `APP_LOG_LEVEL` 移除 |
| B42 | `docs/TODO.md:209` 說 toml「可能需要建立」（已存在） | docs/TODO.md | 低 | 改字 | — | — | NOT_APPLICABLE | 工作區 TODO.md 已無該句（WIP 已改） |
| B43 | 兩個 e2e-results 相依 skip 在 CI 永遠 skip | test_red_flag_cooccurrence_coverage.py:740,799 | 低 | 記錄 | — | — | NOT_APPLICABLE | 反抄襲檢查需真逐字稿；文件已說明 |
| B44 | `test_red_flag_detector_shared.py` 疑似重疊 | tests/unit/pipelines | 低 | 比對 | — | — | NOT_APPLICABLE | 7 個測試全是「detector 的 fallback rules／語意 prompt 必須從 URO_RED_FLAGS 生成」的漂移守衛；test_shared_prompts 測的是 catalogue 本身形狀，無重疊 |
| B45 | 病患自助註冊照存 `license_number` | services/auth_service.py:register | 中 | 非 admin 忽略 | — | — | BLOCKED | 驗證／權限政策變更 |
| B46 | 首次 PDF 後 RSS +550 MB 常駐 | services/report_service.py | 高/中 | render 改 process pool（可回收 child） | API 行程 RSS 在 PDF 後維持 <250 MB；PDF 時間可比 | 實測 RSS + offloop 測試 | DONE | render 改單 worker `ProcessPoolExecutor`（spawn，每 20 份回收）；實測 API 行程 25 份 PDF 後 RSS 168 MB（原 719 MB）、PDF 期間 /health 1.3–1.8 ms（thread 版 100–140、原 956）、首份 +0.5 s 子行程冷啟、後續 1.2 s 不變；測試可 `set_pdf_executor()` 換 thread |
| B47 | `AsyncOpenAI` singleton 從不關閉 | core/openai_client.py | 低 | — | — | — | NOT_APPLICABLE | 行程結束即釋放；reset 函式已刪 |
| B48 | 三處讀 Session 無可見性過濾（alert push、CAS miss 重讀、report-ready） | alert_service.py:398、session_service.py:418、report_queue.py:206 | 低/中 | 加 `session_not_deleted()`（CAS 重讀除外） | 全套綠 | pytest | DONE | alert push 路徑與 report-ready 讀取補 `session_not_deleted()`；CAS 重讀刻意不加 |

## Frontend

| ID | 問題 | 檔案 | 風險/優先 | 修法 | 驗收標準 | 測試 | 狀態 | 結果 |
|---|---|---|---|---|---|---|---|---|
| F01 | 35 個未用 export + 13 DTO | services/api、types、utils、i18n、sentry | 低/高 | 刪 | lint/tsc/test/build | 全部 | DONE | |
| F02 | `utils/validation.ts` 整檔無人用 | utils | 低 | 刪 | 同上 | | DONE | |
| F03 | 9 個未用 alias（含不存在目錄、`@types` 衝突）、stale include | tsconfig.json、vite.config.ts | 低 | 刪 | build | | DONE | |
| F04 | `uuid` 依賴單一用途 | services/websocket.ts | 低 | `crypto.randomUUID` | tests | | DONE | |
| F05 | `@eslint/js`／`playwright` 只靠 transitive | package.json、scripts/verify | 低 | 顯性 devDep／改 import | lint、腳本可跑 | | DONE | |
| F06 | i18n 開機語言與 URL 不一致造成雙載 | i18n/index.ts | 中/高 | `lng` 由路徑決定 | 冷啟動 locale 請求 | locale_requests.mjs | DONE | 20/30 → 10 |
| F07 | logo.png 1.08 MB | public/logo.png | 低/高 | 256 px | 服務端 bytes | curl | DONE | → 86 KB |
| F08 | ThemeToggle／ReportListPage 整店訂閱、PatientListPage 無 memo | 3 檔 | 低/中 | selector／useShallow／useMemo | 全綠 + e2e | | DONE | render 次數未量 |
| F09 | 其餘 9 處整店訂閱 | LoginPage:14、SettingsPage:15,25、AlertListPage:142、NotificationPage:40、SOAPReportPage:175、PatientSettingsPage:24、SessionCompletePage:49、SelectComplaintPage:138 | 低/中 | useShallow | 全綠 + e2e | DONE | 9 處 + PatientListPage 改 `useShallow`；全店訂閱歸零（grep）；render 次數未量 |
| F10 | `ChatBubble` 未 memo、每 token 重建全部泡泡；289 行 WS effect | ConversationPage.tsx | 中 | memo + 拆 hook | 真 OpenAI e2e | — | BLOCKED | 語音路徑：規則要求 `voice-pipeline-invariants` + 付費 e2e 驗證 |
| F11 | 17 個 WS payload 型別無人用（handler 用 inline cast） | types/websocket.ts、DoctorAlertPoller、useWebSocket | 低/低 | handler 改用型別 | tsc | NOT_APPLICABLE | 未執行：型別化 handler 需改 `websocket.ts` 的 `on()` 泛型（語音路徑邊界）；型別保留作契約文件 |
| F12 | 本地日期 key ×4、日標籤 ×2、月區間 ×3、硬編 `'yyyy 年 M 月'` | ReportListPage、AlertListPage、PatientListPage、AuditLogsPage、patientListStore、utils/date.ts | 中/中 | `utils/date.ts` 統一；月標籤走 i18n | 新 node 測試 + e2e | npm test | DONE | `utils/date.ts` 統一 7 個 helper；月標籤走 i18n；新 node 測試 16 斷言 |
| F13 | 狀態標籤表 ×6、嚴重度 ×3 | 多檔 | 低/中 | 一個 `sessionStatusLabel()` + StatusBadge | tsc + e2e | DONE | `utils/sessionStatus.ts` + StatusBadge；AlertItem.severity 強型別（F41）；統一後 `in_progress` 文案三處一致為「對話中」；騰出 3 組舊 key 待下次清 |
| F14 | 密碼／email 驗證 ×3 | Register/Reset/ForgotPassword | 低/低 | `passwordStrengthError(pw,t)` | node 測試 | DONE | `passwordStrengthError/emailFormatError` + 12 斷言 |
| F15 | Header 與 PatientLayout 使用者選單重複 65 行 | layout/ | 低/低 | `<UserMenu/>` | e2e + build | DONE | `UserMenu.tsx`；Header 124→80、PatientLayout 120→81 行 |
| F16 | LanguageSwitcher 內嵌 click-outside；Research 頁手刻 debounce | 2 檔 | 低/低 | 用既有 hook／coalesceRefresh | tsc + e2e | DONE | |
| F17 | 78 個 catch 各自處理錯誤，無共用 `getErrorMessage` | screens/stores | 中/中 | `apiErrorMessage(err,t)`，逐頁套用 | tsc + e2e | DONE | `apiErrorMessage()`；80 個 catch 中 45 個改走（26 screens + 19 stores）、35 個刻意不改（13 在 ConversationPage 邊界、22 個設計上不顯示訊息）；store fallback 字串仍硬編 zh（既有缺口） |
| F18 | 語言狀態三處來源（settingsStore.language 持久化） | settingsStore、LanguageSwitcher、LanguageLayout | 中/中 | 以 URL 派生、停止持久化 | e2e i18n spec | DONE | `settingsStore.language` 移除（persist v1 migrate 清舊值）；切換器只導航；i18n e2e 綠 |
| F19 | Sentry 在 prod bundle 為 0 bytes（DSN 未設）；若設了會進 index chunk | services/sentry.ts、Vercel env | 中 | 動態 import（可做）；DSN 決定（BLOCKED） | build 後 chunk 檢查 | DONE | 動態 import + `vendor-sentry` chunk：設 DSN 時 SDK 360 KB 不進 index；DSN/Vercel 決定仍 BLOCKED |
| F20 | LanguageDetector 與 URL 權威衝突 | i18n/index.ts | 低 | — | — | — | NOT_APPLICABLE | F06 後 detector 只在無前綴路徑生效 |
| F21 | `date-fns` 只用 4 個函式（20 KB chunk） | patientListStore、PatientListPage、DashboardPage | 低/中 | Intl 取代並移除依賴 | build chunk 大小前後 | DONE | `date-fns` 移除；全 JS gz 212,524 → 207,005 B（−5.3 KB），20 KB `format-*` chunk 消失 |
| F22 | prettier 無 config、不在 CI | package.json | 低 | — | — | — | NOT_APPLICABLE | 手動工具，保留 |
| F23 | mock mode 散在 17 檔 ≈560 行 | screens/stores | 中/低 | 集中到 api 邊界 | Playwright | BLOCKED | 需決定引入 MSW（新依賴）或自建 api 邊界 mock adapter；production 已 tree-shake 為零成本，e2e 現有 16 spec 依賴目前 mock 形狀 |
| F24 | 10 個 namespace 全預載 | i18n/index.ts | 中 | 只預載 common | — | — | NOT_APPLICABLE | 110 處跨 namespace `t('admin:…')` 在只宣告 common 的元件內，lazy 會露 key |
| F25 | 6 個 Google Font family 對每種語言全載 | index.html:14-17 | 低/中 | 依 lng 動態插入 CJK family | 字型請求數前後 | locale_requests 變體 | DONE | CJK 字型依 URL 語言注入；css2 payload en-US 344 KB→8 KB、ja/zh −211/−221 KB；請求數不變（瀏覽器本就只抓命中的 woff2 切片） |
| F26 | `ConversationPage` 1,405 行單元件 | screens/patient | 高 | 拆 | 付費 e2e | — | BLOCKED | 同 F10 |
| F27 | PatientListPage 每次 render 分組 | — | — | — | — | — | DONE | 併入 F08 |
| F28 | `DoctorAlertPoller.seen` 無上限、每次 beep 新 AudioContext、KioskIdleGuard mousemove 未節流、useInfiniteScroll observer 重建 | 4 檔 | 低/低 | 上限／重用／節流 | tsc + e2e | DONE | seen 上限 500、單一 AudioContext、arm 1 s 節流、observer 不重建 |
| F29 | CSP `unsafe-eval` | vercel.json | 中 | 收緊 | — | — | BLOCKED | 正式部署設定，本機無法驗 header |
| F30 | `.env.production` 入庫 | frontend/.env.production | 中 | `git rm --cached` | — | — | BLOCKED | 需確認 Vercel env |
| F31 | `vite.config.d.ts` 每次 build 重生 | tsconfig.node.json | 低 | — | — | — | NOT_APPLICABLE | `tsc -b` references 需 composite；已 ignore |
| F32 | CI Node 22 vs `@types/node` 26 | package.json | 低 | — | — | — | NOT_APPLICABLE | 降版型別＝依賴變更；engines 已釘 ≥22.17 |
| F33 | `vite-env.d.ts` 缺 2 個變數宣告 | src/vite-env.d.ts | 低 | 補 | tsc | DONE | |
| F34 | Dockerfile 處理不存在的 pnpm/yarn lockfile | frontend/Dockerfile | 低 | 簡化為 npm ci | docker build | DONE | docker build 成功 |
| F35 | `frontend/DESIGN.md` 無人引用 | docs/README.md | 低 | 索引並標示狀態 | — | — | DONE | docs/README.md 索引並標示與 docs/DESIGN.md 的關係 |
| F36 | 16 個無引用翻譯 key（common 11、conversation 5） | i18n/locales ×5 + public 鏡像 | 低/低 | 逐 key grep 後刪、rebuild 鏡像 | check_translations + extract check | DONE | 16 key × 5 locale 逐一證死後刪；鏡像重生；兩種檢查 PASS |
| F37 | 醫師／管理流程零自動化 UI 測試 | tests/e2e | 中/高 | mock-mode Playwright：login→dashboard→reports→detail、alerts acknowledge、admin users | 新 spec 綠 | playwright | DONE | 3 個 mock dev server/project；新增 doctor_flows（3）與 admin_users（1）spec；Playwright 16/16 |
| F38 | smoothness 腳本未接 npm script | package.json | 低 | `verify:smoothness` | 腳本可跑 | DONE | `verify:smoothness(:perf)` + `with-preview.mjs`；browser 版實跑 exit 0，perf 版未跑（UNVERIFIED 執行） |
| F39 | `createScriptProcessor` 已棄用 | services/audioStream.ts | 中 | AudioWorklet | 真機 | — | BLOCKED | 需裝置驗證（語音路徑） |
| F40 | favicon 用 1 MB PNG | index.html | — | — | — | — | DONE | 併入 F07 |
| F41 | `AlertItem.severity: string` 弱型別 | components/dashboard/AlertItem.tsx:15 | 低 | `AlertSeverity` | tsc | DONE | 併入 F13 |

## Flutter

| ID | 問題 | 檔案 | 風險/優先 | 修法 | 驗收標準 | 測試 | 狀態 | 結果 |
|---|---|---|---|---|---|---|---|---|
| D01 | `cupertino_icons`、`path_provider` 零使用 | pubspec.yaml | 低 | 移除 | analyze/test | | DONE | lock −9 行 |
| D02 | `sessions_api.getSessionsPage` 手刻分頁 | data/api/sessions_api.dart | 低 | parsePage | test | | DONE | |
| D03 | 三處過時註解 | pubspec、ios_doctor_app_test、test_driver | 低 | 改字 | — | | DONE | |
| D04 | `permission_handler` 零 Dart 使用但 pod 在 lock | pubspec、ios/Podfile.lock | 中/低 | scratch 複本驗 `pod install` 差異後移除 | 只有 permission_handler 行離開 lock；test 321 | pod install | DONE | scratch 複本 `pod install` 驗證後套用；Podfile.lock 只少 4 個 `permission_handler_apple` hunk、pbxproj 無變動；pubspec.lock 少 6 個套件塊 |
| D05 | `intl: any` | pubspec | 低 | 釘 ^0.20.2 | pub get 無變動 | DONE | `intl: ^0.20.2`，lock 無變動 |
| D06 | 請求序號／stale 守衛手寫 12 份 | alerts/notifications/sessions controllers + 4 頁 | 中/中 | 共用 helper | notifications_ws_refresh + smoothness 測試綠 | test | DONE | `request_seq.dart`（RequestSeq + bindWsEvents）取代 9 個計數器與 3 組 ws.on/off 迴圈；debounce 兩種語意刻意不合併 |
| D07 | 無限捲動 listener ×6、ChoiceChip 列 ×4、分組清單 ×2、對話泡泡 ×3、microtask 啟動 ×4 | 多頁 | 低/中 | ui_kit helper | analyze/test | DONE | ui_kit：`onNearEnd` ×6、`FilterChipBar` ×4、`GroupedListView` ×2；對話泡泡兩份視覺不同不合併 |
| D08 | 本地日兩份實作 | session_calendar_view vs shared/format.localDayKey | 低/中 | 一份 | session_calendar_test 21 + DST | test | DONE | `format.localDay()` 單一實作；DST 21 綠 |
| D09 | JSON 解析 helper ×5 | data/models | 低 | — | — | — | NOT_APPLICABLE | 非常低價值 |
| D10 | `user_management_page:188` 直接 SnackBar | admin | 低 | showToast | analyze | DONE | |
| D11 | 清單頁整狀態 `ref.watch` ×3 | notification/alert/session list | 低 | select | — | — | NOT_APPLICABLE | 頁面本就讀幾乎全部欄位；對話頁狀態列屬語音路徑（BLOCKED） |
| D12 | `session_list_page` `ListView(children:)` | doctor/screens | 低 | builder | test | DONE | |
| D13 | 每 frame `Int16List` 手動複製 | voice/services/audio_stream_service.dart | 低 | view | 真機 | — | BLOCKED | 語音路徑 |
| D14 | WAV 編碼在主 isolate | 同上 | 中 | 真機量測 | — | — | BLOCKED | 需真機 |
| D15 | `getReportBySession` 兩趟 × 輪詢 | reports_api、session_complete_page | 中 | 需新後端端點 | — | — | BLOCKED | API 契約新增 |
| D16 | `google_fonts` 執行期抓字型 | core/theme | 中 | 內建 Inter 或移除 | — | — | BLOCKED | 產品決定 + 1.3 MB 資產 |
| D17 | Firebase init 在首個 post-frame | doctor_push_watcher.dart:40 | 低 | 延後 1–2 s | push_service_test 28 | test | DONE | 延後 1.5 s；push_service_test 28 綠 |
| D18 | LaunchScreen 白底 | ios/Runner/Base.lproj | 低 | dark variant | Xcode | — | BLOCKED | 需 Xcode／真機驗 |
| D19 | `prefer_const_constructors` 等未啟用 | analysis_options.yaml | 低/中 | 啟用 + `dart fix --apply` | analyze 0、test 321 | DONE | 3 條 const lint 啟用；dart fix 13 處/9 檔；analyze 0 |
| D20 | 3 個 integration test 無文件引用 | README | 低 | 記入 README | — | DONE | README 記載三支 integration test 與跑法（未執行，需 simulator） |
| D21 | `voice_encode_benchmark.dart` 無人引用 | docs/perf_audit | 低 | perf 文件引用 | — | DONE | perf 文件引用 benchmark 工具 |
| D22 | 305 個翻譯 key 無引用 | assets/locales ×5 | 中/低 | 先刪 spot-verified 子集 | check_translations + test | DONE | 刪 9 個子樹＝69 key×5 locale；其餘 ~236 個未引用 key 留 UNVERIFIED |
| D23 | `medical_info_page.build` 179 行、`login_page.build` 252 行 | 2 頁 | 中/低 | 抽 section widget | medical_info_family_test；login 需先補 widget smoke test | test | DONE | medical_info `_patientSection`；login 先補 widget smoke test（2 案）再拆 `_Hero/_LoginForm/_TestFillButtons`（build 252→90 行） |
| D24 | 日曆 `_dayCell/_sessionRow` 深巢狀 | session_calendar_view | 低 | 抽 const widget | calendar tests 27 | test | DONE | `_DayCell`/`_SessionRow`；calendar 21+6+DST 21 綠 |
| D25 | `_grouped()` 每 build 重算 | alert_list/patient_list | 低 | — | — | — | NOT_APPLICABLE | ≤ 一頁筆數 |

## Repo／docs／CI

| ID | 問題 | 檔案 | 風險/優先 | 修法 | 驗收標準 | 狀態 | 結果 |
|---|---|---|---|---|---|---|---|
| R01 | 226+29 檔 WIP 未提交 | — | 高 | 6-commit 切法 | — | BLOCKED | 使用者規則 |
| R02 | 2026-10-10 的 35 項品質修正零文件 | docs/TODO.md | 中 | 寫入 TODO.md | — | DONE | docs/TODO.md 新增「2026-10-10 程式品質修正」段落（含行為變更清單） |
| R03 | `.env.production` 入庫 | frontend | 中 | — | — | BLOCKED | 同 F30 |
| R04 | 5.4 GB 可重建快取 | flutter_app/build、.dart_tool | 低 | — | — | BLOCKED | 使用者決定 |
| R05 | Dockerfile Python 版本 | backend/Dockerfile | — | — | — | — | 見 B39 |
| R06 | 過時敘述：auto-deploy、e2e 佔位、supabase/、§U15 | system_overview、CLAUDE.md | 低 | 改 | — | DONE | |
| R07 | `docs/DESIGN.md` 重複 | design_references | 低 | 刪一份 | — | DONE | |
| R08 | CI 死 placeholder、CSP Supabase 來源 | ci.yml、vercel.json | 低 | 刪 | — | DONE | |
| R09 | `perf_audit_2026-08-22.md` 檔名與內容日期不符 | docs | 低 | — | — | NOT_APPLICABLE | 6 個入站連結 + CLAUDE.md 指向，改名風險 > 收益 |
| R10 | `docs/TODO.md` 2,388 行 | docs | 低 | — | — | NOT_APPLICABLE | §R／§S 等被 CLAUDE.md 以章節引用，搬移會斷引用 |
| R11 | `driver.py` 5.4k 行單檔 | scripts/e2e_realopenai | 中 | 拆 package | 真 OpenAI | BLOCKED | 驗證需付費 e2e |
| R12 | `scripts/e2e_realopenai/README.md:24` 死路徑 | docs | 低 | 改 | — | DONE | |
| R13 | `supabase_rls_policies.sql` 未索引 | docs/README.md | 低 | 加列 | — | DONE | |
| R14 | `docs/AGENTS.md` 與根 `AGENTS.md` 同名 | docs | 低 | — | — | NOT_APPLICABLE | 改名 churn |
| R15 | `.codex/skills/graphify` vendored | .codex | 低 | — | — | BLOCKED | 工具鏈決定 |
| R16 | e2e-playwright 首次在 GitHub 跑 | CI | — | — | — | UNVERIFIED | 無法在本機跑 GitHub Actions |
| R17 | migration CONCURRENTLY 重試冪等 | alembic/versions/20261003_1600 | 中 | 檢查 IF NOT EXISTS／INVALID 處理 | 本機重跑 upgrade 兩次 | DONE | 兩支 CONCURRENTLY migration 都加 pg_index 有效性檢查；drill：INVALID → 重建 valid=true；重跑 upgrade 無動作 |
| R18 | requirements.txt 刪 5 套件的 transitive 影響 | backend/requirements.txt | 中 | 全新 venv `pip check` + import app | pip check 0 問題 | DONE | 全新 venv：`pip check` 117 套件相容、166 tests 綠 |
| R19 | `useDashboardConnection` 是否掛在每個需要的 layout | frontend/src | 低 | grep 驗證 | — | NOT_APPLICABLE | 驗證：`useDashboardConnection` 掛在 MainLayout，所有 dashboard 事件消費者都在其下；無需修改 |
| R20 | compose `APP_DEBUG` | docker-compose.yml | 低 | 刪 | — | DONE | 同 B41 |
| R21 | 整合測試不在 CI | ci.yml | — | — | — | — | 見 B11 |

## 進度摘要（每次更新）
- 2026-10-24 00:30：Backend 10 DONE／Frontend 9 DONE／Flutter 3 DONE／Repo 3 DONE。
- 2026-10-24 01:10（自主執行輪結束）：135 項＝**DONE 88／NOT_APPLICABLE 21／BLOCKED 21／UNVERIFIED 2（B39 Dockerfile 3.12 未在 Railway 實跑、R16 CI 首跑）／PENDING 0**（R05、R21 為指向 B39、B11 的參照列）。最終驗證見 FINAL_REFACTORING_REPORT.md。
