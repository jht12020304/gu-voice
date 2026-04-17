# GU-Voice TODO 清單

> 依據 [`system_issues_and_risks.md`](./system_issues_and_risks.md) 整理的可執行待辦事項。
> 完成一項就把 `[ ]` 改成 `[x]`，並在後面加上完成日期與 commit hash。
>
> 最後更新：2026-04-18（P0 全部程式碼完成，Railway Dashboard 操作與 staging migrate 驗證待做）

---

## P0 — 阻斷級（上線前必修）

### [x] 1. 修 `auth_service.logout` 簽名不匹配 — 2026-04-17（待 commit）

- **檔案**：
  - `backend/app/services/auth_service.py:193`（定義）
  - `backend/app/routers/auth.py:122-126`（呼叫端）
- **要做**：
  - [ ] 重寫 `logout(db, user_id, refresh_token)`：內部 decode refresh token 取 jti 與 exp → 算 ttl → `redis.setex("gu:token_blacklist:{jti}", ttl, "1")`
  - [ ] 若 `refresh_token=None`，撤銷該使用者所有 refresh token（遍歷 Redis 或在 DB 有 sessions 表追蹤）
  - [ ] 加單元測試：登出後同一 access token 呼叫 `/api/v1/auth/me` 應回 401
- **驗收**：`curl -X POST /api/v1/auth/logout` 回 200，不再是 500

### [x] 2. Railway 開 Celery worker + beat service — 2026-04-17（待 commit；Dashboard 操作待手動執行，runbook 已寫）

- **檔案**：Railway Dashboard（不在 repo 內），可能需新增 `backend/scripts/start_worker.sh`、`backend/scripts/start_beat.sh`
- **要做**：
  - [ ] 在 Railway 專案建立 `gu-voice-celery-worker` service，`startCommand = celery -A app.tasks.celery_app worker --loglevel=info --concurrency=2`
  - [ ] 建立 `gu-voice-celery-beat` service，`startCommand = celery -A app.tasks.celery_app beat --loglevel=info`
  - [ ] 兩個 service 共用同一 Redis、同一組 env vars
  - [ ] 手動觸發一次 `check_session_timeouts` 驗證
- **驗收**：Railway logs 能看到 `beat: Starting...` 與每 5 分鐘的 session timeout 檢查輸出

### [x] 3. Firebase Admin SDK 在 lifespan 初始化 — 2026-04-17（待 commit）

- **檔案**：`backend/app/main.py`、新增 `backend/app/core/firebase.py`
- **要做**：
  - [ ] 新增 `app/core/firebase.py`：`initialize_firebase()` 函式，從 `GOOGLE_APPLICATION_CREDENTIALS_JSON`（base64 decode）讀入
  - [ ] `main.py` lifespan 啟動階段呼叫（FCM_CREDENTIALS 未設時要 log warning 不 raise，方便本機開發）
  - [ ] 移除 `notification_retry.py:85` 的動態 import，改成檔頂 import
  - [ ] 測試：手動發一則推播驗證
- **驗收**：冷啟動後第一次推播即可送達，不會 `ValueError: default Firebase app does not exist`

### [x] 4. Alembic migration 補分區表定義 — 2026-04-18（待 commit；需 staging fresh migrate 驗證）

- **檔案**：`backend/alembic/versions/` 新增一個 migration
- **要做**：
  - [ ] 新 migration：把 `conversations`、`audit_logs` 改成 PARTITION BY RANGE(created_at)
  - [ ] 建立當月 + 下月初始分區
  - [ ] `partition_manager.py` 只負責建新月份分區，不負責建 parent table
  - [ ] 在 staging 環境跑一次 `alembic upgrade head` 驗證
- **驗收**：新環境 fresh migrate 後，`\d+ conversations` 顯示 `Partitioned table, partition key: RANGE (created_at)`

### [x] 5. 修 Migration Enum 大小寫 vs ORM value 不一致 — 2026-04-18（待 commit；需 staging fresh migrate 驗證）

