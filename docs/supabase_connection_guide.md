# Supabase 連線與資料庫遷移指南 (適用於 AI Agent)

> 此文件專門記錄連接本專案專屬 Supabase 雲端資料庫時的**特殊技術細節與地雷**。
> **未來的語言模型 (AI Agent) 若要處理後端資料庫或部署工作，請務必先閱讀此文件。**

## 1. Supabase 專案資訊
- **Project Ref**: `udydlelmkusyjmegtviq`
- **資料庫版本**: PostgreSQL 17.6

---

## 2. 資料庫連線 (Critical)
本專案的 FastAPI 後端使用 `asyncpg` 與 `SQLAlchemy 2.0` 非同步連線。直接連線 (Direct connection, port 5432) 在某些網路環境 (包含開發環境) 可能會遭遇 DNS 解析失敗 (`socket.gaierror`)。

🟢 **唯一正確的連線方式：透過 Transaction Pooler**
請在 `.env` 中如此設定：
```env
DB_HOST=aws-1-ap-northeast-1.pooler.supabase.com
DB_PORT=6543
DB_NAME=postgres
DB_USER=postgres.udydlelmkusyjmegtviq
DB_PASSWORD=<你的密碼>
```
*注意：`DB_USER` 必須包含 `.udydlelmkusyjmegtviq` 這個後綴，因為走的是 Pooler (PgBouncer)。*

### ⚠️ 連線地雷與解法 (Asyncpg + PL/Bouncer)
1. **密碼包含特殊字元 (`@`)**：密碼中若有 `@`，直接組裝 URL 會造成 SQLAlchemy 解析失敗，必須使用 `urllib.parse.quote(..., safe="")` 進行 URL Encode（例如 `@` -> `%40`）。目前已在 `app.core.config.py` 中實作。
2. **Prepared Statements 與 Transaction Pooler 衝突**：Supabase 的 Transaction Pooler 背後是 `PgBouncer(Transaction mode)`，**不支援** Prepared Statements。如果沒有停用，會跳出 `<class 'asyncpg.exceptions.DuplicatePreparedStatementError'>` 或 `cannot insert multiple commands into a prepared statement` 錯誤。
   * **解法**：在建立 `create_async_engine` 時，必須傳入 `connect_args={"statement_cache_size": 0}`。

---

## 3. Alembic 資料庫遷移 (Migration)
專案的 Schema 管理由 Alembic 負責。

### 🚨 Alembic 執行注意事項
1. **連線設定 (`env.py`)**：目前 Alembic `env.py` 已改為直接從 `settings.ASYNC_DATABASE_URL` 拿連線字串，避免 ConfigParser 解析 `%40` 時誤認為 Python interpolation (`ValueError: invalid interpolation syntax`) 導致閃退。
2. **SSL 強制要求**：Supabase 要求 SSL 連線。在 `env.py` 及 `database.py` 中，如果偵測到 `supabase` 或 `pooler.supabase`，會自動加上 `ssl=require` 參數。如果遇到連線斷開，請先檢查這段邏輯。
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
