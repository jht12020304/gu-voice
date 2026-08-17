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
| DB 連線與事故 runbook | [supabase_connection_guide.md](supabase_connection_guide.md) |
| Celery worker/beat 建置 | [railway_celery_runbook.md](railway_celery_runbook.md) |
| 本機開發環境 | [full_setup_guide.md](full_setup_guide.md) |
| 新增語言 / i18n 上線 | [runbook/](runbook/) |
| 監控告警 | [observability/](observability/) |
| UI 設計系統 | [DESIGN.md](DESIGN.md)；參考分析見 [design_references/](design_references/) |
| 活的 backlog | [TODO.md](TODO.md)；2026-07-27 真跑修復與六條測試設計教訓見 §R／§R-lessons |
| Flutter 前端（未上生產） | [../flutter_app/README.md](../flutter_app/README.md)；缺口清單見 [TODO.md](TODO.md) §G |

## 歷史文件

[archive/](archive/) 內為已完成的 audit、一次性計畫與 2026-04 舊規格書——**勿當現行文件讀**，詳見其 README。
