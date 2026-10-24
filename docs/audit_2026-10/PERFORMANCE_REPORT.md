# PERFORMANCE_REPORT — 2026-10-23／24

> **2026-10-24 round 2（自主修復輪）**：在本檔之後又完成 Tracker 的 B11–B48／F09–F41／D04–D24／R02–R20 等項目；完整結算與最終驗證見 [FINAL_REFACTORING_REPORT.md](FINAL_REFACTORING_REPORT.md)，逐項狀態見 [REFACTORING_TRACKER.md](REFACTORING_TRACKER.md)，兩個執行代理的逐項報告在 `evidence/exec_frontend_report.md`、`evidence/exec_flutter_report.md`，round-2 效能原始數據在 `evidence/perf_backend_round2_measurements.md`。


> 所有數字都是**本機**（macOS、單 uvicorn worker、`APP_ENV=development`、本機 Postgres/Redis），不是生產 P95。方法與腳本在 [evidence/](evidence/)（`api_probe.py`、`locale_requests.mjs`、`perf_api_*.json`）。可重跑：啟動 backend 於 :18000 後 `PROBE_PID=<pid> PROBE_LABEL=x backend/venv/bin/python -I evidence/api_probe.py`。

## 1. 已修且有前後量測

### 1.1 PDF 匯出阻塞 event loop（最高價值）
方法：背景發一個 `GET /reports/{id}/pdf`，300 ms 後對同一 worker 打 `GET /api/v1/health`。

| | 修改前 | 修改後 |
|---|---|---|
| health 單獨 | 0.9–1.0 ms | 0.9–1.0 ms |
| health 在 PDF 進行中 | **956 ms** | 1.6 / 142 / 112 ms（三次） |
| PDF 本身 | 1,267 ms | 1,242–1,518 ms（不變，預期） |
| 3 份 PDF 並發 | 被阻塞的 loop 序列化 | 3.87 s（鎖序列化，loop 保持回應） |

殘餘 100–140 ms 是 render thread 的 GIL 競爭；要歸零需要 process pool（碼內已標 upgrade path）。副作用：無；render 仍一次一份。

### 1.2 Dashboard 事件 publish 的 Redis 連線
Microbench（本機 Redis，200 次 publish）：每次新 client 0.726 ms／則 → 共用池 0.205 ms／則。每則省 3–4 個 round trip（connect／AUTH／QUIT），生產跨區 RTT 數十 ms 時差距線性放大。**生產數字未量測**。副作用：Celery 路徑（每 task 新 loop）行為不變。

### 1.3 frontend 冷啟動 locale 請求（Chromium headless，vite preview）
| 儲存語言 | URL | 前 | 後 |
|---|---|---|---|
| en-US | /zh-TW/login | 20 req・15.0 KB | **10・7.2 KB** |
| ja-JP | /zh-TW/dashboard | 30・29.2 KB | **10・7.2 KB** |
| zh-TW／en-US | /en-US/login | 20・15.0 KB | 20（zh-TW 是 en-US 的刻意 fallback） |
| 無 | /zh-TW/login | 10・7.2 KB | 10 |

### 1.4 靜態資產
`/logo.png`：1,077,339 B → **85,686 B**（−92%），用途為 favicon 與 32／80 px 顯示（256 px 覆蓋 3× DPI）。

## 2. 已修但未量測（只做了結構性改善，不宣稱加速）
- `admin_service` 兩處 bcrypt（cost 12，200–400 ms CPU）改 `asyncio.to_thread`：同類問題在 `auth_service` 已被 2026-08-22 量測過，這裡沿用；本輪未另測。
- `ThemeToggle`／`ReportListPage` 改選擇器訂閱、`PatientListPage` 分組計算 `useMemo`：未用 Profiler 計 render 次數。

## 3. API 延遲（30 次序列請求，p50／p95 ms）

