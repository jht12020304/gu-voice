# 運維端點的曝光控制 — `/metrics`、`/docs`、`/redoc`、`/openapi.json`

> 2026-08-22。程式在 `backend/app/main.py`，設定在 `backend/app/core/config.py`，
> 行為由 `backend/tests/unit/test_ops_endpoint_exposure.py`（21 項）守著。

## 修之前

這四支端點在生產環境**全部是公開的**，任何人都能直接讀：

```
GET https://gu-voice-app-production.up.railway.app/metrics       → 200
GET .../docs        → 200      GET .../redoc  → 200      GET .../openapi.json → 200
```

裡面**沒有 PHI**——沒有病患姓名、沒有病歷號、沒有報告內容。但合起來是一份完整的偵查資料：

| 洩漏的東西 | 來源 |
|---|---|
| 整個 API 介面：55 支端點、所有 request/response 欄位名稱 | `/openapi.json` |
| 每支端點的流量、錯誤率、延遲分佈 | `http_requests_total`、`http_request_duration_seconds` |
| 問診場次數（依語言）、**紅旗觸發次數**、STT/TTS 延遲 | `urovoice_*` 指標 |
| 精確的 Python 版本（`3.11.16`）、記憶體、CPU、開啟的 fd 數、程序啟動時間 | `process_*`、`python_info` |
| **什麼時段沒有人在用這套系統** | 流量計數隨時間的變化 |

最後一項對醫療系統特別不該送。

## 修之後

| 端點 | development | 其他環境（production） |
|---|---|---|
| `/metrics` | 開（沒設 token 時） | **要 `Authorization: Bearer <METRICS_TOKEN>`** |
| `/openapi.json` | 開 | **要同一個 token** |
| `/docs`、`/redoc` | 開 | **完全不掛路由** |

三個設計決定，每一個都有理由：

1. **沒設 token ＝ 關閉，不是放行。** production 沒有 `METRICS_TOKEN` 就四支全 404。
   fail-open 的預設值在這種端點上等於沒鎖，而且從外面看不出來。
2. **未授權回 404，不回 401。** 401 等於告訴掃描的人「這裡有東西，只是你沒鑰匙」，
   反而把目標標了起來。回應的形狀與「這條路徑不存在」完全一致（有測試釘住）。
3. **`/openapi.json` 上鎖而不是拿掉。** 部署驗證靠它區分新舊容器——`healthz` 恆綠、
   區分不出來（見 `deployment_guide.md` 一、與 `TODO.md:99-129`）。拿掉等於把
   唯一的外部探針一起丟了。

比對走 `secrets.compare_digest`，避免用回應時間把 token 逐字元試出來。
Bearer 的 scheme 大小寫不敏感（各家 client 寫法不一）。

## 設定

| 變數 | 預設 | 說明 |
|---|---|---|
| `METRICS_TOKEN` | `None` | `/metrics` 與正式環境 `/openapi.json` 的權杖。**正式環境沒設＝關閉** |
| `METRICS_ENABLED` | `true` | 設 `false` 連 middleware 都不裝，`/metrics` 一律 404 |
| `DOCS_ENABLED` | 依 `APP_ENV` | 未設時 development 開、其餘關。要在正式環境臨時開 Swagger 就明確設 `true` |

產 token 與設定：

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
railway variables --service gu-voice-app --set "METRICS_TOKEN=<剛剛那串>"
```

用法：

```bash
TOKEN=$(railway variables --service gu-voice-app --kv | sed -n 's/^METRICS_TOKEN=//p')
curl -sS -H "Authorization: Bearer $TOKEN" \
  https://gu-voice-app-production.up.railway.app/metrics | head
```

## ⚠️ 兩個坑

**一、`PROMETHEUS_METRICS_ENABLED` 是一個假開關，已移除。**
`main.py` 原本寫 `getattr(settings, "PROMETHEUS_METRICS_ENABLED", True)`，而 `Settings`
裡從來沒有這個欄位，加上 `model_config` 的 `extra="ignore"`，設環境變數也關不掉——
`getattr` 永遠拿到 fallback 的 `True`。註解卻寫著「若設 PROMETHEUS_METRICS_ENABLED=false 可關閉」。

這與同一天發現的 `railway.toml` 的 `region` 鍵是**同一類**缺陷：設定寫得像有效，
但那個名字在對應的 schema 裡不存在，於是被安靜忽略，沒有錯誤也沒有警告。
`config.py:155` 早就為 JWT token 效期記過同一個坑。**加設定時要驗它真的被讀到。**

**二、`Instrumentator().expose()` 會把這道鎖整個繞過去。**
那是官方範例寫法，會掛一條無條件公開的 `/metrics`。現在只用 `.instrument(app)` 裝
middleware，路由自己掛才擋得住。`test_ops_endpoint_exposure.py::TestWiring` 用靜態檢查
守著這一條——因為改回官方寫法時，其他測試不會紅。

## 已知限制（沒修）

`prometheus_client` 在多 worker 下沒有設 `PROMETHEUS_MULTIPROC_DIR`，所以 `/metrics`
回的是**回應這次請求的那一個 worker** 的計數（`start.sh` 起 4 個）。判斷相對關係
（哪支端點慢、成功與失敗的比例）沒問題，但**絕對值會低估約 4 倍**，也解釋了為什麼
連打十次 `healthz/deep` 之後 `count` 可能只有 1。

要修需要共用目錄 ＋ `MultiProcessCollector` ＋ worker 死亡時的檔案清理。2026-08-22
沒動，因為當時的目的是「把它鎖起來」而不是「讓它更準」。**引用 `/metrics` 的數字時
記得這一點。**

## 相關

- 搬區域的完整流程（含這個 token 必須先設好）：[`railway_region_move.md`](railway_region_move.md)
- 為什麼會去看 `/metrics`：[`perf_audit_2026-08-22.md`](perf_audit_2026-08-22.md)
- 部署驗證怎麼帶 token：[`deployment_guide.md`](deployment_guide.md) 一、
