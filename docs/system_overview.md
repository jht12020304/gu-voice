# GU-Voice 系統總覽

本文件提供 GU-Voice（泌尿科 AI 語音問診助手）的整體架構、技術棧、資料模型、核心流程與目前開發狀態。適合新加入的開發者、PM、或需要快速掌握整個系統樣貌的人閱讀。

> 相關文件：
> - [`deployment_guide.md`](./deployment_guide.md) — 部署與環境變數操作手冊
> - [`app_architecture.md`](./app_architecture.md) — 更細的架構設計文件
> - [`database_spec.md`](./database_spec.md) — 資料表詳細規格
> - [`api_spec.md`](./api_spec.md) — API 端點規格

---

## 一、產品定位

GU-Voice 是一套**以語音對話為核心**的醫療遠端問診系統，協助泌尿科醫師在門診前或門診中，透過 AI 與病患進行結構化問診，並自動：

- 產生 SOAP 報告（主觀 / 客觀 / 評估 / 計畫）
- 建議檢查項目與鑑別診斷
- 偵測急性症狀並即時發出紅旗警示給醫師

目標使用情境：病患可在手機或網頁上用語音與 AI 互動，醫師端 Dashboard 集中檢視報告、警示與病患歷史。

---

## 二、使用者角色

| 角色 | 主要可操作範圍 | 前端路由 |
|------|----------------|----------|
| **病患 (PATIENT)** | 選擇主訴、進行語音/文字問診、查看歷史紀錄 | `/patient/*`、`/conversation/:sessionId` |
| **醫師 (DOCTOR)** | Dashboard、患者清單、SOAP 報告審閱、Alert 處理、通知 | `/dashboard`、`/dashboard/*` |
| **管理員 (ADMIN)** | 繼承醫師權限 + 使用者管理、主訴模板、系統健康、稽核日誌 | `/admin/*` |

角色判斷透過前端 `RoleGuard` HOC 搭配 `useAuthStore`，後端依 JWT claim 授權。

---

## 三、系統架構

```
┌──────────────────────────────────────────────────────────────────┐
│                          使用者裝置                               │
│     病患 (手機/Web)          醫師 (Web Dashboard)                 │
└──────────┬─────────────────────────────┬────────────────────────-┘
           │ HTTPS / WSS                 │ HTTPS / WSS
           ▼                             ▼
┌─────────────────────────────────────────────────────────────────-┐
│         前端：React 18 + TypeScript + Vite（Vercel）              │
│   Zustand  ·  React Router  ·  Tailwind  ·  Axios  ·  i18n        │
└──────────┬──────────────────────────────────────────────────────-─┘
           │ REST (/api/v1/*)  +  WebSocket (/api/v1/ws/*)
           ▼
┌──────────────────────────────────────────────────────────────────┐
│         後端：FastAPI + Uvicorn（Railway，多 worker）              │
│   SQLAlchemy async  ·  JWT  ·  Middleware：CORS / RequestId /     │
│   AuditLogging  ·  WebSocket（conversation / dashboard）          │
└──────┬───────────────┬──────────────────┬──────────────┬─────────┘
       │               │                  │              │
       ▼               ▼                  ▼              ▼
┌────────────┐ ┌───────────────┐ ┌─────────────┐ ┌────────────────┐
│ PostgreSQL │ │    Redis      │ │   OpenAI    │ │   Firebase     │
│ (Supabase) │ │ (cache / pub  │ │ STT / LLM / │ │  FCM (推播)    │
│  +Storage  │ │  sub / Celery)│ │ TTS / SOAP  │ │                │
└────────────┘ └───────┬───────┘ └─────────────┘ └────────────────┘
                       │
                       ▼
                ┌──────────────┐
                │ Celery       │
                │ Worker/Beat  │
                │ (背景任務)    │
                └──────────────┘
```

監控層：Sentry（前後端錯誤追蹤）、Railway / Vercel 各自的 Logs。

---

## 四、技術棧

### 4.1 前端

| 類別 | 選擇 |
|------|------|
| 框架 / 語言 | React 18.3 + TypeScript 5.6 |
| 建置工具 | Vite 6 |
| UI | Tailwind CSS 3.4（`class` 策略深色模式）+ Headless UI + Lucide Icons |
| 狀態管理 | Zustand 5 |
| 路由 | React Router 6（nested + role-based guards） |
| HTTP | Axios 1.7（自動 snake_case ↔ camelCase、401 自動 refresh token） |
| 即時 | 自製 `WebSocketManager`（指數退避重連 + 心跳） |
| 其他 | i18n、Supabase JS、Sentry Browser |

