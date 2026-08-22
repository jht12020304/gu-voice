# Railway 區域搬遷 Runbook — 後端搬到新加坡

> 2026-08-22。對應 `backend/railway.toml` 的 `[deploy.multiRegionConfig]` 修正。
> 效能稽核脈絡見 [`perf_audit_2026-08-22.md`](perf_audit_2026-08-22.md)；
> 連線設定的唯一權威來源是 [`supabase_connection_guide.md`](supabase_connection_guide.md)。

## 0. 為什麼

後端跑在 **Railway us-west2（加州）**，Supabase 在 **ap-southeast-1（新加坡）**。
每一句 SQL 都橫跨一次太平洋。

實測（2026-08-22，生產 `/metrics` ＋ curl）：

| 端點 | 伺服器端耗時 |
|---|---|
| `GET /api/v1/health`（**完全不碰 DB / Redis**） | **1.88 ms** |
| `GET /api/v1/healthz/deep`（一句 `SELECT 1` ＋ 一個 Redis `PING`） | **1.55 s** |
| `GET /api/v1/sessions` | 4.06 s |
| `GET /api/v1/dashboard/monthly-summary` | 3.90 s |
| `GET /api/v1/reports` | 3.32 s |
| `GET /api/v1/notifications/unread-count`（就是數個數字） | 2.09 s |

827 倍。而且不只是慢：**38 次 deep check 有 20 次超過 2 秒的內部逾時、回 HTTP 500**
（`asyncio.wait_for` 砍掉查詢後，`get_db` 的 `await session.commit()` 炸掉）。

`railway.toml` 本來就寫了 `region = "asia-southeast1"`，註解也寫著「選擇離台灣最近的區域」。
**它從來沒生效過**，而且錯了兩次：Railway 的 config schema 沒有 `region` 這個鍵
（無法辨識的鍵被安靜忽略），而且新加坡的完整代號是 `asia-southeast1-eqsg3a`。

## 1. 要搬什麼

| 服務 | 現在 | 有 volume？ | 搬遷成本 |
|---|---|---|---|
| `gu-voice-app`（FastAPI ＋ celery worker/beat 同容器） | US West | 無 | 重新部署，**無停機** |
| `Redis`（`redis-volume`） | US West | **有** | **有停機**，volume 要跟著搬 |

Celery 在 API 容器裡跑（`scripts/start.sh:104`，`RUN_CELERY_IN_API` 預設 `true`），
所以**沒有第三個 service 要處理**——搬 app 就等於把 worker 和 beat 一起搬。

⚠️ **`numReplicas` 必須維持 1。** beat 全系統只能一個實例，副本數 >1 會讓排程任務重複觸發。
要調大之前先照 [`railway_celery_runbook.md`](railway_celery_runbook.md) 把 beat 拆出去。

## 2. 順序：先搬 app，Redis 之後再說

**不要為了「一次搬完」而把有停機的那一步擋在前面。**

Railway 的私有網路**可以跨區**（`redis.railway.internal` 搬完仍然解析得到、仍然通），
只是**不做區域感知的路由**。所以 app 先搬、Redis 還在加州的中間狀態是：

| | 現在 | app 搬完（Redis 還在加州） | 兩邊都搬完 |
|---|---|---|---|
| Postgres 來回 | ~1.5 s | **~30 ms** | ~30 ms |
| Redis 來回 | ~1 ms | ~170 ms（跨太平洋） | ~1 ms |
| 每個已登入請求 | **~1.5 s+** | **~200–400 ms**（看打幾次 Redis） | **~35 ms** |

中間狀態已經是 7 倍改善，而且**零停機**。Redis 那步可以挑離峰時段慢慢做。

> 我一開始警告過「只搬 app 會讓 `redis.railway.internal` 解析不到、Celery 掛掉、
> JWT 黑名單 fail-open」。**那是錯的**——查 Railway 官方文件與 Central Station 的
> 官方回覆後確認私有網路跨區可用。中間狀態只是變慢，不會壞。

## 2.5 先做這一步：在 Railway 設 `METRICS_TOKEN`

