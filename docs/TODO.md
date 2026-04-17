# GU-Voice TODO 清單

> 依據 [`system_issues_and_risks.md`](./system_issues_and_risks.md) 整理的可執行待辦事項。
> 完成一項就把 `[ ]` 改成 `[x]`，並在後面加上完成日期與 commit hash。
>
> 最後更新：2026-04-18（P0 全部完成：3 個 Railway service 都 ACTIVE，partition + enum migration 已在 staging 跑過）

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

### [x] 2. Railway 開 Celery worker + beat service — 2026-04-18 (1b7a41e)（worker + beat service 已 ACTIVE）

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

### [x] 4. Alembic migration 補分區表定義 — 2026-04-18 (caa60ce)（已在 Railway 主 API deploy 成功跑過 `alembic upgrade head`）

- **檔案**：`backend/alembic/versions/` 新增一個 migration
- **要做**：
  - [ ] 新 migration：把 `conversations`、`audit_logs` 改成 PARTITION BY RANGE(created_at)
  - [ ] 建立當月 + 下月初始分區
  - [ ] `partition_manager.py` 只負責建新月份分區，不負責建 parent table
  - [ ] 在 staging 環境跑一次 `alembic upgrade head` 驗證
- **驗收**：新環境 fresh migrate 後，`\d+ conversations` 顯示 `Partitioned table, partition key: RANGE (created_at)`

### [x] 5. 修 Migration Enum 大小寫 vs ORM value 不一致 — 2026-04-18 (caa60ce)（已在 Railway 主 API deploy 成功跑過 `alembic upgrade head`）

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

### [x] 6. JWT 黑名單檢查納入 `get_current_user` — 2026-04-18（待 commit）

- **檔案**：`backend/app/core/dependencies.py`、`backend/tests/unit/services/test_get_current_user_blacklist.py`
- **要做**：
  - [x] `get_current_user` 在 `verify_access_token` 後，取 jti 檢查 `redis.exists("gu:token_blacklist:{jti}")`
  - [x] 有命中 → raise `UnauthorizedException("Token 已失效")`
  - [x] 單元測試：blacklist 命中 → 401；未命中 → 正常通過（`test_get_current_user_blacklist.py`，2 tests pass）
- **驗收**：登出後同一 access token 打 `/me` 回 401

### [x] 7. OpenAI 呼叫統一 timeout + retry + token 預算 — 2026-04-18（待 commit）

- **檔案**：`backend/app/core/openai_client.py`（新增）、7 個 pipeline / websocket 呼叫點、`backend/tests/unit/services/test_openai_client.py`
- **要做**：
  - [x] `openai_client.py`：singleton `get_openai_client()`（`AsyncOpenAI(timeout=60)`）、`call_with_retry()`（tenacity AsyncRetrying，指數退避最多 3 次，白名單 `APITimeoutError / RateLimitError / APIConnectionError`）、`count_tokens` + `budget_messages`（保留 system、從頭部丟舊訊息）
  - [x] `llm_conversation.py`：`get_openai_client()` + `budget_messages` + `call_with_retry`（streaming 僅 create 時重試）
  - [x] `supervisor.py` / `soap_generator.py` / `red_flag_detector.py`：`call_with_retry` 包 JSON mode 呼叫
  - [x] `stt_pipeline.py`：每次重試重建 BytesIO；`tts_pipeline.py`：audio.speech.create 包 retry
  - [x] `websocket/conversation_handler.py` 中的動態 AsyncOpenAI 也切到 singleton
  - [x] 單元測試 8 tests pass（singleton、三類錯誤重試、非白名單不重試、上限 raise、budget 保留 system）
- **驗收**：測試模擬 RateLimitError 成功退避重試；模型 context_limit 被縮至極小時保留 system 並丟舊訊息

### [x] 8. Axios 401 refresh race 改用 shared promise — 2026-04-18（待 commit）

- **檔案**：`frontend/src/services/api/client.ts`
- **要做**：
  - [x] 把 `isRefreshing + failedQueue` 重寫成 `refreshPromise: Promise<string> | null`
  - [x] 401 時若 `refreshPromise` 已存在就 await 同一個，一次 `/auth/refresh` 對應所有併發請求
  - [x] Refresh 失敗：finally 清空 refreshPromise、`clearAuthAndRedirect()` 導回 login
  - [ ] 前端無 vitest / jest 設定，先以 type-check 通過 + `_getInflightRefresh()` debug hook 保留單測入口
