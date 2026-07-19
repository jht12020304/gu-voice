# GU-Voice 系統問題與斷點盤點

本文件由資深全端工程師角度審閱，列出需要修復的問題、技術債、以及部署風險。
所有 🔴 嚴重項目皆經過程式碼驗證；🟡 警告與 🟢 建議項目可能需開發者再次確認情境。

> 盤點範圍：backend/ + frontend/ + alembic/ + docker-compose + railway.toml + .env/.env.example
> 盤點日期：2026-04-17
> 相關文件：[system_overview.md](./system_overview.md)、[deployment_guide.md](./deployment_guide.md)

---

## 嚴重度圖例

- 🔴 **嚴重**：會在 production 造成功能失效、資安漏洞、或資料錯誤
- 🟡 **警告**：技術債、行為不一致、或潛在 UX/效能問題
- 🟢 **建議**：最佳實踐改善

---

## 一、後端 — 🔴 嚴重

### 1.1 `auth_service.logout` 簽名不匹配，呼叫會拋 TypeError

- **位置**：
  - 定義：`backend/app/services/auth_service.py:193` — `async def logout(redis, jti: str, ttl: int)`
  - 呼叫：`backend/app/routers/auth.py:122-126` — `await auth_service.logout(db, user_id=..., refresh_token=...)`
- **問題**：參數名與型別完全對不上，實際呼叫會 `TypeError`
- **影響**：登出 API 永遠 500；token 無法加入黑名單，被盜 token 無法撤銷
- **建議**：重新實作 `logout`：接 `db`、`user_id`、`refresh_token`，內部解析 jti/ttl 寫入 Redis，同時撤銷 refresh token

### 1.2 JWT 黑名單未在驗證環節檢查

- **位置**：`backend/app/core/dependencies.py`（`get_current_user` 流程）
- **問題**：即使把 jti 寫入 `gu:token_blacklist:{jti}`，驗證時沒檢查
- **影響**：登出形同虛設，舊 token 繼續可用
- **建議**：`get_current_user` 先 `verify_access_token` → 取 jti → `await redis.exists(f"gu:token_blacklist:{jti}")` → 有就拒絕

### 1.3 Migration Enum 大小寫與 ORM value 不一致

- **位置**：
  - Migration：`backend/alembic/versions/20260412_0302-c98fa7840c8c_initial_schema.py:28,166,…` — `sa.Enum('PATIENT', 'DOCTOR', 'ADMIN', name='userrole')` 大寫
  - ORM：`backend/app/models/enums.py` — `PATIENT = "patient"` 小寫 value
- **問題**：SQLAlchemy 預設存 Python enum 的 **name**（大寫），但程式判斷時常用 `role.value`（小寫），資料庫 CHECK/ENUM TYPE 的值也是大寫
- **影響**：
  - 前端 `enums.ts` 用小寫 `"patient"`，API response 若直接回傳 enum value 會不一致
  - 新建記錄可能踩到 `invalid input value for enum`
- **建議**：明確設定 `Enum(UserRole, values_callable=lambda x: [e.value for e in x])` 讓 DB 存 value（小寫），並寫 data migration 轉換舊資料

### 1.4 Sentry SDK 未初始化

- **位置**：`backend/app/main.py`（無 `sentry_sdk.init` 呼叫）
- **驗證**：`grep sentry_sdk.init` 全專案無匹配
- **影響**：`requirements.txt` 裝了 `sentry-sdk[fastapi]==2.19.2` 但從未啟動；正式環境錯誤不會上報
- **建議**：在 `lifespan` 啟動階段加：
  ```
  sentry_sdk.init(dsn=settings.SENTRY_DSN, environment=settings.APP_ENV,
                  traces_sample_rate=0.1, send_default_pii=False,
                  before_send=_redact_sensitive)
  ```

### 1.5 Firebase Admin SDK 未初始化

- **位置**：`backend/app/tasks/notification_retry.py:85`（task 內才動態 `import firebase_admin.messaging` 並 `send`）
- **驗證**：`grep firebase_admin.initialize_app` 全專案無匹配
- **影響**：第一次呼叫 `messaging.send()` 會 `ValueError: The default Firebase app does not exist`；所有推播任務失敗
- **建議**：在 lifespan 啟動時呼叫 `firebase_admin.initialize_app(credentials.Certificate(...))`，憑證從 `GOOGLE_APPLICATION_CREDENTIALS_JSON`（base64）或檔案路徑讀入

