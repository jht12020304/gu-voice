# GU-Voice 部署與設定操作手冊

本文件說明如何修改 Railway、Vercel、Supabase 的設定，並成功部署到正式環境。

---

## 目前正式環境網址

| 服務 | 網址 |
|------|------|
| **前端** (Vercel) | `https://gu-voice-jht12020304y-7696s-projects.vercel.app` |
| **後端 API** (Railway) | `https://gu-voice-api-production.up.railway.app` |
| **健康檢查** | `https://gu-voice-api-production.up.railway.app/api/v1/health` |
| **Supabase 資料庫** | `https://udydlelmkusyjmegtviq.supabase.co` |

---

## 一、部署流程（最重要）

**只要 push 到 GitHub，前端和後端會自動部署。**

```bash
# 修改程式碼後
git add <修改的檔案>
git commit -m "描述你做了什麼"
git push origin main
```

- **Vercel** 自動抓 `frontend/` 目錄重新 build 並部署
- **Railway** 自動重新 build Docker image 並部署

> ⚠️ 特別注意：如果修改了 `backend/scripts/start.sh`，每次編輯後都必須重新設定執行權限，否則 Railway 部署會失敗：
> ```bash
> git update-index --chmod=+x backend/scripts/start.sh
> git add backend/scripts/start.sh
> git commit -m "restore executable bit on start.sh"
> git push origin main
> ```

---

## 二、Railway — 後端設定

### 修改環境變數（最常用）

**方法一：Raiway Dashboard（推薦）**

