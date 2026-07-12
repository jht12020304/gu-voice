# GU_0410 — GU Voice 泌尿科語音問診系統

院內候診 Kiosk 的語音 AI 問診系統：病患已在現場、問診完成後等看診。FastAPI + Celery 後端、React + Vite 前端、5 語言（zh-TW / en-US / ja-JP / ko-KR / vi-VN）。

## 專案結構

```
backend/            → FastAPI + Celery。app/pipelines/ 問診管線（llm_conversation、red_flag_detector、
                      supervisor、soap_generator、prompts/）、app/websocket/、alembic/ migrations
frontend/           → React + Vite + TS。src/i18n/locales/ 是翻譯源頭；public/locales/ 是 build 鏡像
docs/               → 規格、audit、runbook（單一真相來源；docs/AGENTS.md 為部署細節指南）
scripts/            → check_translations.py、e2e_realopenai/（真 OpenAI E2E 工具，見其 README.md）
supabase/           → 本機 supabase CLI 設定（untracked）
.claude/skills/     → 專案技能（入庫，載入時機見各 skill description）
graphify-out/       → graphify 知識圖譜（untracked，可重建；graph.html 互動圖、GRAPH_REPORT.md）
```

## 常用指令

- Frontend（在 `frontend/`）：`npm run dev`、`npm run build`（tsc + vite，翻譯改動後必跑）、`npm run lint`、`npm run type-check`、`npm run test:e2e`（Playwright）、`npm run i18n:extract:check`
- Backend（在 `backend/`）：`venv/bin/pytest tests/`（unit / integration / e2e 分層）、`venv/bin/uvicorn app.main:app --reload`
- 本機全端：`docker compose up -d`（frontend :80、backend :8000、postgres :5432、redis :6379）
- 翻譯完整性：`python scripts/check_translations.py`
- 碼庫探索：`graphify query "<問題>"`／`graphify path A B`／`graphify explain <符號>`（對 `graphify-out/graph.json` 查詢，涵蓋 code＋docs；程式碼大幅改動後用 `/graphify . --update` 增量重建）

## 部署重點

`git push origin main` → Vercel（frontend）與 Railway（backend）自動部署，不需手動 release。生產 DB = Supabase `gu-voice-prod`（ref `xobxnlvtilezridrekdm`，ap-southeast-1）；環境變數真相 = Railway `DATABASE_URL`，docs 內舊 ref（udydl…/nydhm…）已過期。細節與除錯流程見 `deploy-production` skill 與 [docs/AGENTS.md](docs/AGENTS.md)。

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
- Never：commit `.env*`、`vercel_*.yml`（含 live secrets，.gitignore 已擋）
- Never：用 URL 以外的來源（cookie、navigator、後端偏好）當前端語言權威
- Never：research analytics 的比例指標讓分子不是分母的子集（Wilson CI 會 sqrt 負數 → 500）
