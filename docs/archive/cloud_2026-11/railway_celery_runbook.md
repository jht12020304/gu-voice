# Railway Celery Worker / Beat 部署 Runbook

> ## ⚠️ 2026-07-26：現行做法是同容器，本文件是「要拆成獨立 service 時」才照著做
>
> `backend/scripts/start.sh` 已在**主 API 容器內**起 celery worker + beat，
> 由 `RUN_CELERY_IN_API`（預設 `true`）控制。生產目前就是這個型態，
> **不需要照本文件建 service**。
>
> 同容器的理由：(a) 不必跨 service 複製 20+ 個環境變數（本文件步驟 4 自己就警告過
> 每個 service 的 DB pool 要各自調，那是漂移來源）；(b) 每多一個常駐 service 就多一組
> Supabase session-pooler 連線，正是 2026-07-04 pooler idle 佔滿事故的成因。
>
> **什麼時候該照本文件拆出去**：worker 吃掉 API 的 CPU 影響問診延遲、需要獨立擴縮 worker、
> 或要把 `numReplicas` 調大（beat 全系統只能一個副本，**調大 replicas 前必須先拆 beat**，
> 否則排程重複觸發）。拆完把 `RUN_CELERY_IN_API=false`。
>
> 歷史：本文件原寫「TODO #2 已完成、worker + beat service 已 ACTIVE」——那是假的，
> 2026-07-26 實查兩個 service 都不存在，導致 #31 的 Celery 單一路徑一上生產就讓 SOAP
> 全部卡 GENERATING（見 PR #34）。

---

> 對應 TODO #2（P0）。背景：Railway 原本只部署了 FastAPI 主服務，Celery 的
> worker 與 beat 從未被啟動，所有排程任務（session 超時檢查、分區建立、推播重試）
> 都不會執行。以下是手動於 Railway Dashboard 建立兩個新 service 的步驟。

---

## 目前 repo 內已備好的資產

| 檔案 | 用途 |
|------|------|
| `backend/scripts/start_worker.sh` | Celery worker 啟動腳本（優雅關閉 + concurrency/log level env） |
| `backend/scripts/start_beat.sh`   | Celery beat 啟動腳本（單一副本，schedule 寫到 `/tmp`） |
| `backend/app/tasks/__init__.py`   | Celery app 定義，`beat_schedule` 含兩個 task |

兩個 script 已 `chmod +x`，Dockerfile 與 API service 共用同一 image。

---

## Railway Dashboard 操作步驟

### 1. Worker Service

1. Project → **+ New** → **Empty Service**，命名為 `gu-voice-celery-worker`
2. **Settings → Source** 選同一個 GitHub repo、同一分支，root 設為 `backend/`

   > 主 API service（專案 `gu-voice-api` / service `gu-voice-app`，
   > https://gu-voice-app-production.up.railway.app）用 Docker build
   > （`RAILWAY_DOCKERFILE_PATH=Dockerfile`）。
   > ⚠️ **2026-07-26 更正：部署是手動的**——`cd backend && railway up --detach --service gu-voice-app`。
   > GitHub App 的 check suite 在每次 main merge 都永遠停在 `queued`、從不觸發部署
   > （舊文件寫「已接上自動部署」是錯的，見 `deployment_guide.md` 一、）。
   > 改任一環境變數則會用既有 image 觸發 redeploy（約 1 分鐘、免重建）。
3. **Settings → Deploy**
   - **Start Command**: `/app/scripts/start_worker.sh`
   - **Restart Policy**: `ON_FAILURE`（最多重試 5 次）
   - **Replicas**: `1`（可依量調大）
   - **Health Check**: 留白（worker 無 HTTP endpoint）
