# docs/ 導覽 — 先讀這裡

> 三件最常被舊文件誤導的事，先釘死：
> **部署是手動的**——merge 到 main 不會上線，要自己跑 `railway up`（後端）與 `vercel --prod`（前端），
> 詳見 [deployment_guide.md](deployment_guide.md) 一、（2026-07-26 更正，先前文件寫「全自動」是錯的）・
> **生產 DB = Supabase `gu-voice-prod`，ref `xobxnlvtilezridrekdm`（ap-southeast-1）**・
> **前端 dev port = 5175**。

## 現行文件（單一真相來源）

### 維護範圍（2026-10-03）

**iOS App 與 React 網頁版都繼續維護，共用同一套後端。** 這項決定取代舊文件中的「網頁除役／Flutter 取代 React」規劃。2026-10-03 已部署獨立 staging 後端與 React preview，iOS 候選包已簽章、尚未上傳 TestFlight；production 未變更。環境入口見 [發佈設定 §0](ios_release_settings.md#0-2026-10-03-staging-候選包與測試環境)。

| 產品／服務 | 程式碼 | 開發與驗證 |
|---|---|---|
| iOS App（病患 kiosk、醫師、管理員） | `flutter_app/` | 在該目錄用 `fvm flutter run`；`fvm flutter analyze`、`fvm flutter test` |
| 網頁版（React + Vite） | `frontend/` | Node ≥ 22.17；`npm ci`、`npm run dev`；`npm run lint`、`npm run type-check`、`npm test`、`npm run test:e2e`、`npm run build` |
| 共用 REST／WebSocket／背景工作 | `backend/` | FastAPI + Celery；`venv/bin/pytest tests/unit -q`，整合測試依各測試所需的本機服務執行 |

Flutter Web 保留為預覽用途；既有切換文件不代表要替換 React。iOS 發佈仍依 [TestFlight 設定](ios_release_settings.md)；網頁與後端依 [部署指南](deployment_guide.md) 手動部署。

翻譯由各端維護：React 的 `frontend/src/i18n/locales/` 是網頁來源，`frontend/public/locales/` 是建置鏡像；`flutter_app/assets/locales/` 是 App 來源。共用功能修改要檢查兩端，平台專用功能不必複製未使用的 key。從 repo 根目錄分別執行：

```bash
python scripts/check_translations.py
python scripts/check_translations.py --locales-dir flutter_app/assets/locales
```

兩端各自以自己的 zh-TW 為基準，依 `scripts/check_translations.py` 檢查 key 覆蓋率（預設門檻 95%）；目前 beta 語系的阻擋範圍仍為 `common`。網頁改翻譯後先跑 `npm run build` 更新鏡像，再檢查翻譯。

### 文件索引

| 主題 | 文件 |
|---|---|
| 系統架構 + 問診管線不變式 | [app_architecture.md](app_architecture.md)（權威）；高層 onboarding 看 [system_overview.md](system_overview.md) |
| 紅旗偵測（規則層設計＋偏誤報政策） | [app_architecture.md §2.3.2](app_architecture.md)；**改關鍵字或抑制守衛前必讀** [TODO.md](TODO.md) §R-lessons |
| 問診端到端流程 | [consultation_flow.md](consultation_flow.md) |
| 一場問診的資料落地（含 **admin 軟刪除**的欄位與覆蓋範圍） | [session_data_inventory.md](session_data_inventory.md) |
| /research 研究分析 | [research_analytics.md](research_analytics.md) |
| 部署方法（手動兩步） | [deployment_guide.md](deployment_guide.md) 一、＋ `.claude/skills/deploy-production`；env/dashboard 操作細節見 [AGENTS.md](AGENTS.md) |
| env 變數 / dashboard 操作 | [deployment_guide.md](deployment_guide.md) |
| **iOS／TestFlight 設定值（唯一權威來源）** | [ios_release_settings.md](ios_release_settings.md)——Team ID、bundle ID、SKU、ExportOptions、憑證與金鑰位置、上傳指令、目前上線的 build。**值只留這一份**；操作流程見 [deployment_guide.md](deployment_guide.md) 二、，決策與踩過的坑見 `.claude/skills/ios-testflight`，現況與 PHI 風險見 [TODO.md](TODO.md) §V8 |
| **推播不通的診斷 runbook** | [push_troubleshooting.md](push_troubleshooting.md)——六個斷點的查法。⚠️「App 內有跳、鎖定畫面沒有」**不代表推播壞了**：站內走 WebSocket，與推播完全獨立 |
| DB 連線與事故 runbook | [supabase_connection_guide.md](supabase_connection_guide.md) |
| Celery worker/beat 建置 | [railway_celery_runbook.md](railway_celery_runbook.md) |
| 本機開發環境 | [full_setup_guide.md](full_setup_guide.md) |
| Codex 程式知識圖譜 / Graphify MCP | [graphify_codex.md](graphify_codex.md) |
| 新增語言 / i18n 上線 | [runbook/](runbook/) |
| 監控告警 | [observability/](observability/) |
| UI 設計系統 | [DESIGN.md](DESIGN.md)（Linear 風格參考，原 `design_references/linear_app_design.md` 為同一份、已合併）；其他參考分析見 [design_references/](design_references/)；前端實際元件規則以 `.claude/skills/design-taste-frontend` 為準 |
| **2026-10 全面稽核／清理／效能**（稽核前後數據、未提交修改清單、待拍板事項） | [audit_2026-10/CODEBASE_AUDIT.md](audit_2026-10/CODEBASE_AUDIT.md)、[REFACTORING_REPORT](audit_2026-10/REFACTORING_REPORT.md)、[PERFORMANCE_REPORT](audit_2026-10/PERFORMANCE_REPORT.md)、[TEST_REPORT](audit_2026-10/TEST_REPORT.md)、[PROJECT_STRUCTURE](audit_2026-10/PROJECT_STRUCTURE.md)、**[REFACTORING_TRACKER](audit_2026-10/REFACTORING_TRACKER.md)（逐項狀態）**、**[FINAL_REFACTORING_REPORT](audit_2026-10/FINAL_REFACTORING_REPORT.md)（結算）**；原始證據與 patch 在 `audit_2026-10/evidence/` |
| Supabase RLS 政策（是否已套用到 gu-voice-prod 無文件記載，待確認） | [supabase_rls_policies.sql](supabase_rls_policies.sql) |
| 網頁版實際元件設計系統（Stripe/Intercom/Sentry 比例稿；與 `docs/DESIGN.md` 的 Linear 參考不同；`design-taste-frontend` skill 為現行規則） | [../frontend/DESIGN.md](../frontend/DESIGN.md) |
| 活的 backlog | [TODO.md](TODO.md)；2026-07-27 真跑修復與六條測試設計教訓見 §R／§R-lessons；2026-08-23 三項使用者需求（登入頁精簡／admin 刪除問診／場次日曆）與其留下的坑見 §W |
| **運維端點曝光控制** | [ops_endpoint_exposure.md](ops_endpoint_exposure.md)——`/metrics`／`/docs`／`/redoc`／`/openapi.json` 的鎖法與理由、`METRICS_TOKEN` 設定、以及 `/metrics` 在多 worker 下會低估約 4 倍這個限制 |
| **後端搬區域（新加坡）** | [railway_region_move.md](railway_region_move.md)——為什麼要搬（實測 827 倍差距）、app 與 Redis 的先後順序、Redis volume 弄丟會失去什麼、驗收與回退。設定值本身在 `backend/railway.toml` 與 [supabase_connection_guide.md](supabase_connection_guide.md) |
| **效能／體感流暢度（唯一權威來源）** | [perf_audit_2026-08-22.md](perf_audit_2026-08-22.md)——最新 **2026-10-03 iOS＋React 整體流暢度稽核**：12 項修復結果、可重跑驗收與真機待驗範圍；2026-08-22 紀錄保留在下半部。**結論只留這一份**，別的檔連結過來就好 |
| **產品介紹影片（自動產生）** | [../flutter_app/README.md](../flutter_app/README.md) §介紹影片——`tool/record_demo.sh` 一行產出 60 秒 MP4（模擬器錄影＋walkthrough 驅動＋ffmpeg 字卡）。⚠️ 只准打本機後端；模擬器要先 shutdown 再 boot；本機 ffmpeg 沒有 `drawtext` |
| Flutter Web 預覽／歷史切換流程 | [flutter_web_cutover.md](flutter_web_cutover.md)；App 開發見 [../flutter_app/README.md](../flutter_app/README.md)，缺口見 [TODO.md](TODO.md) §G／§V |

## 歷史文件

[archive/](archive/) 內為已完成的 audit、一次性計畫與 2026-04 舊規格書——**勿當現行文件讀**，詳見其 README。