- **檔案**：
  - `backend/alembic/versions/20260412_0302-c98fa7840c8c_initial_schema.py`（目前用 `'PATIENT','DOCTOR'`）
  - `backend/app/models/enums.py`（value 是小寫）
  - 所有 ORM model 的 `Column(Enum(UserRole))`
- **要做**：
  - [ ] ORM 改用 `Enum(UserRole, values_callable=lambda x: [e.value for e in x])` 強制存小寫 value
  - [ ] 寫 data migration：`ALTER TYPE userrole RENAME VALUE 'PATIENT' TO 'patient'` 等（PG 12+ 支援）
  - [ ] 相同處理 `sessionstatus`、`alertseverity`、`conversationrole` 等所有 enum
  - [ ] 前端 `enums.ts` 不變（已經是小寫）
  - [ ] 跑整合測試確認 register / login / create session 正常
- **驗收**：DB 直接查 `SELECT role FROM users LIMIT 1` 回 `patient`（小寫），API response 也是小寫

---

## P1 — 本週內

### [ ] 6. JWT 黑名單檢查納入 `get_current_user`

- **檔案**：`backend/app/core/dependencies.py`
- **要做**：
  - [ ] `get_current_user` 在 `verify_access_token` 後，取 jti 檢查 `redis.exists("gu:token_blacklist:{jti}")`
  - [ ] 有命中 → raise `UnauthorizedException("Token 已失效")`
- **驗收**：登出後同一 access token 打 `/me` 回 401

### [ ] 7. OpenAI 呼叫統一 timeout + retry + token 預算

- **檔案**：新增 `backend/app/core/openai_client.py`、修改 5 個 pipeline
- **要做**：
  - [ ] `openai_client.py`：singleton `get_openai_client()` 回傳 `AsyncOpenAI(timeout=60)`
  - [ ] 用 `tenacity` 包 retry：`@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10), retry=retry_if_exception_type((APITimeoutError, RateLimitError)))`
  - [ ] 用 `tiktoken` 在送 LLM 前算 token 數，超過 `model_context_limit - max_tokens` 就截斷舊對話
  - [ ] `llm_conversation.py`、`supervisor.py`、`soap_generator.py`、`red_flag_detector.py`、`stt_pipeline.py`、`tts_pipeline.py` 全部改用 singleton
- **驗收**：手動模擬 OpenAI 429，系統能退避後重試成功

### [ ] 8. Axios 401 refresh race 改用 shared promise

- **檔案**：`frontend/src/services/api/client.ts`
- **要做**：
  - [ ] 把 `isRefreshing: boolean` 換成 `refreshPromise: Promise<string> | null`
  - [ ] 401 時若 `refreshPromise` 已存在就 await 同一個
  - [ ] Refresh 失敗：清空 refreshPromise、clear storage、導回 login
  - [ ] 單元測試：模擬同時 5 個請求 401，只應打一次 refresh endpoint
- **驗收**：DevTools Network 裡，token 過期後只看到一次 `/auth/refresh` 呼叫

### [ ] 9. Sentry 初始化 + 敏感資料過濾

- **檔案**：`backend/app/main.py`、`frontend/src/main.tsx` 或 `src/lib/sentry.ts`
- **要做**：
  - [ ] 後端：`sentry_sdk.init(dsn, environment, traces_sample_rate=0.1, send_default_pii=False, before_send=redact_sensitive)`
  - [ ] `redact_sensitive`：去掉 `password`、`access_token`、`refresh_token`、`Authorization` header
  - [ ] 前端：`Sentry.init({ dsn: VITE_SENTRY_DSN, tracesSampleRate: 0.1, beforeSend })`
  - [ ] 手動 `raise Exception("test")` 驗證 Sentry 收得到
- **驗收**：Sentry dashboard 能看到事件，且 payload 無密碼 / token

### [ ] 10. Prometheus instrument 接上