同一批改動把 `/metrics`、`/docs`、`/redoc`、`/openapi.json` 從**全部公開**改成鎖起來
（`app/main.py`；理由與行為見 [`ops_endpoint_exposure.md`](ops_endpoint_exposure.md)）。

⚠️ **這件事必須排在部署之前**，否則第一次部署完，你就沒有工具驗它有沒有成功——
`/openapi.json` 是唯一能區分新舊容器的外部探針（`healthz` 恆綠），而它現在要 token。

```bash
# 產一組 token（純隨機字串，跟任何既有金鑰無關）
python3 -c "import secrets; print(secrets.token_urlsafe(32))"

# 設進 Railway（不會觸發重新部署）
railway variables --service gu-voice-app --set "METRICS_TOKEN=<剛剛那串>"

# 之後所有驗收指令都靠它
TOKEN=$(railway variables --service gu-voice-app --kv | sed -n 's/^METRICS_TOKEN=//p')
```

沒設 token 的正式環境 = 四支端點全部 404（fail closed，不是放行）。

## 3. 步驟 A：搬 `gu-voice-app`（無停機）

`backend/railway.toml` 已經改好，內容是：

```toml
[deploy.multiRegionConfig."asia-southeast1-eqsg3a"]
numReplicas = 1
```

1. **確認 TOML 解得開**（改壞了 Railway 會安靜忽略整份設定）：
   ```bash
   backend/venv/bin/python -c "import tomllib;print(tomllib.load(open('backend/railway.toml','rb'))['deploy'])"
   ```
   應該看到 `'multiRegionConfig': {'asia-southeast1-eqsg3a': {'numReplicas': 1}}`。

2. **記下搬遷前的基準**（之後要比對，見 §5）：
   ```bash
   for i in 1 2 3 4 5; do
     curl -sS -o /dev/null -w "%{http_code} %{time_starttransfer}s\n" \
       https://gu-voice-app-production.up.railway.app/api/v1/healthz/deep
   done
   ```

3. **部署**。⚠️ 照 `CLAUDE.md` 部署重點的既有流程——CLI 5.41.2 起 `railway up`
   一律上傳 git root，必須先匯出：
   ```bash
   TMP=$(mktemp -d)
   git archive HEAD:backend | tar -x -C "$TMP"
   cd "$TMP"
   railway link -p gu-voice-api -s gu-voice-app -e production
   railway up --detach
   ```
   > `railway.toml` 在 `backend/` 底下，匯出後會落在該目錄根部，Railway 才讀得到。

4. **用眼睛確認區域真的變了**——config-as-code 生效與否不要用猜的：
   ```bash
   railway status          # 應顯示 region: Southeast Asia
   ```
   或後台 → `gu-voice-app` → Settings → Regions & Replicas，
   應該從 `US West (California, USA)` 變成 `Southeast Asia (Singapore)`。

   **如果還是 US West**：代表這個鍵仍然沒被吃到。改用後台 UI 直接選區域
   （config-as-code 會鎖住那個欄位，需要先把 `multiRegionConfig` 從 toml 拿掉再重部署）。

5. 跑 §5 的驗收。

## 4. 步驟 B：搬 Redis（**有停機，挑離峰**）

Railway 官方說法：改區域本身不停機，**除非該 service 掛了 volume**——那就要連 volume
一起搬，過程會停機，時間依 volume 大小而定。

### 先搞清楚弄丟 Redis 會失去什麼

| Redis 內容 | key | 弄丟的後果 |
|---|---|---|
| **Refresh token 登記簿** | `gu:refresh:{user_id}:{jti}` | **所有人被登出。** `/auth/refresh` 查不到 jti 就拒絕（`test_refresh_unknown_jti_is_rejected`），大家要重新登入 |
| Access token 黑名單 | `gu:token_blacklist:{jti}` | 已撤銷的 access token 恢復有效，直到自然過期（15 分鐘） |
| 密碼重設 token | `RESET_TOKEN_KEY_PREFIX` | 已寄出、還沒點的重設連結失效 |
| Celery broker / result（db 1 / 2） | — | **排隊中的 SOAP 報告任務消失**，那些報告會卡在 `generating` |
| 限流計數 | rate limit keys | 無所謂，重算就好 |

