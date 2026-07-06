# Supabase 連線與資料庫遷移指南 (適用於 AI Agent)

> 此文件專門記錄連接本專案專屬 Supabase 雲端資料庫時的**特殊技術細節與地雷**。
> **未來的語言模型 (AI Agent) 若要處理後端資料庫或部署工作，請務必先閱讀此文件。**

## 1. Supabase 專案資訊
- **生產 Project**: `gu-voice-prod`，**Project Ref `xobxnlvtilezridrekdm`**，region **ap-southeast-1（Singapore）**，compute `micro`（DB max_connections ≈ 60）。
- **真相來源＝Railway `DATABASE_URL` 環境變數**（`railway variables --service gu-voice-app --kv`）。生產實際：`postgresql://postgres.xobxnlvtilezridrekdm:<pw>@aws-1-ap-southeast-1.pooler.supabase.com:5432/postgres`（session-mode pooler，見 §2）。
- **⚠️ Project Ref 漂移警告（2026-07-06 踩過的雷）**：專案曾重建、ref 換過但沒同步更新到處。目前散落三個 ref：
  - ✅ **`xobxnlvtilezridrekdm`** — 現行生產（Railway 用的、Dashboard 上的 `gu-voice-prod`）。**只信這個。**
  - ❌ `udydlelmkusyjmegtviq` — 本文與 `deployment_guide.md` 舊版寫的，**已過期**。
  - ❌ `nydhmqtogqlwhuuolzos`（ap-northeast-2、port 6543）— **本地 `backend/.env` 裡的舊 ref，該帳號已無此專案存取權**。本機若直接用 `.env` 連 DB 會連到死專案；跑後端 / E2E 一律用 `scripts/e2e_realopenai/local.env` 覆寫成本機 docker（或改指 `xobxnlvtilezridrekdm`）。診斷連線問題時**務必先確認你連的是哪個 ref**（我 2026-07-06 就是被 `.env` 舊 ref 誤導、以為 pooler 壞了）。
- **資料庫版本**: PostgreSQL 17.6

---

## 2. 資料庫連線 (Critical)
本專案的 FastAPI 後端使用 `asyncpg` 與 `SQLAlchemy 2.0` 非同步連線。直接連線 (Direct connection, port 5432) 在某些網路環境 (包含開發環境) 可能會遭遇 DNS 解析失敗 (`socket.gaierror`)。

🟢 **正確的連線方式：一律走 Pooler host（不要用 direct connection 5432）**
開發環境 / Alembic 遷移使用 **Transaction-mode（port 6543）**，請在 `.env` 中如此設定：
```env
DB_HOST=aws-1-ap-southeast-1.pooler.supabase.com
DB_PORT=6543
DB_NAME=postgres
DB_USER=postgres.xobxnlvtilezridrekdm
DB_PASSWORD=<你的密碼>
```
*注意：`DB_USER` 必須包含 `.xobxnlvtilezridrekdm` 這個後綴，因為走的是 Pooler (PgBouncer)。*

> 🚨 **生產環境（Railway 常駐容器）必須改用 Session-mode Pooler（port 5432）**
> 上面的 6543 是 **Transaction-mode**，適合本機開發 / 短連線與 Alembic 遷移。但**常駐容器**若用 6543，PgBouncer 會讓 `asyncpg` 為 JSONB codec 型別 introspection 建立的 prepared statement 在不同 backend 間失效，造成特定端點偶發 500（錯誤訊息：`prepared statement "__asyncpg_stmt_*__" does not exist`）。
> Session-mode 下每個 client 連線對應專屬 backend，prepared statement 持久，可根治此問題。設定時**沿用同一個 pooler host，只把 port 改成 5432**（注意：這與「direct connection 5432」不同，host 仍是 pooler）：
> ```env
> DB_HOST=aws-1-ap-southeast-1.pooler.supabase.com
> DB_PORT=5432
> # Session pooler 連線數有限，務必把連線池調小
> DB_POOL_SIZE=5
> DB_MAX_OVERFLOW=5
> ```