- **驗收**：DevTools Network 裡，token 過期後只看到一次 `/auth/refresh` 呼叫；搭配後端 P1-#11 reuse detection 不會被自家併發踢掉

### [x] 9. Sentry 初始化 + 敏感資料過濾 — 2026-04-18（待 commit）

- **檔案**：`backend/app/core/sentry.py`（新增）、`backend/app/main.py`、`frontend/src/services/sentry.ts`（新增）、`frontend/src/main.tsx`、`backend/tests/unit/services/test_sentry_redact.py`
- **要做**：
  - [x] 後端 `init_sentry()`：`traces_sample_rate=0.1, send_default_pii=False, before_send=redact_sensitive`，FastAPI/Starlette/Asyncio integrations；lifespan 啟動時呼叫，未設 DSN 時 log warning 不阻擋
  - [x] `redact_sensitive`：遞迴清洗 dict/list，凡 key contains `password / access_token / refresh_token / authorization / api_key / secret / jwt / cookie` 均取代為 `[Filtered]`
  - [x] 前端 `src/services/sentry.ts`：同樣策略，`beforeSend` + `beforeBreadcrumb` 都套 redact；未設 `VITE_SENTRY_DSN` 靜默跳過
  - [x] 單元測試 5 tests pass（Authorization / body password+tokens / 巢狀 / 非敏感欄位不動 / Set-Cookie 大小寫）
  - [ ] 手動 `raise Exception("test")` 實機驗證 — 留給 deploy 後以 API 客戶端觸發
- **驗收**：Sentry dashboard 能看到事件，且 payload 無密碼 / token

### [x] 10. Prometheus instrument 接上 — 2026-04-18（待 commit）

- **檔案**：`backend/app/main.py`
- **要做**：
  - [x] `Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)`
  - [x] 本機 `TestClient` smoke test：`/metrics` 回 200 + text format 指標
  - [ ] Railway Grafana 或外部 Prometheus scrape config — deploy 後配
- **驗收**：`curl /metrics` 拿到 text format 指標 ✅

### [x] 11. Refresh token rotation + reuse detection — 2026-04-18（待 commit）

- **檔案**：`backend/app/services/auth_service.py`、`backend/tests/unit/services/test_refresh_token_rotation.py`
- **要做**：
  - [x] 簽發 refresh token 時存 Redis：`gu:refresh:{user_id}:{jti} → 1`，TTL = token exp - now
  - [x] `refresh_token()` atomic 消耗舊 jti（`DEL` 回傳 0 即視為 replay）
  - [x] 偵測到 reuse → 掃 `gu:refresh:{user_id}:*` 全刪，並 raise `UnauthorizedException("Refresh token 重複使用，請重新登入")`
  - [x] `logout()` 帶 refresh → 同步刪 rotation 登記；未帶 refresh → 撤銷該 user 所有 refresh 登記
  - [x] 單元測試 5 tests pass（rotate 成功、replay 被拒、未登記 jti 拒、logout 清 rotation）
- **驗收**：用同一 refresh token 連呼叫兩次，第二次回 401 並把該 user 登出

---

## P2 — 當月

### [x] 12. `.env.example` / docker-compose / config.py 三者對齊（2026-04-18 完成）