4. **Variables**：複製主 API service 的所有環境變數（右上角「…」→ Copy Variables）
   - 必備：`DATABASE_URL` or `DB_*`、`REDIS_URL` or `REDIS_*`、`OPENAI_API_KEY`、
     `FCM_CREDENTIALS_JSON`、`APP_SECRET_KEY`、`JWT_*`、`SENTRY_DSN`
   - 可額外加：`CELERY_CONCURRENCY=2`
   - **DB 連線**：worker/beat 同為常駐容器，`DATABASE_URL` 必須走 Supabase
     **session-mode pooler**（host `aws-1-ap-southeast-1.pooler.supabase.com`，**port 5432**），
     不要用 transaction-mode（6543）——6543 的 PgBouncer 會讓 asyncpg 的 prepared statement
     跨 backend 失效。並把連線池調小：`DB_POOL_SIZE=5`、`DB_MAX_OVERFLOW=5`
     （session pooler 連線數有限，每個 service 都會佔用連線）。
5. Deploy，在 Logs 確認看到：
   ```
   celery@... ready.
   [worker] Celery Worker 已啟動
   ```

### 2. Beat Service

**重要：整個系統只能有 1 個 beat 副本，否則 schedule 會重複觸發。**

1. 重複步驟 1–4，命名為 `gu-voice-celery-beat`
2. **Start Command**: `/app/scripts/start_beat.sh`
3. **Replicas**: `1`（絕對不要改）
4. 部署後 Logs 應看到：
   ```
   beat: Starting...
   Scheduler: Sending due task check-session-timeouts ...（每 5 分鐘一次）
   ```

---

## 驗收清單

- [ ] Worker service 部署成功，Logs 5 分鐘後能看到「received task ...check_session_timeouts」
- [ ] Beat service Logs 每 5 分鐘記錄 `Sending due task check-session-timeouts`
- [ ] 手動把 session 的 `updated_at` 改成 11 分鐘前，等 5 分鐘後該 session 被標為 timeout
- [ ] 月曆到 25 日凌晨後，確認 `conversations_YYYY_MM` / `audit_logs_YYYY_MM` 下月分區被自動建立（先做完 TODO #4 分區 migration 這個才會成立）

---

## 成本與擴展建議

- 初期：worker 1 個（concurrency=2）+ beat 1 個 ≒ Railway `$5/month × 2 services`
- 高併發推播或 SOAP 產生卡：把 worker `numReplicas` 拉到 2 或 3，每個 replica
  `CELERY_CONCURRENCY=4`。Beat 永遠維持 1 個
- 未來遷移到 K8s：beat 建議用 `celery-beat-redbeat` 套件或改走 k8s CronJob，
  消除單點

---

## 疑難排解

| 症狀 | 可能原因 |
|------|----------|
| Worker 啟動卡在 `Connecting to redis://...` | `REDIS_URL` 沒設或格式錯，Redis service 還沒起 |
| `ValueError: default Firebase app does not exist` | `FCM_CREDENTIALS_JSON` 沒複製過來；見 `app/core/firebase.py` |
| Beat 重複觸發同一 task | 多個 beat 副本同時跑 → `numReplicas = 1` 檢查 |
| 任務一直 pending 沒被消化 | Worker 沒訂閱到同一 broker 的 queue，檢查 `REDIS_URL` 是否與 API 一致 |
| 任務噴 `prepared statement "__asyncpg_stmt_*__" does not exist` | `DATABASE_URL` 用到 transaction-mode pooler（6543）；改用 session-mode（**5432**）。偵測邏輯見 `app/core/database.py` 的 `_is_supabase`（從 `ASYNC_DATABASE_URL` 解析 host） |
| Worker / Beat 一啟動就 crash 或反覆 restart | 從 API 複製來的 `CORS_ORIGINS` / `MULTILANG_DISABLED_LANGUAGES` 格式問題：pydantic-settings v2 會先 `json.loads()`，舊 code 需**合法 JSON 陣列**；新 code（`app/core/config.py` 已加 `Annotated[..., NoDecode]`）逗號分隔或 JSON 陣列皆可 |
