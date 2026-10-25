# CODEBASE_AUDIT — 2026-10-23 全面盤點

> **2026-10-24 round 2（自主修復輪）**：在本檔之後又完成 Tracker 的 B11–B48／F09–F41／D04–D24／R02–R20 等項目；完整結算與最終驗證見 [FINAL_REFACTORING_REPORT.md](FINAL_REFACTORING_REPORT.md)，逐項狀態見 [REFACTORING_TRACKER.md](REFACTORING_TRACKER.md)，兩個執行代理的逐項報告在 `evidence/exec_frontend_report.md`、`evidence/exec_flutter_report.md`，round-2 效能原始數據在 `evidence/perf_backend_round2_measurements.md`。


> 讀法：本檔是摘要與決策清單；每一條的 file:line 證據在 [evidence/](evidence/) 的四份原始稽核（backend／frontend／flutter／repo）。分類：**A** 確定使用必須保留・**B** 高度確定無用可安全移除・**C** 疑似無用需驗證・**D** 重複可合併・**E** 效能／架構改善空間。
> 配套：[REFACTORING_REPORT.md](REFACTORING_REPORT.md)（實際改了什麼）、[PERFORMANCE_REPORT.md](PERFORMANCE_REPORT.md)、[TEST_REPORT.md](TEST_REPORT.md)、[PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md)。

## 0. 稽核當下的 Git 狀態（最重要的一條）

- Repo 是 `gu-voice/`（上層 `chatgu/` 不是 git repo）。`main` @ `e41cc9e`（2026-09-09）。
- 工作區有 **226 個已修改 + 29 個新增 + 3 個刪除的未提交檔**（+6,674／−3,508），來自 2026-10-03（流暢度 F01–F12、iOS M1–M3）、2026-10-10（backend 18 項 + frontend 17 項品質修正，**無任何文件記載**）、文件／CI 改動與 demo 影片工具。完整主題拆解與建議的 6-commit 切法見 [evidence/audit_repo.md §1](evidence/audit_repo.md)。
- 依使用者規則未提交這批 WIP；以 tag `wip-snapshot-2026-10-23`（commit `e54956e`，含 untracked 檔）做了不動工作區的完整快照，並從 HEAD 開了 `refactor/codebase-audit-2026-10` 分支。本輪所有修改都疊在這個工作區之上，可用 `git diff wip-snapshot-2026-10-23` 精確分離。

## 1. 原始架構摘要

| 區域 | 技術 | 規模（稽核前） | 入口／流程 |
|---|---|---|---|
| `backend/` | FastAPI + SQLAlchemy async + Celery + Redis + OpenAI，Python 3.12（Dockerfile 仍 3.11） | app 35,130 行／119 檔；tests 40,334 行；66 REST + 2 WS 路由 | `app/main.py` → 12 routers → services → models；病患 WS `conversation_handler.py`（3,410 行）；Celery beat 4 任務；alembic 23 版 |
| `frontend/` | React 18 + Vite 6 + Zustand 5 + react-router 6 + i18next | 29,492 行／159 檔；31 個 lazy 頁面 | `main.tsx` → `RootNavigator`（ProtectedRoute／RoleGuard）→ screens；`services/api/*`、`websocket.ts`、`audioStream.ts` |
| `flutter_app/` | Flutter 3.41.3（fvm）+ Riverpod 3 + go_router 17 + dio | 18,113 行／111 檔；28 條路由全部 `_lngKeyed` | `main.dart` → `app.dart` → `app_router.dart`；語音管線 `features/voice/services/*` |
| `scripts/` | 翻譯檢查、真 OpenAI e2e driver（5,397 行單檔） | 13 tracked + 3 new | CI 跑 `scripts/tests` |
| `docs/` | 47 份現行文件 + archive | 34k 行 | 入口 `docs/README.md` |

詳細模組地圖：[evidence/audit_backend.md §1](evidence/audit_backend.md)、[evidence/audit_frontend.md §1](evidence/audit_frontend.md)、[evidence/audit_flutter.md §1](evidence/audit_flutter.md)、[PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md)。

## 2. 問題清單（依類別）

### 2.1 B — 確定無用，已於本輪移除（證據見各 evidence 檔 §2–§3）

