# 泌尿科 AI 語音問診助手 -- 雲端部署指南

> **版本**: 1.0.0
> **日期**: 2026-04-10
> **適用環境**: Supabase + Railway + Vercel
> **文件狀態**: Draft

---

## 目錄

1. [架構總覽](#1-架構總覽)
2. [Supabase 設定](#2-supabase-設定)
3. [Railway 設定](#3-railway-設定)
4. [Vercel 設定](#4-vercel-設定)
5. [環境變數完整清單](#5-環境變數完整清單)
6. [開發/Staging/Production 環境分離策略](#6-開發stagingproduction-環境分離策略)
7. [CI/CD Pipeline](#7-cicd-pipeline)
8. [監控與日誌](#8-監控與日誌)
9. [成本估算](#9-成本估算)
10. [安全性檢查清單](#10-安全性檢查清單)

---

## 1. 架構總覽

### 1.1 系統架構圖

```
                          ┌──────────────────────┐
                          │   使用者 (Browser)     │
                          └──────────┬───────────┘
                                     │ HTTPS
                                     ▼
                    ┌────────────────────────────────┐
                    │     Vercel (React Dashboard)    │
                    │     dashboard.gu-voice.com      │
                    │                                 │
                    │  - 醫師儀表板 (Doctor Dashboard) │
                    │  - 問診列表 / SOAP 報告檢視      │
                    │  - 紅旗警示即時推播              │
                    └───────┬──────────┬─────────────┘
                            │          │
               REST API     │          │  Realtime (WebSocket)
               HTTPS        │          │
                            ▼          ▼
  ┌──────────────────────────────────────────────────────────┐
  │              Railway (FastAPI Backend)                    │
  │              api.gu-voice.com                             │
  │                                                          │
  │  ┌─────────────┐  ┌──────────────┐  ┌────────────────┐  │
  │  │ Auth Service │  │ Session Svc  │  │ SOAP Generator │  │
  │  │ (JWT RS256)  │  │ (對話管理)    │  │ (報告生成)      │  │
  │  └──────┬──────┘  └──────┬───────┘  └───────┬────────┘  │
  │         │                │                   │           │
  │  ┌──────┴────────────────┴───────────────────┴────────┐  │
  │  │              AI Pipeline Service                    │  │
  │  │  - STT Orchestrator (Google Cloud STT v2 Chirp)    │  │
  │  │  - LLM Processing (GPT-4o / GPT-4o-mini)          │  │
  │  │  - TTS Orchestrator (Google Cloud TTS Neural2)     │  │
  │  │  - Red Flag Detection (GPT-4o-mini)                │  │
  │  └────────────────────────────────────────────────────┘  │
  └────┬──────────┬──────────┬──────────┬───────────────────┘
       │          │          │          │
       ▼          ▼          ▼          ▼
  ┌─────────┐ ┌───────┐ ┌────────┐ ┌──────────────────┐
  │Supabase │ │ Redis │ │OpenAI  │ │ Google Cloud     │
  │         │ │(Cache)│ │  API   │ │                  │
  │-Postgres│ │       │ │        │ │ - STT v2 (Chirp) │
  │-Auth    │ │Railway│ │-GPT-4o │ │ - TTS Neural2    │
  │-Storage │ │Plugin │ │-GPT-4o │ │                  │
  │-Realtime│ │  or   │ │ -mini  │ │ Lang: zh-TW      │
  │         │ │Upstash│ │        │ │ Voice: cmn-TW    │
  └─────────┘ └───────┘ └────────┘ └──────────────────┘
```

### 1.2 資料流簡述

| 步驟 | 流向 | 說明 |
|------|------|------|
| 1 | Browser → Vercel | 載入 React SPA 靜態資源 |
| 2 | Vercel → Railway | REST API 呼叫 (建立 Session、取得報告等) |
| 3 | Railway → Supabase | 資料庫 CRUD、Auth 驗證、音檔存取 |
| 4 | Railway → OpenAI | GPT-4o 對話生成 / SOAP 報告 / 紅旗偵測 |
| 5 | Railway → Google Cloud | 語音轉文字 (STT) / 文字轉語音 (TTS) |
| 6 | Railway → Redis | 對話狀態快取、JWT 黑名單、Rate Limiting |
| 7 | Supabase Realtime → Vercel | WebSocket 推播紅旗警示至 Dashboard |

---

## 2. Supabase 設定

### 2.1 建立 Project

1. 前往 [supabase.com](https://supabase.com) 並登入
2. 點擊 **New Project**，設定：
   - **Organization**: 選擇或建立組織
   - **Project Name**: `gu-voice-prod` (或 `gu-voice-dev` / `gu-voice-staging`)
   - **Database Password**: 產生強密碼並妥善保存
   - **Region**: `Northeast Asia (Tokyo)` -- 選擇離台灣最近的區域
   - **Pricing Plan**: Pro (Production) / Free (開發)
3. 等待 Project 初始化完成，記下以下資訊：
   - **Project URL**: `https://<project-ref>.supabase.co`
   - **Anon Key**: 用於前端
   - **Service Role Key**: 用於後端 (擁有完整權限，絕對不可暴露於前端)
   - **Database Connection String**: `postgresql://postgres.<ref>:<password>@aws-0-ap-northeast-1.pooler.supabase.com:6543/postgres`

### 2.2 Database 設定

使用 Supabase SQL Editor 或 Supabase CLI 執行以下初始化：

```sql
-- 啟用必要 Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";     -- 模糊搜尋

-- 建立 Enum 類型
CREATE TYPE user_role AS ENUM ('patient', 'doctor', 'admin');
CREATE TYPE session_status AS ENUM ('waiting', 'in_progress', 'completed', 'aborted_red_flag');
CREATE TYPE message_role AS ENUM ('patient', 'assistant', 'system');

-- 建立核心資料表 (參照 database_spec.md 完整定義)
-- users, patients, sessions, conversations, soap_reports,
-- chief_complaints, red_flag_alerts, audit_logs 等
```

**啟用 Row Level Security (RLS)**：

```sql
-- 所有資料表都必須啟用 RLS
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE patients ENABLE ROW LEVEL SECURITY;
ALTER TABLE sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE soap_reports ENABLE ROW LEVEL SECURITY;

-- 範例 Policy: 醫師僅能讀取自己的 Session
CREATE POLICY "doctors_read_own_sessions" ON sessions
  FOR SELECT
  USING (doctor_id = auth.uid());

-- 範例 Policy: 病患僅能讀取自己的資料
CREATE POLICY "patients_read_own_data" ON patients
  FOR SELECT
  USING (user_id = auth.uid());
```

### 2.3 Auth 設定

在 Supabase Dashboard → **Authentication** → **Settings**：

1. **Email Auth**:
   - 啟用 Email/Password 登入
   - 關閉 Email Confirmation (開發階段) / 啟用 (Production)
   - 設定 Redirect URL: `https://dashboard.gu-voice.com/auth/callback`

2. **JWT Configuration**:
   - Algorithm: `RS256` (Supabase 預設)
   - Access Token Expiry: `900` 秒 (15 分鐘)
   - Refresh Token Expiry: `604800` 秒 (7 天)
   - 在 Dashboard → Settings → API → JWT Settings 調整

3. **Custom Claims** (透過 Database Function):

```sql
-- 將 user role 加入 JWT claims
CREATE OR REPLACE FUNCTION public.custom_access_token_hook(event jsonb)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE
  user_role text;
BEGIN
  SELECT role INTO user_role FROM public.users WHERE id = (event->>'user_id')::uuid;
  event := jsonb_set(event, '{claims,user_role}', to_jsonb(user_role));
  RETURN event;
END;
$$;
```

### 2.4 Storage 設定

在 Supabase Dashboard → **Storage**：

1. 建立 Bucket: `audio-recordings`
   - **Public**: `false` (私有)
   - **File size limit**: `50MB`
   - **Allowed MIME types**: `audio/wav, audio/webm, audio/ogg, audio/mp3`

2. 設定 Storage Policy：

```sql
-- 後端 Service Role 可上傳/讀取
CREATE POLICY "service_role_full_access" ON storage.objects
  FOR ALL USING (bucket_id = 'audio-recordings' AND auth.role() = 'service_role');

-- 醫師可讀取自己病患的音檔
CREATE POLICY "doctors_read_audio" ON storage.objects
  FOR SELECT USING (
    bucket_id = 'audio-recordings'
    AND EXISTS (
      SELECT 1 FROM sessions s
      WHERE s.doctor_id = auth.uid()
      AND storage.objects.name LIKE 'sessions/' || s.id::text || '/%'
    )
  );
```

3. **資料保留策略** (3 年)：
   - 透過 Supabase Edge Function 或 cron job 定期清理超過 3 年的音檔
   - 建立 `storage_retention_policy` 表追蹤檔案建立時間

### 2.5 Realtime 設定

在 Dashboard → **Database** → **Replication**：

1. 啟用以下資料表的 Realtime：
   - `sessions` -- Session 狀態變更推播
   - `red_flag_alerts` -- 紅旗警示即時推播
   - `notifications` -- 通知推播

2. 前端訂閱範例 (在 Vercel Dashboard 中使用)：

```typescript
const channel = supabase
  .channel('red-flag-alerts')
  .on('postgres_changes',
    { event: 'INSERT', schema: 'public', table: 'red_flag_alerts' },
    (payload) => { showRedFlagNotification(payload.new); }
  )
  .subscribe();
```

---

## 3. Railway 設定

### 3.1 建立 Service

1. 前往 [railway.app](https://railway.app) 並登入
2. 點擊 **New Project** → **Deploy from GitHub repo**
3. 選擇後端 Repository，Railway 會自動偵測 Dockerfile
4. 設定 Service 名稱: `gu-voice-api`

### 3.2 Dockerfile 策略

在專案根目錄建立 `Dockerfile`：

```dockerfile
# ---- Build Stage ----
FROM python:3.11-slim AS builder

WORKDIR /build
COPY requirements/production.txt requirements.txt
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ---- Runtime Stage ----
FROM python:3.11-slim AS runtime

# 建立非 root 使用者
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser

# WeasyPrint / PDF 產生所需系統依賴
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 libpangocairo-1.0-0 libpangoft2-1.0-0 \
    libffi-dev libcairo2 libgdk-pixbuf2.0-0 \
    fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=builder /install /usr/local
COPY ./app /app/app
COPY ./alembic /app/alembic
COPY ./alembic.ini /app/alembic.ini

RUN chown -R appuser:appuser /app
USER appuser

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health')"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
```

> **注意**: `fonts-noto-cjk` 是產生含中文的 PDF 報告所必需的字型套件。

### 3.3 Health Check Endpoint

```python
# app/api/v1/endpoints/health.py
from fastapi import APIRouter
from datetime import datetime

router = APIRouter()

@router.get("/api/v1/health")
async def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "1.0.0",
        "services": {
            "database": "connected",  # 實際應檢查 DB 連線
            "redis": "connected",     # 實際應檢查 Redis 連線
        }
    }
```

在 Railway Dashboard → Service Settings：
- **Health Check Path**: `/api/v1/health`
- **Health Check Timeout**: `5s`

### 3.4 Railway 環境變數

在 Railway Dashboard → Service → **Variables** 中設定 (詳見第 5 節完整清單)。

### 3.5 Auto-Deploy 設定

1. Railway Dashboard → Service → **Settings** → **Source**
2. 連接 GitHub Repository
3. 設定 **Branch**: `main` (Production) / `develop` (Staging)
4. 啟用 **Auto Deploy**: 每次 push 到指定分支自動部署

### 3.6 Redis 設定

**方案 A -- Railway Redis Plugin (推薦開發/Staging)**：
1. Railway Dashboard → **New** → **Database** → **Redis**
2. Railway 會自動注入 `REDIS_URL` 環境變數

**方案 B -- Upstash (推薦 Production)**：
1. 前往 [upstash.com](https://upstash.com) 建立 Redis 實例
2. Region 選擇 `ap-northeast-1`
3. 將 Connection String 設定為 Railway 環境變數 `REDIS_URL`

---

## 4. Vercel 設定

### 4.1 部署 React Dashboard

1. 前往 [vercel.com](https://vercel.com) 並登入
2. 點擊 **Add New** → **Project** → 匯入 GitHub Repository
3. **Framework Preset**: `Next.js` (或 `Create React App`，依專案架構而定)
4. **Build Settings**:
   - Build Command: `npm run build`
   - Output Directory: `build` (CRA) 或 `.next` (Next.js)
   - Install Command: `npm ci`
5. **Root Directory**: 若為 Monorepo，指定前端子目錄路徑，如 `packages/web`

### 4.2 環境變數

在 Vercel Dashboard → Project → **Settings** → **Environment Variables**：

| 變數名稱 | 範例值 | 說明 |
|----------|--------|------|
| `NEXT_PUBLIC_API_URL` | `https://gu-voice-api-prod.up.railway.app` | Railway 後端 API URL |
| `NEXT_PUBLIC_SUPABASE_URL` | `https://<ref>.supabase.co` | Supabase Project URL |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | `eyJhbGciOi...` | Supabase 前端公開金鑰 |
| `NEXT_PUBLIC_APP_ENV` | `production` | 環境標識 |
| `SENTRY_DSN` | `https://xxx@sentry.io/xxx` | Sentry 錯誤追蹤 (Server-side) |
| `SENTRY_AUTH_TOKEN` | `sntrys_xxx` | Sentry Source Map 上傳 |

> **重要**: `NEXT_PUBLIC_` 前綴的變數會暴露於瀏覽器端，絕對不可放入 Secret Key。

### 4.3 Custom Domain

1. Vercel Dashboard → Project → **Settings** → **Domains**
2. 新增: `dashboard.gu-voice.com`
3. 依照 Vercel 指示在 DNS 設定 CNAME 記錄

### 4.4 Auto-Deploy

Vercel 預設已啟用 Git Integration：
- Push 到 `main` → 自動部署至 Production
- 開 Pull Request → 自動產生 Preview Deployment

---

## 5. 環境變數完整清單

### 5.1 Railway (Backend) 環境變數

```bash
# ===== Application =====
APP_ENV=production
APP_LOG_LEVEL=WARNING
APP_PORT=8000
APP_WORKERS=4

# ===== Supabase / Database =====
DATABASE_URL=postgresql://postgres.<ref>:<password>@aws-0-ap-northeast-1.pooler.supabase.com:6543/postgres
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_SERVICE_ROLE_KEY=eyJhbGciOi...  # 完整權限，僅後端使用
SUPABASE_JWT_SECRET=<jwt-secret>

# ===== Redis =====
REDIS_URL=redis://default:<password>@<host>:6379

# ===== OpenAI =====
OPENAI_API_KEY=sk-proj-...
OPENAI_MODEL_CONVERSATION=gpt-4o
OPENAI_MODEL_SOAP=gpt-4o
OPENAI_MODEL_RED_FLAG=gpt-4o-mini
OPENAI_TEMPERATURE_CONVERSATION=0.7
OPENAI_TEMPERATURE_SOAP=0.3
OPENAI_TEMPERATURE_RED_FLAG=0.2
OPENAI_MAX_TOKENS_CONVERSATION=512
OPENAI_MAX_TOKENS_SOAP=4096

# ===== Google Cloud =====
GOOGLE_APPLICATION_CREDENTIALS_JSON='{"type":"service_account",...}'
GOOGLE_STT_LANGUAGE_CODE=zh-TW
GOOGLE_TTS_VOICE_NAME=cmn-TW-Neural2-A
GOOGLE_TTS_SPEAKING_RATE=0.9
GOOGLE_TTS_SAMPLE_RATE=24000

# ===== Auth =====
JWT_PRIVATE_KEY_PATH=/app/keys/private.pem
JWT_PUBLIC_KEY_PATH=/app/keys/public.pem
ACCESS_TOKEN_EXPIRE_MINUTES=15
REFRESH_TOKEN_EXPIRE_DAYS=7

# ===== Storage =====
SUPABASE_STORAGE_BUCKET=audio-recordings

# ===== Monitoring =====
SENTRY_DSN=https://xxx@sentry.io/xxx

# ===== CORS =====
CORS_ORIGINS=https://dashboard.gu-voice.com
```

### 5.2 Vercel (Frontend) 環境變數

```bash
NEXT_PUBLIC_API_URL=https://gu-voice-api-prod.up.railway.app
NEXT_PUBLIC_SUPABASE_URL=https://<project-ref>.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=eyJhbGciOi...
NEXT_PUBLIC_APP_ENV=production
SENTRY_DSN=https://xxx@sentry.io/xxx
SENTRY_AUTH_TOKEN=sntrys_xxx
```

### 5.3 Supabase 設定值 (Dashboard 中設定)

| 設定項 | 值 |
|--------|-----|
| JWT Expiry (Access Token) | `900` 秒 |
| JWT Expiry (Refresh Token) | `604800` 秒 |
| Site URL | `https://dashboard.gu-voice.com` |
| Redirect URLs | `https://dashboard.gu-voice.com/auth/callback` |
| CORS Allowed Origins | `https://dashboard.gu-voice.com` |

---

## 6. 開發/Staging/Production 環境分離策略

### 6.1 三環境架構

| 項目 | Development | Staging | Production |
|------|-------------|---------|------------|
| **Supabase Project** | `gu-voice-dev` | `gu-voice-staging` | `gu-voice-prod` |
| **Railway Service** | `gu-api-dev` | `gu-api-staging` | `gu-api-prod` |
| **Vercel** | Preview Deployments | `staging.gu-voice.com` | `dashboard.gu-voice.com` |
| **Redis** | Railway Plugin | Railway Plugin | Upstash (Production tier) |
| **GitHub Branch** | `feature/*` | `develop` | `main` |
| **OpenAI Model** | `gpt-4o-mini` (節省成本) | `gpt-4o` | `gpt-4o` |
| **Log Level** | `DEBUG` | `INFO` | `WARNING` |

### 6.2 分支策略

```
feature/xxx ──PR──▶ develop ──PR──▶ main
                        │                │
                  auto-deploy       auto-deploy
                        │                │
                        ▼                ▼
                    Staging          Production
```

### 6.3 環境隔離原則

1. **每個環境使用獨立的 Supabase Project** -- 資料庫、Auth、Storage 完全隔離
2. **每個環境使用獨立的 API Key** -- OpenAI、Google Cloud 使用不同 Key 或設定用量上限
3. **Production 資料永不複製到其他環境** -- 使用 seed data 或匿名化資料
4. **環境變數透過各平台 Dashboard 管理** -- 不存入版本控制

---

## 7. CI/CD Pipeline

### 7.1 GitHub Actions -- 後端自動部署 (Railway)

```yaml
# .github/workflows/deploy-backend.yml
name: Deploy Backend to Railway

on:
  push:
    branches: [main]
    paths:
      - 'backend/**'
      - 'Dockerfile'
      - 'requirements/**'

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install -r requirements/test.txt
      - run: pytest tests/ --cov=app --cov-report=xml
      - uses: codecov/codecov-action@v4
        with:
          file: coverage.xml

  deploy:
    needs: test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: railwayapp/cli-action@v1
        with:
          railway_token: ${{ secrets.RAILWAY_TOKEN }}
      - run: railway up --service gu-voice-api --detach
```

> **注意**: Railway 預設會在 push 到連結的分支時自動部署。
> 此 GitHub Actions 的用途是確保測試通過後才觸發部署，可在 Railway 中關閉自動部署改用 CLI 手動觸發。

### 7.2 Vercel 自動部署

Vercel 內建 Git Integration，無需額外 CI/CD 設定：
- `main` 分支 push → Production 部署
- Pull Request → Preview 部署 (含唯一 URL)

### 7.3 Database Migration 策略

使用 **Supabase CLI** 管理資料庫遷移：

```bash
# 安裝 Supabase CLI
npm install -g supabase

# 連結到遠端 Project
supabase link --project-ref <project-ref>

# 建立新的 Migration
supabase migration new add_red_flag_severity_column

# 編輯 supabase/migrations/xxxxxx_add_red_flag_severity_column.sql
# ALTER TABLE red_flag_alerts ADD COLUMN severity TEXT DEFAULT 'high';

# 推送 Migration 到遠端
supabase db push

# 檢查 Migration 狀態
supabase migration list
```

**Migration CI/CD 流程**：

```yaml
# .github/workflows/migrate-db.yml
name: Database Migration

on:
  push:
    branches: [main]
    paths:
      - 'supabase/migrations/**'

jobs:
  migrate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: supabase/setup-cli@v1
        with:
          version: latest
      - run: |
          supabase link --project-ref ${{ secrets.SUPABASE_PROJECT_REF }}
          supabase db push
        env:
          SUPABASE_ACCESS_TOKEN: ${{ secrets.SUPABASE_ACCESS_TOKEN }}
```

---

## 8. 監控與日誌

### 8.1 Railway Logs

- Railway Dashboard → Service → **Logs** 提供即時日誌串流
- 支援關鍵字搜尋與時間範圍篩選
- 建議在 FastAPI 中使用 `structlog` 結構化日誌：

```python
import structlog
logger = structlog.get_logger()
logger.info("session_created", session_id=session_id, patient_id=patient_id)
```

### 8.2 Supabase Dashboard

- **Database**: 查詢效能、連線數、資料庫大小
- **Auth**: 登入次數、註冊數、失敗登入
- **Storage**: 儲存空間使用量
- **Realtime**: 活躍連線數、訊息吞吐量

### 8.3 Sentry 錯誤追蹤

**後端整合**：

```python
# app/main.py
import sentry_sdk
sentry_sdk.init(
    dsn=settings.SENTRY_DSN,
    traces_sample_rate=0.1,   # 10% 的 request 追蹤效能
    environment=settings.APP_ENV,
)
```

**前端整合**：

```typescript
// src/index.tsx
import * as Sentry from '@sentry/react';
Sentry.init({
  dsn: process.env.NEXT_PUBLIC_SENTRY_DSN,
  environment: process.env.NEXT_PUBLIC_APP_ENV,
  tracesSampleRate: 0.1,
});
```

### 8.4 Uptime Monitoring

建議使用 [Better Uptime](https://betteruptime.com) 或 [UptimeRobot](https://uptimerobot.com)：

| 監控項目 | URL | 檢查頻率 | 預警通知 |
|----------|-----|----------|----------|
| API Health | `https://api.gu-voice.com/api/v1/health` | 每 1 分鐘 | Slack + Email |
| Dashboard | `https://dashboard.gu-voice.com` | 每 5 分鐘 | Slack + Email |
| Supabase | Supabase Status Page | -- | 訂閱官方通知 |

---

## 9. 成本估算

### 9.1 每月費用估算 (USD)

| 服務 | Dev (1-5 人測試) | Staging (100 使用者) | Production (1000 使用者) |
|------|-----------------|---------------------|------------------------|
| **Supabase** | $0 (Free tier) | $25 (Pro) | $25 + 用量超額 ~$50 |
| **Railway** | $5 (Hobby) | $20 (Pro, ~1GB RAM) | $50-100 (Pro, 2-4GB RAM) |
| **Vercel** | $0 (Hobby) | $20 (Pro) | $20 (Pro) |
| **Redis (Upstash)** | $0 (Free tier) | $10 (Pay-as-you-go) | $30-50 |
| **OpenAI API** | $5-10 | $50-100 | $300-800 |
| **Google Cloud STT** | $5-10 | $30-60 | $200-500 |
| **Google Cloud TTS** | $2-5 | $10-20 | $50-150 |
| **Sentry** | $0 (Free tier) | $0 (Free tier) | $26 (Team) |
| **Domain + DNS** | $15/年 | -- | -- |
| **合計** | ~$20-30 | ~$170-260 | ~$700-1,700 |

### 9.2 成本優化建議

1. **OpenAI**: 紅旗偵測使用 `gpt-4o-mini` 而非 `gpt-4o`，節省約 90% 費用
2. **Google STT**: 使用 Chirp v2 streaming 模式，按實際秒數計費
3. **Redis**: 開發環境使用 Railway 內建 Redis，Production 才使用 Upstash
4. **Supabase Storage**: 定期清理過期音檔，避免儲存費用累積
5. **Vercel**: 善用 ISR/SSG 減少 Serverless Function 呼叫次數

---

## 10. 安全性檢查清單

### 10.1 API Keys 與密鑰管理

- [ ] 所有 API Key 儲存於各平台的環境變數管理中，不存入 Git
- [ ] `.env` 檔案已加入 `.gitignore`
- [ ] OpenAI API Key 設定用量上限 (Usage Limits)
- [ ] Google Cloud Service Account 僅授予最小權限 (STT/TTS API only)
- [ ] 每 90 天輪換一次 API Key (OPENAI_API_KEY, SUPABASE_SERVICE_ROLE_KEY)
- [ ] JWT RS256 Private Key 安全儲存，每 6 個月 rotation

### 10.2 Supabase RLS Policies

- [ ] 所有資料表已啟用 Row Level Security
- [ ] 醫師僅能存取自己的 Session 與病患資料
- [ ] 病患僅能存取自己的對話紀錄
- [ ] Admin 角色透過 Service Role Key 操作，不透過 RLS
- [ ] Storage Bucket 設定為 Private，透過 Signed URL 存取音檔
- [ ] 定期使用 `supabase inspect db policies` 審查 Policy

### 10.3 CORS 設定

- [ ] Railway FastAPI CORS 僅允許 Vercel Domain:
  ```python
  app.add_middleware(
      CORSMiddleware,
      allow_origins=["https://dashboard.gu-voice.com"],
      allow_credentials=True,
      allow_methods=["GET", "POST", "PUT", "DELETE"],
      allow_headers=["Authorization", "Content-Type"],
  )
  ```
- [ ] Supabase Dashboard 中設定 Allowed Origins
- [ ] 不使用 `allow_origins=["*"]` 於 Production

### 10.4 Rate Limiting

- [ ] 後端實作 Rate Limiting (使用 Redis + `slowapi`):
  ```python
  # 全域: 100 requests / 分鐘 / IP
  # Auth endpoints: 10 requests / 分鐘 / IP
  # AI endpoints: 20 requests / 分鐘 / User
  ```
- [ ] OpenAI API 設定 Organization-level rate limit
- [ ] Supabase 啟用內建 Rate Limiting

### 10.5 傳輸與儲存安全

- [ ] 所有通訊使用 HTTPS/WSS (TLS 1.2+)
- [ ] 資料庫連線使用 SSL (`?sslmode=require` in DATABASE_URL)
- [ ] PII (個人可識別資訊) 欄位使用 pgcrypto 加密儲存
- [ ] 音檔存取透過有時效的 Signed URL (15 分鐘過期)
- [ ] SOAP 報告 PDF 加入浮水印: "AI 輔助生成，需醫師確認"

### 10.6 部署前最終檢查

- [ ] 執行 `npm audit` / `pip audit` 檢查依賴漏洞
- [ ] 確認 Dockerfile 使用非 root 使用者
- [ ] 確認 Production 環境 `APP_LOG_LEVEL=WARNING` (不洩漏 DEBUG 資訊)
- [ ] 確認 Sentry 已正確設定並接收到測試事件
- [ ] 確認 Health Check Endpoint 正常運作
- [ ] 確認 Database Migration 已成功執行
- [ ] 進行一次完整的端對端測試 (建立 Session → 對話 → 產生 SOAP)
