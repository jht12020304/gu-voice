# FINAL_REFACTORING_REPORT — 2026-10-24

> 範圍：2026-10-23 稽核（round 1）＋ 2026-10-24 自主修復輪（round 2）＋ 使用者授權「都做完」後的 round 3。唯一進度真相是 [REFACTORING_TRACKER.md](REFACTORING_TRACKER.md)；本檔是結算。
>
> **Round 3 結果（2026-10-24 12:50）**：全部工作已提交到 `refactor/codebase-audit-2026-10`——前 6 個 commit 是從 `wip-snapshot-2026-10-23` 快照樹以暫存 index 重建的 2026-10-03／10-10 未提交工作（檔案與工作區逐位元相同），之後 4 個稽核 commit + 1 個 round-3 commit；已推上 origin，**草稿 PR #116 的 CI 全綠**（backend-tests 含新的 `alembic upgrade head` + `tests/integration` 步驟、frontend-checks、flutter-checks、e2e-playwright、i18n 兩端矩陣）。Round 3 另完成：`GET /sessions/{id}/report` 一趟式端點（Flutter 輪詢由 2N 請求降為 N）、自助註冊不再存 `license_number`、F13 騰出的 75 個翻譯 entry 刪除、`verify:smoothness:perf` 實跑、Flutter 5.4 GB 快取清理；查證 Vercel production **零環境變數** → `.env.production` 暫不可移出版控。

## 1. 修復統計

| 項目 | 數量 |
|---|---|
| 原始問題總數（Tracker 列） | 135（含 2 列參照列 R05／R21） |
| 已修復並驗收（DONE） | **93** |
| 經查證不需修改（NOT_APPLICABLE，皆附理由） | 22 |
| 未驗證（UNVERIFIED） | 1：B39 Dockerfile 3.11→3.12（本機 docker build + 容器內 import 成功；Railway 部署為手動流程，未實跑） |
| 阻礙（BLOCKED，需你授權／付費／裝置／外部帳號） | 17（見 §5） |
| 剩餘 PENDING | 0 |

