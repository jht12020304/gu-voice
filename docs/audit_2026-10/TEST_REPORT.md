# TEST_REPORT — 2026-10-24 最終驗證

> **2026-10-24 round 2（自主修復輪）**：在本檔之後又完成 Tracker 的 B11–B48／F09–F41／D04–D24／R02–R20 等項目；完整結算與最終驗證見 [FINAL_REFACTORING_REPORT.md](FINAL_REFACTORING_REPORT.md)，逐項狀態見 [REFACTORING_TRACKER.md](REFACTORING_TRACKER.md)，兩個執行代理的逐項報告在 `evidence/exec_frontend_report.md`、`evidence/exec_flutter_report.md`，round-2 效能原始數據在 `evidence/perf_backend_round2_measurements.md`。


環境：macOS（Darwin 27）、Python 3.12.14（`backend/venv`，venv 的 bin 腳本 shebang 已失效，一律 `venv/bin/python -m …`）、Node 26.8.1（CI 是 22）、Flutter 3.41.3（fvm）、本機 Postgres 16／Redis 7（`gu_smoothness-*` 容器，:55432／:56379，migration head `smoothness_20261003`）、Google Chrome + Playwright chromium。

## 1. 自動化測試結果（稽核後，`evidence/`無重跑紀錄者皆為 final_verification 一次跑完）

| 套件 | 指令 | 結果 | 備註 |
|---|---|---|---|
| backend unit（CI 範圍） | `pytest tests/unit` + CI env | **4,911 passed, 2 skipped** | 基準 4,904/3；+7 新測試；skip ①`test_terminal_path_six_things_matrix` Celery 跨行程格（刻意）②`test_red_flag_audit_2026_08` 臨床政策格（刻意）；第三個 skip（需 e2e results）本機有檔所以跑了 |
| backend integration（真 PG） | `pytest tests/integration` | **13 passed** | 基準 12；+1 軟刪除逾時；**CI 不跑這層**（E，建議加入） |
| backend lint | `ruff --select F401,F811,F821,F841` | 0 | 基準 50 個 |
| scripts/tests | `pytest scripts/tests` | 21 passed | |
| 翻譯完整性 | `check_translations.py`（web／ios） | OK（稽核期間兩端皆 OK；見 evidence 與 §3） | |
| frontend | `npm run lint`／`type-check`／`npm test`／`i18n:extract:check`／`npm run build` | 全綠；15/15 | |
| frontend e2e | `npx playwright test`（mock API） | **12/12**（批次 03 後與批次 07 後各跑一次） | |
| flutter | `fvm flutter analyze`／`fvm flutter test`／`TZ=America/New_York test/session_calendar_test.dart` | 0 issues／**321**／21 | |
| OpenAPI 契約 | `test_openapi_contract.py` | 綠（73 路由、119 schema 與快照一致） | 本輪未動任何路由 |

## 2. 新增測試一覽
`test_openapi_contract.py`（契約）、`test_session_timeout_soft_delete.py`（unit）、`test_session_timeout_soft_delete_pg.py`（integration）、`test_report_pdf_offloop.py`、`test_blacklist_prefix_single_source.py`、`test_publish_dashboard_event_pool.py`（2 案）。前四支在修改前都先確認是紅的。

## 3. 「測試通過」≠「功能正常」：功能清單與覆蓋狀態

| 功能 | 自動化覆蓋 | 本輪額外驗證 | 未驗證／風險 |
|---|---|---|---|
| 病患註冊／登入／refresh／登出／黑名單 | unit（含新 AST 測試） | 以真後端註冊 + 登入 + `/auth/me` 探測 | 無 |
| 問診 WS（語音 chunk／文字／紅旗／自動結束／終態六件事） | 大量 unit（stub OpenAI）+ AST 跳閘器 | 無；本輪只改了紅旗 fan-out 的查詢來源 | **真 OpenAI e2e 未跑**（本輪未動 prompt／管線邏輯，依規則不需要，但 `_notify_doctors_red_flag` 的查詢共用屬 WS 路徑，建議下次 e2e 時順帶看紅旗通知筆數） |
| SOAP 產生（Celery） | unit | 無 | 未動 |
| PDF 匯出 | unit（內容 + 新 off-loop） | 真後端匯出 12 份、並發 3 份 | 生產字型／記憶體行為 |
| 場次逾時（Celery beat） | unit + 新 integration | 真 PG 驗證軟刪除不被取消 | Celery 排程本身未跑 |
| 儀表板 WS／事件 publish | unit（cross-worker）+ 新池測試 | microbench | 生產 Redis RTT |
| 清單／分頁（sessions／reports／alerts／notifications／patients／audit） | unit + smoothness integration | 全部 GET 路由 30 次探測皆 200 | 刪掉的 React wrapper 對應的 4+ 條後端路由無人呼叫，未驗證是否有外部消費者 |
| 管理員功能（users／complaints／health／audit） | unit | 探測 200 | React／Flutter 管理頁面零 UI 測試（既有缺口） |
| 語言切換／i18n | frontend e2e（en 無 CJK）+ flutter 測試 | 冷啟動請求量測五種情境 | i18n 從 URL 初始化後，**非語言前綴路徑**（`/`）仍走 detector——與原行為同 |
| 推播（APNs／FCM） | unit | 無 | 未動 |
| iOS 真機語音（麥克風／STT／TTS／VAD） | 無 | 無 | 既有紅字（TODO §V1），本輪未動語音程式 |
| 部署相容性 | 無 | `alembic current` 本機；Dockerfile 未 build | alembic SSL 判斷改動只在 Supabase/pooler host 生效，**未對生產 URL 實跑** |

## 4. 剩餘風險
1. 所有修改未 commit，與 WIP 混在同一工作區；回復路徑見 REFACTORING_REPORT §6。
2. `tests/integration` 不在 CI；軟刪除鐵律只靠本機。
3. 前端 `useShallow`／選擇器改動以 Playwright 12 案 + 15 單元為證，無 render 計數。
4. 刪除的 frontend API wrapper 若 Vercel 上還有舊 bundle 無影響；後端路由保留，無介面變更（契約測試綠）。
5. `permission_handler` 等 C 項未動。