- **檔案**：`backend/app/main.py`
- **要做**：
  - [ ] `Instrumentator().instrument(app).expose(app)`（`/metrics` endpoint）
  - [ ] Railway 若有 Grafana 或外部 Prometheus，配 scrape config
- **驗收**：`curl /metrics` 能拿到 text format 指標

### [ ] 11. Refresh token rotation + reuse detection

- **檔案**：`backend/app/services/auth_service.py:148`
- **要做**：
  - [ ] 簽發 refresh token 時存 Redis：`gu:refresh:{user_id}:{jti} → 1`，TTL = 7 天
  - [ ] `refresh_token()` 檢查舊 jti 是否仍在 Redis（存在才允許換）→ 換完立刻刪除
  - [ ] 若偵測到舊 jti 已被刪但又被使用（reuse）→ 撤銷該 user 所有 refresh token，強制重新登入
- **驗收**：用同一 refresh token 連呼叫兩次，第二次回 401 並把該 user 登出

---

## P2 — 當月

### [ ] 12. `.env.example` / docker-compose / config.py 三者對齊

- **檔案**：`backend/.env.example`、`docker-compose.yml`、`backend/app/core/config.py`
- **要做**（推薦方案）：
  - [ ] `config.py` 加 `@field_validator` 優先讀 `DATABASE_URL`（有就用、沒有才組 `DB_*`）
  - [ ] `JWT_PRIVATE_KEY` 同上：若值包含 `BEGIN RSA` 當 PEM，否則當路徑
  - [ ] 把 `APP_LOG_LEVEL` / `LOG_LEVEL` 合併為單一欄位
  - [ ] 更新 `.env.example` 註解清楚兩種用法
- **驗收**：docker-compose up 能直接起、Railway 現有 env vars 不用改也能跑

### [ ] 13. Conversation 表加 `UNIQUE(session_id, sequence_number)` + `updated_at`

- **檔案**：新 migration、`backend/app/models/conversation.py`
- **要做**：
  - [ ] 新 migration 加 unique constraint + `updated_at` column
  - [ ] Model 加 `updated_at: Mapped[datetime]` with `onupdate=func.now()`
  - [ ] 如果已有重複 seq 資料，先寫清理 script

### [ ] 14. Login rate limit + OpenAI per-user limit

- **檔案**：`backend/app/routers/auth.py`、`backend/app/core/rate_limit.py`（新增）
- **要做**：
  - [ ] 用 Redis 做 sliding window
  - [ ] `/auth/login`：每 IP 每分鐘 10 次，超過回 429
  - [ ] 連續失敗 5 次：鎖帳號 10 分鐘
  - [ ] LLM 呼叫：每 user 每分鐘 20 次

### [ ] 15. WebSocket token 改 handshake message

- **檔案**：`frontend/src/services/websocket.ts`、`backend/app/websocket/conversation_handler.py`
- **要做**：
  - [ ] 前端連線不帶 `?token=`，連上後送 `{ type: "auth", token: <jwt> }`
  - [ ] 後端收到 auth message 前不處理其他訊息；驗證失敗 close(4001)
  - [ ] 兼容舊行為一段時間（query param 也接受），再慢慢切換

### [ ] 16. Supabase RLS policy

- **檔案**：Supabase SQL Editor（不在 repo）
- **要做**：
  - [ ] `sessions`：病患 `patient_id = auth.uid()`；醫師 `doctor_id = auth.uid() OR role='admin'`
  - [ ] `soap_reports`：依 session ownership
  - [ ] `red_flag_alerts`、`notifications` 同理
  - [ ] 把 SQL 存到 `docs/supabase_rls_policies.sql` 以便版本控制
- **驗收**：用病患 A 的 token 嘗試讀病患 B 的 session → 空結果

### [ ] 17. Audit log 實際落表 + 7 年保留

- **檔案**：`backend/app/core/middleware.py`、新 Celery task
- **要做**：
  - [ ] Middleware 非同步寫 `audit_logs` 表（sensitive 操作才寫）
  - [ ] 新 Celery task：每月清理 7 年前的分區 `ALTER TABLE audit_logs DETACH PARTITION ...` + `DROP`