Git：11 個 commit、草稿 PR [#116](https://github.com/jht12020304/gu-voice/pull/116)，CI 兩次全綠（runs 40063230858、40063557906）。

## 2. 實際修改內容

淨足跡（相對 WIP 快照，排除三個 lockfile）：**238 個既有檔 +2,204／−5,764 行**（其中約 1,983 行「刪除」是快照比對對 untracked 檔的假性顯示，實際約 −3,780），加上新檔：backend 9 支測試 + `core/health.py` + migration；frontend `UserMenu.tsx`、`utils/sessionStatus.ts`、`utils/validation.ts`（重建）、2 支 node 測試、2 支 Playwright spec、`with-preview.mjs`；Flutter `request_seq.dart`、`login_page_test.dart`；文件 7 份。

### 修改的檔案（主要）
- backend：`services/{session,report,alert,notification,admin,patient,complaint,audit_log,research,dashboard,auth,tts}` 、`websocket/{connection_manager,conversation_handler,dashboard_handler}`、`tasks/{session_timeout,report_queue}`、`core/{dependencies,exceptions,middleware,security,config,openai_client}`、`cache/redis_client.py`、`alembic/env.py` + 2 個 migration、`schemas/{auth,session}`、`models/enums.py`、`pipelines/{tts_pipeline,llm_conversation}`、`utils/pagination.py`、Dockerfile、`.env.example`
- frontend：9 個頁面的訂閱、`utils/date.ts`、`services/api/client.ts`（`apiErrorMessage`）、`services/sentry.ts`、`stores/{settings,patientList,…}`、`components/layout/{Header,PatientLayout,LanguageLayout}`、`i18n/index.ts`、`index.html`、`vite.config.ts`、`tsconfig.json`、`playwright.config.ts`、`Dockerfile`、`vercel.json`、5 locale × 2 namespace
- flutter：3 個 controller + 7 個頁面（`RequestSeq`／ui_kit helper）、`shared/format.dart`、`session_calendar_view.dart`、`medical_info_page.dart`、`login_page.dart`、`doctor_push_watcher.dart`、`analysis_options.yaml`、`pubspec.yaml`、5 locale × 5 namespace
- repo：`.github/workflows/ci.yml`（整合測試步驟、死 placeholder）、`docker-compose.yml`、`CLAUDE.md`、`docs/README.md`、`docs/TODO.md`（2026-10-10 段落）、`docs/system_overview.md`、`scripts/tests/test_locale_lists_in_sync.py`

### 刪除的檔案
`frontend/src/utils/validation.ts`（舊版；後以兩個 helper 重建）、`docs/design_references/linear_app_design.md`（與 `docs/DESIGN.md` 逐位元相同）、5 個 `.DS_Store`。依賴：`uuid`、`date-fns`（web）；`cupertino_icons`、`path_provider`、`permission_handler`（Flutter）。

### 重構的模組
cursor 分頁（8 處 → `keyset_after`、11 處 → `page_slice`）、健康探針（2 → `core/health`）、`ResearchService._assemble`（CC 104 → 8 個 section 函式，最高 21）、通知 fan-out 語言查詢、授權擁有權查詢、frontend 日期／狀態／驗證／使用者選單 helper、Flutter 請求序號守衛／捲動／篩選列／分組清單／本地日／日曆 cell／登入頁／intake 頁拆分。

### 修復的 Bug
1. 逾時任務會取消並廣播**軟刪除**場次（鐵律違反）→ 真 PG 測試釘住。
2. PDF 匯出同步阻塞 event loop（所有 kiosk WS 凍結 ~1 s）。
3. JWT 黑名單前綴雙定義（漂移＝登出 token 繼續有效）。
4. `alembic/env.py` 以 `DB_HOST` 判 SSL，注入 `DATABASE_URL` 時失效。
5. 4xx 錯誤文案忽略 `?lng`／`X-Language`（與 200 語言不一致）。
6. CONCURRENTLY migration 失敗殘留 INVALID 索引會讓容器重啟永遠失敗 → 自癒。
7. frontend `settingsStore.language` 與 URL 權威衝突；i18n 開機雙載；`PatientListPage` 硬編中文月份。
8. `reportStore.reviewReport` 吞掉後端錯誤訊息。
9. 兩處讀 Session 無軟刪除過濾（alert push、report-ready）。

### 效能改善項目（皆有前後量測，見 §4）
PDF 子行程化（記憶體／loop）、dashboard publish 連線池重用、儀表板索引 + sargable 述詞、通知語言批次查詢、admin bcrypt 離開 loop、logo、i18n 開機請求、CJK 字型 payload、`date-fns` 移除、12 處整店訂閱→選擇器（未量 render）。

## 3. 測試驗收

| 套件 | 指令 | 結果（最終 round-2 重跑，evidence/final_verification_round2.log） |
|---|---|---|
| backend unit | `venv/bin/python -m pytest tests/unit`（CI env） | **4,915 passed, 2 skipped**（基準 4,904／3；+11 新測試；DB 停掉時為 4,914／3） |
| backend integration（真 PG） | `pytest tests/integration` | **13 passed**（基準 12） |
| backend lint | ruff F401/F811/F821/F841 | 0（基準 50） |
| OpenAPI 契約 | `test_openapi_contract.py` + 現場 `/openapi.json` 比對 | 73 路由 = 73，0 增 0 減 |
| scripts | `pytest scripts/tests` | 21 passed |
| 翻譯 | `check_translations.py`（web／ios） | OK／OK；`i18n:extract:check` PASS |
| frontend | lint／type-check／`npm test`／build | 0／clean／**17**（基準 15）／OK |
| frontend e2e | Playwright | **16/16**（基準 12；+3 doctor、+1 admin，三個 mock server） |
| flutter | analyze／test／DST calendar | 0 issues／**323**（基準 321）／21 |
| CI 模擬 | 全新 postgres:15 + `alembic upgrade head` + integration | 13 passed |
| 映像檔 | `docker build` backend（3.12）／frontend | 成功；容器內 `import app.main` OK |
| 依賴完整性 | 全新 venv `pip check` + 166 tests | 相容／綠 |

測試覆蓋範圍：核心商業邏輯（stub OpenAI）、API 契約、授權限縮（unit + 真 PG）、軟刪除每條路徑、分頁 SQL、WS 事件、通知 fan-out、PDF、前端 store／helper、病患與醫師／管理 UI 流程（mock API）、Flutter 控制器／頁面／日曆／登入。

**尚未驗證的功能**（自動化測試通過 ≠ 功能正常）：真 OpenAI 問診 e2e（未跑，本輪未動管線）；iOS 真機語音；Railway 上 Dockerfile 3.12 與新 migration；GitHub Actions 新步驟首跑；`verify:smoothness:perf` 腳本執行；B39／R16 以外的部署相容性（Vercel CSP 未動）。

## 4. 效能比較（本機，方法與原始輸出在 evidence/）

| 指標 | 修改前 | 修改後 | 幅度 | 限制 |
|---|---|---|---|---|
| `/health` 在 PDF 匯出期間 | 956 ms | **1.3–1.8 ms** | −99.8% | 單 worker 本機 |
| API 行程 RSS（25 份 PDF 後） | 737 MB | **168 MB** | −77%；記憶體移到可回收子行程（657 MB，每 20 份回收） | macOS 字型；production 絕對值不同 |
| API 行程 RSS 探測全程峰值 | 959–964 MB | **182 MB** | −81% | |
| PDF 首份／後續 | 1.27 s／1.25 s | 1.70 s（子行程冷啟）／1.17–1.21 s | 首份 +0.45 s | 子行程每 20 份重啟一次 |
| Dashboard publish 每則事件 | 0.73 ms（新連線） | **0.21 ms**（連線池） | −71%；生產跨區 RTT 時線性放大 | 本機 microbench |
| 排隊清單 SQL（100k 場次、2% active） | 5.65 ms Seq Scan | **1.08 ms** index | −81% | 合成資料 |
| 今日場次計數 | 4.72 ms（舊式 `date()` 6.6 ms） | **1.05 ms** | −78% | |
| 待確認紅旗計數 | 0.20 ms（低待確認比）／13.1 ms（33% 待確認） | **0.05 ms**／13.1 ms | −75%／0 | partial index 只在待確認佔比低時被選用 |
| 通知 fan-out 語言查詢 | N 次 | **1 次** | 測試釘住 | 未計時 |
| 全 JS gzip | 212,611 B | **207,005 B** | −2.6%（date-fns chunk 20 KB 消失） | |
| logo.png | 1,077 KB | **86 KB** | −92% | |
| 冷啟動 locale 請求（語言與 URL 不一致時） | 20／30 | **10** | −50／−67% | en-US URL 因 fallback 設計不變 |
| Google Fonts css2 payload（en-US） | 344,530 B | **8,366 B** | −98%（請求數不變） | |
| Sentry 若設 DSN | 進 index chunk | 獨立 360 KB chunk 動態載入 | 不影響首屏 | DSN 未設 |
| 其餘 GET p50 | 4–30 ms | 4–9 ms | 不歸功本輪：baseline 為冷 cache | |

未量測（刻意不宣稱）：選擇器／memo／const 對 render 次數的影響；admin bcrypt；Flutter 任何真機指標。

## 5. 剩餘風險（全部列出）

### BLOCKED（需你決定／授權／付費／裝置／外部帳號）
B15 `REDIS_KEY_PREFIX` 政策（改 key 影響既有黑名單／限流；本機 Railway CLI 未登入，無法確認生產值）・B32 研究分析預設時間窗（API 語意）・B35 Celery 每 task 新 loop/engine（需 worker 環境觀測）・B37 `conversation_handler`／紅旗規則／SOAP 拆分（AST 跳閘器 + 付費 e2e）・F10／F26 `ConversationPage`（語音路徑 + 付費 e2e）・F23 mock 集中化（是否引入 MSW 新依賴）・F29 CSP `unsafe-eval`（正式 header 無法本機驗）・F30／R03 `.env.production` 移出版控（**Vercel production 目前零環境變數**，先 `vercel env add VITE_API_BASE_URL／VITE_WS_BASE_URL／VITE_APP_ENV production`）・F39 AudioWorklet（裝置）・D13／D14 語音服務微優化與 WAV isolate（真機）・D16 google_fonts 內建（產品決定）・D18 LaunchScreen（Xcode）・R11 driver.py 拆分（付費 e2e）・R15 vendored graphify skill。

已自行結案的原阻礙項：R01 WIP 提交（已拆 6 commit）、R04 快取（已清）、B12 四條 dashboard 路由（改判 NOT_APPLICABLE：其 service 方法是 integration 測試釘軟刪除規則的入口）、B45（已修）、D15（已以新端點完成）。

### UNVERIFIED
B39 Dockerfile 3.12（Railway 未實跑）；D22 剩餘約 236 個 Flutter 翻譯 key（兩套掃描器結果不一致，無 UI 測試能抓到動態組字漏網，刻意不刪）。

### 其他已知
- 所有修改已在分支上以 11 個 commit 提交；要回復某一批用 `git revert <commit>`，或對照 `evidence/patches/`。
- F17 仍有 35 個 catch 刻意不改（13 在語音頁、22 設計上不顯示訊息）；store fallback 字串仍硬編中文。
- `permission_handler` 移除改了 `Podfile.lock`（只少該 pod）；下次 TestFlight 建置會看到此差異，屬預期。
- B46 子行程以 `spawn` 啟動：Railway 容器需允許子行程（一般允許）；首份 PDF 多 0.5 s。
- 第二次 EXPLAIN 顯示 alert partial index 在高待確認佔比時不被選用，無退步、但該情境無收益。
