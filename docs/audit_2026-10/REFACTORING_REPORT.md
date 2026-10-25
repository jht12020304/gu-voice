# REFACTORING_REPORT — 2026-10-23／24 實際修改

> **2026-10-24 round 2（自主修復輪）**：在本檔之後又完成 Tracker 的 B11–B48／F09–F41／D04–D24／R02–R20 等項目；完整結算與最終驗證見 [FINAL_REFACTORING_REPORT.md](FINAL_REFACTORING_REPORT.md)，逐項狀態見 [REFACTORING_TRACKER.md](REFACTORING_TRACKER.md)，兩個執行代理的逐項報告在 `evidence/exec_frontend_report.md`、`evidence/exec_flutter_report.md`，round-2 效能原始數據在 `evidence/perf_backend_round2_measurements.md`。


> 所有修改都疊在未提交的 WIP 之上（見 [CODEBASE_AUDIT.md §0](CODEBASE_AUDIT.md)）。本輪**沒有建立任何 commit**（使用者規則：不得擅自提交既有未提交修改，而本輪改動與 WIP 碰到同一批檔案，無法乾淨分離）。要看本輪確切改了什麼：`git diff wip-snapshot-2026-10-23`。
> 淨變動（排除 lockfile 與快照比對的 untracked 假性刪除）：約 **+158／−1,195 行、78 個既有檔 + 7 個新測試檔 + 1 個刪除的重複文件**。

## 1. 先建立的保護（Phase 2）

| 測試 | 目的 | 修改前狀態 |
|---|---|---|
| `backend/tests/unit/test_openapi_contract.py` + `openapi_contract_snapshot.json` | 73 條路由 + 119 個 schema 的 method/path/參數/required/欄位名快照；任何介面增減都紅。刻意變更用 `UPDATE_OPENAPI_SNAPSHOT=1` | 綠（基準） |
| `tests/unit/tasks/test_session_timeout_soft_delete.py` | 逾時 SELECT 必須帶 `is_deleted` 條件 | **紅**（真缺陷） |
| `tests/integration/test_session_timeout_soft_delete_pg.py` | 真 Postgres：軟刪除的 in_progress 場次不得被逾時任務取消或廣播（依 CLAUDE.md 把新讀取路徑登記進軟刪除清單） | **紅**：軟刪場次被改成 cancelled |
| `tests/unit/services/test_report_pdf_offloop.py` | PDF render 期間 event loop 必須持續跑（10 ms ticker ≥ 10 步） | **紅**：ticker 0 步 |
| `tests/unit/services/test_blacklist_prefix_single_source.py` | AST 斷言 `auth_service` 不再自己定義黑名單前綴 | **紅** |
| `tests/unit/websocket/test_publish_dashboard_event_pool.py` | 同 loop 重用連線池、別的 loop 退回短命 client | 新功能 |

## 2. 修正（行為改變，皆有測試）

| 檔案 | 修改 | 驗證 |
|---|---|---|
| `backend/app/tasks/session_timeout.py` | stale-session SELECT 加 `session_not_deleted()` | 上述兩支測試轉綠 |
| `backend/app/services/report_service.py` | WeasyPrint render 移到 `asyncio.to_thread`，以 `threading.Lock` 維持一次一份的序列化（`_render_pdf_blocking`） | 測試轉綠；實測 `/health` during PDF 956 ms → 1.6–142 ms（PERFORMANCE_REPORT） |
| `backend/app/services/auth_service.py` | 刪除自己的 `BLACKLIST_KEY_PREFIX`，改 import `core.dependencies` 那份 | AST 測試轉綠 |
| `backend/app/services/admin_service.py` | 兩處同步 `hash_password` 改 `asyncio.to_thread`（保留模組名以便 monkeypatch） | 全套 4,911 綠 |
| `backend/app/cache/redis_client.py` + `websocket/connection_manager.py` | 記錄建池的 loop；`publish_dashboard_event` 在同一 loop 重用池，否則維持短命 client；`close()` → `aclose()`（消掉 DeprecationWarning） | 新測試 2 綠；本機 microbench 0.73 → 0.21 ms／則 |
| `backend/app/websocket/conversation_handler.py` | 紅旗 fan-out 改呼叫 `NotificationService._doctor_targets`（刪掉第二份相同查詢） | 相關 4 支測試檔綠 |
| `backend/alembic/env.py` | SSL 判斷改解析 `DATABASE_URL` 的 host（與 `core/database.py` 同法） | `alembic current` 本機 OK；以 pooler URL 驗算：舊判斷 False、新判斷 True |
| `frontend/src/i18n/index.ts` | `init({ lng })` 直接取路徑語言，detector 只在無前綴時生效 | 冷啟動 locale 請求 20/30 → 10（PERFORMANCE_REPORT） |
| `frontend/public/logo.png` | 1024² → 256²（1,077,339 → 85,686 B） | 服務端實測 |
| `frontend/src/components/common/ThemeToggle.tsx`、`screens/doctor/ReportListPage.tsx`（`useShallow`）、`screens/doctor/PatientListPage.tsx`（`useMemo`） | 整店訂閱改選擇器／memo | lint・tsc・15 tests・build・Playwright 12/12（**未量測 render 次數**） |

