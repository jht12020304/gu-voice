# GU-Voice AI 泌尿科問診系統：完整開發與環境設定指南

本文件提供開發人員快速理解專案路徑、環境變數配置以及如何啟動各項服務。

---

## 1. 專案目錄結構 (Project Paths)

專案採用前後端分離架構：

*   **前端路徑**: `/Users/chun/Desktop/GU_0410/frontend`
    *   框架: React + Vite + Tailwind CSS
    *   入口網址: `http://localhost:3000` (或 `http://127.0.0.1:3000`)
*   **後端路徑**: `/Users/chun/Desktop/GU_0410/backend`
    *   框架: FastAPI (Python 3.12+)
    *   API 入口: `http://localhost:8000/api/v1`
    *   API 文檔: `http://localhost:8000/docs`
*   **文檔路徑**: `/Users/chun/Desktop/GU_0410/docs` (包含各項規格書與部署指南)

---

## 2. 環境設定 (Environment Variables)

### 後端 (.env)
路徑: `backend/.env`
關鍵配置：
*   **DB_HOST**: `aws-1-ap-northeast-1.pooler.supabase.com` (Supabase 雲端資料庫)
*   **SUPABASE_URL**: `https://udydlelmkusyjmegtviq.supabase.co`
*   **REDIS_URL**: `redis://localhost:6379/0` (用於 Supervisor 指導訊息快取)
*   **OPENAI_API_KEY**: (已配置 gpt-4o / gpt-4o-mini 等模型金鑰)
*   **CORS_ORIGINS**: `["http://localhost:5173", "http://localhost:3000"]` (允許前端存取)

### 前端 (.env)
路徑: `frontend/.env`
關鍵配置：
*   **VITE_API_BASE_URL**: `http://localhost:8000/api/v1` (指向本地後端)
*   **VITE_WS_BASE_URL**: `ws://localhost:8000/api/v1/ws` (WebSocket 連線)
*   **VITE_SUPABASE_URL**: 同後端設定

---

## 3. 啟動服務順序 (Startup Guide)

要讓系統完全運作，請依序執行以下指令：

### 第一步：啟動 Redis (快取服務)
Supervisor 二次診斷模型需要 Redis 來存遞指導訊息。
```bash
# 如果你有安裝 Docker
docker run -d -p 6379:6379 redis
# 或者直接執行本地 redis-server
redis-server
```

### 第二步：啟動後端 API (FastAPI)
開啟新的 Terminal 分頁：
```bash
cd backend
source venv/bin/activate  # 進入虛擬環境
# 啟動並監管 Hot Reload
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 第三步：啟動前端 (Vite)
開啟另一個 Terminal 分頁：
```bash
cd frontend
npm install  # (初次啟動需安裝)
npm run dev -- --host 127.0.0.1 --port 3000
```

---

## 4. 關鍵功能路徑 (Key URLS)

*   **登入頁面**: [http://localhost:3000/login](http://localhost:3000/login)
*   **病患虛擬問診**: 登入後點擊「開始問診」-> 前往 `/session/{id}`
*   **後端健康檢查**: [http://localhost:8000/api/v1/health](http://localhost:8000/api/v1/health)

---

## 5. 雲端基礎設施 (Cloud Services)

*   **資料庫 (Supabase Postgres)**: 存放所有使用者、病患、問診場次、對話細節與 SOAP 報告。
*   **AI 模型 (OpenAI)**: 
    *   `gpt-5.4`: Supervisor (背景指導)
    *   `gpt-5.4-mini`: Worker (前端真人對話串流)
*   **身分驗證**: 目前後端 `AuthService` 透過內部加密解密，並與 `users` 資料表比對，不直接依賴 Supabase Auth 模組，確保資料一致性。

---

## 6. 注意事項
*   **WebSocket 穩定性**: 如果您在 `http://localhost:3000` 看到「載入對話失敗」，請檢查後端是否因 `google.auth.exceptions.DefaultCredentialsError` 崩潰。我已加入 try-except，現在應會自動降級到「純文字模式」。
*   **DB 連線**: 因使用 Supabase Pooler (Port 5432)，連線較為穩定。