### ⚠️ 連線地雷與解法 (Asyncpg + PL/Bouncer)
1. **密碼包含特殊字元 (`@`)**：密碼中若有 `@`，直接組裝 URL 會造成 SQLAlchemy 解析失敗，必須使用 `urllib.parse.quote(..., safe="")` 進行 URL Encode（例如 `@` -> `%40`）。目前已在 `app.core.config.py` 中實作。
2. **Prepared Statements 與 Transaction Pooler 衝突**：Supabase 的 Transaction Pooler 背後是 `PgBouncer(Transaction mode)`，**不支援** Prepared Statements。如果沒有停用，會跳出 `<class 'asyncpg.exceptions.DuplicatePreparedStatementError'>` 或 `cannot insert multiple commands into a prepared statement` 錯誤。
   * **解法**：在建立 `create_async_engine` 時，必須傳入 `connect_args={"statement_cache_size": 0}`。

---

## 3. Alembic 資料庫遷移 (Migration)
專案的 Schema 管理由 Alembic 負責。

### 🚨 Alembic 執行注意事項
1. **連線設定 (`env.py`)**：目前 Alembic `env.py` 已改為直接從 `settings.ASYNC_DATABASE_URL` 拿連線字串，避免 ConfigParser 解析 `%40` 時誤認為 Python interpolation (`ValueError: invalid interpolation syntax`) 導致閃退。
2. **SSL 強制要求 & Supabase 偵測來源**：Supabase 要求 SSL 連線。在 `env.py` 及 `database.py` 中，如果偵測到 `supabase` 或 `pooler.supabase`，會自動加上 `ssl=require` 參數。如果遇到連線斷開，請先檢查這段邏輯。
   * **注意（已修）**：`database.py` 的 `_is_supabase` 偵測改為從 `settings.ASYNC_DATABASE_URL` 解析 host，**不再只看 `settings.DB_HOST`**。原因：若部署時以完整 `DATABASE_URL` 注入（Railway 常見做法），`DB_HOST` 仍會是預設值 `localhost`，導致 SSL 與 pooler mitigation（session-mode 相關處理）全部失效。
3. **Enum Type 的坑 (PostgreSQL)**：
   - SQLAlchemy 2.0 原生可以自動在 `op.create_table` 時建立 PostgreSQL 的 `ENUM` type (只要你不寫 `create_type=False`)。
   - **坑點**：如果是 `server_default`，例如 `sa.text("'WAITING'")`，大小寫必須與 Enum 定義的字串 **完全吻合**。如果 Enum 定義了 `'WAITING'` 但 Default 給了 `'waiting'`，Alembic migrate 會直接吐錯誤 (`InvalidTextRepresentationError`)。

### 執行遷移的正確指令
確保在 `backend` 資料夾下，然後執行：
```bash
# 1. 確保虛擬環境載入
cd backend

# 2. 生成遷移檔 (僅當有改動 models 時)
python3 -m alembic revision --autogenerate -m "description"

# 3. 升級資料庫至最新版
python3 -m alembic upgrade head
```

---

## 4. 未來部署要點
- 請記得將取得的 `SUPABASE_URL`、`SUPABASE_SERVICE_ROLE_KEY`、`SUPABASE_ANON_KEY` 等環境變數配置在 Railway / Vercel 的專案設定上。
- **不要**將 JWT keys 寫死在任何程式碼內，只能放環境變數。

---

## 5. 連線故障排除 / Supabase 事故 runbook（2026-07-06 事故學到的）

**症狀**：Railway app 起得來（基本 `GET /api/v1/health` 回 200），但 `GET /api/v1/healthz/deep` 的 **db check `timeout >2.0s`** 或 `sqlalchemy.exc.PendingRollbackError: Can't reconnect until invalid transaction is rolled back`；生產零星/全面 DB 錯誤。