### 4.2 後端

| 類別 | 選擇 |
|------|------|
| 框架 | FastAPI + Uvicorn（4 workers） |
| 語言 | Python 3.11 |
| ORM | SQLAlchemy 2.0 async + asyncpg |
| 資料庫 | PostgreSQL 15+（Supabase 託管） |
| 認證 | JWT（RS256 / HS256）+ Passlib bcrypt |
| 快取 / Broker | Redis 7 |
| 背景任務 | Celery（Redis broker，Asia/Taipei 時區） |
| 檔案 | WeasyPrint（SOAP PDF）、Supabase Storage（音檔簽名 URL） |
| 外部 API | OpenAI、Firebase Admin、Sentry |

### 4.3 基礎設施

| 層級 | 服務 |
|------|------|
| 前端 | **Vercel**（自動從 GitHub main branch 部署） |
| 後端 | **Railway**（Docker 多階段建置，`backend/scripts/start.sh` 啟動） |
| 資料庫 | **Supabase**（PostgreSQL + RLS + Storage） |
| 快取 / 佇列 | Redis（Railway 或 Upstash），同時做 Celery broker / result backend |
| 監控 | Sentry（10% 取樣率） |
| CI/CD | GitHub push → Vercel + Railway 自動部署 |

---

## 五、目錄結構

### 5.1 後端（`backend/app/`）

| 子模組 | 職責 |
|--------|------|
| `api/` 或 `routers/` | REST 路由（auth、sessions、reports、alerts、patients…） |
| `websocket/` | WebSocket：對話串流、Dashboard 即時推播 |
| `services/` | 業務邏輯（session、auth、alert、report、notification…） |
| `pipelines/` | LLM 流程：STT / LLM 對話 / TTS / SOAP / 紅旗偵測 / Supervisor |
| `models/` | SQLAlchemy ORM |
| `schemas/` | Pydantic 請求 / 回應結構 |
| `core/` | config、database、security、exception、middleware |
| `tasks/` | Celery 背景任務（分區管理、超時、通知重試） |
| `cache/` | Redis 上下文快取 |
| `utils/` | 音訊 / 日期工具 |
| `main.py` | 進入點：lifespan、middleware、router 註冊、`/api/v1/health` |

### 5.2 前端（`frontend/src/`）

| 子模組 | 職責 |
|--------|------|
| `screens/` | 頁面（`auth/`、`doctor/`、`patient/`、`admin/`） |
| `components/` | UI 元件（common、layout、form、audio、chat、medical、dashboard） |
| `stores/` | Zustand：auth、alert、conversation、report、patient、settings |
| `services/api/` | 10 個 API 模組，共用 `apiClient` |
| `services/` | `websocket.ts`、`audioStream.ts`（WebRTC 錄音） |
| `hooks/` | `useAuth`、`useWebSocket`、`useAudioStream`、`useRedFlagAlerts` |
| `types/` | enums、websocket、API response |
| `navigation/` | `RootNavigator` + role guards |
| `i18n/` | 多語系 |

---

## 六、資料模型

> 詳細欄位請見 [`database_spec.md`](./database_spec.md)。

### 6.1 主要資料表

| 資料表 | 用途 |
|--------|------|
| `users` | 所有帳號（病患、醫師、管理員） |
| `patients` | 病患醫療檔案（與 `users` 一對一） |
| `sessions` | 問診場次（狀態、主訴、紅旗標記） |
| `conversations` | 對話紀錄（**按月分區**，含音檔 URL、STT 信心分數） |
| `soap_reports` | SOAP 報告（S/O/A/P、ICD-10、審核狀態） |
| `red_flag_alerts` | 紅旗警示事件 |
| `red_flag_rules` | 紅旗規則（醫師可管理） |
| `chief_complaints` | 主訴清單（預設 + 自訂） |
| `notifications` | 站內 / 推播通知 |
| `fcm_devices` | FCM 推播 token |
| `audit_logs` | 稽核日誌（**按月分區**，合規保留 7 年） |

### 6.2 主要關聯

```
users ──┬── patients (1:1)
        ├── sessions (doctor_id, 1:N)
        ├── notifications (1:N)
        ├── fcm_devices (1:N)
        └── audit_logs (1:N)

patients ─── sessions (1:N)
chief_complaints ─── sessions (1:N)

sessions ──┬── conversations (1:N)
           ├── soap_reports (1:1)
           └── red_flag_alerts (1:N)

red_flag_rules ─── red_flag_alerts (1:N)
```

### 6.3 遷移

