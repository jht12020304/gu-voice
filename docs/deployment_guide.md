# GU-Voice 部署與設定操作手冊

本文件說明如何修改 Railway、Vercel、Supabase 的設定，並成功部署到正式環境。

---

## 目前正式環境網址

| 服務 | 網址 |
|------|------|
| **正式前端／React** (Vercel) | `https://gu-voice-chuns-projects-068de742.vercel.app` |
| **Flutter Web staged preview** | `https://gu-voice-flutter-preview.vercel.app`（未通過實體語音驗證前不得 promote） |
| **後端 API** (Railway) | `https://gu-voice-app-production.up.railway.app` |
| **健康檢查** | `https://gu-voice-app-production.up.railway.app/api/v1/health` |
| **Supabase 資料庫** | 專案 `gu-voice-prod`，ref `xobxnlvtilezridrekdm`（region ap-southeast-1）；DB 連線 host `aws-1-ap-southeast-1.pooler.supabase.com`、**port 5432 session-mode**。⚠️ 舊 ref `udydlelmkusyjmegtviq`／`nydhmqtogqlwhuuolzos` 已過期，真相以 Railway `DATABASE_URL` 為準，故障排除見 `supabase_connection_guide.md` §5 |

---

## 一、部署流程（最重要）

> ⚠️ **2026-07-26 更正：部署是手動的。merge 到 `main` 不會讓任何東西上線。**
> Railway 與 Vercel 的 GitHub App 裝在 repo 上，但它們的 check suite 在**每一次** main merge 都永遠停在 `queued`（對 #29／#30／#31／#32 逐一查證），從不收斂成部署；Railway 每一筆歷史部署的 `meta.cliCaller` 都是手動 CLI。
> 過去文件寫的「已接上自動部署」是錯的判斷——那些「已部署生產」之所以成立，是因為當天有人手動補跑 `railway up`。
> 自己查證：`gh api repos/jht12020304/gu-voice/commits/<sha>/check-suites`

**程式碼上線 = merge 到 main，然後手動部署兩邊。**

```bash
# 1. 程式碼進 main（PR merge 或 push）
git push origin main

# 2. 後端 → Railway
#    ⚠️ 不可以直接在 repo 裡跑 railway up：CLI 5.41.2 起會上傳整個 git root（在 backend/ 裡跑也一樣），
#    Railpack 看到 monorepo 就 FAILED（2026-08-20 實測；帶路徑參數 `railway up <path>` 也會 `prefix not found`）。
#    正確做法＝把 backend/ 的「已 commit 內容」匯出到非 git 目錄再 up：
DEPLOY_DIR=$(mktemp -d)
git archive HEAD:backend | tar -x -C "$DEPLOY_DIR"
cd "$DEPLOY_DIR"
railway link -p gu-voice-api -s gu-voice-app -e production
railway up --detach
curl https://gu-voice-app-production.up.railway.app/api/v1/healthz/deep   # 期待 {"status":"ok",...}

# 3a. 現行 React 前端 → Vercel（專案 gu-voice，個人 team chuns-projects-068de742）
cd frontend && npm run build && vercel --prod
#    ⚠️ 正式網址 gu-voice-chuns-projects-068de742.vercel.app 的 alias 不會隨 --prod 自動移動
#    （會釘在舊 deployment；gu-voice.vercel.app 才會自動跟上），要手動補：
vercel alias set <新deployment網址> gu-voice-chuns-projects-068de742.vercel.app

# 3b. Flutter Web staged build/deploy 見 docs/flutter_web_cutover.md
```