| 區域 | 項目 | 數量 |
|---|---|---|
| backend | ruff F401/F841 未用 import／變數（app 26、tests 20），兩個看似未用但被測試 import 的 re-export 保留並加 `# noqa` | 46 |
| backend | 無呼叫者符號：`InternalErrorException`、`reset_openai_client`、`TTSPipeline.synthesize_to_url`（連同 Supabase client 初始化）、`AlertService.delete_rule_entry`、`ComplaintService.get_active_list`、`ConnectionManager.{broadcast_report_generated,get_session_connection,is_session_connected,active_session_count}`、`TokenResponse` 別名、2 個 aliased re-import | 13 |
| backend | 無讀取者的 Settings 欄位：`APP_HOST/APP_PORT/APP_WORKERS`、`RED_FLAG_SEMANTIC_ONLY_THRESHOLD`（含 `.env.example`） | 4 |
| frontend | 整檔 `src/utils/validation.ts`；`date.ts` 5 個、`format.ts` 3 個 helper；`BETA_LANGUAGES`、`sentry._redact`、`enums.ts` 兩張硬編中文標籤表；`FCMDevice/ErrorResponse/RedFlagRule` 型別；14 個無人呼叫的 API wrapper（red-flag rules ×4、dashboard ×4、notification prefs／FCM ×4、patient create/update、getComplaint）及其 13 個 DTO；9 個無人使用的 path alias（含指向不存在目錄的 `@pages/@assets`、與 npm scope 衝突的 `@types`）；`uuid` 依賴（改 `crypto.randomUUID`） | 37+ |
| flutter | `path_provider`、`cupertino_icons` 直接依賴（零 Dart 引用、不影響 Podfile.lock） | 2 |
| repo | `docs/DESIGN.md` 與 `docs/design_references/linear_app_design.md` 逐位元相同（刪後者）；5 個 `.DS_Store`；CI 兩個已死的 `VITE_SUPABASE_*` placeholder；`vercel.json` CSP 的 Supabase 來源（SPA 已不連 Supabase） | — |

### 2.2 A — 看起來沒用但必須保留（搜不到引用 ≠ 沒用）

| 項目 | 為什麼保留 |
|---|---|
| `conversation_handler.py:475 _coerce_hpi_pct`、`:484 _SESSION_EMITTED_RED_FLAGS_KEY` | 被 `test_auto_conclude.py`、`test_red_flag_dedup.py`、`test_e84_red_flag_title_localization.py` 從 handler import；盲跑 `ruff --fix` 會弄壞三支測試 |
| `AudioService`（整個類） | `docs/session_data_inventory.md:304` 記載的產品決定；`test_audio_service_config.py` import |
| `enums.SupportedLanguage` | `scripts/tests/test_locale_lists_in_sync.py` 用 regex 讀它的原始碼，CI 執行 |
| `config.DATABASE_URL` property、`ACTIVE_LANGUAGES` | alembic env.py／三支測試 |
| 所有 Flutter lib 檔、所有 WS 訊息型別 | import graph 全可達；WS 訊息雙向都有對端 |
| `scripts/e2e_realopenai/results/*.json`（untracked） | TODO.md 與 e2e skill 引用為驗收證據，磁碟上是唯一副本 |
| `tests/unit/test_terminal_path_six_things_matrix.py` 的位置 | CLAUDE.md：`parents[2]` 硬推路徑，不可移入子目錄 |

### 2.3 C — 需要你決定（本輪刻意未動）

| 項目 | 證據 | 建議 |
|---|---|---|
| **17 條兩端都沒呼叫的 API 路由**：`/dashboard/{stats,queue,recent-alerts,recent-sessions}`（儀表板改吃 WS `initial_state`；`/queue` 無 LIMIT）、`/alerts/rules` CRUD ×4、`/notifications/preferences` ×2、`POST/PUT /patients`、`GET /complaints/{id}`、`GET /reports/{id}/revisions`、`GET /audit-logs/{id}` | [evidence/audit_backend.md §4](evidence/audit_backend.md)；React 端對應 wrapper 本輪已刪，後端路由保留 | 對外介面變更，等你拍板。四條 `/dashboard/*` 最明確；其餘可能有 ops／外部用途 |
| `frontend/.env.production` 自初始 commit 入庫 | 違反 CLAUDE.md「Never commit .env*」；含 production API URL、兩個已死的 `VITE_SUPABASE_*`、public anon key | 先確認 Vercel 環境變數已設 `VITE_API_BASE_URL/VITE_WS_BASE_URL/VITE_APP_ENV`，再 `git rm --cached` |
| Dockerfile `python:3.11-slim` vs CI／venv 3.12 | 測試跑在映像檔不用的版本上 | 改 3.12 需實際 build 驗證 |
| `sessions(status, created_at)`、`red_flag_alerts(acknowledged_by IS NULL)` 無索引 | 每次狀態變更廣播都掃；`func.date(created_at)` 不可用索引 | 先 `EXPLAIN ANALYZE`，再加 CONCURRENTLY 索引（schema 變更） |
| `permission_handler`（Flutter） | 零 Dart 引用，但 pod 在 Podfile.lock | 在 scratch checkout 驗 `pod install` 差異後再移除 |
| 305/1,211 個 Flutter 翻譯 key、16 個 React 翻譯 key 未被引用 | 動態 key 組字已排除 24／18 種 pattern | 逐 namespace 刪、每次跑 `check_translations.py`；本輪未動 |
| `railway-worker.toml`／`railway-beat.toml`／`start_worker.sh`／`start_beat.sh` + `docs/railway_celery_runbook.md` | 描述未部署的拓樸（worker/beat 跑在 API 容器內） | 四檔與 runbook 一起留或一起歸檔 |
| `flutter_app/build`（2.6 GB）、`.dart_tool`（2.8 GB）、五個 `graphify-out/`（143 MB） | 全部可重建 | `fvm flutter clean` 時機由你定 |
| 3 個無人引用的 integration test（`doctor_walkthrough`／`doctor_dashboard_ws`／`lng_deep_link`） | 不在 CI、無文件指向 | 驗仍可跑，或併入 README |
| `.codex/skills/graphify/`（vendored 112 KB） | 與全域安裝版會漂移 | 評估是否移出版控 |