- 工具：**Alembic 1.14**
- 位置：`backend/alembic/versions/`
- Railway 啟動時由 `start.sh` 自動跑 migration（含 5 次重試）
- `conversations`、`audit_logs` 採 **monthly range partition**，由 Celery Beat 每月 25 日 03:00 自動建立下月分區

---

## 七、API 與 WebSocket

所有端點前綴：`/api/v1/`

| 模組 | 前綴 | 用途 |
|------|------|------|
| auth | `/auth` | 登入、登出、refresh token、密碼重設 |
| patients | `/patients` | 病患 CRUD |
| sessions | `/sessions` | 問診場次生命週期 |
| complaints | `/complaints` | 主訴管理 |
| reports | `/reports` | SOAP 報告、PDF 下載 |
| alerts | `/alerts` | 紅旗警示查詢 / 確認 |
| dashboard | `/dashboard` | 醫師統計儀表板 |
| notifications | `/notifications` | FCM 裝置、推播歷史 |
| admin | `/admin` | 管理員操作 |
| audit-logs | `/audit-logs` | 稽核日誌查詢 |

**WebSocket**
- `/api/v1/ws/sessions/{session_id}/stream` — 即時問診對話串流
- `/api/v1/ws/dashboard` — 醫師 Dashboard 即時推播（新 alert、session 狀態）

健康檢查：`GET /api/v1/health`

---

## 八、核心流程

### 8.1 病患問診流程

1. 登入（JWT Access 15 分鐘 + Refresh 7 天）
2. 在 `/patient/` 選擇主訴（預設清單或自訂）
3. 進入 `/conversation/:sessionId`，WebSocket 建立連線
4. 瀏覽器錄音（WebRTC）→ 送到後端 → Whisper STT → LLM 追問 → TTS 回覆
5. 每一輪都跑紅旗偵測（關鍵字規則 + LLM 語意）
6. 若觸發紅旗：中斷對話 → 推播通知醫師 → 儲存結果
7. 完成後 → 自動生成 SOAP → 等待醫師審閱 → 收到結果通知

### 8.2 醫師流程

1. 登入 → 進入 `/dashboard`（紅旗警示優先排序）
2. 點擊紅旗事件查看詳情 → 確認處置
3. 於 Reports 頁面開啟 SOAP 報告 → 看對話全文、鑑別診斷、建議檢查
4. 批註 / 修正 → 回饋給病患

### 8.3 LLM 資料流

```
患者語音
   ↓  (WebRTC → WebSocket)
後端 audioStream handler
   ↓
STT pipeline (Whisper-1, 中文)
   ↓  文字
LLM conversation pipeline (gpt-5.4-mini, reasoning_effort=none)
   ├─► Red Flag Detector (gpt-4o-mini)  ──► 若觸發 → Alert
   └─► Supervisor 背景任務 (gpt-5.4-mini, reasoning_effort=medium)
         └─ 指導下一輪提問方向
   ↓
TTS pipeline (tts-1, voice=nova, speed=0.9)
   ↓  音訊串流回前端
對話結束時
   ↓
SOAP Generator (gpt-4o, temperature=0.3)
   ↓
PostgreSQL (soap_reports) + Dashboard 推播
```

---

## 九、外部整合

| 服務 | 用途 | 環境變數前綴 |
|------|------|---------------|
| **OpenAI** | STT / LLM 對話 / Supervisor / SOAP / 紅旗偵測 / TTS | `OPENAI_*` |
| **Supabase** | PostgreSQL + Auth + Storage（音檔）+ Realtime | `SUPABASE_URL`、`SUPABASE_SERVICE_ROLE_KEY`、DB 連線變數 |
| **Firebase (FCM)** | 行動裝置推播（`firebase_admin.messaging`） | `GOOGLE_APPLICATION_CREDENTIALS_JSON` |
| **Sentry** | 錯誤追蹤（前後端） | `SENTRY_DSN`、`VITE_SENTRY_DSN` |
| **Redis** | 快取、JWT 黑名單、Celery broker / result backend | `REDIS_URL`（Celery 共用） |

目前尚未整合：Stripe（無計費需求）、Intercom（無即時客服需求）。

---

## 十、環境變數速查

> 完整清單請看 `backend/.env.example` 與 [`deployment_guide.md`](./deployment_guide.md)。