- **驗收**：DB 查 `SELECT COUNT(*) FROM audit_logs` 每天有新紀錄

### [ ] 18. CORS `allow_methods` / `allow_headers` 收緊

- **檔案**：`backend/app/main.py:95-97`
- **要做**：明確列舉方法與 headers

### [ ] 19. HTTP 安全 header middleware

- **檔案**：新 `backend/app/core/middleware.py` 擴充
- **要做**：加 `SecurityHeaderMiddleware`（HSTS、X-Content-Type-Options、X-Frame-Options、Referrer-Policy）

### [ ] 20. Health check 加深度檢查

- **檔案**：`backend/app/main.py:160`
- **要做**：新增 `/api/v1/healthz/deep` 檢查 DB、Redis

### [ ] 21. `backend/.dockerignore` 新增

- **檔案**：新 `backend/.dockerignore`
- **要做**：排除 `.env`、`venv`、`.git`、`*.log`、`__pycache__`、`tests/`、`keys/`

---

## P3 — 技術債 / 長期改善

### [ ] 22. 前端型別補齊 + zod runtime validation

- `frontend/src/types/api.ts` 把 `unknown[]` 換成具體 interface
- 新裝 `zod`，關鍵 API response 加 schema 驗證

### [ ] 23. 前端 404 / loading / RoleGuard 改善

- `RootNavigator.tsx` 加 `<Route path="*" element={<NotFoundPage />} />`
- `RoleRedirect` 處理 `isLoading` 狀態
- `useAuthStore` 的 token 儲存統一以 localStorage 為 source of truth

### [ ] 24. 前端表單驗證

- Login / Register / 主訴選擇：接 `react-hook-form` + `zod`
- 密碼強度：至少 8 字、含數字 + 字母

### [ ] 25. Mock mode 在 production 強制關閉

- `vite.config.ts`：production build 時 `define: { "import.meta.env.VITE_ENABLE_MOCK": "false" }`

### [ ] 26. Safari / iOS 音訊相容性

- 真機測試：iOS Safari 錄音、播放
- `MediaRecorder` MIME type fallback
- `webkitAudioContext` fallback 確認

### [ ] 27. i18n 英文翻譯補齊

- `frontend/src/i18n/locales/en/*.json` 缺 key 補齊
- 搜尋硬編碼中文抽到 i18n

### [ ] 28. E2E 測試 + GitHub Actions CI

- 後端：`pytest-asyncio` + docker-compose 起 DB/Redis 跑 integration
- 前端：`playwright` 跑核心 happy path
- `.github/workflows/ci.yml`：PR 自動跑 lint + test + build

### [ ] 29. Redis DB index 分離

- Cache → `/0`、Celery broker → `/1`、Celery result → `/2`
- 修 `config.py` + docker-compose + Railway env

### [ ] 30. 音檔生命週期管理

- Celery Beat 加月度清理 task
- 或改用 Supabase Storage lifecycle rule

### [ ] 31. `forgot_password` 實作 email 發送

- 接 SendGrid / SES / Supabase Auth email
- Reset token 存 Redis `gu:reset:{token} → user_id`，TTL 30 分鐘

### [ ] 32. `docs/專案開發進度.md` 更新

- Prompt chain upgrade 已完成（Phase 4，41 tests）但未反映
- 加「最後更新日期」與「狀態」欄位

---

## 追蹤約定

- PR 描述附上 TODO 編號（例如 `Fixes TODO #3`）
- 合併後回此文件把 `[ ]` 改成 `[x]`，加完成日期 + commit：
  ```
  - [x] 3. Firebase Admin SDK 在 lifespan 初始化 — 2026-04-20 (abc1234)
  ```
- 新發現問題直接加到 P2 或 P3，P0/P1 保留現狀不擴編
- 每週 review 一次優先級