⇒ **優先用「搬 volume」而不是「重建 Redis」。** 真的要重建，就當作一次計畫性登出，
挑沒有人在問診的時段，事後檢查有沒有卡在 `generating` 的報告。

### 步驟

1. 確認目前沒有進行中的問診場次與排隊中的 SOAP 任務。
2. Railway 後台 → `Redis` service → Settings → Regions & Replicas → 選
   **Southeast Asia (Singapore)**。
   > Redis 這個 service **沒有** railway.toml 管，直接在 UI 改即可。
3. 等 volume 搬完、service 回到 Online。
4. 確認 app 連得上（`/api/v1/healthz/deep` 的 `checks.redis` 要是 `ok`）。
5. 確認 Celery 活著——排一份 SOAP 報告，看它有沒有離開 `generating`。

## 5. 驗收

```bash
B=https://gu-voice-app-production.up.railway.app/api/v1

# 1) 一句 SELECT 1 + 一個 PING。搬遷前 ~1.55 s 且過半回 500。
for i in 1 2 3 4 5 6 7 8; do
  curl -sS -o /dev/null -w "%{http_code} %{time_starttransfer}s\n" "$B/healthz/deep"
done
```

| 指標 | 搬遷前 | A 之後（Redis 還在加州） | A+B 之後 |
|---|---|---|---|
| `/healthz/deep` | ~1.85 s，**逾半 500** | ~0.4 s，全 200 | **< 0.3 s，全 200** |
| 儀表板 | 3.90 s | ~0.6 s | **~0.3 s** |
| 問診記錄 | 4.06 s | ~0.6 s | **~0.3 s** |

```bash
# 2) 逐支端點的真實伺服器端耗時（生產 Prometheus）
#    2026-08-22 起要帶 token；沒帶會回 404 而不是 401。
#    注意 /metrics 在網域根部，不在 /api/v1 底下。
#    sum/count 要一起看，而且要記得 4xx 的快速失敗也算在裡面——
#    只看 sum/count 的平均會被那些 <0.1 s 的失敗拉低（我 2026-08-22 就這樣高估過 38%）。
curl -sS -H "Authorization: Bearer $TOKEN" \
  https://gu-voice-app-production.up.railway.app/metrics \
  | grep -E "http_request_duration_seconds_(sum|count)"
```

⚠️ **不要期待客戶端掉到 0.19 秒。** Railway 給台灣的邊緣節點是**東京**（`x-railway-edge: hnd1`），
所以新加坡的 origin 會多一段東京↔新加坡。實際地板約 **0.25–0.3 秒**。

## 6. 回退

改回 `us-west2` 再部署一次即可（app 無停機；Redis 又要再搬一次 volume）。
Postgres 完全不受影響——`DATABASE_URL` 指的是 Supabase，不是 Railway。

## 7. 這一步**不會**修好的事

搬完之後，剩下的瓶頸依序是（細節見 [`perf_audit_2026-08-22.md`](perf_audit_2026-08-22.md)）：

- `DB_POOL_SIZE=2` / `DB_MAX_OVERFLOW=1`（4 個 worker × 3 ＝ 全站 12 條）。
  實測 14 個並發請求會排成六階梯、最慢 6.7 s。
  **搬完之後再調**——連線佔用時間從 1.5 s 掉到 ~30 ms，12 條就夠了；
  之後再放回文件建議的 5/5（4 workers × 10 ＝ 40，低於 `max_connections ≈ 60`）。
- `sessions.created_at` 沒有索引，而每一支清單與儀表板查詢都 order by 它。
- `pool_pre_ping=True` 每次 checkout 多一趟；改 `pool_recycle=300`。
- `dashboard_service.py:502` 三個序列 `await` 可以 `asyncio.gather`。
- React 生產前端的報告清單 N+1（`ReportListPage.tsx:223` 抓 `limit:100` ＋ 每列一次
  `getSession`，而那支 API 會連整份逐字稿一起回）——Flutter 端 2026-08-22 已修，網頁端沒修。
- 兩個前端都沒有查詢快取，每次導覽都重抓。搬完之後**這才會變成主要瓶頸**。