**先分辨三種根因（別急著動手）**：
1. **Supabase 平台事故**（最先排除）：到 **Supabase Dashboard 專案首頁**看 **Status 是否 `Unhealthy`** + 頂部有無 **「We are investigating a technical issue」橫幅**；再看 **status.supabase.com** 事故是否列到本專案 region（**ap-southeast-1**）。若 Dashboard 的 DB metrics 顯示 **CPU/RAM 低、連線數遠未滿（如 17/60）**，代表 **DB 本身健康、是連線 pooler(Supavisor) 被平台事故拖累** → **不是我們的碼、也不是連線飽和**。
   - **⚠️ 事故期間絕對不要重啟 / resize 這個 Supabase 專案**：Supabase 事故常正是影響 **project restart/resize/branch/restore** 這類操作；官方原文「existing projects 除非在事故期間被 restart/resize 否則不受影響」。此時重啟反而可能卡進容量不足的復原佇列更久。**做法＝等平台恢復容量、retry**。
   - **Railway `railway redeploy` 只重啟 app 容器、不會重啟 Supabase 專案**：對 Supabase 端 pooler 問題無效，還多一次連線 churn，事故期間別亂重啟。
2. **Pooler 連線飽和**（我方）：DB metrics 顯示連線數逼近上限 / idle 佔死。見 §急救。**注意**：`direct connection`（`db.<ref>.supabase.co:5432`）**現在 DNS 已不解析（此專案 IPv4 直連已停用）**，無法再用它繞過 pooler 清 idle——舊記憶的「direct 清 idle 急救法」已失效。要清 idle 只能經 pooler（session-mode 5432）用該專案憑證跑 `pg_terminate_backend(... where state='idle')`，或到 Dashboard → Database → Roles/Connections 處理。
3. **我方程式碼**：只有在近期改了 DB 連線 / 交易 / pool 設定才可能。純業務邏輯改動（如問診/紅旗 pipeline）**不會**造成連線層 timeout；別誤把平台事故歸咎於自己的部署（部署時間點常與事故撞在一起）。

**分辨口訣**：`/health` 200 + `/healthz/deep` db timeout + Dashboard 連線數沒滿 + status.supabase.com 有事故 → **Supabase 平台事故，等它恢復，別重啟專案**。

### 5a. 事故緩解「後」的復原 playbook（2026-07-06 實戰驗證）

Supabase 平台事故緩解、Dashboard Status 轉回 **`Healthy`** 後，app 仍可能持續 `/healthz/deep` db fail——因為**事故期間 app 的 SQLAlchemy 連線池卡進壞交易**（`PendingRollbackError: Can't reconnect until invalid transaction is rolled back`），該池不會自癒、會一直重用壞連線。步驟：

1. **先確認 Supabase 端真的好了**：用 prod `DATABASE_URL`（`railway variables --service gu-voice-app --kv`）跑一輪**全新連線穩定性測試**（psycopg2 連 10 次量延遲）。若 10/10 ok、延遲 ~1s（僅首條 cold 可能 ~2.6s）＝DB/pooler 已穩。
2. **強制全新 app 容器**：`cd backend && railway up --detach --service gu-voice-app`。
   - **⚠️ `railway redeploy` 不可靠**：實測它**沒有真的換掉容器**（logs 無新 startup 序列、`PendingRollbackError` 依舊）——還是舊的壞池在服務。**一律用 `railway up`**（會重新上傳 image、確定產生全新容器+乾淨連線池）。可到 Railway service 頁確認最新 deployment 是 **Active / Deployment successful**。
3. **驗收看「真實功能」，不要只看 `/healthz/deep`**：`/healthz/deep` 的 db check 是**硬性 2.0s timeout**，pooler 剛回溫時 cold 連線偶爾 ~2.6s 就報 fail（**假警報**）。真正判斷 app 是否可用：
   - `POST /auth/login`（seed doctor）回 **token** = DB 讀寫正常。
   - `GET /api/v1/research/analytics`（doctor Bearer）回 **200 + cohort 數** = 深層查詢正常。
   - deep health 多數綠、偶爾一次 timeout＝pooler 尚在回溫，會自行消失，非故障。

**潛在改進（非緊急）**：(a) app engine 加 `pool_pre_ping=True`，讓壞連線被自動汰換、DB 短暫抖動後不需重啟即自癒；(b) 把 `/healthz/deep` 的 DB 檢查 timeout 從 2s 放寬到 ~5s，避免 pooler 回溫期的假警報。
**Supabase 端 pool size**：Dashboard → Settings → Database → Connection pooling 的 **Connection pool size**（Micro 預設 15，可調）。事故/飽和時可暫調大（如 30，仍安全低於 DB max_connections ~60；Max client connections 固定 200）給 headroom；本次已調 30。
