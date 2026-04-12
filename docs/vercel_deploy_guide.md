# GU-Voice AI 泌尿科問診系統 - 部署指南 (Vercel + PaaS)

本指南將詳細說明如何將本專案部署至雲端環境，特別是針對前端部署至 Vercel 的流程。

> ⚠️ **【重要架構提醒】為什麼我不建議將「後端」也部署到 Vercel？**
> Vercel 主要是為前後端分離的 Serverless 函數（如 Next.js API Routes）設計。本專案的「AI 問診後端」重度仰賴以下兩項功能，而這些在 Vercel Serverless 無法運作：
> 1. **WebSocket 長連線**：問診對話採用 `ws://` 進行即時串流對話，Vercel Serverless 有嚴格的單次執行時間限制（通常 10~60 秒）且不支援持久化 WebSocket。
> 2. **背景非同步任務 (Background Tasks)**：我們使用了 `asyncio.create_task` 來呼叫 `Supervisor`（gpt-5.4 醫療指導模型），Vercel 的 Serverless 函數在回應 HTTP 請求後就會立刻凍結，導致背景的生成任務完全死機。
> 
> **🏆 推薦架構：**
> *   **前端 (React / Vite)** ➡️ 部署至 **Vercel** (極速、全球 CDN)
> *   **後端 (FastAPI)** ➡️ 部署至支援 WebSocket 的 PaaS (例如 **Render**, **Railway**, **Zeabur**, 或 **Fly.io**)
> *   **資料庫 (PostgreSQL)** ➡️ 繼續使用 **Supabase**
> *   **快取 (Redis)** ➡️ 使用 Upstash 或 Render 內建 Redis

---

## 第一步：前端部署至 Vercel

Vercel 非常適合 Vite + React 架構，只需簡單設定。

### 1. 調整 Vite 配置 (確保靜態路由沒問題)
在專案前端的 `vite.config.ts` 中，通常不需要大幅修改，但建議加入 SPA 路由回退設定：
新增或確認 `vercel.json` 於 `frontend/` 目錄下（如果你想讓 Vercel 自動處理深層路由）：
```json
{
  "rewrites": [
    {
      "source": "/(.*)",
      "destination": "/index.html"
    }
  ]
}
```

### 2. 在 Vercel 面板部屬
1. 註冊/登入 [Vercel](https://vercel.com)。
2. 點擊 **Add New Project**，並與你的 GitHub 帳號綁定。
3. 選擇本專案的 Repository。
4. **Project Settings (專案設定)**：
   * **Framework Preset**: 選擇 `Vite`
   * **Root Directory**: 輸入 `frontend` (因為前端代碼在 frontend 資料夾內)
   * **Build Command**: `npm run build`
   * **Output Directory**: `dist`
5. **Environment Variables (環境變數)**：
   你必須在這裡設定前端需要的全域變數 (請從你本地的 `.env` 中複製)：
   * `VITE_API_BASE_URL`: **(這必須填寫你未來要部署的後端正式網址，例如 `https://gu-voice-api.onrender.com/api/v1`)**
   * `VITE_WS_BASE_URL`: **(例如 `wss://gu-voice-api.onrender.com/api/v1`)**
   * `VITE_ENABLE_MOCK`: `false`
6. 點擊 **Deploy**，等候 1-2 分鐘即可完成部署並獲得一組上線網址（例如 `https://gu-voice.vercel.app`）。

---

## 第二步：後端部署至 Render (以支援 WebSocket)

以 Render (.com) 為例，它是目前免費且完美支援 FastAPI + WebSocket 的平台。

### 1. 準備 `requirements.txt` 和啟動指令
後端已經寫好了 `uvicorn app.main:app --host 0.0.0.0 --port 8000`，你可以直接使用。

如果在 `backend/` 下有 `render.yaml` 可以更方便，或者在 UI 上設定：

### 2. 在 Render 面板部署
1. 註冊/登入 [Render](https://render.com)。
2. 點擊 **New+** -> **Web Service**。
3. 綁定你的 GitHub Repository。
4. 設定條件：
   * **Root Directory**: `backend`
   * **Environment**: `Python`
   * **Build Command**: `pip install -r requirements.txt`
   * **Start Command**: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
5. **Environment Variables (環境變數)**：
   這非常關鍵，請將後端需要的 `.env` 複製上去：
   * `SUPABASE_URL`: 你的 Supabase 網址
   * `SUPABASE_SERVICE_ROLE_KEY`: Supabase 的 Service 密鑰
   * `OPENAI_API_KEY`: 你的 OpenAI 金鑰
   * `REDIS_URL`: 如果你有外部 Redis (如 Upstash)，填寫這裡；如果沒有請在 Render 開一個免費 Redis 服務並將 Internal URL 填入這。
   * *(如果還要支援語音)* `GOOGLE_APPLICATION_CREDENTIALS_JSON`: 將 Google 授權 JSON 整包貼成長字串（或改由程式讀取環境變數配置）。
   * `CORS_ORIGINS`: 填上你在 Vercel 部署獲得的前端網址 `https://gu-voice.vercel.app` (超級重要，不然會被 CORS 擋住)

### 3. 等候部署完成
Render 部署可能需要幾分鐘，完成後會給你一個後端網址（例如 `https://gu-voice-backend.onrender.com`）。

---

## 第三步：最後環境變數更新與測試

1. **更新 Frontend 在 Vercel 的環境變數**：
   此時你已經有後端的正式網址。回到 Vercel 的專案設定 -> **Environment Variables**，把剛才的網址填入：
   * `VITE_API_BASE_URL`: `https://gu-voice-backend.onrender.com/api/v1`
   * `VITE_WS_BASE_URL`: `wss://gu-voice-backend.onrender.com/api/v1`
   然後在 Vercel 點擊 **Redeploy**，讓新的變數生效入打包好的代碼中。

2. **Supabase Redirect URLs 更新**：
   前往 Supabase 控制台 -> Authentication -> URL Configuration：
   * 將 **Site URL** 改為你 Vercel 的網址（例如 `https://gu-voice.vercel.app`）。
   * 取消本地 `http://localhost:3000` 或將其移至 Additional Redirect URLs 中。

3. **測試上線流程**：
   * 進入 Vercel 前端網址，登入你的系統。
   * 開啟問診畫面，觀察文字訊息和 WebSocket 連線是否順利。
   * 查看 Render 後端 Log 確定 Supervisor 任務也正確啟動。

## 總結
雖然前端可以輕鬆放在 Vercel 獲得全球 CDN 提速，但即時語音問診的「靈魂」──WebSocket 和雙模型監控背景任務，依賴可長時間運行的狀態機伺服器。這樣的切分架構（Vercel 前端 + Render/Railway 後端）是業界最普遍也最穩定的做法。
