# 效能與整體流暢度稽核

## 2026-10-03 隔離測試環境與送測準備

獨立 staging 後端、Postgres、Redis 與 React preview 已建立；production 未變更，也尚未 commit／push。環境網址、合成帳號位置、IPA build／雜湊以 [iOS 發佈設定 §0](ios_release_settings.md#0-2026-10-03-staging-候選包與測試環境) 為準。

| 檢查 | 結果與範圍 |
|---|---|
| 後端／資料層 | 三個服務在 Singapore；DB／Redis deep health 均 ok，migration `smoothness_20261003` 與通知索引已存在，Celery worker／beat 啟動。DB 僅有合成 doctor／patient 帳號，沒有 production 裝置 token；建立帳號用的臨時 DB TCP proxy 已移除。 |
| 真實 staging API | API 移至新加坡後 **8 組完整通過**：health、OpenAPI 版本／匿名保護、CORS、雙角色登入、7 個醫師列表／摘要端點、31 天月曆／角色界線、實際 LLM＋TTS＋緊急紅旗中止＋SOAP generated＋dashboard 事件＋通知／月曆更新，以及跨站 token 續期。另有無 cookie 客戶端用換發的新 token 讀取 `/auth/me` 的獨立驗收。 |
| 真實瀏覽器連線 | Chrome 154 桌面與 Playwright WebKit 26.4 iPhone 尺寸登入、報告、通知、場次與重新整理保留登入通過；HTTP／WS 確認指向 staging。此處未攔截 API，也不等於實體 iPhone Safari。 |
| iOS 候選產物 | `build_ios_testflight.sh` 六關全過、analyze 無問題、317 tests 通過；已簽章、確認 API／WS 為 staging，未內嵌 E2E／KIOSK 帳密。 |
| Apple | ASC 回 `FORBIDDEN.REQUIRED_AGREEMENTS_MISSING_OR_EXPIRED`；使用者選擇稍後處理。尚未確認 ASC 最新 build 號、未 validate／upload／分發，不能把本機 IPA 稱為 TestFlight 驗收完成。 |

送測準備中額外修正：

- Railway 實際部署 manifest 顯示 API 仍在美西，不能只因 `railway.toml` 寫了新加坡就判定已同區。已對 staging API 設定單一新加坡 replica，確認三個服務的最新 deployment 均 SUCCESS、舊 API 已退出。相同本機連線各 5 次暖連線樣本：deep health 中位數 **1,624.6ms → 133.6ms**，普通 health **157.1ms → 138.0ms**；這是本次外部請求耗時樣本，**不是生產 P95 或真機效能**。保留前後區域與原始樣本，後續部署也須查實際 manifest（[Railway 區域設定格式](https://docs.railway.com/config-as-code/reference#multi-region-configuration)）。
- Vite 原本強制要求 React 已不使用的 Supabase URL／anon key，造成乾淨的 preview 建置失敗；移除這兩項舊檢查，API URL 仍必填。乾淨 Vercel 建置成功，lint 與 14 個 React 測試檔通過。
- iOS 打包訊息會顯示實際指定的 API／WS，避免 staging 被標成 production；保留預設 production 的資料風險提醒。有一個可重跑 banner 合約測試，驗收工具共 **20 tests 通過**。
- 手機尺寸目視驗收發現醫師固定側欄擠壓主內容、兩種角色的長姓名撐高 Header。修正共用外殼：窄畫面收合側欄、沿用現有 Modal 展開導覽、收整姓名、採用動態視窗高度；Sidebar 計數沿用既有全域更新，開選單不另發請求。本機 Chrome／WebKit 各 **9 情境通過**，新增 320／390px、Escape／焦點返回與角色外殼檢查。真機鍵盤、瀏覽器工具列與安全區仍待裝置實測。

完整證據保存在 `~/.local/share/gu-voice/releases/202610031213-staging/acceptance/`，包含來源 SHA-256 清單、部署識別、API／瀏覽器 JSON、截圖與建置紀錄。保留首輪失敗：API 腳本先誤認月曆應回 31 個非空日、續期時混用帳號 cookie；瀏覽器腳本先等待了頁面沒有呼叫的 stats 端點。修正驗收假設後重驗相關步驟，未放寬 CSRF 或產品權限。初次啟動的兩個 API worker 亦有已被既有程式捕捉的分區 `DuplicateTableError` 競爭；服務繼續啟動，不宣稱啟動 log 零錯誤。

## 2026-10-03 修復與驗收

維護範圍維持 **Flutter iOS App + React 網頁 + FastAPI 共用後端**。F01–F12 的程式修正已完成並有可重跑的驗收；以下是本機驗收結果；後續 staging 進度見上節。**尚未提交或部署 production，也尚未達成真機整體流暢度的最終驗收**。下方修復前基線和 8 月紀錄保留作比較。

### 逐項結果

| ID | 已完成的修正 | 本機驗收與限制 |
|---|---|---|
| F01 | go_router 保留五個醫師分頁；帳號變更重建 navigator。 | 20 次分頁往返保留搜尋、選中月份與捲動位置，月摘要不因回訪重抓；切語言／帳號無舊帳號狀態。 |
| F02 | 報告列表直接使用已附病患資訊；後端回傳符合篩選／權限的 review counts，兩端共用。 | 20 列從 **22 次降至 1 次**請求，0 次逐列場次明細；150 份報告正確計數。舊後端未提供 counts 時 iOS 才走相容備援。 |
| F03 | 通知立即導頁，背景樂觀標示已讀；失敗恢復權威資料。 | 注入 1,200ms 已讀延遲：Chrome 約 **31ms**、WebKit 約 **51ms** 導頁；250ms 時已在目標頁。已讀失敗、舊回覆及帳號切換皆有回歸檢查。 |
| F04 | Suspense 放進醫師／病患內容區，保留導航外殼。 | 路由 chunk 延遲 1,000ms，250ms 時 Header、Sidebar 仍顯示。 |
| F05 | 100ms 合併事件；請求中來新事件完成後補刷；請求序號／帳號版本排除遲到結果。 | 3 個連續事件只追加 1 次列表請求；同帳號成功／失敗反序、請求中事件及跨帳號結果均受檢查。刷新保留現有內容。 |
| F06 | React 對 503／timeout 保留登入並顯示重試；憑證被拒才清除；refresh singleflight 與 WS 世代隔離。 | 503、timeout、重試、401、token 刷新合併、登入切換期間的舊請求／舊 WS callback 通過。 |
| F07 | 只有紅旗判定已完成且無警示、非收尾輪時，逐句提前送文字／音訊；加入拉丁標點斷句與匿名階段計時。 | 五語、待判定／失敗／high／critical／收尾、串流中斷等 12 項測試通過；中斷只保存已送出的文字。真 OpenAI 一般問診及中英文緊急紅旗情境通過，SOAP 為 generated。**2 秒 VAD 保留；真麥克風與端到端首音訊仍待真機量測。** |
| F08 | 波形／錄音秒數獨立訂閱；網頁波形節流 20Hz，VAD 判斷頻率維持。 | Flutter 60 次波形／時間更新不重建既有文字；Chrome 40／200 則對話各測 3 秒，歷史泡泡 props 各只更新一輪，皆無 >50ms long task。Root commit 54／55 次主要仍包含狀態子樹，不能等同全頁重建或真機幀率。 |
| F09 | 新增按本地日界線聚合 API；月份快取 60 秒、最多 12 月；選日明細 20 筆分頁，移除 1,000 筆截斷。 | 1,001 筆月統計正確，首屏 1 次聚合 + 1 次日明細；載入更多、跨月回訪快取、DST、時區與醫師權限驗證通過。 |
| F10 | queue／stats 合併查詢並省掉廣播未用明細；開場廣播以獨立 DB session 背景處理；月摘要改 SQL 聚合；通知合併計數並加索引。 | PostgreSQL 實際 1,001／10,001 筆資料驗證：通知列表 2 次 SQL、queue＋stats 廣播 2 次 SQL；通知排序 EXPLAIN 使用複合索引。這是 round-trip 減少，**不是宣稱整個 DB 只掃一次**。 |
| F11 | 登入後由醫師外殼共用 dashboard socket；報告／通知頁即時失效更新，斷線才輪詢；通知 commit 後才發 report_generated。 | 停留通知／報告頁即可看到新資料；跨頁保持 1 條 socket；事件 burst 合併，斷線備援仍會提示新增紅旗；另有通知 commit→事件順序測試。 |
| F12 | iOS 三種長列表使用 builder；網頁使用原生 content-visibility 跳過畫面外繪製。 | iOS 1,000 筆時捲動前後只建可見列（<30 張 Card）。Chrome 1,000 筆報告搜尋 **43ms**、通知點擊 **116ms**；末列鍵盤焦點往返通過。DOM 仍隨已載列數增長（18,157／7,125 節點）；超過此規模或實測超預算再加虛擬化。 |

以上瀏覽器毫秒數是這台 Mac 的單次合成資料樣本，**不是生產 P95、真實使用者 INP p75 或 iPhone 成績**。網頁原生繪製策略依 [MDN content-visibility](https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/Properties/content-visibility)，保留 DOM 與鍵盤順序，不新增套件。

### 驗收中額外修正

- 真 OpenAI 發現 Supervisor 在核心 HPI 未齊前優先補選配病史；對話模型與 Supervisor 改用同一份順序規則，必問風險／急症優先，其餘先補核心 HPI；下一輪同時收到合法的 missing_hpi 欄位，不再只讀一段 next_focus。onset 回答不知道不代表 duration 已回答。驗收中曾有核心完整度停在 70% 的失敗場次，已另存結果供對照；不以只保留 PASS 的方式宣稱穩定。修正未降低紅旗或回合上限。
- E2E 分析器原本只在「重問」識別持續／間歇同義句，卻不在「第一次問」識別，造成錯誤 INCOMPLETE。現在兩者使用同一規則；有回歸測試證明真正重問仍 FAIL、只有單邊詞彙不會誤建拒答 cutoff。另把指定情境的 onset／duration 拒答固定為測試輸入，其餘回答仍由模擬 LLM 生成，避免模擬器把持續／間歇問題誤答成加重因素，導致拒答路徑根本沒測到。
- 網頁語言解析跳過不存在的短語碼目錄：zh-TW 啟動 locale URL 從 20 降至 10，五個完整 locale 與既有 fallback 保留；尚未改成逐頁載入全部 namespace。
- CocoaPods 最低版本對齊 Runner 原有的 iOS 15，修正 Xcode 27 把舊 pod 的 iOS 9／12／13 deployment target 視為錯誤；未提高 App 原本的最低支援版本。
- WAV 編碼保留既有實作：Mac AOT、每種長度 30 樣本，10／30／60 秒音訊 P95 約 4.4／9.4／11.9ms。量測工具：`flutter_app/tool/voice_encode_benchmark.dart`（`fvm dart compile exe tool/voice_encode_benchmark.dart -o /tmp/gu-voice-encode && /tmp/gu-voice-encode`）。這無法證明 iPhone 成本，但不足以支持現在增加 isolate 或改音訊協定。

### 可重跑檢查

| 檢查 | 結果／入口 |
|---|---|
| Flutter | `fvm flutter analyze --no-pub` 無問題；`fvm flutter test --no-pub` **317 通過**；[smoothness_regression_test.dart](../flutter_app/test/smoothness_regression_test.dart)、[conversation_page_ux_test.dart](../flutter_app/test/conversation_page_ux_test.dart)。使用釘定 Flutter 3.41.3。 |
| iOS 編譯／啟動 | Xcode 27、arm64 iOS 27 模擬器編譯成功；全新 `GU Smoothness Acceptance` 模擬器啟動到登入頁。此為 debug smoke，不當作 profile 效能成績。 |
| React | `npm run lint`、`npm test`（14 個測試檔）、production build 成功；[狀態回歸](../frontend/scripts/verify/smoothness-state.test.mjs)。 |
| 瀏覽器流程 | [smoothness-browser.mjs](../frontend/scripts/verify/smoothness-browser.mjs)：Chrome 154、Playwright WebKit 26.4 各 9 情境通過（包含後續補上的手機導覽）；WebKit 引擎測試不等於實體 iPhone Safari。 |
| 長列表／語音 UI | [smoothness-performance.mjs](../frontend/scripts/verify/smoothness-performance.mjs)：40／200 則逐字稿，100／1,000 列報告和通知，6 組量測與門檻通過。 |
| 後端 | `venv/bin/pytest tests/unit -q` **4,879 通過、2 skipped**；環境須提供純測試 RS256 金鑰（下方歷史紀錄有產生方式）。包含逐句串流與中途失敗的 12 項檢查。 |
| 真 PostgreSQL | [test_smoothness_queries_pg.py](../backend/tests/integration/test_smoothness_queries_pg.py) ＋既有 doctor authz 測試 **10 通過**；local migration 已成功執行。非 SQLite／mock SQL。 |
| 真 OpenAI | `dontknow_zh`、`torsion_critical_zh`、`torsion_critical_en`：PASS、SOAP generated、受測工作區 provenance verified；緊急情境為 rule_hit 並阻止繼續問診。採文字 WS 輸入，**沒有驗到真 STT／麥克風**。 |
| 翻譯／驗收工具 | `backend/venv/bin/pytest scripts/tests -q` **20 通過**；`scripts/check_translations.py --mirrors frontend/public/locales,flutter_app/assets/locales` 通過。 |

瀏覽器流程跑法（frontend 目錄；build 未開 mock mode，腳本攔截全部後端 HTTP／WS，使用合成資料）：

```bash
npm run build -- --outDir /tmp/gu-smoothness-dist
npm run preview -- --outDir /tmp/gu-smoothness-dist --host 127.0.0.1 --port 4317
# 另一終端，同樣在 frontend：
node scripts/verify/smoothness-browser.mjs
SMOOTHNESS_BROWSER=webkit node scripts/verify/smoothness-browser.mjs
node scripts/verify/smoothness-performance.mjs
```

iOS 本機已驗過的建置（flutter_app 目錄，`<simulator-id>` 替換成 `xcrun simctl list devices` 的 arm64 目標）：

```bash
(cd ios && pod install)
xcodebuild -workspace ios/Runner.xcworkspace -scheme Runner -configuration Debug \
  -sdk iphonesimulator -destination 'platform=iOS Simulator,id=<simulator-id>' \
  ARCHS=arm64 ONLY_ACTIVE_ARCH=YES CODE_SIGNING_ALLOWED=NO build
```

本機 Xcode 27 的通用雙架構 `fvm flutter build ios --simulator --debug --no-pub` 尚會卡在 SDK 工具的 `lipo -verify_arch arm64 x86_64`（報 `requires exactly one input file`，但 `lipo -info` 顯示兩架構都存在）；單 arm64 命令已成功，未修改 Flutter SDK 或排除真機架構。

本次量測產物在 `/tmp/gu-smoothness-{chrome,webkit}-final2.json`、`/tmp/gu-smoothness-performance-final.json`、`/tmp/gu-smoothness-ios-launch.png`；真 OpenAI 紀錄在已忽略版控的 `scripts/e2e_realopenai/results/`。可重跑的驗收程式已留在 repository，不依賴暫存腳本。

### 發佈與剩餘驗收

- 發佈先上後端與 Alembic `smoothness_20261003` migration，再上兩端，因新版 iOS 月曆依賴 `/dashboard/calendar`。新通知索引用 concurrent 建置；production 尚未變更；獨立 staging 已完成此順序中的後端與 React preview，iOS 候選 IPA 尚待 Apple 協議／上傳。
- **待真機**：最慢支援 iPhone／60Hz／120Hz／iPad profile build 的捲動和鍵盤幀時間；冷暖啟動、真實慢速／中斷網路、麥克風與慢速說話、電話／背景打斷恢復、VoiceOver／大字體／減少動態效果。
- **待實際環境量測**：Web INP p75／LCP、DB／Redis RTT 與 P95、完整「最後語音→VAD→上傳→STT→首音訊」。現有 log 僅提供匿名 STT／LLM／首 chunk 階段，不能拿文字 E2E 換算全程。
- 字型載入與首次通知權限對實機啟動的影響仍是待量測候選，尚未證實為瓶頸；沒有為此增加套件或重寫框架。

## 2026-10-03 修復前基線（歷史對照）

維護範圍是 **Flutter iOS App、React 網頁、共用 FastAPI 後端**。本輪依使用者「整體操作都要流暢」的要求，檢查啟動、醫師分頁、列表／搜尋、通知、語音問診、資料規模及失敗恢復。**目前最明確的問題是重複請求、導頁等待、不保留操作狀態，以及語音頁重繪範圍過大。**

本節保留同日修復前的問題與數字；目前狀態以上方修復驗收表為準。下方 2026-08-22 的數字及部署敘述只代表當時。2026-10-03 前一輪 iOS M1–M3 的修正仍在工作區，這次以修正後程式碼為基準；React 的同類路徑、場次列表同帳號內的請求排序並不在先前通知修正的涵蓋範圍。

### 證據與限制

- React 以 `npm run build -- --outDir /tmp/gu-voice-smoothness-dist` 建置 production bundle，再由 Chrome 154 + Playwright 操作。HTTP／WebSocket 全部攔截，使用合成資料與假 token，禁止瀏覽器連至外部服務。沒有使用內建 mock mode，故走的是正式頁面及 API 邏輯。
- Flutter 使用釘定 SDK 的 `fvm flutter test --no-pub test/_smoothness_audit_test.dart`，3 個診斷情境都重現預期問題。使用真實 router／頁面／controller、假的 HTTP 與 socket；這是行為診斷，**不是 iPhone 幀率測試**。診斷檔刻意未入庫（一次性、已丟棄），不把「舊 bug 必須存在」的斷言放進正式回歸套件。
- Chrome 的 1,000ms chunk 延遲與 1,200ms API 延遲都是刻意注入的條件；下列耗時不能當成目前生產環境的 P95。沒有量測真機耗電、真實麥克風、Safari 或線上 DB 查詢計畫，也未呼叫真實 LLM。
- `mobile-app-ux-auditor` 掃描 185 個檔案。lib 內 268 條訊號多為 tooltip、label、權限等關鍵字提示，含跨框架誤判，**不計為 268 個已確認缺陷**。本表只列實際核對的流暢度問題。
- 本輪只新增稽核紀錄，未修改產品行為或部署。

### 優先處理的 12 個問題

P1 是核心操作明確受影響，P2 是規模或特定條件下的瓶頸。每項標出「重現」或「程式路徑確認」；後者不代表已測得真機掉幀或生產延遲。

| ID／優先 | 操作與問題 | 證據、使用者影響 | 最小改善方向與驗收 |
|---|---|---|---|
| F01／P1 | **iOS 切分頁丟狀態並重抓資料** | **重現**：dashboard → sessions → dashboard，月摘要 API 從 1 次變 2 次；sessions 輸入搜尋字串後切走再回來，字串變空。五個分頁是獨立 route，頁面 State 被銷毀。 | 保留各分頁的 navigator／頁面狀態，沿用 go_router 的狀態分支；依帳號清除。連續切換 20 次，搜尋、月份、捲動位置保留；資料未失效時不重抓。 |
| F02／P1 | **網頁報告清單仍有逐筆查詢** | **重現**：20 份報告 → 1 次列表 + 1 次 `limit=100` 統計用列表 + 20 次場次明細＝**22 次**，不含登入與導覽列請求。後端列表已附病患／主訴／場次欄位，React 仍不使用。統計又只數首 100 份，超過後會少算。 | 直接使用現成列表欄位，沿用已修 iOS 的相容策略；計數使用真正總數。報告頁請求數不隨首屏列數增加；用 >100 份資料驗證計數。 |
| F03／P1 | **網頁點通知，要等已讀 API 才跳頁** | **重現**：對已讀 API 注入 1,200ms 延遲，250ms 時仍在通知頁且無 loading spinner，約 **1,249ms** 才導頁。`handleOpen` 在導航前 `await markRead`。 | 導頁先回應，已讀背景處理並處理失敗；使用相同 1,200ms 條件，導頁不應等待該請求。 |
| F04／P1 | **網頁第一次換頁會連導覽列一起消失** | **重現**：未下載的病患頁 chunk 延遲 1,000ms，250ms 時 Header、Sidebar 都不可見，只剩整頁 spinner。根層 Suspense 包住整個 Routes。 | 將 loading boundary 放在內容區，保留外殼；必要時預抓常用 route。慢速 chunk 載入期間導覽持續可見可用。 |
| F05／P1 | **即時事件連發造成重抓，舊結果還能倒灌** | **兩端重現**：連續送出 `session_created`、`session_status_changed`、`queue_updated`，各產生 **3 次**場次列表請求。**Flutter 另重現**同帳號兩個 reload 反序完成後，較舊的 `waiting` 列表覆蓋較新的 `completed` 列表。上一輪只讓通知列表接受最新請求，場次列表尚未套用。 | 合併短時間事件；請求中有新事件時記為待刷新，完成後補一次；用請求序號丟棄舊回覆。驗收事件 burst 與反序成功／失敗回覆；保留帳號隔離。 |
| F06／P1 | **網頁暫時故障會把使用者踢回登入** | **重現**：儲存登入憑證後，讓 `/auth/me` 回 503，頁面轉 `/login`，access／refresh token 都被刪除。`hydrateFromStorage` 的 catch 不區分故障原因；refresh 失敗也統一清登入。 | 將暫時網路／5xx 與憑證失效分開，提供可重試狀態。移植已驗證的 iOS 行為契約，測試 503、timeout、401、切帳號期間的遲到回覆。 |
| F07／P1 | **每個語音回合有多段必等路徑** | **程式路徑確認**：兩端自然停講都等 2 秒；iOS 整段 WAV 在結束時才編碼並 base64 上傳。後端雖從 LLM 接收串流並預先合成 TTS，對病患的第一個文字／音訊 chunk 卻要等生成迴圈完成、持久化與紅旗 gate 後才送。斷句又只認 `。！？\n`，使用拉丁標點的回覆要等尾段。 | 先分段量「停講→送出→STT→首文字→首音訊」，保留「我說完了」即送入口；設計能保持安全判定與結束規則的串流。**不可直接刪掉紅旗 gate、硬縮 VAD 或先播未通過的內容**。修改前依語音不變式驗證，五語與慢速說話都要驗。 |
| F08／P2 | **波形更新牽動整個語音頁** | **量測重建，未證明掉幀**：40 則合成逐字稿，開 fake mic 的 3,002ms 內 **181 次 React root commit**；關 mic 對照 3,003ms 內 1 次。React 每個 rAF 都寫 Zustand，頁面訂閱整個 store，所有 ChatBubble 再建 props；iOS 雖節流到最高 20Hz，仍整頁 watch state。本機兩組皆無 >50ms long task。 | 將波形／秒數的訂閱限於對應元件、避免重建歷史逐字稿；沿用既有狀態框架。用 40／200 則對話在真機 profile 測 build／raster、鍵盤與捲動；安全橫幅及終態兩欄必須維持一致更新。 |
| F09／P2 | **iOS 日曆載入整月，資料多就等更久且截斷** | **重現**：後端每頁 100 筆、持續回 hasMore；`fetchRange` 發出 **10 次循序請求**後只回 1,000 筆，沒有告訴呼叫者仍有資料。日曆等全部載完才分桶顯示，跨月也不快取。 | 月曆先取按日聚合數量，選日再分頁取明細；維持本地時區定義。用 1,001+ 筆資料驗證不默默少算、首屏不等十頁。 |
| F10／P2 | **後端把統計成本放進即時互動路徑** | **程式路徑確認，尚未 EXPLAIN／壓測**：病患 WS 開場前 await `broadcast_queue_and_stats`；內部 queue 3 次＋全域 stats 4 次 SQL 依序執行，取得 50 筆 queue 明細後廣播卻只送空 queue。月摘要搬出整月 Session ORM 再於 Python 統計；通知列表查列表、總數、未讀數，client 又另查未讀。模型及 migrations 未見匹配通知排序的複合索引。 | 先移除沒有消費者的明細計算、合併聚合與重複計數，再測 1k／10k 資料的 SQL 計畫。若將廣播移至背景，要有獨立 DB 生命週期並保持跨 worker 事件可靠性；不能只跳過通知。 |
| F11／P2 | **網頁資訊更新速度不一致** | **程式路徑確認**：Header 未讀數只在掛載時抓；通知頁只在掛載時抓列表，沒有即時訂閱。醫師外殼的紅旗輪詢是 **20 秒**；dashboard socket 綁於個別頁面，離頁就 disconnect。使用者需重新進頁才看見某些變化。 | 以登入生命週期維護共用 dashboard 連線，集中通知失效／去重，避免每頁各開關 socket；輪詢僅作恢復手段。停留通知／報告頁時，新事件要在約定延遲內出現；切頁不拆共用連線。 |
| F12／P2 | **長列表的 UI 工作量隨已載資料一直增長** | **程式路徑確認，尚未真機掉幀量測**：Flutter 病患／報告／紅旗列表使用 `ListView(children: [for ...])`，每次先建立全部列；React 通知／報告以 `.map` 渲染全部已載列，無視窗化。分頁限制下載量，並沒有限制累積 UI 建構／DOM 數量。 | Flutter 先用既有 builder／sliver，只建立可見列；React 先量 100／1,000 筆的 DOM 與互動，再決定是否需要視窗化。保留搜尋、分組、鍵盤焦點及讀屏順序。 |

### 程式定位

以下行號以本輪檢查時工作區為準。

| 問題 | 入口與共同根因 |
|---|---|
| F01 | [app_router.dart](../flutter_app/lib/core/router/app_router.dart):176、[doctor_shell.dart](../flutter_app/lib/features/doctor/screens/doctor_shell.dart):31、[dashboard_page.dart](../flutter_app/lib/features/doctor/screens/dashboard_page.dart):62、[session_list_page.dart](../flutter_app/lib/features/doctor/screens/session_list_page.dart):26 |
| F02 | [ReportListPage.tsx](../frontend/src/screens/doctor/ReportListPage.tsx):215／256、[reportStore.ts](../frontend/src/stores/reportStore.ts):151、[report.py](../backend/app/schemas/report.py):60 |
| F03 | [NotificationPage.tsx](../frontend/src/screens/doctor/NotificationPage.tsx):67、[notificationStore.ts](../frontend/src/stores/notificationStore.ts):73 |
| F04 | [RootNavigator.tsx](../frontend/src/navigation/RootNavigator.tsx):107／126、[MainLayout.tsx](../frontend/src/components/layout/MainLayout.tsx):24 |
| F05 | [sessions_list_controller.dart](../flutter_app/lib/features/doctor/state/sessions_list_controller.dart):47、[SessionListPage.tsx](../frontend/src/screens/doctor/SessionListPage.tsx):63／97；同類無請求排序保護的篩選入口：[alerts_controller.dart](../flutter_app/lib/features/doctor/state/alerts_controller.dart):101／144 |
| F06 | [authStore.ts](../frontend/src/stores/authStore.ts):177、[client.ts](../frontend/src/services/api/client.ts):257 |
| F07 | [audio_stream_service.dart](../flutter_app/lib/features/voice/services/audio_stream_service.dart):37／332、[audioStream.ts](../frontend/src/services/audioStream.ts):132、[conversation_handler.py](../backend/app/websocket/conversation_handler.py):55／1779／1997／2379 |
| F08 | [audioStream.ts](../frontend/src/services/audioStream.ts):286、[useAudioStream.ts](../frontend/src/hooks/useAudioStream.ts):57、[ConversationPage.tsx](../frontend/src/screens/patient/ConversationPage.tsx):88／1247、[conversation_page.dart](../flutter_app/lib/features/voice/screens/conversation_page.dart):51 |
| F09 | [sessions_api.dart](../flutter_app/lib/data/api/sessions_api.dart):118、[session_calendar_view.dart](../flutter_app/lib/features/doctor/screens/session_calendar_view.dart):229 |
| F10 | [conversation_handler.py](../backend/app/websocket/conversation_handler.py):627、[dashboard_handler.py](../backend/app/websocket/dashboard_handler.py):252／393／595、[dashboard_service.py](../backend/app/services/dashboard_service.py):484、[notification_service.py](../backend/app/services/notification_service.py):346 |
| F11 | [Header.tsx](../frontend/src/components/layout/Header.tsx):37、[NotificationPage.tsx](../frontend/src/screens/doctor/NotificationPage.tsx):47、[DoctorAlertPoller.tsx](../frontend/src/components/DoctorAlertPoller.tsx):18、[useWebSocket.ts](../frontend/src/hooks/useWebSocket.ts):144 |
| F12 | Flutter [patient_list_page.dart](../flutter_app/lib/features/doctor/screens/patient_list_page.dart):178、[report_list_page.dart](../flutter_app/lib/features/doctor/screens/report_list_page.dart):229、[alert_list_page.dart](../flutter_app/lib/features/doctor/screens/alert_list_page.dart):163；React [NotificationPage.tsx](../frontend/src/screens/doctor/NotificationPage.tsx):110 |

### 次要候選與排除項目

- **啟動資源**：本次 zh-TW 網頁載入 20 個 locale URL，其中 10 個是程式未提供的 `/locales/zh/`；只有五個完整 locale 目錄。i18next 同時預載所有 namespace，語言解析還包含短語碼。應調整語言解析及按頁 namespace 載入，保留 fallback 行為。這次沒有證明它是啟動最大的耗時。
- **iOS 字型／權限**：Inter 由 `GoogleFonts.interTextTheme` 取用，pubspec 未 bundle 字型；通知權限在登入後首幀即啟動。列為冷啟動重排與首次互動的候選，未量測實體裝置的影響，不能把非同步 Firebase 初始化直接說成 UI thread 被阻塞。
- **不把 bundle 大小當成目前主因**：production 建置成功，路由已 lazy load；入口 JS 約 100.87KB（gzip 33.30KB），React vendor 約 165.97KB（gzip 54.31KB）。這不構成改框架／全面重寫的證據。
- **不沿用舊部署測速當今天的數值**：2026-08-22 的 Railway／Redis 跨區測量是歷史紀錄，本輪沒有重新連線測量。需在實際測試環境另查 DB／Redis RTT、冷啟動及 P95。
- **不把上一輪 308 個 Flutter 測試通過視為效能達標**：現有 CI 守編譯、靜態分析與功能，但沒有 frame timing、頁面請求預算、首音訊及 route 回應延遲的驗收。

### 執行順序與驗收標準

1. **先縮短日常操作等待**：F01–F06。保留分頁、立即導頁、縮小 loading 範圍、拿掉逐列查詢、合併事件並排除舊回覆；同步處理網頁的暫時故障恢復。
2. **再處理長時間與資料增加後的流暢度**：F08、F09、F11、F12。分離波形更新、修月曆資料形狀與上限、統一即時資料生命週期；在 40／200 則對話及 100／1,000 筆列表下量測。
3. **量出語音及後端關鍵路徑再修改**：F07、F10。採同一個匿名回合 ID 分段計時，不記錄音訊或病歷文字；依 STT／LLM／TTS／DB／Redis 各自的 P50／P95 決定順序。

建議的工程門檻如下，**是待驗收目標，不是目前成績**：

| 指標 | 建議門檻／契約 |
|---|---|
| 點擊回饋／已載分頁切換 | P95 ≤100ms；非必要網路不能阻擋導頁；慢網路不隱藏導航、不得先清掉已載內容。 |
| Web 真實互動 | p75 INP ≤200ms、LCP ≤2.5s；另量測「點擊到目標內容可用」，避免 INP 良好但仍等資料。門檻依 [INP 官方說明](https://web.dev/articles/inp)、[LCP 官方說明](https://web.dev/articles/lcp)。 |
| iOS 捲動／鍵盤／轉場 | 最慢支援真機使用 profile build；60Hz 以每幀約16.7ms、120Hz 約8.3ms 為預算，記錄超時幀比例與 P95。模擬器與 debug build 不作達標依據，依 [Flutter 官方 profiling 指引](https://docs.flutter.dev/perf/ui-performance)。 |
| 列表資料一致性 | 事件 burst 合併；舊成功／失敗不能覆蓋新結果；資料量超過上限必須明示或正確分頁。 |
| 語音回應 | 先取得「最後語音→VAD 結束→上傳完→STT 完→首文字→首音訊」分段基線；區分靜音判定與服務延遲。自然停講的 2 秒不能被藏在 API 計時之外。 |
| 恢復與回訪 | 暫時 503／timeout 保留登入；斷網重連、背景回前景、切頁回來不丟輸入／選取／位置，且不呈現舊帳號資料。 |

必要矩陣：iPhone 60Hz／120Hz、iPad、桌面 Chrome／Safari；冷／暖啟動、正常／慢速／中斷網路、40／200 則逐字稿、100／1,000+ 筆列表。鍵盤打開、大字體、減少動態效果、VoiceOver，以及語音被電話／切背景打斷後的恢復都尚待裝置驗收。

### 本機重現紀錄

| 檢查 | 結果 |
|---|---|
| production React build | 成功；產物在 `/tmp/gu-voice-smoothness-dist`。 |
| Playwright 正式流程診斷 | 5 個情境完成：報告請求、lazy 導航外殼、通知點擊、bootstrap 503、WS burst。腳本 `/tmp/gu-voice-smoothness-browser.mjs`；結果 `/tmp/gu-voice-smoothness-browser.json`。 |
| React 麥克風對照 | 2 組各約3秒，40則逐字稿；1 vs 181 root commit，皆無 >50ms long task。腳本 `/tmp/gu-voice-smoothness-voice.mjs`；結果 `/tmp/gu-voice-smoothness-voice.json`。 |
| Flutter 診斷 | 3 個情境：切分頁／搜尋／burst、回覆反序、月資料截斷；log `/tmp/gu-voice-smoothness-flutter.log`。這些斷言描述目前缺陷，並不表示修好了。 |

`/tmp` 是本次診斷暫存，不是 CI 產物。後續修復時應將相同情境改成正向回歸測試，並把真機與網路測量納入發佈驗收。

## 2026-08-22 歷史稽核紀錄

以下保留當時調查、修正與取捨；「已部署」「尚未修」等敘述按原日期解讀。

單一權威來源：**這一輪「app 不順」查了什麼、修了什麼、還剩什麼**。
其他文件不重抄結論，連結過來即可。

稽核方式：7 個面向各派一個 agent 讀真實原始碼（cold start／rebuild 範圍／前端網路／
SQL／event loop 阻塞／語音管線延遲／體感流暢度），每一條再由一個敵意查證 agent 逐條
反駁。**42 條提出、33 條存活、9 條被駁回**。被駁回的不列在這裡——它們的價值是「不要再
查一次」，摘要見下方 §4。

驗證狀態：`fvm flutter analyze` 全綠、`fvm flutter test` **236 項全過**（稽核前 217）、
`venv/bin/pytest tests/unit` **4751 項全過、0 失敗**（稽核前 4743）。

⚠️ 後端測試**沒 export JWT 金鑰時會有 25 項失敗**，訊息是
`jwt.exceptions.InvalidKeyError: Could not parse the provided public key`。那與程式碼無關，
是本機環境缺 RS256 測試金鑰；export `JWT_PRIVATE_KEY`／`JWT_PUBLIC_KEY` 之後全綠。
第一次看到時我用 `git stash` 對照過 HEAD，失敗集合一模一樣——**下次別再花時間查它**。
金鑰是純本機測試用、與生產無關，掉了就重生一組：

```bash
openssl genrsa -out /tmp/jwt_private.pem 2048
openssl rsa -in /tmp/jwt_private.pem -pubout -out /tmp/jwt_public.pem
export JWT_PRIVATE_KEY="$(cat /tmp/jwt_private.pem)" JWT_PUBLIC_KEY="$(cat /tmp/jwt_public.pem)"
```
iOS simulator（iPhone 17／iOS 26.5）實機開機驗過三次；Flutter Web release build
在本機 SPA server 上驗過深連結 `/vi-VN/reset-password?token=…`：語言段與 query 都完整保留。

---

### 1. 已修：開機路徑

開機是這次最大的一塊。修之前的順序是：

```
main()
  ├─ await Locales.loadAll()   50 次「循序」rootBundle 讀取 + 50 次 json.decode（主 isolate）
  ├─ await bootstrap()
  │    ├─ await TokenStore.load()   Keychain
  │    └─ await getMe()             打 Railway，逾時上限 30 秒
  └─ runApp()                       ← 在這之前畫面上只有靜態 LaunchImage
```

也就是說，**登入中的醫師每次冷啟動都在盯一張不會動的啟動圖**，直到一趟 Railway 來回
結束為止（本機實測該後端 warm TTFB ~270ms、cold ~400ms；手機行動網路再加 RTT）。
網路慢就更久，最壞情況 30 秒，而且沒有轉圈、沒有任何回饋。

| 改動 | 檔案 | 內容 |
|---|---|---|
| `runApp` 不再等網路 | `flutter_app/lib/main.dart` | `bootstrap()` 改成不 await。第一幀立刻畫得出來 |
| 開機畫面 | `flutter_app/lib/features/auth/boot_gate.dart`（新） | 轉圈延遲 450ms 才淡入——快的開機完全不會閃一下 |
| router 延後建立 | `flutter_app/lib/app.dart` | **這條是關鍵**：boot 沒完成前不建 GoRouter。否則深連結頁面會在 token 載入前就發 API、吃 401，跟 bootstrap 自己的 getMe 搶 refresh token |
| 語言只載需要的 | `flutter_app/lib/core/i18n/locales_loader.dart` | 50 次循序 → 當前語言＋其 fallback 鏈，10 個併發。其餘 4 種語言在第一幀後 **2 秒** 才背景補（web 上那是 40 個 HTTP 請求，不該跟使用者第一次點擊搶頻寬） |
| 開機語言解析 | `flutter_app/lib/core/router/lng.dart` | `bootLanguage()`：web 讀 URL、其他讀裝置語系，與 router redirect 同一套規則 |
| 網路失敗不再毀掉登入狀態 | `flutter_app/lib/features/auth/auth_notifier.dart` | **原本任何 exception 都會 `TokenStore.clear()`**——院內 Wi-Fi 抖一下，醫師就被登出、要重打密碼，而 token 根本是好的。現在只有 401/403 才清；網路類錯誤走 `bootOffline` 顯示重試 |
| 開機逾時 | 同上 | getMe 8 秒（Dio 本身是 30 秒）。30 秒的空畫面與當機無法區分 |
| 重試畫面有出口 | `boot_gate.dart` | 「有存著的 token ＋ 連不上後端」原本會變成死路（登入頁在 router 後面、router 在 boot 後面）。加了本地登出 |
| 白畫面 → 看得見的錯誤 | `flutter_app/lib/core/error_boundary.dart`（新） | 這支 App 沒有 Crashlytics（§V7），任何未捕捉的 Dart 例外在 release iOS 上就是**一片空白**，測試者只能回報「打不開」。三個掛勾：`FlutterError.onError`、`PlatformDispatcher.onError`、`ErrorWidget.builder`。細節照樣進 stderr，`flutter logs` 看得到 |
| Web 開機遮罩 | `flutter_app/web/index.html`、`web/flutter_bootstrap.js` | Flutter 畫的東西（含上面那個 BootGate）都在 `main.dart.js` 裡，4.1MB 下載＋編譯完成前一個像素都沒有。改成靜態 DOM 遮罩，Flutter 第一幀畫完才拿掉 |

⚠️ **`ErrorWidget.builder` 與 BootGate 都刻意只用原生元件**，不吃 `Theme`／`Directionality`／
`MediaQuery` 繼承——它們可能被插在 `MaterialApp` 之上，缺什麼就得自己帶，否則「替換壞掉的
子樹」這件事本身又會拋一次。

⚠️ **`bootOffline` 也算「還沒開完機」**。第一版只看 `booted`，結果重試畫面永遠到不了——
是 `test/boot_gate_test.dart` 抓到的。那條測試現在守著這件事。

### 2. 已修：醫師端（iOS 的主戰場）

| 改動 | 檔案 | 前 → 後 |
|---|---|---|
| 報告清單 N+1 | `backend/app/schemas/report.py`、`services/report_service.py`、`flutter_app/.../report_list_page.dart` | **22 個請求 → 2 個**。`GET /reports` 現在 eager-load 場次與病患，隨報告一起回姓名／主訴／狀態／紅旗 |
| 統計卡 | `report_list_page.dart` | 原本抓 `limit:100` 整整 100 份完整 SOAP 報告只為了數 4 個數字，而且**超過 100 筆就默默少算**。改成 4 個併發的 `limit:1` 讀 `pagination.totalCount` |
| 通知頁抓取 | `notifications_controller.dart` | 兩個獨立端點原本 `await` 串著跑 → `Future.wait` |
| 通知抓取失敗 | `notification_page.dart` | **原本顯示「沒有新通知」**。iOS 醫師的 landing page 在網路失敗時對他說「沒事發生」，沒有錯誤、沒有重試。改成錯誤分支排在空狀態之前，加重試鈕與下拉更新 |
| 點通知 | `notification_page.dart` | 原本 await mark-read 才導頁——iOS 上最常用的手勢要等一趟來回（逾時上限 30 秒）才有反應。樂觀更新本來就是同步先寫的，不必等 |
| 通知清單 | `notification_page.dart` | `ListView(children:)` → `ListView.builder`。這個 controller 每收到一個 dashboard WS 事件就重抓，等於全院任何病患動一下就重建所有列 |
| SOAP 報告頁 | `soap_report_page.dart` | 4 趟循序 → 併發，報告先畫。**順手補了一個安全漏洞**：`_session` 還沒回來時原本算成「無紅旗」，現在是獨立的 `unknown` 狀態（`SizedBox.shrink()` 看起來就是「這個場次沒有紅旗」） |
| 研究分析頁 | `research_analytics_page.dart` | build 裡 `GlobalKey()` → 每次重建都把 9 張圖表拆掉重建、重播進場動畫。改成固定 id 的快取 key |

### 3. 已修：語音管線與後端

| 改動 | 檔案 | 內容 |
|---|---|---|
| 波形寫入 | `flutter_app/lib/features/voice/services/audio_stream_service.dart` | AI 說話（hard mute）時完全不發——那時麥克風聽到的是喇叭回音。其餘時候節流到 20Hz。原本是每個 mic buffer 一次全頁重建（iOS ~47/秒） |
| 秒數寫入 | 同上 | 100ms 一次 → 只在**整秒變化**時才發。畫面是 `toStringAsFixed(0)`，十次有九次字串一模一樣卻重建整頁 |
| 假的斷線橫幅 | `conversation_page.dart` | `connecting` 是初始值，所以病患進問診頁**第一眼看到的就是「連線中斷，正在重新連線…」**，而且撐過整個麥克風授權對話框。改成細進度條 |
| gzip | `backend/app/main.py` | 全站沒有壓縮。這個 API 回的 JSON 壓縮比 5–10 倍，而診間 Wi-Fi 上「傳幾個 byte」正是使用者在等的東西 |
| bcrypt 移出 event loop | `backend/app/core/security.py`、`services/auth_service.py` | cost-12 是 200–400ms **不可中斷**的 CPU。跑在 event loop 上等於一個人登入、全院停擺：問診 WS 的音訊 chunk 送不出去、STT 上傳卡住 |
| ThemeData 快取 | `flutter_app/lib/core/theme/app_theme.dart` | getter → `static final`。每次 `App.build` 都重跑兩次 `ColorScheme.fromSeed` ＋ `GoogleFonts.interTextTheme` |

### 4. 沒修，以及為什麼

分三類。

> ⚠️ **2026-08-22 稍晚追加：這一輪最大的一條不在下面的表裡。**
> 後端跑在 Railway 加州、Supabase 在新加坡，**每一句 SQL 都橫跨太平洋**——
> 不碰 DB 的端點 1.88 ms，跑一句 `SELECT 1` 的端點 1.55 s，而且過半會撞上 2 秒逾時回 500。
> `railway.toml` 原本就想指定新加坡，但用了 Railway 不存在的 `region` 鍵，安靜失效。
> 已修正成 `[deploy.multiRegionConfig."asia-southeast1-eqsg3a"]`，
> **搬遷步驟見 [`railway_region_move.md`](railway_region_move.md)**。
> 下面那些前端的等待時間，在這一條修好之前都是次要項。
>
> ✅ **2026-08-22 已部署**（main `175e704`、Railway deployment `fd780d67`）：
> 服務已在 Southeast Asia。`healthz/deep` 從 **1.85 s／20-38 回 500** 變成
> **0.413 s／10-10 全 200**，扣掉網路後的伺服器端工作 1.55 s → **0.19 s**。
> 剩下那 0.19 s 幾乎全是 **Redis 仍在加州**（volume 1077 MB，搬遷要排維護窗口，
> 見 [`railway_region_move.md`](railway_region_move.md) §4）。

#### 4a. 需要你拍板（臨床或部署決策，不該由我單方面改）

| 項目 | 檔案 | 為什麼要你決定 |
|---|---|---|
| **VAD 靜音 2 秒才送出** | `audio_stream_service.dart:37` | 每個語音回合固定 2 秒「看起來當掉」——狀態列還寫著聆聽中、波形還在動、伺服器一個 byte 都還沒收到。但調短會**切掉講話比較慢的病患**，那是臨床參數不是效能參數 |
| **`main.dart.js` 每次都重抓** | `tool/prepare_vercel_output.dart:37` | 4.1MB／brotli 866KB，`no-store` 且沒有 service worker，每次開頁都重抓。正解是檔名加 hash ＋ immutable 快取，但那要動部署腳本（`build_vercel_output.sh:56` 還在 grep 字面的 `main.dart.js`），而 Flutter Web 目前是 staged、還沒 promote |
| **LLM 回覆不是串流吐出** | `websocket/conversation_handler.py:1763` | 病患每答完一句，要等「LLM 全部生成完 ＋ 紅旗閘門過 ＋ 第一段 TTS 好」才看得到任何東西。改成邊生成邊送是這條線上最大的體感改善，但它動的是問診管線——照鐵律要先讀 `voice-pipeline-invariants`，改完要跑 `e2e-real-openai` |
| **斷句只認 CJK 標點** | `websocket/conversation_handler.py:50` | en-US／ko-KR／vi-VN 完全吃不到逐句 TTS。修法本身很小（補拉丁標點），但同樣落在問診管線的守則裡 |

#### 4b. 明確判定「不要這樣做」

- **不要把 `_ws.connect` 挪到 `openMic` 前面**。`audio_stream_service.dart:212` 在 openMic 成功時把
  `_muteMode` 重設成 `none`；AI 回合若落在那個空窗，麥克風會被悄悄解除靜音並錄進 TTS 回音
  （語音不變式 #3）。要並行得先讓 openMic 保留既有 mute 狀態，那是另一個改動，不是換順序。
- **`ConversationPage` 的 `.select` 收斂**先不做。收斂本身是對的，但每一個橫幅欄位
  （`redFlags`／`guidance`／`supervisorDegraded`／`error`／`voiceUnavailable`／`connection`）
  都必須出現在某個 selector 裡，漏掉 `redFlags` 就是**紅旗橫幅不會出現**。
  本輪先做零風險的那一半（上面的波形／秒數節流），已經拿掉絕大部分重建。
- **`completed` / `abortedRedFlag` 不得搬出同一個 state 物件**。
  `conversation_page.dart:52-59` 記著一個真實 bug：從不同 emission 讀這兩個欄位，
  會把紅旗中止的病患送到一般感謝頁。

#### 4c. 已查證、可以直接做，只是這輪沒排進去

| 嚴重度 | 位置 | 內容 |
|---|---|---|
| medium | `backend/app/websocket/conversation_handler.py:615` | 病患問診 WS handshake 在送出開場白前，循序跑 7 次全表掃描 |
| medium | `backend/app/services/notification_service.py:360` | 通知清單排序在沒有索引的 `created_at` 上，外加兩個無上限 `COUNT(*)`。這張表每個醫師每場完成問診就長一列 |
| medium | `backend/app/services/dashboard_service.py:472` | 月統計把整個月的 Session ORM 物件（含 `intake_data` JSONB）都撈進記憶體，只為了累加計數 |
| medium | `backend/app/websocket/dashboard_handler.py:269` | 每次場次狀態變更，在病患的 connect path 上同步跑 7 次查詢 |
| medium | `flutter_app/lib/data/api/reports_api.dart:71` | `getReportBySession` 固定兩趟；病患等報告的畫面會輪詢 12 次＝24 個請求，其中一半只為了讀 `status` |
| medium | `flutter_app/.../audio_stream_service.dart:329` | 整段語音在講完後才以未壓縮 base64 WAV 一次上傳，永遠無法與「正在講」重疊。15 秒的回答約 640KB |
| medium | `flutter_app/.../doctor_shell.dart:31` | 五個醫師分頁是五條獨立 route，每次切換整頁重建：dashboard 重新轉圈重抓、搜尋框與捲動位置全丟。正解是 `StatefulShellRoute` |
| low | `flutter_app/lib/features/doctor/doctor_push_watcher.dart:41` | `Firebase.initializeApp()` 與 iOS 通知授權對話框跑在第一個 post-frame callback，正好卡在醫師開 App 後第一次點擊 |
| low | `flutter_app/lib/shared/format.dart:8` | 清單每次 build 都重跑排序與 `DateFormat` 建構 |
| low | `flutter_app/.../sessions_list_controller.dart:43` | 每個 dashboard WS 事件都重抓 50 筆場次，沒有 debounce；後端一次病患動作會發 2–3 個相符事件 |
| low | `backend/app/services/session_service.py:1204` | `GET /sessions/{id}/conversations` 為了回一頁而把整份逐字稿載入兩次 |

#### 4d. 兩個稽核沒抓到、我自己看到的

- **`google_fonts` 在執行期從網路抓 Inter**（`core/theme/app_theme.dart:29`，pubspec 沒有 bundle 字型）。
  首次啟動會有字型切換的重排，而且在防火牆嚴格的院內網路會直接抓不到。
  內建的代價是 **1.3MB**（Inter 400/500/600/700 各 ~325KB）——iOS 的 25MB IPA 吃得下，
  但 Flutter Web 會在啟動時把宣告的字型全部載入，等於 web 冷啟動多 1.3MB。
  **這是取捨，所以留給你決定**；另外注意 Inter 沒有 CJK 字符，這個 App 的中文本來就是走系統字型。
- **iOS LaunchScreen 背景寫死純白**（`ios/Runner/Base.lproj/LaunchScreen.storyboard:22`，
  `red=1 green=1 blue=1`）。深色模式的醫師每次冷啟動都會先閃一下全白再跳進深色 App。
  修法是啟動圖加 dark appearance 變體 ＋ storyboard 改用動態色，並讓 `tool/gen_app_icons.py`
  一起產生——目前那支腳本只產淺色版。

---

### 5. 被駁回的 9 條（不用再查一次）

敵意查證推翻的，摘其要：

- **切換 `MaterialApp` ↔ `MaterialApp.router` 會整棵樹重掛** — 查了 SDK 3.41.3 的 `app.dart:1688-1716`，
  結論不成立。實測深連結（含 query）在切換後完整保留。
- **`warmRemaining()` 在第一個 post-frame 打 40 個請求** — 量級錯了（`await` 在迴圈內，是循序的）。
  即便如此仍加了 2 秒延遲，見 §1。
- **Celery `.delay()` 在 event loop 上阻塞紅旗路徑** — 字面正確，但使用者感受不到。
- **開場白 TTS 逐句循序合成** / **TTS 分段之間會有停頓** — 客戶端 `tts_playback_controller` 已經把播放
  與合成重疊掉了。
- **病患 intake 表單每個按鍵都重建整頁** — 程式碼確實如此，但一個表單頁的重建成本不構成可感知的卡頓。
- **`/dashboard/queue` 沒有 LIMIT** — 是死碼（WS 那條孿生實作有 cap 50）。
- **報告清單掃兩次全表** — query 形狀引用正確，但推論建立在兩個站不住的前提上。

---

### 相關

- 開機路徑的行為契約由 `flutter_app/test/boot_locale_load_test.dart`、`test/boot_gate_test.dart` 守著
- 報告的場次上下文由 `backend/tests/unit/schemas/test_report_session_context.py`（含「絕不觸發 lazy load」那條）
  與 `flutter_app/test/report_session_context_test.dart`（部署順序：後端還沒更新時要退回舊路徑）守著
- Web 開機遮罩由 `flutter_app/test/vercel_output_config_test.dart` 守著
- iOS 發佈設定值一律見 [`ios_release_settings.md`](ios_release_settings.md)，這裡不重抄