### 2.4 D — 重複邏輯（本輪合併的標 ✔）

| 項目 | 位置 | 狀態 |
|---|---|---|
| `BLACKLIST_KEY_PREFIX` 定義兩處 | `core/dependencies.py:33` vs `services/auth_service.py:46` | ✔ 單一來源 + AST 測試 |
| 在職臨床人員 fan-out 查詢 | `conversation_handler._notify_doctors_red_flag` vs `notification_service._doctor_targets` | ✔ 共用 `_doctor_targets` |
| keyset cursor 分頁述詞 ×6、`has_more` 收尾 ×11 | report／alert／notification／admin／patient services | 未動（`session_service._apply_cursor_keyset` 可抽到 `utils/pagination`） |
| `REDIS_KEY_PREFIX` 只有 3/20 個 key 遵守 | `conversation_handler.py:53-54` 等 | 未動（決定要一律套或拆掉設定） |
| frontend 本地日期 key ×4、日標籤 ×2、月區間 ×3、狀態標籤表 ×6、Header／PatientLayout 使用者選單 | 見 [evidence/audit_frontend.md §6](evidence/audit_frontend.md) | 僅刪除死的那份；合併未動 |
| flutter 請求序號守衛 ×12、無限捲動 listener ×6、ChoiceChip 篩選列 ×4、`sessions_api` 手刻分頁 | 見 [evidence/audit_flutter.md §5](evidence/audit_flutter.md) | ✔ `sessions_api` 改走 `parsePage`；其餘未動 |

### 2.5 E — 效能／架構（量測結果見 PERFORMANCE_REPORT）

| 項目 | 狀態 |
|---|---|
| PDF 匯出同步 WeasyPrint 阻塞 event loop | ✔ 已修並量測 |
| admin bcrypt 同步呼叫 | ✔ 已修（`asyncio.to_thread`） |
| `publish_dashboard_event` 每則事件新開 Redis 連線 | ✔ API 行程重用連線池（loop-aware） |
| 首次 PDF 後 RSS +550 MB 不回收 | 未修；需 process pool 或字型策略 |
| `/research/analytics` 無日期過濾、`/dashboard/queue` 無 LIMIT、notification fan-out N+1 | 未修（E，需 EXPLAIN） |
| `conversation_handler._handle_text_message` 1,202 行（CC 81）、`ResearchService._assemble` CC 104 | 刻意不拆：前者受 AST 跳閘器與語音管線不變式保護 |
| frontend logo 1.08 MB、i18n 開機重複載入 | ✔ 已修並量測 |
| frontend 12 處整店訂閱、`ChatBubble` 未 memo、`ConversationPage` 1,405 行單元件 | 部分（ThemeToggle／ReportListPage／PatientListPage）；`ConversationPage` 屬語音路徑未動 |
| Flutter 4 處整狀態 `ref.watch`、`google_fonts` 執行期抓字型、WAV 編碼在主 isolate（已 benchmark） | 未動 |

## 3. 安全／設定相關發現

- 沒有 print／pdb／硬編 secrets；55 個 TODO 標記全是 ticket 交叉引用。
- 工作區內已存在 CLAUDE.md 所述「修復中、未 commit」的兩個消毒修正（`soap_generator.py:738-747`、`prompts/shared.py:1752-1762`），本輪未碰。
- `alembic/env.py` 以 `DB_HOST` 判斷 SSL，注入完整 `DATABASE_URL` 時失效（runtime engine 早已修）→ ✔ 已對齊。
- `scripts/e2e_realopenai/local.env` 入庫但值全為 localhost 開發用；`frontend/.env.local`、`backend/.env` 正確被忽略。
- 公開註冊強制 `role=patient`（AUTH-3）正確；但 `license_number` 對病患也照存（小瑕疵，未動）。

## 4. 文件層發現

- 現行文件 0 個壞連結（WIP 已修 14 個絕對路徑）；31 個壞連結全在 `docs/archive/`。
- 已修的過時敘述：`system_overview.md` 「main 自動部署」「e2e 佔位」、CLAUDE.md 不存在的 `supabase/` 目錄、CLAUDE.md §U15 對 alert_list／audit_logs 的描述。
- 未動：`docs/TODO.md` 2,388 行（可把 2026-04～06 已結案區塊移入 archive）；`perf_audit_2026-08-22.md` 檔名與內容日期不符；`frontend/DESIGN.md` 無人引用；`docs/AGENTS.md` 與根目錄 `AGENTS.md` 同名異用；**2026-10-10 的 35 項品質修正沒有任何文件記載**（建議先寫進 TODO.md 再提交）。