## 3. 刪除（dead code，證據在 evidence/）

| 區域 | 刪除內容 |
|---|---|
| backend app | 26 個未用 import；`InternalErrorException`；`reset_openai_client`；`TTSPipeline.synthesize_to_url` + Supabase client 初始化 + `_STORAGE_BUCKET/_SIGNED_URL_EXPIRE_SECONDS`；`delete_rule_entry`；`ComplaintService.get_active_list`；`ConnectionManager` 四個 helper；`TokenResponse` 別名；`APP_HOST/APP_PORT/APP_WORKERS`、`RED_FLAG_SEMANTIC_ONLY_THRESHOLD`（config + `.env.example`）；`conversation_handler` 兩個 aliased re-import 與一個 local import；`dashboard_handler` 遮蔽的 local `json` import |
| backend tests | 20 個未用 import、3 個未讀取的區域變數（呼叫本身保留） |
| frontend | `src/utils/validation.ts`；`date.ts`：`parseISO/isToday/isThisWeek/toDateString/toTimeString`；`format.ts`：`truncateText/formatWaitingTime/formatRelative`；`BETA_LANGUAGES`；`sentry._redact`；`enums.sessionStatusDisplay/alertSeverityDisplay`；`types/index.ts`：`RedFlagRule/FCMDevice/ErrorResponse`；API wrappers：`admin.ts` 紅旗規則 ×4 + `RULES_BASE`、`complaints.getComplaint`、`dashboard.ts` ×4、`notifications.ts` ×4、`patients.createPatient/updatePatient`；`types/api.ts` 13 個 DTO；tsconfig／vite 9 個 alias 與不存在的 `vite-env.d.ts` include；`uuid` 依賴（→ `crypto.randomUUID`） |
| frontend deps | `uuid` 移除；`@eslint/js` 從隱性變顯性 devDependency（同已安裝版本 9.39.4）；smoothness 腳本改從 `@playwright/test` 匯入 |
| flutter | `cupertino_icons`、`path_provider` 直接依賴（pubspec.lock −9 行）；`sessions_api.getSessionsPage` 手刻分頁改 `parsePage`；三處過時註解 |
| repo | `docs/design_references/linear_app_design.md`（與 `docs/DESIGN.md` 相同）；5 個 `.DS_Store`；CI 兩個死 placeholder；`vercel.json` CSP 的 Supabase 來源 |

## 4. 文件修正

`docs/system_overview.md`（自動部署、e2e 佔位）、`CLAUDE.md`（不存在的 `supabase/`；§U15 的 alert_list／audit_logs 描述）、`docs/README.md`（設計文件合併說明 + 本稽核索引）。

## 5. 刻意不做的（含理由）

- **不重構 `conversation_handler.py`、紅旗規則層、SOAP prompt**：受 AST 跳閘器、`voice-pipeline-invariants` 與臨床拍板保護；需要真 OpenAI e2e 驗收。
- **不刪 17 條未呼叫路由、不 untrack `.env.production`、不動 Dockerfile 版本、不加索引**：對外介面／部署／schema 變更，等使用者確認。
- **不合併 cursor 分頁 ×6、frontend 日期 helper ×4、flutter 守衛 ×12**：有價值但非零風險，且本輪無法獨立 commit；列入 CODEBASE_AUDIT §2.4 待辦。
- **不剪翻譯 key**：動態 key 組字風險，收益小。
- **不批次刪 5.4 GB Flutter 快取**：可重建但重建要時間，由使用者決定。

## 6. 回復方式

- 整輪回復：`git checkout wip-snapshot-2026-10-23 -- .`（回到稽核前工作區；新測試檔用 `git clean -n` 先看再刪）。
- 單批回復：[evidence/patches/](evidence/patches/) 有 `batch01…batch08` 八份 patch（相對 `wip-snapshot-2026-10-23` 的 diff），可逐批 `git apply -R`。