| 端點 | baseline | after（兩次） | 備註 |
|---|---|---|---|
| GET /api/v1/health | 1.1 / 1.5 | 0.9 / 1.0 | |
| GET /auth/me | 7.4 / 10.4 | 4.2 / 6.1 | |
| GET /sessions | 7.2 / 8.9 | 5.3 / 6.2・6.0 / 6.9 | |
| GET /reports | 8.3 / 12.3 | 10.6 / 14.7・7.1 / 12.0 | |
| GET /alerts | 24.4 / 49.0 | 7.6 / 9.7・4.9 / 11.4 | ⚠️ 見下 |
| GET /admin/users | 27.7 / 44.5 | 6.9 / 8.0・7.4 / 11.9 | ⚠️ |
| GET /audit-logs | 29.1 / 46.2 | 5.9 / 7.4・4.1 / 8.3 | ⚠️ |
| POST /auth/login | 197.8 / 200.8 | 186.8 / 207.1 | bcrypt，設計如此 |
| GET /reports/{id}/pdf | 1,248.8 / 1,983.8 | 1,303.8 / 1,487.0・1,235.5 / 1,252.7 | render 成本不變 |
| GET /admin/system/health | 274 / 400 | 270 / 336 | 內含對 OpenAI 的真實網路呼叫 |
| 20 並發 GET /sessions wall | 228.8 ms | 233.0・143.4 ms | |

⚠️ `/alerts`、`/admin/users`、`/audit-logs` 由 20–30 ms 降到 4–7 ms **不能歸功於本輪修改**：baseline 是在 `docker start` 資料庫後立刻量的（冷 buffer cache），兩次 after 數字彼此一致。結論：這三條在暖機後本來就是 4–7 ms。

## 4. 記憶體
| 情境 | RSS |
|---|---|
| 剛啟動 | 168 MB |
| login + 幾個 GET | 172–177 MB |
| **第一次 PDF 後** | **719 MB** |
| 第 12 次 PDF 後 | 737 MB（+1.6 MB／份；未判定是否持續成長） |
| 探測全程峰值 | 959–964 MB |

本機字型是 macOS 的 `NotoSansTC.ttf`（variable font，測試輸出有 `instantiateVariableFont` 警告）；production 用 `fonts-noto-cjk`，絕對值可能不同，但「首次 render 後常駐」的模式相同。4 個 worker 各做過一次 PDF 就是 ~4×550 MB。**未修**；選項：PDF 改在 process pool／獨立 Celery worker 產生、或改用靜態 CJK 字型檔並量測。

## 5. 其他基準（供日後比較）
| 指標 | 稽核前 | 稽核後 |
|---|---|---|
| backend import `app.main` | 0.68–0.70 s | 未重測 |
| backend unit suite | 4,904 pass／15 s | 4,911 pass／11.8 s |
| frontend JS gz（全部 chunk） | 212,611 B | 212,524 B（死碼本來就被 tree-shake） |
| frontend 首頁路徑 gz（index+vendor-react+vendor-utils+css） | 117,391 B | 未重測（主 chunk 36.16 → 36.13 KB gz） |
| frontend smoothness（200 則逐字稿 3 s） | 53 root commits、200 bubble updates、無 >50 ms long task | 未重測 |
| Flutter WAV encode 60 s（Mac AOT） | p50 4.3–4.7 ms／p95 4.5–7.7 ms | — |
| `fvm flutter test` | 321／21 s | 321／5 s（暖快取） |

## 6. 未量測／未修的瓶頸（含量法）
- `/research/analytics` 無日期過濾、Q4 拉全部 SOAP JSONB：`EXPLAIN ANALYZE` at 10k sessions。
- `sessions(status, created_at)`、`red_flag_alerts(acknowledged_by IS NULL)` 無索引；`func.date(created_at)` 不可用索引：每次狀態變更廣播都掃（`dashboard_handler.py:521-538`）。
- notification fan-out 每位醫師兩個 round trip（N+1，N≈10）。
- Celery `run_async` 每個 task 新 loop + 新 engine：`pg_stat_activity` 看連線數。
- frontend `ConversationPage` 串流時每個 token 重建全部 `ChatBubble`（無 memo）：React Profiler during AI reply；屬語音路徑，需先讀 `voice-pipeline-invariants`。
- Flutter：`google_fonts` 執行期抓字型（kiosk 網路受限時首屏 reflow）、WAV 編碼在主 isolate（真機未測）、四處整狀態 `ref.watch`。