### 1.6 Celery Worker / Beat 在 Railway 未啟動

- **位置**：`backend/railway.toml`（只有一個 `start.sh` 啟 Uvicorn）
- **問題**：`app/tasks/__init__.py` 有 Celery app 與 beat_schedule，但 Railway 沒有另開 worker service
- **影響**：
  - `check-session-timeouts`（5 分鐘檢查閒置）從未執行
  - `ensure-monthly-partitions`（每月建分區）從未執行 → conversations/audit_logs 分區表新月份會寫不進去
  - `report_queue`、`notification_retry` task 也沒有 worker 在跑
- **建議**：Railway 上建立兩個 service：`celery-worker`（`celery -A app.tasks.celery_app worker`）與 `celery-beat`（`celery -A app.tasks.celery_app beat`），共用同一個 Redis

### 1.7 OpenAI 呼叫缺 timeout / retry / rate-limit 處理

- **位置**：`backend/app/pipelines/llm_conversation.py`、`supervisor.py`、`soap_generator.py`、`stt_pipeline.py`、`tts_pipeline.py`
- **問題**：
  - `AsyncOpenAI(...)` 未設 timeout，可能永久掛起
  - 沒有 `openai.RateLimitError` / `APITimeoutError` 的 retry
  - `tiktoken==0.8.0` 有裝但沒用到（沒做 token 預算檢查）
- **影響**：OpenAI 短暫 5xx 或限流時整個問診流程中斷；長 prompt 可能超過模型限制
- **建議**：
  - 建立 `app/core/openai_client.py` 工廠函式，統一設 `timeout=60`
  - 包一層 `tenacity` retry（`requirements.txt` 已裝 tenacity 9.0）— 指數退避、最多 3 次
  - LLM 呼叫前用 tiktoken 估算 prompt token，超過則截斷 conversation_history

### 1.8 Alembic migration 沒有建立分區表結構

- **位置**：`backend/app/tasks/partition_manager.py` vs `backend/alembic/versions/`
- **問題**：`conversations`、`audit_logs` 的 parent partitioned table 與初始分區沒在 migration 裡；partition_manager.py 靠 runtime 建立下月分區，但 base table 的 `PARTITION BY RANGE(created_at)` 定義在哪？
- **影響**：第一次 `alembic upgrade head` 建出來的 `conversations` 可能是一般表，不是分區表；之後 partition_manager 的 `ATTACH PARTITION` 會失敗
- **建議**：在 initial schema migration 直接用 `op.execute("CREATE TABLE conversations (...) PARTITION BY RANGE (created_at)")` 並建立當月 + 下月分區

### 1.9 `forgot_password` 是 placeholder

- **位置**：`backend/app/services/auth_service.py:234-240` 註解明確寫「目前為 placeholder，實際應整合 email 發送服務」
- **影響**：`/api/v1/auth/forgot-password` 永遠不會真的寄信
- **建議**：整合 SendGrid / SES / Supabase Auth email；或至少在回應清楚標示「功能尚未開通」

---

## 二、後端 — 🟡 警告

### 2.1 `.env.example` 與 `config.py` 欄位名大量不一致