1. 登入 [railway.app](https://railway.app)
2. 選擇專案 `gu-voice-backend`
3. 點擊服務 `gu-voice-api`
4. 上方 tab 選 **Variables**
5. 找到要改的變數，直接點擊修改
6. 儲存後 Railway 自動觸發重新部署

**方法二：Railway CLI（Terminal）**

```bash
# 先確認連結到正確的專案（第一次使用才需要）
railway link --project gu-voice-backend
railway service gu-voice-api

# 查看所有環境變數
railway variables list

# 修改單一變數
railway variables set 變數名稱='新的值'

# 例如更新 CORS
railway variables set CORS_ORIGINS='["https://gu-voice-jht12020304y-7696s-projects.vercel.app","http://localhost:3000"]'
```

### 重要環境變數說明

| 變數 | 用途 | 注意事項 |
|------|------|----------|
| `CORS_ORIGINS` | 允許的前端網域（JSON 陣列） | **必須包含 Vercel 的完整網址**，否則瀏覽器會擋住 |
| `DB_HOST` | Supabase 資料庫主機 | 不要改，改了會連不到 DB |
| `OPENAI_API_KEY` | OpenAI API 金鑰 | 若過期或額度不足，問診功能會失效 |
| `JWT_SECRET_KEY` | JWT 簽名密鑰 | 改了會讓所有人的 token 失效（需重新登入） |
| `REDIS_URL` | Redis 連線（快取/BlackList） | 改了 logout/token 黑名單會失效 |
| `LOG_LEVEL` | 日誌等級 | 設定為 `INFO`（大寫）即可，腳本會自動轉小寫 |

### 查看後端 Log

```bash
railway logs
```

或在 Railway Dashboard → 服務 → **Logs** tab。

---

## 三、Vercel — 前端設定

### 修改環境變數

1. 登入 [vercel.com](https://vercel.com)
2. 切換到 `jht12020304y-7696s-projects` 這個 team（左上角下拉選擇）
3. 選擇專案 `gu-voice`
4. 左側選 **Settings** → **Environment Variables**
5. 修改後點 **Save**
6. 回到 **Deployments**，點選最新的部署 → **Redeploy**（環境變數不會自動重新部署）

### 重要環境變數說明

| 變數 | 目前值 | 用途 |
|------|--------|------|
| `VITE_API_BASE_URL` | `https://gu-voice-api-production.up.railway.app/api/v1` | 前端呼叫後端 API 的網址 |
| `VITE_WS_BASE_URL` | `wss://gu-voice-api-production.up.railway.app/api/v1/ws` | WebSocket 連線網址 |
| `VITE_SUPABASE_URL` | `https://udydlelmkusyjmegtviq.supabase.co` | Supabase 連線 |
| `VITE_SUPABASE_ANON_KEY` | `eyJhbGci...` | Supabase 公開金鑰 |

> ⚠️ 如果 Railway 的 API 網址改了，記得同步更新 `VITE_API_BASE_URL` 和 `VITE_WS_BASE_URL`。

### Deployment Protection（重要）

Vercel 預設會開啟 Deployment Protection，讓網站只有登入 Vercel 的人才能訪問。若不小心開啟，網站會變成 401：

1. Vercel Dashboard → `gu-voice` 專案 → **Settings**
2. 找到 **Deployment Protection**
3. 確認 **Vercel Authentication** 是 **Disabled**

---

## 四、Supabase — 資料庫

### 查看資料

1. 登入 [supabase.com](https://supabase.com)
2. 選擇專案 `udydlelmkusyjmegtviq`
3. 左側 **Table Editor** → 選擇資料表（如 `users`、`sessions`）

### 常用資料表

| 資料表 | 說明 |
|--------|------|
| `users` | 所有使用者（病患、醫師、管理員） |
| `sessions` | 問診場次紀錄 |
| `messages` | 問診對話內容 |
| `soap_reports` | SOAP 病歷報告 |

### 新增/修改使用者（直接操作 DB）

在 Supabase **SQL Editor** 執行：

```sql
-- 查詢所有 admin 帳號
SELECT id, email, name, role, is_active, created_at FROM users WHERE role = 'ADMIN';

-- 停用某個帳號
UPDATE users SET is_active = false WHERE email = 'someone@example.com';

-- 刪除測試帳號
DELETE FROM users WHERE email = 'test_probe_delete@gu-voice.com';
```

> ⚠️ 直接操作資料庫要謹慎，建議先備份或在 SQL Editor 用 `SELECT` 確認再執行 `UPDATE`/`DELETE`。

---

## 五、常見問題排查

### 問題：前端顯示「登入失敗」或網路錯誤

**原因最可能是 CORS 設定錯誤。**

確認步驟：
1. 打開瀏覽器開發者工具（F12）→ **Network** tab
2. 點登入，找到失敗的請求
3. 如果看到 `CORS error` 或 `Access-Control-Allow-Origin` 缺少，就是 CORS 問題

修復：
```bash
railway variables set CORS_ORIGINS='["https://gu-voice-jht12020304y-7696s-projects.vercel.app","http://localhost:3000","http://localhost:5173"]'
```

---

### 問題：Railway 部署失敗 — "We don't have permission to execute your start command"

`start.sh` 缺少執行權限（每次用編輯器修改這個檔案後就會發生）：

```bash
git update-index --chmod=+x backend/scripts/start.sh
git add backend/scripts/start.sh
git commit -m "fix: restore executable bit on start.sh"
git push origin main
```

---

### 問題：Railway 部署失敗 — uvicorn log-level 錯誤

已修復（`start.sh` 會自動把 LOG_LEVEL 轉小寫）。若再次出現，確認 `start.sh` 第 43 行是：
```bash
LOG_LEVEL="$(echo "${LOG_LEVEL:-info}" | tr '[:upper:]' '[:lower:]')"
```

---

### 問題：Vercel build 失敗 — TypeScript 錯誤

查看 Vercel Dashboard → Deployments → 失敗的部署 → **Build Logs**，找到錯誤行數，修復後 push 即可。

---

### 問題：後端健康檢查失敗

```bash
# 直接查看 Railway log
railway logs | tail -50
```

常見原因：
- 資料庫連線失敗（Supabase 暫時不可用）
- 環境變數缺少或錯誤
- Python 套件安裝失敗（查看 build log）

---

## 六、本地開發啟動

```bash
# 後端
cd backend
source venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

# 前端（另開一個 terminal）
cd frontend
npm run dev -- --host 127.0.0.1 --port 3000
```

本地前端會使用 `frontend/.env`（指向 `localhost:8000`），不影響正式環境。

---

## 七、GitHub Repo

所有程式碼：`https://github.com/jht12020304/gu-voice`

- `main` branch → 直接部署到正式環境
- 建議：重大修改先開新 branch 測試，確認沒問題再 merge 到 main