- **檔案**：`backend/.env.example`、`docker-compose.yml`、`backend/app/core/config.py`、`backend/tests/unit/core/test_config_env_precedence.py`
- **已做**：
  - [x] `config.py`：`DATABASE_URL` / `REDIS_URL` 改用 `validation_alias`，顯式值優先於 `DB_*` / `REDIS_*` 元件；`_to_sync_db_url` / `_to_async_db_url` 雙向標準化驅動後綴，連 Railway/Heroku 的 `postgres://` 舊格式都吃
  - [x] `JWT_PRIVATE_KEY` / `JWT_PUBLIC_KEY`：自動偵測 `BEGIN` 當 PEM 內容、否則當路徑；Railway 常見的字面 `\n` 會自動還原成真換行；未設時 fallback 到 `*_PATH`
  - [x] `APP_LOG_LEVEL` → `LOG_LEVEL` 單一欄位，對齊 `scripts/start.sh` / `.env.example` / `docker-compose.yml`
  - [x] `.env.example`：方案 A（顯式 URL）/ 方案 B（元件）並列並加註解；JWT 兩種用法都寫
  - [x] `docker-compose.yml`：註解標明顯式 URL 走優先分支、HS256 是 dev 用替代
  - [x] 測試：`tests/unit/core/test_config_env_precedence.py` 15 項（URL 優先序 / 驅動標準化 / PEM-vs-path / `\n` 還原 / HS256 略過 PEM / LOG_LEVEL 單一來源）
- **驗收**：`venv/bin/python -m pytest tests/unit/ -q --ignore=tests/unit/api` → 96 passed；`from app.main import app` 乾淨載入

### [x] 13. Conversation 表加唯一性保證 + `updated_at`（2026-04-18 完成）

- **檔案**：
  - `backend/alembic/versions/20260418_1400-conversations_updated_at_and_seq_guard.py`
  - `backend/app/models/conversation.py`
  - `backend/app/services/conversation_service.py`
  - `backend/tests/unit/services/test_conversation_seq_lock.py`
- **已做**：
  - [x] 新 migration 加 `updated_at TIMESTAMPTZ NOT NULL DEFAULT now()` + BEFORE UPDATE trigger (`conversations_set_updated_at_trg`) 自動維護
  - [x] 新 migration 加 BEFORE INSERT trigger (`conversations_check_seq_unique_trg`) 檢查 `(session_id, sequence_number)` 跨分區唯一（**分區表無法 native UNIQUE 除非納入 partition key，所以走 trigger**）
  - [x] 偵測現存 dupes 的 `DO $$ ... RAISE NOTICE`，不強制失敗（conversations 目前僅開發資料）
  - [x] `ConversationService.create` 加 `pg_advisory_xact_lock(hashtext(session_id))` 序列化同 session 的 `MAX(seq)+1` 計算，消除併發 race，trigger 退居兜底
  - [x] Model 加 `updated_at: Mapped[datetime]`（不靠 SQLAlchemy onupdate，由 DB trigger 維護）
  - [x] 單元測試 2 項（lock 在 MAX select 之前、lock key 為 session_id 字串）
  - [x] 真 PG（本機 supabase_db）驗證：重複插入被擋、updated_at 隨 UPDATE 前進、5x 併發插入在 advisory lock 下拿到唯一序號 2..6
- **驗收**：`alembic upgrade head` 乾淨套用；單元 98 passed；併發寫不再重號

### [x] 14. Login rate limit + OpenAI per-user limit (2026-04-18)

- **檔案**：`backend/app/core/rate_limit.py`（新增）、`backend/app/routers/auth.py`、`backend/app/services/auth_service.py`、`backend/app/websocket/conversation_handler.py`、`backend/tests/unit/core/test_rate_limit.py`（新增）
- **要做**：
  - [x] `SlidingWindowLimiter`：Redis sorted-set + `ZREMRANGEBYSCORE`/`ZCARD`/`ZADD` 在 atomic pipeline 中跑；超限時從 `ZRANGE(0, 0, withscores)` 算 `retry_after`（ceil 到下一秒，不超過 window）
  - [x] `enforce_login_ip_rate_limit(ip)`：每 IP 每分鐘 10 次，`/auth/login` 路由從 `X-Forwarded-For` 第一段取 IP（Railway/Cloudflare 代理層），超過抛 `RateLimitExceededException`（HTTP 429，`scope="ip"`）
  - [x] `enforce_account_not_locked` + `record_login_failure` + `clear_login_failures`：連續 5 次失敗寫 `gu:rl:login_locked:{email}`（TTL 600s）並清計數；成功登入呼叫 `clear_login_failures`；email 一律 `.lower()` 避免大小寫繞過
  - [x] `AuthService.login` 流程：IP 檢查 → 帳號鎖定檢查 → 密碼驗證（失敗時 `record_login_failure` 再 re-raise `InvalidCredentials`）→ 成功時 `clear_login_failures`
  - [x] `enforce_llm_per_user_rate_limit(user_id)`：每 user 每分鐘 20 次；在 `_handle_audio_chunk` 於 `is_final=True` 後、STT 之前檢查（一次語音輪次算 1 次），超限走 WS `error` frame `{code: "RATE_LIMIT_EXCEEDED", retryAfter}` 並 return，不中斷連線
  - [x] 單元測試 12 項（sliding window 允許/阻擋邊界、IP 第 11 次觸發、空 IP 跳過、失敗計數第 5 次鎖且清計數、鎖定期間 enforce_account_not_locked 抛/未鎖通過、clear 清計數+鎖、大小寫混用不逃過、LLM 超限、多 user 互不影響、`user_id=None` 跳過）