> **前端唯一活的網址＝`https://gu-voice-chuns-projects-068de742.vercel.app`**（2026-07-26 釐清＋切換）
>
> - Vercel 專案 `gu-voice`，個人 team `chuns-projects-068de742`。2026-07-26 建立並端到端驗證通過
>   （登入 → dashboard 解析出使用者 → /research 撈到真實生產資料）。
> - **舊網址已停用**：`project-9w0vq.vercel.app` 與 `gu-voice-jht12020304y-7696s-projects.vercel.app`
>   （同一 deployment 的兩個 alias）在**已停用的舊 Vercel 帳號** scope 下，現帳號完全進不去
>   （dashboard 404、`vercel inspect` 找不到），**無法再部署**；且 2026-07-26 已從
>   Railway `CORS_ORIGINS` 移除 → **那兩個網址現在打不到 API，開了會登入失敗**。
>   HTML 還是會載出來（Vercel 仍在服務靜態檔），所以症狀是「頁面正常但登入沒反應」。
> - ⚠️ **kiosk 裝置的書籤／首頁必須改指新網址**，否則現場無法問診。
> - ⚠️ `FRONTEND_BASE_URL` 仍指舊網址（影響重設密碼信的連結），待改。
> - 移除舊 origin 前先確認沒有 `in_progress` 場次（`select status, count(*) from sessions group by status`），
>   否則會把正在問診的病患打斷。回滾＝把舊 origin 加回 `CORS_ORIGINS`（env 改動約 1 分鐘 redeploy）。
>
> 新 clone 第一次要先 link（`.vercel/` 不入庫）：
> ```bash
> cd frontend && vercel link --yes --project gu-voice
> ```

> ⚠️ **Deployment Protection 會讓新專案回 302 到 `vercel.com/sso-api`**（不是 401）。
> dashboard 是 Settings → Deployment Protection → Vercel Authentication → Disabled；
> 無法開 dashboard 時用 API（token 讀 CLI 自己的 auth 檔，勿印出來）：
> ```bash
> python3 -c "
> import json,os,urllib.request
> tok=json.load(open(os.path.expanduser('~/Library/Application Support/com.vercel.cli/auth.json')))['token']
> pj=json.load(open('.vercel/project.json'))
> r=urllib.request.Request(f\"https://api.vercel.com/v9/projects/{pj['projectId']}?teamId={pj['orgId']}\",
>   data=json.dumps({'ssoProtection':None}).encode(), method='PATCH',
>   headers={'Authorization':f'Bearer {tok}','Content-Type':'application/json'})
> print(json.load(urllib.request.urlopen(r))['ssoProtection'])"
> ```

- **Railway** 用 Docker build（`RAILWAY_DOCKERFILE_PATH=Dockerfile`，Dockerfile 在 `backend/`）。⚠️ **CLI 5.41.2 起 `railway up` 一律上傳 git root，cwd 與 link 位置都救不了**（舊版文件寫「從 backend/ 跑」「link 綁目錄」皆已失效）——只能用上面的 `git archive` 匯出法。失敗徵兆：build log 出現 `Railpack could not determine how to build the app`，且舊容器仍 Active——**healthz 綠不代表新碼上線**，要看 dashboard 最新 deployment 是否 Active 且時間吻合。
- **Vercel** 正確 team 是個人 team **`chuns-projects-068de742`**；舊 `jht12020304y-7696s-projects` 已停用，勿再切換過去。
- 只改環境變數（不改程式碼）時**不需重新 build**：Railway 會用既有 image 觸發 redeploy（約 1 分鐘）。
- 事故復原時用 `railway up` 而非 `railway redeploy`——後者實測不會真的換容器（見 `supabase_connection_guide.md` §5a）。

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
2. 選擇專案 `gu-voice-api`
3. 點擊服務 `gu-voice-app`
4. 上方 tab 選 **Variables**
5. 找到要改的變數，直接點擊修改
6. 儲存後 Railway 會用**既有 image 觸發 redeploy**（約 1 分鐘，免重新 build）

**方法二：Railway CLI（Terminal）**

```bash
# 先確認連結到正確的專案（第一次使用才需要）
railway link --project gu-voice-api
railway service gu-voice-app

# 查看所有環境變數
railway variables list

# 修改單一變數
railway variables set 變數名稱='新的值'

# 例如更新 CORS
railway variable set CORS_ORIGINS='["https://gu-voice-chuns-projects-068de742.vercel.app","https://gu-voice-flutter-preview.vercel.app","http://localhost:5175"]'
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
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | DB 連線池大小 | 用 session-mode pooler 時連線數有限，設 `5` / `5` |

> ⚠️ **Gotcha 1：`CORS_ORIGINS` 的格式**
> pydantic-settings v2 對 `list[str]` 欄位會在 source 層先 `json.loads()`。目前 code（`app/core/config.py`）已對 `CORS_ORIGINS` 與 `MULTILANG_DISABLED_LANGUAGES` 加上 `Annotated[list[str], NoDecode]`，讓 `field_validator` 接到原始字串、**「逗號分隔字串」與「JSON 陣列」兩種格式都能接受**。
> 但若部署的是**舊 code**，把 `CORS_ORIGINS` 注入逗號分隔字串（如 `https://a.com,https://b.com`）會 `SettingsError` → 容器一啟動就 crash → healthcheck 永遠失敗 → Railway 顯示 offline。保險起見統一用合法 **JSON 陣列**。

