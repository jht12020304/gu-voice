# docs/ 導覽 — 先讀這裡

> 三件最常被舊文件誤導的事，先釘死：
> **部署 = `git push origin main` 前後端全自動**（Vercel + Railway，無手動步驟）・
> **生產 DB = Supabase `gu-voice-prod`，ref `xobxnlvtilezridrekdm`（ap-southeast-1）**・
> **前端 dev port = 5175**。

## 現行文件（單一真相來源）

| 主題 | 文件 |
|---|---|
| 系統架構 + 問診管線不變式 | [app_architecture.md](app_architecture.md)（權威）；高層 onboarding 看 [system_overview.md](system_overview.md) |
| 問診端到端流程 | [consultation_flow.md](consultation_flow.md) |
| 一場問診的資料落地 | [session_data_inventory.md](session_data_inventory.md) |
| /research 研究分析 | [research_analytics.md](research_analytics.md) |
| 部署方法（自動部署） | [AGENTS.md](AGENTS.md) + `.claude/skills/deploy-production` |
| env 變數 / dashboard 操作 | [deployment_guide.md](deployment_guide.md) |
| DB 連線與事故 runbook | [supabase_connection_guide.md](supabase_connection_guide.md) |
| Celery worker/beat 建置 | [railway_celery_runbook.md](railway_celery_runbook.md) |
| 本機開發環境 | [full_setup_guide.md](full_setup_guide.md) |
| 新增語言 / i18n 上線 | [runbook/](runbook/) |
| 監控告警 | [observability/](observability/) |
| UI 設計系統 | [DESIGN.md](DESIGN.md)；參考分析見 [design_references/](design_references/) |
| 活的 backlog | [TODO.md](TODO.md) |

## 歷史文件

[archive/](archive/) 內為已完成的 audit、一次性計畫與 2026-04 舊規格書——**勿當現行文件讀**，詳見其 README。
