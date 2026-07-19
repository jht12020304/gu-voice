# 研究分析（Research Analytics）功能文件

> 建立日期：2026-07-06｜對應 PR #16（基礎頁）、#17（期刊級重構）、#18（Wilson CI hotfix）
> 狀態：已上線生產（Vercel 前端 + Railway 後端）

問診數據的**去識別化聚合分析**，供醫師端做學術研究與國際期刊投稿準備。頁面 `/research`（醫師/管理員可見），端點 `GET /api/v1/research/analytics`。每場問診結束後圖表自動更新。

---

## 1. 設計目標與文獻依據

指標選擇與圖表/統計呈現方式對齊國際期刊評估框架：

| 框架 | 用途 | 對應本頁 |
|---|---|---|
| **DECIDE-AI**（Nature Medicine 2022） | AI 決策支援系統早期臨床評估的報告指引 | 整體評估定位（院內小規模實地評估）；投稿逐項對照其 17 項 AI 條目 |
| **AMIE**（Nature 2025） | 對話式診斷 AI 的評估軸（病史採集、診斷、管理、溝通） | HPI 10 欄完整度 = 病史採集軸 |
| **症狀檢查器 triage 文獻**（JMIR 等） | sensitivity/specificity、under-triage 率 | 紅旗率、偵測延遲、確認率（過程指標；正式需醫師金標準算敏感度） |
| **PDQI-9** | 醫療文件品質 9 維度工具 | 醫師審閱同意率為 pragmatic proxy（正式需雙評分者 + ICC/kappa） |
| **SAMPL 統計指引** | 比例附分子/分母 + CI；非常態用中位數 + IQR | Wilson 95% CI、median/IQR |
| **Weissgerber 2015（PLOS Biology）** | 連續資料勿用長條圖（遮蔽分佈） | 時長/輪次/字數改用箱形圖 |

---

## 2. 端點

```
GET /api/v1/research/analytics
```

- **認證**：必要；**角色** `doctor` / `admin`（`require_role`）
- **Query（皆選填）**：
  | 參數 | 型別 | 說明 |
  |---|---|---|
  | `date_from` | date（YYYY-MM-DD） | 收案起日（依 `session.created_at`，含當日）|
  | `date_to` | date | 收案迄日（含當日）|
- **回應**：全去識別化 aggregate（計數、比例、分佈、描述統計），**不含任何病患層級可識別資料**。
- 命名後端 snake_case，前端 axios interceptor 自動轉 camelCase。

### 回應結構（頂層）

```
generated_at, date_from, date_to
cohort          — 收案流 + 週趨勢 + 完成率（Wilson CI）
demographics    — Table 1：年齡摘要/年齡帶/性別/主訴 case mix
efficiency      — 時長/輪次/每輪字數（NumericSummary 含箱形 whisker）+ 直方圖
history_taking  — HPI 10 欄完整度 + 各欄填答率
safety          — 紅旗率(CI)/嚴重度/偵測層/緊急度/偵測延遲/確認率(CI)/確認延遲
stt_quality     — STT 信心分佈 + 低信心率(CI) + 各語言 + 語音占比
documentation   — AI 信心/ICD 驗證率(CI)/審閱結果/同意率(CI)/revision 原因
by_language     — 各語言子群摘要 + 紅旗率(CI)（森林圖 + table）
```

### 共用型別

- **`NumericSummary`**：`n, mean, sd, median, p25, p75, min, max, whisker_low, whisker_high, outliers[]`。
  median/p25/p75/whisker/outliers 直接支援箱形圖繪製（Tukey 1.5×IQR 圍籬）。
- **`Proportion`**：`numerator, denominator, value, ci_low, ci_high`（0~1；分母 0 時後三者為 null）。
  CI 為 **Wilson score 95% 區間**（小樣本比 Wald 準確、不越界 [0,1]）。

---

## 3. 統計方法（`app/services/research_service.py`）

DB 只做 6 個單純取數查詢（Q1 sessions、Q2 病患對話輪、Q3 紅旗、Q4 SOAP、Q5 revision reason、Q6 demographics join patients+chief_complaints）；**所有統計在純 Python helper 計算**，可無 DB 單元測試。

- `wilson_proportion(num, den)` — Wilson score 95% CI（`_Z_95=1.96`）。教科書驗證：8/10 → (0.490, 0.943)。
- `summarize(values)` — n/mean/SD/median/IQR/min/max + Tukey whisker + 離群點。
- `percentile(sorted, q)` — 線性內插（同 PG `percentile_cont`）。
- `histogram(values, edges)` — 固定桶邊界，最後一桶右閉。
- `hpi_completeness(subjective)` — SOAP hpi 10 欄「非空」比例（AMIE 病史採集軸 proxy）。
- `age_band(age)` — `<40 / 40-59 / 60-74 / 75+`（泌尿科攝護腺相關集中 60+）。
- demographics 以**病患層級去重**（同病患多場次年齡/性別只計一次），case mix 以**場次**計。

