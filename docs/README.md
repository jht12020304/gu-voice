# docs/ 導覽 — 先讀這裡

> 三件最常被舊文件誤導的事，先釘死：
> **部署是手動的**——merge 到 main 不會上線，要自己跑 `railway up`（後端）與 `vercel --prod`（前端），
> 詳見 [deployment_guide.md](deployment_guide.md) 一、（2026-07-26 更正，先前文件寫「全自動」是錯的）・
> **生產 DB = Supabase `gu-voice-prod`，ref `xobxnlvtilezridrekdm`（ap-southeast-1）**・
> **前端 dev port = 5175**。

## 現行文件（單一真相來源）

| 主題 | 文件 |
|---|---|
| 系統架構 + 問診管線不變式 | [app_architecture.md](app_architecture.md)（權威）；高層 onboarding 看 [system_overview.md](system_overview.md) |
| 紅旗偵測（規則層設計＋偏誤報政策） | [app_architecture.md §2.3.2](app_architecture.md)；**改關鍵字或抑制守衛前必讀** [TODO.md](TODO.md) §R-lessons |
| 問診端到端流程 | [consultation_flow.md](consultation_flow.md) |
| 一場問診的資料落地 | [session_data_inventory.md](session_data_inventory.md) |
| /research 研究分析 | [research_analytics.md](research_analytics.md) |
| 部署方法（手動兩步） | [deployment_guide.md](deployment_guide.md) 一、＋ `.claude/skills/deploy-production`；env/dashboard 操作細節見 [AGENTS.md](AGENTS.md) |
| env 變數 / dashboard 操作 | [deployment_guide.md](deployment_guide.md) |
| **iOS／TestFlight 設定值（唯一權威來源）** | [ios_release_settings.md](ios_release_settings.md)——Team ID、bundle ID、SKU、ExportOptions、憑證與金鑰位置、上傳指令、目前上線的 build。**值只留這一份**；操作流程見 [deployment_guide.md](deployment_guide.md) 二、，決策與踩過的坑見 `.claude/skills/ios-testflight`，現況與 PHI 風險見 [TODO.md](TODO.md) §V8 |
| DB 連線與事故 runbook | [supabase_connection_guide.md](supabase_connection_guide.md) |
| Celery worker/beat 建置 | [railway_celery_runbook.md](railway_celery_runbook.md) |
| 本機開發環境 | [full_setup_guide.md](full_setup_guide.md) |
| 新增語言 / i18n 上線 | [runbook/](runbook/) |
| 監控告警 | [observability/](observability/) |
| UI 設計系統 | [DESIGN.md](DESIGN.md)；參考分析見 [design_references/](design_references/) |
| 活的 backlog | [TODO.md](TODO.md)；2026-07-27 真跑修復與六條測試設計教訓見 §R／§R-lessons |
| **運維端點曝光控制** | [ops_endpoint_exposure.md](ops_endpoint_exposure.md)——`/metrics`／`/docs`／`/redoc`／`/openapi.json` 的鎖法與理由、`METRICS_TOKEN` 設定、以及 `/metrics` 在多 worker 下會低估約 4 倍這個限制 |
| **後端搬區域（新加坡）** | [railway_region_move.md](railway_region_move.md)——為什麼要搬（實測 827 倍差距）、app 與 Redis 的先後順序、Redis volume 弄丟會失去什麼、驗收與回退。設定值本身在 `backend/railway.toml` 與 [supabase_connection_guide.md](supabase_connection_guide.md) |
| **效能／體感流暢度（唯一權威來源）** | [perf_audit_2026-08-22.md](perf_audit_2026-08-22.md)——2026-08-22 那一輪稽核查了什麼、修了什麼、還剩什麼（含「已查證但刻意不做」與理由）。**結論只留這一份**，別的檔連結過來就好 |
| Flutter Web staged rollout | [flutter_web_cutover.md](flutter_web_cutover.md)；程式與本機跑法見 [../flutter_app/README.md](../flutter_app/README.md)，缺口見 [TODO.md](TODO.md) §G／§V |

## 歷史文件

[archive/](archive/) 內為已完成的 audit、一次性計畫與 2026-04 舊規格書——**勿當現行文件讀**，詳見其 README。
