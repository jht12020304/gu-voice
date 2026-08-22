# 效能稽核與最佳化 — 2026-08-22

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

## 1. 已修：開機路徑

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

## 2. 已修：醫師端（iOS 的主戰場）

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

## 3. 已修：語音管線與後端

| 改動 | 檔案 | 內容 |
|---|---|---|
| 波形寫入 | `flutter_app/lib/features/voice/services/audio_stream_service.dart` | AI 說話（hard mute）時完全不發——那時麥克風聽到的是喇叭回音。其餘時候節流到 20Hz。原本是每個 mic buffer 一次全頁重建（iOS ~47/秒） |
| 秒數寫入 | 同上 | 100ms 一次 → 只在**整秒變化**時才發。畫面是 `toStringAsFixed(0)`，十次有九次字串一模一樣卻重建整頁 |
| 假的斷線橫幅 | `conversation_page.dart` | `connecting` 是初始值，所以病患進問診頁**第一眼看到的就是「連線中斷，正在重新連線…」**，而且撐過整個麥克風授權對話框。改成細進度條 |
| gzip | `backend/app/main.py` | 全站沒有壓縮。這個 API 回的 JSON 壓縮比 5–10 倍，而診間 Wi-Fi 上「傳幾個 byte」正是使用者在等的東西 |
| bcrypt 移出 event loop | `backend/app/core/security.py`、`services/auth_service.py` | cost-12 是 200–400ms **不可中斷**的 CPU。跑在 event loop 上等於一個人登入、全院停擺：問診 WS 的音訊 chunk 送不出去、STT 上傳卡住 |
| ThemeData 快取 | `flutter_app/lib/core/theme/app_theme.dart` | getter → `static final`。每次 `App.build` 都重跑兩次 `ColorScheme.fromSeed` ＋ `GoogleFonts.interTextTheme` |

## 4. 沒修，以及為什麼

分三類。

> ⚠️ **2026-08-22 稍晚追加：這一輪最大的一條不在下面的表裡。**
> 後端跑在 Railway 加州、Supabase 在新加坡，**每一句 SQL 都橫跨太平洋**——
> 不碰 DB 的端點 1.88 ms，跑一句 `SELECT 1` 的端點 1.55 s，而且過半會撞上 2 秒逾時回 500。
> `railway.toml` 原本就想指定新加坡，但用了 Railway 不存在的 `region` 鍵，安靜失效。
> 已修正成 `[deploy.multiRegionConfig."asia-southeast1-eqsg3a"]`，
> **搬遷步驟見 [`railway_region_move.md`](railway_region_move.md)**。
> 下面那些前端的等待時間，在這一條修好之前都是次要項。

### 4a. 需要你拍板（臨床或部署決策，不該由我單方面改）

| 項目 | 檔案 | 為什麼要你決定 |
|---|---|---|
| **VAD 靜音 2 秒才送出** | `audio_stream_service.dart:37` | 每個語音回合固定 2 秒「看起來當掉」——狀態列還寫著聆聽中、波形還在動、伺服器一個 byte 都還沒收到。但調短會**切掉講話比較慢的病患**，那是臨床參數不是效能參數 |
| **`main.dart.js` 每次都重抓** | `tool/prepare_vercel_output.dart:37` | 4.1MB／brotli 866KB，`no-store` 且沒有 service worker，每次開頁都重抓。正解是檔名加 hash ＋ immutable 快取，但那要動部署腳本（`build_vercel_output.sh:56` 還在 grep 字面的 `main.dart.js`），而 Flutter Web 目前是 staged、還沒 promote |
| **LLM 回覆不是串流吐出** | `websocket/conversation_handler.py:1763` | 病患每答完一句，要等「LLM 全部生成完 ＋ 紅旗閘門過 ＋ 第一段 TTS 好」才看得到任何東西。改成邊生成邊送是這條線上最大的體感改善，但它動的是問診管線——照鐵律要先讀 `voice-pipeline-invariants`，改完要跑 `e2e-real-openai` |
| **斷句只認 CJK 標點** | `websocket/conversation_handler.py:50` | en-US／ko-KR／vi-VN 完全吃不到逐句 TTS。修法本身很小（補拉丁標點），但同樣落在問診管線的守則裡 |

### 4b. 明確判定「不要這樣做」

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

### 4c. 已查證、可以直接做，只是這輪沒排進去

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

### 4d. 兩個稽核沒抓到、我自己看到的

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

## 5. 被駁回的 9 條（不用再查一次）

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

## 相關

- 開機路徑的行為契約由 `flutter_app/test/boot_locale_load_test.dart`、`test/boot_gate_test.dart` 守著
- 報告的場次上下文由 `backend/tests/unit/schemas/test_report_session_context.py`（含「絕不觸發 lazy load」那條）
  與 `flutter_app/test/report_session_context_test.dart`（部署順序：後端還沒更新時要退回舊路徑）守著
- Web 開機遮罩由 `flutter_app/test/vercel_output_config_test.dart` 守著
- iOS 發佈設定值一律見 [`ios_release_settings.md`](ios_release_settings.md)，這裡不重抄