### ⚠️ 承重不變式：比例的分子必須是分母的子集

`wilson_proportion` 若 `numerator > denominator` → `p>1` → `sqrt(負數)` → **500**（生產 request 742f698d 曾觸發，見 PR #18）。

根因：紅旗率的分母是**終態場次**（completed + aborted），但紅旗可落在 in_progress / cancelled 場次。若分子直接用「所有有紅旗場次」會超過分母。

修法（兩層）：
1. **呼叫端**：`safety.alert_session` 與各語言 `red_flag_rate` 的分子改為 `sessions_with_alert ∩ terminal_ids`（`terminal_with_alert`）。
2. **`wilson_proportion` 內防禦性 `clamp p∈[0,1]`**，即使未來母體再不一致也不 500。

其他比例呼叫（completion / acknowledged / low_confidence / icd10_verified / physician_agreement）分子本就是分母子集，安全。**新增任何比例指標時，務必確認分子與分母同母體。**

---

## 4. 前端視覺化（期刊級）

圖表原語在 `frontend/src/screens/doctor/research/charts.tsx`，純 inline SVG 手刻（無外部圖表依賴）：

- **箱形圖**（`BoxPlotGroup`）— 連續資料分佈：median 線、IQR box、Tukey whisker、離群圈、n= 標註。**不用長條圖呈現連續資料**。
- **比例條 + 95% CI 誤差線**（`ProportionRow`）— bar 長度=點估計，疊黑色 CI whisker + caps。
- **森林圖**（`ForestPlot`）— 各語言子群紅旗率點估計 + Wilson CI，點大小反映樣本量，虛線=整體參考線，x 軸 0–100%。
- **Table 1**（`ResearchAnalyticsPage` 內）— 病患基線特徵表。
- **Figure 1–8 編號** + caption + footnote + n=；每張圖一顆「↓ SVG」鈕，序列化為**向量 SVG**（投稿排版用，內嵌白底）。
- 調色盤過 dataviz `validate_palette`（light `#ffffff` / dark `#1e2330` 雙面）；文字一律 ink token；CI 誤差線 `dark:text-white` 確保暗底可讀。
- i18n `research` namespace 5 語系（zh-TW / en-US / ja-JP / ko-KR / vi-VN）。

### 即時更新

`/research` 頁訂閱 dashboard WebSocket 的 `report_generated` / `session_status_changed` 事件，**debounce 1.5s 後自動 refetch** → 每場問診結束（或報告生成）圖表自動更新，無需手動刷新。

---

## 5. 資料來源

研究指標的底層資料就是 §問診數據盤點（見 [session_data_inventory.md](session_data_inventory.md)）：

- `sessions`（狀態、語言、時長、時間戳）
- `conversations`（病患輪的 `stt_confidence`、`metadata.input_source`、字數）
- `red_flag_alerts`（嚴重度、偵測層 confidence、alert_type、偵測/確認時間）
- `soap_reports`（subjective.hpi、plan.urgency、ai_confidence_score、icd10_verified、review_status）
- `soap_report_revisions`（reason 分佈）
- `patients` + `chief_complaints`（demographics + case mix）

> 這些欄位的品質修復（真實 STT 信心、metadata、紅旗輪標記等）見 session_data_inventory.md §11。舊資料缺值（NULL）會被統計自動排除，不影響既有功能。

---

## 6. 正式發表前仍需人工補齊

頁尾 Methods 卡與本節提醒：本頁皆為去識別化聚合統計，**不等於可直接投稿的分析**。正式發表前需：

1. **IRB 審查**與**事前註冊分析計畫**。
2. Triage 敏感度需以**醫師判讀為金標準**另行計算（本頁紅旗率等為過程指標）。
3. PDQI-9 需**抽樣、雙評分者評分並報告 ICC/kappa**（本頁同意率僅 proxy）。
4. 依實際樣本數報告信賴區間；小樣本語言子群（森林圖 CI 很寬）解讀須謹慎。

---

## 7. 部署與驗證

- **後端**：Railway `gu-voice-app` 服務已連 GitHub，merge 到 main 即自動部署（見 [deployment_guide.md](deployment_guide.md)）。啟動腳本自動跑 migration。
- **前端**：Vercel 跟 main 自動部署；research locale 隨 build 同步到 `public/locales`。
- **本地 E2E 驗證**：docker 起 PG16+Redis → `alembic upgrade head` → seed（`scratchpad/seed_research_e2e.py` 等；注意 conversations 按月分區，seed 日期須落在既有分區月份）→ uvicorn 帶 `CORS_ORIGINS` 含 vite dev port → Playwright 逐 Figure 目檢 → Redis publish `gu:dashboard:events` 模擬跨行程 `report_generated` 驗即時更新。
- **測試**：後端 `tests/unit/services/test_research_service.py`（Wilson CI 教科書值、箱形 whisker、age band、demographics 去重、非終態紅旗回歸）。