**後端必備**
- 應用：`APP_ENV`、`APP_SECRET_KEY`、`APP_LOG_LEVEL`、`LOG_LEVEL`（uvicorn）、`CORS_ORIGINS`
- 資料庫：`DB_HOST`、`DB_PORT`、`DB_NAME`、`DB_USER`、`DB_PASSWORD`（由 config 組成 asyncpg URL）、`SUPABASE_URL`、`SUPABASE_SERVICE_ROLE_KEY`
- 認證：`JWT_ALGORITHM`、`JWT_SECRET_KEY`（HS256）、`JWT_PRIVATE_KEY_PATH`/`JWT_PUBLIC_KEY_PATH`（RS256）、`ACCESS_TOKEN_EXPIRE_MINUTES`、`REFRESH_TOKEN_EXPIRE_DAYS`
- 外部 API：`OPENAI_API_KEY`、`OPENAI_MODEL_*`、`OPENAI_TEMPERATURE_*`、`OPENAI_MAX_TOKENS_*`、`OPENAI_REASONING_EFFORT_*`、`OPENAI_STT_MODEL`、`OPENAI_TTS_MODEL`、`GOOGLE_APPLICATION_CREDENTIALS_JSON`、`SENTRY_DSN`
- Redis：`REDIS_HOST`、`REDIS_PORT`、`REDIS_PASSWORD`、`REDIS_DB`、`REDIS_KEY_PREFIX`（Celery broker 直接用組出的 `REDIS_URL`，不需額外變數）

> `.env.example` 與 `config.py` 有若干不一致（例如 `.env.example` 寫 `DATABASE_URL` / `REDIS_URL` 但 `config.py` 實際讀 `DB_HOST` 等分段欄位）。實際以 `backend/app/core/config.py` 的 Settings 欄位為準。

**前端必備**（皆為 `VITE_*`）
- `VITE_API_BASE_URL`、`VITE_WS_BASE_URL`
- `VITE_SUPABASE_URL`、`VITE_SUPABASE_ANON_KEY`
- `VITE_SENTRY_DSN`、`VITE_ENABLE_MOCK`

---

## 十一、安全性設計

- **Row Level Security**：醫師僅能看自己的 session、病患僅能看自己的資料
- **音檔簽名 URL**：15 分鐘過期
- **SOAP PDF 浮水印**：「AI 輔助生成，需醫師確認」
- **稽核日誌**：所有寫入 / 敏感查詢自動經 `AuditLoggingMiddleware` 紀錄
- **PII 欄位級加密**（規劃中）
- **AI 免責聲明**於病患端與 SOAP 報告明確標註

---

## 十二、背景任務

Celery + Redis，時區 Asia/Taipei：

| 任務 | 排程 | 用途 |
|------|------|------|
| `session_timeout` | 每 5 分鐘 | 檢查閒置問診超過 600 秒自動關閉 |
| `partition_manager` | 每月 25 日 03:00 | 建立下個月的 `conversations` / `audit_logs` 分區 |
| `report_queue` | 事件觸發 | SOAP 報告生成 |
| `notification_retry` | 事件觸發 | 推播失敗時的重試 |

任務結果保留 24 小時，單次執行逾時 10 分鐘。

---

## 十三、本地開發

```bash
# 後端
cd backend
source venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

# 前端（另開 terminal）
cd frontend
npm run dev -- --host 127.0.0.1 --port 3000
```

或用 `docker compose up -d` 一次起所有服務：PostgreSQL 16（`:5432`）、Redis 7（`:6379`）、Backend（`:8000`）、Frontend（`:80`）。

---

## 十四、目前開發狀態

> 以下為 2026-04-17 的快照，實際進度以 `./專案開發進度.md` 為準。

**已完成**
- 核心語音問診流程（STT + LLM + TTS + VAD）
- 紅旗警示雙層偵測（規則 + 語意）
- SOAP 報告自動生成與儲存
- 醫師 Dashboard（統計、列表、實時監看）
- 病患端問診歷史
- JWT 認證、RBAC、稽核日誌
- FCM 推播、WebSocket 即時通訊
- Vercel + Railway + Supabase 正式部署

**進行中**
- Alert Triage / Report Review 工作區 UI 重新設計
- Dashboard 月度概覽與病患分組
- Sidebar 導航優化
- LLM prompt 優化（gpt-5.4 reasoning）

**未來規劃**
- Google / Apple OAuth
- 病患端 SOAP 完整查閱
- 醫師端批量報告匯出
- 圖表分析與趨勢追蹤
- 欄位級 PII 加密

---

## 十五、GitHub 與部署

- Repo：`https://github.com/jht12020304/gu-voice`
- `main` branch 直接部署到正式環境（Vercel + Railway 自動觸發）
- 重大修改建議先開 feature branch，確認後再 merge 到 main