- **驗收**：單元 110 passed；`from app.main import app` 乾淨；key 命名 `gu:rl:*` 便於維運 `SCAN` 分類

### [x] 15. WebSocket token 改 handshake message (2026-04-18)

- **檔案**：`backend/app/websocket/auth.py`（新增）、`backend/app/websocket/conversation_handler.py`、`backend/app/websocket/dashboard_handler.py`、`backend/app/websocket/connection_manager.py`、`frontend/src/services/websocket.ts`、`backend/tests/unit/websocket/test_auth_handshake.py`（新增）
- **要做**：
  - [x] 共用 `authenticate_websocket(ws, context)`：先 `accept()` → 試 `?token=`（legacy，有 warning log）→ 否則 `receive_text()` 等 handshake，5s 逾時；成功回 JWT payload，失敗統一 `close(4001)`
  - [x] `ConnectionManager.connect_session` / `connect_dashboard` 加 `already_accepted=False` 參數，讓 handshake 先 accept 後再註冊不會 double-accept
  - [x] `conversation_handler` / `dashboard_handler` 切換到共用 helper；保留舊查詢參數模式兼容一段時間
  - [x] 前端 `WebSocketManager.createConnection`：URL 不再帶 `?token=`；`onopen` 送 `{type:"auth", token:...}`（頂層 raw，不走 `this.send()` 的 WSMessage 信封）
  - [x] 單元測試 12 項（handshake 成功、legacy query 兼容、accept 只呼叫一次、`type=authenticate` alias、JWT 無效 / timeout / 非 JSON / 錯 type / 缺 token / 空 token / 非 dict JSON 都 close 4001）
- **驗收**：單元 122 passed；`from app.main import app` 乾淨；完全移除 query-param 路徑只需刪 `authenticate_websocket` 內 legacy 分支並確認日誌為 0

### [x] 16. Supabase RLS policy (2026-04-18)

- **檔案**：`docs/supabase_rls_policies.sql`（新增，約 260 行）
- **要做**：
  - [x] 4 個 helper function：`gu_current_user_role()`、`gu_is_admin()`、`gu_is_doctor_or_admin()`、`gu_current_patient_id()`（STABLE + SECURITY DEFINER，讀 `public.users` / `public.patients` 表判斷）
  - [x] `sessions`：病患經 patients.user_id = auth.uid() 推回 patient_id；醫師 `doctor_id = auth.uid() OR doctor_id IS NULL`（可接候補）；admin 全開；INSERT 限自己名下、UPDATE 限自己負責或 admin
  - [x] `soap_reports`：依 session ownership 判讀取；醫師 UPDATE 限自己負責的
  - [x] `red_flag_alerts`：同 soap；醫師 acknowledge 限自己負責或未指派
  - [x] `notifications`：`user_id = auth.uid()` 讀寫；admin 可讀全部
  - [x] Throwaway postgres:15-alpine 驗證：套用 SQL 乾淨；病患 A 讀 sessionB → **0 rows**；醫師 D（指派 A）看 2 場；醫師 E（未指派）看 1 場；admin 看 2 場／全表
- **驗收**：Throwaway 驗證全部 pass；所有 `DROP POLICY IF EXISTS` + `CREATE POLICY` 皆可重跑；service_role（後端 FastAPI）自動 bypass RLS 不影響現有邏輯

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