| `.env.example` 寫的 | `config.py` 實際讀的 | 結果 |
|--------------------|---------------------|------|
| `DATABASE_URL=postgresql+asyncpg://...` | `DB_HOST`、`DB_PORT`、`DB_NAME`、`DB_USER`、`DB_PASSWORD` | `DATABASE_URL` 被 `extra="ignore"` 忽略 |
| `REDIS_URL=redis://...` | `REDIS_HOST`、`REDIS_PORT`、`REDIS_PASSWORD`、`REDIS_DB` | 同上被忽略 |
| `LOG_LEVEL=INFO` | `APP_LOG_LEVEL`（內部 logger）+ `start.sh` 的 `LOG_LEVEL`（uvicorn） | 兩者並存但容易混淆 |
| `JWT_PRIVATE_KEY=<PEM 內容>` | `JWT_PRIVATE_KEY_PATH=<檔案路徑>` | 存 PEM 到 env 讀不到 |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES=30` | `ACCESS_TOKEN_EXPIRE_MINUTES=15` | 不同名、預設值也不同 |
| `DATABASE_POOL_SIZE` | `DB_POOL_SIZE` | 不同名 |

- **建議**：二選一統一
  - 方案 A：更新 `.env.example` 與 `docker-compose.yml` 改用 `DB_HOST` 等分段欄位
  - 方案 B（推薦，雲端友善）：在 `config.py` 加 `@field_validator`，優先吃 `DATABASE_URL` / `REDIS_URL`；把 `JWT_PRIVATE_KEY` 直接當內容讀

### 2.2 `docker-compose.yml` 環境變數與 config.py 不匹配

- `docker-compose.yml:47-53` 用 `DATABASE_URL`、`REDIS_URL`、`LOG_LEVEL`
- Backend 容器讀不到，會 fallback 到 `DB_HOST=localhost`（容器內沒 postgres）→ 連線失敗
- **建議**：同 2.1，改成 `DB_HOST=postgres`、`DB_PORT=5432`、`REDIS_HOST=redis` 等

### 2.3 CORS `allow_methods=["*"]`、`allow_headers=["*"]`

- **位置**：`backend/app/main.py:95-97`
- **問題**：搭配 `allow_credentials=True` 雖然 `allow_origins` 不是 `*` 所以沒違規，但預設行為寬鬆
- **建議**：列明 `["GET","POST","PUT","PATCH","DELETE","OPTIONS"]` 與常用 headers（`Authorization`、`Content-Type`、`X-Request-Id`）

### 2.4 無 HTTP 安全 header middleware

- 後端無 `Strict-Transport-Security`、`X-Content-Type-Options`、`X-Frame-Options`、`Referrer-Policy`
- **建議**：寫一個 `SecurityHeaderMiddleware`，或直接在 Railway 的 proxy 層加

### 2.5 Login endpoint 無 rate limit

- **位置**：`backend/app/routers/auth.py:64-75`
- **問題**：密碼用 bcrypt 延緩了暴力破解，但沒有 IP / 帳號嘗試次數限制
- **建議**：`slowapi` 或 Redis 手刻計數器：每 IP 每分鐘 10 次、連續失敗 5 次鎖帳號 10 分鐘

### 2.6 OpenAI 端內部無限流

- **位置**：所有 pipeline
- **問題**：一個病患長對話可能用光整個組織的 rate limit 額度
- **建議**：以 user_id 為 key 在 Redis 做 sliding window（例如每人每分鐘 ≤ 20 次 LLM 呼叫）

### 2.7 Prometheus Instrumentator 沒接

- **位置**：`requirements.txt:64` 裝了 `prometheus-fastapi-instrumentator==7.0.2`，`main.py` 沒呼叫
- **影響**：沒有 HTTP 延遲 / 錯誤率指標
- **建議**：`Instrumentator().instrument(app).expose(app)` 一行就接上

### 2.8 Health check 過淺

- **位置**：`backend/app/main.py:160-167` 只回硬編碼 `status="ok"`
- **建議**：檢查 DB `SELECT 1`、Redis `PING`、OpenAI 可選（會燒錢，只在 `/healthz/deep` 跑）

### 2.9 `AuditLoggingMiddleware` 只寫 logger，不寫 audit_logs 表

- **位置**：`backend/app/core/middleware.py`（推測，需確認）
- **問題**：`audit_logs` 資料表存在但沒人寫入，合規保留 7 年從何談起
- **建議**：middleware 非同步把關鍵動作寫進表（login、register、admin 操作、敏感讀取）

### 2.10 `exceptions.py` unhandled_exception 可能洩漏堆疊

- **建議**：production 環境回傳「伺服器錯誤，請稍後再試」，完整 stack 只記到 logger + Sentry

### 2.11 WebSocket 記憶體 / 限流風險

- **位置**：`backend/app/websocket/connection_manager.py`、`conversation_handler.py`
- **問題**：
  - `active_connections` dict 沒有上限
  - 單條連線沒有訊息大小 / 頻率限制
- **建議**：連線數上限、訊息限 `max_size=1MB`、每秒 token 預算限制

### 2.12 `conversation_handler.py` reconnect checksum 機制過嚴

- **位置**：`backend/app/routers/sessions.py:159-213`（重連端點）+ handler 的 resumeFrom 邏輯
- **問題**：用內容 checksum 驗證，中間任一字訂正過就對不上 → fallback 到全新 session
- **建議**：改用 sequence number + timestamp，允許輕微差異時提示使用者

### 2.13 測試僅涵蓋 prompt 單元測試

- **位置**：`backend/tests/`
- **問題**：無 DB/Redis/WebSocket 整合測試、沒有 CI
- **建議**：補 pytest-asyncio + docker-compose 跑 integration；`.github/workflows/` 加 CI

---

## 三、前端 — 🔴 嚴重

### 3.1 Axios 401 refresh token race condition

- **位置**：`frontend/src/services/api/client.ts`（interceptor）
- **問題**：用布林 `isRefreshing` + queue，並發多請求 401 可能觸發多次 refresh；refresh 失敗後殘留狀態
- **建議**：改用單一 `refreshPromise: Promise<string> | null`，所有同時 401 的請求 await 同一個 promise

### 3.2 WebSocket token 以 query string 傳遞

- **位置**：`frontend/src/services/websocket.ts`（連線時把 JWT 放在 URL）
- **風險**：
  - 會出現在 browser history、server access log、proxy log
  - 若有 crash reporting 把 URL 送出也會外洩
- **建議**：建連線後第一則訊息送 `{ type: "auth", token }`，或用 WebSocket subprotocol header

---

## 四、前端 — 🟡 警告

### 4.1 Token 存在 localStorage（XSS 可竊取）

- **位置**：`frontend/src/stores/authStore.ts`
- **權衡**：localStorage 易用但對 XSS 零防禦
- **建議**：長期改用 `httpOnly; Secure; SameSite=Strict` cookie（需後端配合），短期至少確保 CSP + 無 innerHTML 拼接

### 4.2 `lucide-react@^1.8.0` 版本異常

- **位置**：`frontend/package.json:26`
- **問題**：實際 lucide-react 主版本是 `0.xxx`（例 `0.468.0`），`1.8.0` 是錯的包或非主線
- **建議**：`npm ls lucide-react` 確認，改為 `^0.468.0` 或最新穩定版

### 4.3 WebSocket 重連無限重試（token 過期不停重連）

- **位置**：`frontend/src/services/websocket.ts`
- **建議**：close code 4001（認證失敗）時停止重連並導回登入

### 4.4 MediaStream 釋放在例外路徑缺失

- **位置**：`frontend/src/services/audioStream.ts`
- **問題**：`getUserMedia` 成功但 `AudioContext` 失敗時，track 沒 stop → 麥克風燈一直亮
- **建議**：用 try/finally 包 cleanup

### 4.5 型別寬鬆

- `frontend/src/types/api.ts`：`medicalHistory?: unknown[]`、`Record<string, unknown>` 等
- 建議補具體 interface，或用 zod runtime schema 驗證 API 回傳

### 4.6 無 404 / NotFound 頁面

- **位置**：`frontend/src/navigation/RootNavigator.tsx`
- 建議：`<Route path="*" element={<NotFoundPage />} />`

### 4.7 `RoleGuard` 未處理 `isLoading`

- 未登入時短暫閃爍受保護頁面

### 4.8 表單驗證不足

- Login / Register 無 email 格式、密碼強度驗證
- 建議用 `react-hook-form` + `zod` 或 `yup`

### 4.9 Mock mode 旗標可能誤上 production

- `VITE_ENABLE_MOCK`
- 建議 `vite.config.ts` production build 階段 `define` 強制為 `false`

### 4.10 i18n 翻譯不完整

- `src/i18n/locales/en/conversation.json` 缺 key；許多中文硬編碼未抽出

### 4.11 音訊錄音 Safari / iOS 相容性未處理

- MediaRecorder MIME type、`webkitAudioContext` fallback
- 建議在目標裝置實測並加 fallback

---

## 五、資安與部署 — 🔴 嚴重

### 5.1 `backend/.env` 本機含真實 key；雖未提交 git，仍需留意

- **狀況**：`.env` 本機存在、含真實 OpenAI key、Supabase service role key、DB 密碼
- **驗證**：`git ls-files | grep .env` → 只列出 `.env.example` 與 `frontend/.env.production`（前端那支通常只有 anon key，公開無妨），**`backend/.env` 沒被追蹤** ✓
- **剩餘風險**：
  - 本機 `.env` 若被誤 `cp .env backend/app/` 或列入備份 zip 仍會外洩
  - 團隊其他人若沒看 `.gitignore` 可能會誤提交 `.env.local`
- **建議**：
  - 加 `pre-commit` hook `detect-secrets` 擋誤提交
  - 定期輪替 OpenAI key（每季）
  - Supabase service role key 改存 Railway 環境變數，本機開發用 anon key + RLS policy

### 5.2 Vercel `frontend/.env.production` 有追蹤，需確認只含 public key

- **驗證**：`git ls-files` 有 `frontend/.env.production`
- **建議**：確認檔案只含 `VITE_SUPABASE_URL` 與 `VITE_SUPABASE_ANON_KEY`（這支 anon key 本來就是公開的，搭配 RLS 使用才安全）；**絕對不可** 放 service role key

### 5.3 無 Supabase RLS policy（假設）

- **位置**：無處可看 SQL policy 設定
- **風險**：API 層雖有 `require_role`，但沒有 DB 層隔離；若 service role key 洩漏或 API 漏檢查，病患能撈別人的 SOAP
- **建議**：
  - 每個有 owner 的表（sessions、soap_reports、red_flag_alerts、notifications）啟 RLS
  - 醫師 / 病患政策分別寫 policy
  - 即使以 service role 繞過 RLS，也要在 API 層做 ownership check

### 5.4 RS256 金鑰管理混亂

- **位置**：`backend/app/core/config.py:74-98`
- **問題**：`JWT_ALGORITHM` 預設 RS256，但 `JWT_PRIVATE_KEY_PATH="keys/private.pem"` 讀檔；Railway 上通常是把 PEM 內容直接貼 env var 而不是檔案
- **現況**：若讀不到檔，config.py 回空字串，簽 token 時應該會拋錯
- **建議**：支援 `JWT_PRIVATE_KEY`（PEM 內容）優先於 `JWT_PRIVATE_KEY_PATH`，兩者都有就取 env

### 5.5 Refresh token 沒有 rotation / reuse detection

- **位置**：`backend/app/services/auth_service.py:148-190`
- **問題**：`refresh_token()` 發新 pair 但沒撤銷舊 refresh token；若舊 token 被盜，攻擊者可一直換
- **建議**：
  - 每個 refresh token 存 Redis `gu:refresh:{jti} → user_id` + TTL
  - 用過就刪（或加 blacklist）
  - 偵測到重複使用（舊 jti 又出現）→ 撤銷該使用者全部 session

### 5.6 Dockerfile 沒有 `.dockerignore`

- **位置**：`backend/`
- **風險**：`COPY . /app` 可能把 `.env`、`venv/`、`.git/`、`tests/`、`backend.log` 打進 image
- **建議**：加 `backend/.dockerignore`：
  ```
  .env
  .env.*
  venv/
  .venv/
  .git
  *.log
  __pycache__
  *.pyc
  tests/
  keys/
  ```

---

## 六、資料層與觀測性

### 六.1 🔴 模型 / migration 問題

#### 6.1.1 Conversation 表缺 `UNIQUE(session_id, sequence_number)`

- `backend/app/models/conversation.py`、initial migration
- **影響**：同一 session 可能有重複 seq → 對話順序錯亂
- **建議**：加 unique constraint，程式端塞資料前 `SELECT MAX(seq)+1`（或改 Postgres sequence）

#### 6.1.2 Conversation 無 `updated_at`

- 改對話內容後無法追蹤修改時間，稽核弱
- **建議**：加 `updated_at` + `onupdate=now()`

#### 6.1.3 所有 FK 未宣告 `ondelete`

- `session.doctor_id`、`notification.user_id`、`audit_log.user_id` 等
- **建議**：依業務語意分別設 `CASCADE` / `SET NULL` / `RESTRICT`

### 六.2 🟡 OpenAI 整合

- 各 pipeline 各自 `new AsyncOpenAI(...)` — 無連線池、無統一 retry
- `gpt-5.4-mini` 這個模型名稱需確認你的 OpenAI 組織額度可用；建議在應用啟動時 `await client.models.list()` 驗證至少一個 production 模型可達
- `tiktoken` 裝了但沒用

### 六.3 🟡 Redis 使用

- Celery broker 與 cache 共用同一 DB index（都用 `settings.REDIS_URL`）
- 建議分 DB：`/0` cache、`/1` celery broker、`/2` celery result

### 六.4 🟡 Supabase Storage 音檔生命週期未定

- 沒看到自動刪除機制（法規常要求 3 年或特定期間）
- 建議：Celery Beat 加月度清理 task；或用 Supabase Storage 的 lifecycle rule

### 六.5 🟡 WebSocket missed message 無補回

- 斷線重連期間送出的事件遺失
- 建議：以 Redis list 緩存最近 N 則，重連時帶 `resumeFrom=seq` 補送

### 六.6 🟡 Audit log 合規保留期未實作

- 資料模型有 `audit_logs`，但無自動清理 task、無分區剪除
- 若合規要保留 7 年，需文件化並用 partition detach 清舊資料

---

## 七、文件 / 流程

- 🟡 `./專案開發進度.md` 與實際程式碼漂移：例如 prompt upgrade 已完成（41 tests），但進度文件未更新
- 🟡 `.env.example` 與 `config.py` 不一致（見 2.1），新人難以上手
- 🟢 `docs/` 有多份 spec 檔（backend_spec、frontend_spec、api_spec…）但沒有「最新狀態」標注；建議頂部加「最後更新日期」與「狀態：已對齊實作 / 待更新」

---

## 八、優先修復順序

### P0（阻斷級，立即修）

1. **`auth_service.logout` 簽名不匹配**（§1.1）— logout API 現在就是壞的
2. **Celery worker / beat 在 Railway 沒啟動**（§1.6）— session_timeout 與分區管理都沒在跑
3. **Firebase 未 initialize_app**（§1.5）— 推播任務會炸
4. **Alembic 分區表定義缺失**（§1.8）— 會在下月 1 號爆炸
5. **Migration enum 大小寫 vs ORM value 衝突**（§1.3）— 任何 role 查詢都有風險

### P1（下週內）

6. **JWT 黑名單在 `get_current_user` 檢查**（§1.2）
7. **OpenAI timeout / retry / tiktoken 預算**（§1.7）
8. **Axios 401 refresh race condition**（§3.1）
9. **Sentry init + Prometheus instrument**（§1.4、§2.7）
10. **Refresh token rotation + reuse detection**（§5.5）

### P2（當月完成）

11. `.env.example` 與 config.py 對齊 + docker-compose 修正（§2.1、§2.2）
12. Conversation unique constraint + updated_at（§6.1.1、§6.1.2）
13. Login rate limit（§2.5）+ OpenAI 使用者限流（§2.6）
14. WebSocket token 改 handshake message（§3.2）
15. Supabase RLS policy（§5.3）
16. Audit log 實際落表 + 清理策略（§2.9、§6.6）

### P3（技術債）

17. 前端型別補齊、zod runtime 驗證
18. Safari / iOS 音訊相容
19. i18n 英文翻譯補齊
20. E2E 測試 + GitHub Actions CI

---

## 九、需再次人工確認的項目

以下是 agent 報告中有疑慮、我還沒完全驗證的點，建議實際開啟檔案或跑一次程式確認：

1. Supabase 是否已啟用 RLS（無法從本地 repo 判斷）
2. Sentry DSN 是否在 Railway env vars 中設定（決定 §1.4 修完是否生效）
3. 實際 production 使用的 OpenAI 組織是否有 `gpt-5.4-mini` 模型存取權
4. `backend/.env` 是否僅存在於本機；團隊所有成員機器是否都 gitignore 正確
5. `frontend/.env.production` 實際內容（必須僅含 public 值）
6. Railway 是否另外設有 Celery worker / beat service（若沒看到請照 §1.6 建立）

---

## 十、結語

目前系統核心功能（問診、SOAP 生成、紅旗、Dashboard）大致到位，但上線前至少要把 P0 清單清掉，否則：

- 使用者點「登出」會看到 500（§1.1）
- 閒置 session 永不超時、下個月分區會爆（§1.6、§1.8）
- 推播一則都發不出（§1.5）
- 正式錯誤完全沒人知道（§1.4）

以上。修完 P0 + P1 後，這份文件請再跑一次檢查並更新狀態。