> ⚠️ **Gotcha 2：Supabase pooler 模式（務必用 session-mode，port 5432）**
> 常駐的 Railway 容器要用 **session-mode pooler（port `5432`）**，不要用 transaction-mode（`6543`）。6543 的 PgBouncer 會讓 asyncpg 的 JSONB codec 型別 introspection 用的 prepared statement 跨 backend 失效，造成特定端點 500（錯誤訊息：`prepared statement "__asyncpg_stmt_*__" does not exist`）。session-mode 每個 client 連線對應專屬 backend，prepared statement 才會持久。
> code（`app/core/database.py`）已修：`_is_supabase` 改從 `ASYNC_DATABASE_URL` 解析 host 來偵測；先前只看 `settings.DB_HOST`，但以完整 `DATABASE_URL` 注入時 `DB_HOST` 仍是預設 `localhost` → mitigation 全失效。

### 查看後端 Log

```bash
railway logs
```

或在 Railway Dashboard → 服務 → **Logs** tab。

---

## 三、Vercel — 前端設定

### 修改環境變數

1. 登入 [vercel.com](https://vercel.com)
2. team 選 `chuns-projects-068de742`（chun's projects）
   > 舊文件寫的 `jht12020304y-7696s-projects` 是**已停用帳號**下的 scope，現帳號進不去（404）。
   > kiosk 現在還是開那份舊部署，但無法再對它部署——見「一、部署流程」的說明。
3. 選擇專案 `gu-voice`
4. 左側選 **Settings** → **Environment Variables**
5. 修改後點 **Save**
6. 回到 **Deployments**，點選最新的部署 → **Redeploy**（環境變數不會自動重新部署）

### 重要環境變數說明

| 變數 | 目前值 | 用途 |
|------|--------|------|
| `VITE_API_BASE_URL` | `https://gu-voice-app-production.up.railway.app/api/v1` | 前端呼叫後端 API 的網址 |
| `VITE_WS_BASE_URL` | `wss://gu-voice-app-production.up.railway.app/api/v1/ws` | WebSocket 連線網址 |
| `VITE_SUPABASE_URL` | `https://xobxnlvtilezridrekdm.supabase.co` | Supabase 連線（舊 ref `udydlelmkusyjmegtviq` 已過期） |
| `VITE_SUPABASE_ANON_KEY` | `eyJhbGci...` | Supabase 公開金鑰 |

> ⚠️ 如果 Railway 的 API 網址改了，記得同步更新 `VITE_API_BASE_URL` 和 `VITE_WS_BASE_URL`。
>
> ℹ️ `VITE_API_BASE_URL` / `VITE_WS_BASE_URL` 以 **Vercel dashboard 的環境變數**為準，會**覆寫 repo 內的 `frontend/.env.production`**；要改正式環境請在 Vercel dashboard 改，並 Redeploy。

### Deployment Protection（重要）

Vercel 預設會開啟 Deployment Protection，讓網站只有登入 Vercel 的人才能訪問。若不小心開啟，網站會變成 401：

1. Vercel Dashboard → `gu-voice` 專案 → **Settings**
2. 找到 **Deployment Protection**
3. 確認 **Vercel Authentication** 是 **Disabled**

---

## 四、Supabase — 資料庫

### 查看資料

1. 登入 [supabase.com](https://supabase.com)
2. 選擇專案 `gu-voice-prod`（ref `xobxnlvtilezridrekdm`）
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
railway variable set 'CORS_ORIGINS=["https://gu-voice-chuns-projects-068de742.vercel.app","https://gu-voice-flutter-preview.vercel.app","http://localhost:5175"]'
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
