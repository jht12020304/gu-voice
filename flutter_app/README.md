# flutter_app — GU Voice 單一碼庫前端

取代 `frontend/`（React + Vite）的 Flutter 實作，一份碼庫出 **web + iOS + Android**。**backend 完全不動**，打的是同一組 REST / WebSocket API。

兩套前端目前並存：`frontend/` 仍是正式網址在跑的版本；Flutter Web 已部署到
`https://gu-voice-flutter-preview.vercel.app` 做 staged production 驗證，尚未 promote。
release build、78 tests、五語 deep link、CORS 與測試病患登入已過，實體麥克風／STT／TTS／VAD 仍待驗。

## 2026-08-22 轉向：iOS 單一 App（含語音問診）

平台分工推翻：**只留 App，網頁走向除役**。kiosk iPad（候診區共用機）跑病患語音問診，
醫師/管理員用自己的裝置跑同一顆 App。實作重點：

- 平台閘門拆除，`route_guard.dart` 只剩**角色守衛**；拆之前先修掉 `/patients` 前綴
  誤中的病患越權洞（`role_guard_test.dart` 釘死）。
- 醫師 landing 依平台：原生 → `/notifications`，web（過渡期）→ `/dashboard`。
- kiosk iPad（病患帳號）**不註冊推播**；閒置登出 180 秒照舊（`KIOSK_IDLE_TIMEOUT_SECONDS`）。
- 已在 iOS simulator × 本機後端上驗過：醫師/病患 landing 與越權防線
  （`ios_doctor_app_test.dart`）、**12 個醫師+admin 頁在 iPhone 寬度零 overflow**
  （`mobile_layout_walkthrough_test.dart`——順手抓到 research 頁 dispose 裡 ref.read
  的生命週期炸彈，已修）。

## ⚠️ 尚未驗證的部分（讀這份之前先看這裡）

**病患端非語音全流程已真跑驗畢（2026-07-27，文字代替語音）；麥克風／VAD 路徑仍是零實測。**
每一條都是「沒人試過」，不是「試過有問題」。`flutter analyze` 與 `flutter test` 全綠
**不代表**這些能用（這輪就有兩次靜態全綠但 app 在真機一片紅）。

| 未驗證 | 為什麼要緊 |
|---|---|
| **麥克風路徑一次都沒跑過** | **2026-08-22 起這是 iOS 的正式路徑（kiosk iPad），不再只是 web 的事。** 這是 app 的存在理由。四條語音修法（AI 回音被當病患答話、TTS chain 洩漏→VAD 卡死、pause 順序讓半句症狀消失、硬鎖 re-assert）全靠單元測試與讀碼推論。文字流程繞過 VAD，驗不到這四條 |
| **TTS 從未實機播過音** | 測試用 fake player；fake 是 broadcast stream 而真 player 是 `BehaviorSubject.seeded`，「陳舊 completed 被重播」整類 bug 結構性測不到 |
| **Web 語音是未決策的 HIGH risk** | 麥克風原始 PCM 需手寫 AudioWorklet JS interop。「web 可用」目前只對非語音頁成立 |
| **iOS 實機只驗到「裝得起來」** | 打包鏈已通到底：2026-08-21 已產出**真簽章 .ipa** 並上傳 TestFlight（build `202608211213`，狀態「準備測試」），2026-08-21 起 App Store Connect 顯示兩位測試員**已安裝**該 build。但「裝得起來」不等於「打得開、功能能用」——**還沒有任何人回報實際使用結果**——醫師端角色分流／通知列表／APNs 推播在真機一次都沒驗，2026-08-22 起 `lib/core/error_boundary.dart` 掛上 `FlutterError.onError`／`PlatformDispatcher.onError`／`ErrorWidget.builder`，例外會顯示成一行可讀訊息、堆疊寫進 stderr（`flutter logs` 看得到）。**但那不是崩潰回報**——沒有 Sentry／Crashlytics，錯誤不會自己送到任何地方，仍要測試者手動回報（docs/TODO.md §V7／§V8） |
| **Android 完全沒碰** | 只跑過 iOS simulator；release 簽章缺 keystore 會刻意失敗，連 release 包都出不來 |
| **`replay()` 未 await `stopActive()`** | 推測性：若 just_audio 未串行化 method call → completer 永不解決 → VAD 永久硬靜音。刻意未修（見 docs/TODO.md H5） |

### 已驗過的（別重複做）

`integration_test/patient_text_flow_test.dart`——iOS Simulator × 本機後端 × 真 OpenAI，
用**文字輸入**代替語音走完 登入→選主訴→intake→WS handshake→AI 追問→結束/紅旗中止→SOAP：

- `normal`（頻尿 4 輪）→ 場次 `completed`、逐字稿 9 則、SOAP `generated` 且 `zh-TW`
- `redflag`（睪丸扭轉）→ 場次 `aborted_red_flag`、紅旗 1 筆、感謝頁走紅旗變體

跑法見 [`docs/TODO.md`](../docs/TODO.md) §V2。**跑之前一定要
`xcrun simctl privacy <udid> grant microphone com.guvoice.guVoice`**——`flutter test`
每次重裝都會重置 TCC，沒授權時 `start()` 會卡在 `await openMic()`，
`_ws.connect` 排在它後面，症狀是 WS 停在 `connecting`（看起來像 WS 壞掉，其實是麥克風）。

**剩下的最小驗證路徑**：iOS Simulator 可以用 Mac 的麥克風，不必實機。真的對著麥克風講一次，
特別驗——暫停時半句話有沒有進逐字稿、AI 講話時麥克風是否被鎖、TTS 中斷後 VAD 是否恢復。

**iOS release 打包與上傳（2026-08-21，Xcode 26.6 / Flutter 3.41.3）**：
真簽章走完全程——`tool/build_ios_testflight.sh` 六關全綠，產出 `build/ios/ipa/gu_voice.ipa`
（25,440,529 bytes），`xcrun altool --validate-app` 回 VERIFY SUCCEEDED with no errors，
上傳後 App Store Connect 自動處理通過，TestFlight 狀態「準備測試」且標記「內部」。
產物斷言：`aps-environment = production`（這一行同時證明 App ID 有 Push Notifications capability）、
`get-task-allow = false`、`Assets.car` 2,285,304 bytes、`CFBundleIconName = AppIcon`（巢狀路徑）、
`ITSAppUsesNonExemptEncryption = false`。`flutter clean` 後重跑 `pod install` 對 `ios/Podfile.lock` **零變動**。
build `202609030649` 已發到先行測試群組：App 會把 Apple 原生 APNs token 一併登記，
後端優先直送 Apple、失敗才回退 FCM；用來修正 FCM 回報成功但 iPhone 沒顯示的實機問題。
待楊佳倫手機更新、登入後複驗鎖定畫面、通知中心與前景橫幅。

## 開機路徑（2026-08-22 改過，動 `main.dart` 前先讀）

`main()` **不再** await `bootstrap()`。第一幀在 `runApp()` 後立刻畫得出來，`BootGate`
蓋著畫面直到 `booted` 翻過去，網路失敗時給重試而不是把人丟回登入頁。

三件事是有承重的，改的時候別拆掉：

1. **boot 沒完成前不建 `routerProvider`**（`lib/app.dart` 的 `_routed`）。建了的話
   深連結頁面會在 token 載入前就發 API、吃 401，跟 bootstrap 自己的 getMe 搶 refresh token。
2. **`bootOffline` 也算「還沒開完機」**。只看 `booted` 會讓重試畫面永遠到不了
   （`test/boot_gate_test.dart` 就是為此存在）。
3. **`Locales.loadForBoot(lng)` 必須涵蓋 `t()` 的整條 fallback 鏈**，否則第一幀會渲染
   退階語言、然後在背景補完時肉眼可見地重畫一次（`test/boot_locale_load_test.dart`）。

`loadAll()` 維持載滿五種語言的舊契約——二十幾個既有測試靠它。

完整的稽核結論、還沒修的項目、以及「已查證但刻意不做」的理由，見
[`docs/perf_audit_2026-08-22.md`](../docs/perf_audit_2026-08-22.md)。這裡不重抄。

## 現況

26 條路由與 React 版對齊（病患問診、醫師 dashboard／SOAP／紅旗／research、admin 四頁、auth 四頁）。語音管線核心（VAD 決策矩陣、TTS epoch 世代取消、PCM ring buffer）已移植並有單元測試。

已知缺口（2 blocker + 11 high，含 kiosk 閒置登出、醫師端全域紅旗提示、家族史欄位）見 [`docs/TODO.md`](../docs/TODO.md) §G。

## 跑法

```bash
fvm flutter pub get
fvm flutter run -d chrome                 # web，預設打 http://localhost:8000
fvm flutter run                           # 接上的 iOS / Android 裝置
fvm flutter analyze && fvm flutter test   # 合併前必跑
```

⚠️ **一律用 `fvm flutter`，不要用 PATH 上的裸 `flutter`**（`.fvmrc` 釘 3.41.3，
homebrew 那支是 3.47.0）。3.47 的 Swift Package Manager 預設是開的，會把
`.flutter-plugins-dependencies` 翻成 `swift_package_manager_enabled=true` 並動到
`ios/Podfile.lock`。2026-08-21 為此誤判成「SPM／CocoaPods 半切換要做架構決策」，
實際只是跑錯 SDK——改用 fvm 之後 `pod install` 對 `Podfile.lock` 零變動。

後端位址用 `--dart-define` 覆寫。變數名是 `API_BASE` / `WS_BASE`（**不是** `*_BASE_URL`），且值要**含 path 後綴**——見 `lib/core/config/env.dart`：

```bash
# 打生產後端（碰 iOS 一律 fvm flutter，見下方 iOS TestFlight 段的地雷）
fvm flutter run \
  --dart-define=API_BASE=https://gu-voice-app-production.up.railway.app/api/v1 \
  --dart-define=WS_BASE=wss://gu-voice-app-production.up.railway.app/api/v1/ws
```

iOS Simulator（首次會跑 `pod install`，較久）：

```bash
xcrun simctl boot 'iPhone 17'; open -a Simulator
fvm flutter build ios --simulator --debug --dart-define=API_BASE=... --dart-define=WS_BASE=...
xcrun simctl install booted build/ios/iphonesimulator/Runner.app
xcrun simctl launch booted com.guvoice.guVoice
```

⚠️ Android emulator 上 `localhost` 是模擬器自己，要用 `10.0.2.2` 才連得到宿主機。

## Web 預覽與正式切換

Flutter SDK 由 [`.fvmrc`](.fvmrc) 固定版本。`./tool/build_vercel_output.sh` 會執行
analyze、test、release build，並產生 Vercel Build Output；公開版若偵測到 E2E
帳密會直接拒絕建置。暫存正式部署、實機語音驗證、promotion 與 rollback 步驟見
[`docs/flutter_web_cutover.md`](../docs/flutter_web_cutover.md)。

## iOS TestFlight（醫師端內部測試）

```bash
./tool/build_ios_testflight.sh            # 六關：前置檢查／build number／後端位址／analyze+test／build ipa／產物驗證
./tool/build_ios_testflight.sh --help
../backend/venv/bin/python tool/gen_app_icons.py --check   # 單獨檢查 App Icon 資產（缺檔 exit 1）
```

腳本只打包**不上傳**；產物驗證過了才由人手動傳（現行走 App Store Connect API key ＋
`xcrun altool`，先 `--validate-app` 再 `--upload-app`；Transporter.app 是備援）。
**所有設定值（Team ID、bundle ID、SKU、ExportOptions、金鑰位置、目前上線的 build）
只留在 [`docs/ios_release_settings.md`](../docs/ios_release_settings.md)**，這裡不重抄。
前置條件（Apple 側，含 Paid Apps Agreement、帳號角色、APNs 金鑰上傳 Firebase、
regulated medical device 申報、隱私政策 URL）、驗收斷言逐條、上傳、App Store Connect
內部測試群組、第一次上機驗證推播、build 到期與 iOS 版本門檻，全部在
[`docs/deployment_guide.md`](../docs/deployment_guide.md) 二、；管道現況、未解的資料風險
與「加第 2 個測試人員之前」的前置條件見 [`docs/TODO.md`](../docs/TODO.md) §V8。

⚠️ 這條線的三個地雷：**碰到 iOS 一律用 `fvm flutter`**（`.fvmrc` 釘 3.41.3；PATH 上的裸 `flutter` 是
homebrew 3.47.0，SPM 預設開，會動到 `ios/Podfile.lock`）、
**不要改 `ios/Runner/Runner.entitlements` 的 `aps-environment`**（值由 provisioning profile 決定，改了沒用）、
**內測包打的是生產後端**。現行問診在基本資料頁必選醫師；已指派場次的通知只送該醫師，
doctor／臨床 admin 也只讀自己被指派的病患資料。system admin 仍可全院稽核，legacy
未指派報告通知仍保留全體在職醫護 fallback。

⚠️ 推播與報告仍含被指派病患的 PHI；`testFlightInternalTestingOnly` 也只限制散佈，
不能取代帳號授權。production 只給獲授權院內人員，未授權工程／PM 使用 staging；
完整邊界見 [`docs/TODO.md`](../docs/TODO.md) §V8。

## 測試分層

- `test/`（78 項，純函式 + 少量 widget）——CI 會跑（`flutter analyze` 對 info 級也 exit 1）。
- `integration_test/`（**需要真 simulator，不在 CI**；`flutter test` 不帶參數只跑 `test/`，天然排除）：
  - `login_smoke_test.dart` — 登入冒煙，驗 dio／iOS Keychain 持久化／bootstrap 還原／導向
  - `kiosk_idle_logout_test.dart` — 真等逾時驗病患被登出＋token 清除
  - `patient_text_flow_test.dart` — **病患全流程（文字代替語音）**，打真後端＋真 OpenAI，見上方「已驗過的」
  - `demo_walkthrough_test.dart` — **不是測試，是產品介紹影片的驅動腳本**（見下方「介紹影片」）
- 憑證一律只從 `--dart-define` 讀，沒給就 skip。

## 介紹影片（自動產生，2026-09-09）

一行產出 60 秒 1080×1920 的產品介紹影片：

```bash
cd flutter_app && ./tool/record_demo.sh --output ~/Desktop/UroSense_demo.mp4
```

它做的事：重開模擬器 → `simctl io recordVideo` 開錄 → 跑
`integration_test/demo_walkthrough_test.dart`（登入 → 選醫師 → 問診 → 醫師端通知 →
快速開單 → SOAP 報告）→ 停錄 → 剪成 60 秒並疊中文字卡。

**前提**：本機後端（`docker compose up -d postgres redis` ＋ uvicorn）與 **Celery worker**
都要在跑——沒有 worker 就等不到 `report_ready`，快速開單那段會空等。腳本會先檢查，缺了直接擋。

| 檔案 | 職責 |
|---|---|
| `tool/record_demo.sh` | 串接全流程；用 Dart 端印的 `DEMO_MARK_START <epoch>` 把 build 的空桌面剪掉 |
| `tool/make_demo_video.sh` | ffmpeg 後製：變速、裁成 1080×1920、疊字卡、淡入淡出 |
| `tool/demo_captions.py` | 用 Pillow 把中文字卡渲染成帶 alpha 的 PNG |
| `tool/demo_captions.example.json` | 字卡時間軸與文案 |

四件會咬人的事，動它之前先讀：

- ⚠️ **一律先 `shutdown` 再 `boot` 模擬器。** 沿用已開著的模擬器連跑第二次，100% 卡在
  `openMic`，後端連一次 WS 握手都收不到（2026-09-09 重現兩次）。這發生在 Dart 拿到控制權
  之前，測試碼裡救不了，只能由 `record_demo.sh` 負責。
- ⚠️ **不要用 ffmpeg 的 `drawtext` / `subtitles` / `ass`。** 本機 Homebrew 的 ffmpeg 9.0.1
  沒編 libfreetype／libass，這三個濾鏡直接失敗。中文字卡走 Pillow 渲染 PNG ＋ `overlay`。
- ⚠️ **只准打本機後端。** 腳本硬性拒絕 `https://` 與 railway 位址：這支會被重複執行，打正式
  環境等於每跑一次就建真場次、對四支真醫師手機發推播。
- ⚠️ **字卡目前綁固定秒數，而 walkthrough 每次長度會變**（LLM 回應快慢不同，實測 2:14 與
  2:21），成品固定壓成 60 秒 → 變速倍率跟著變 → **同一組字卡在不同次錄影會對到不同畫面**。
  要根治得讓 walkthrough 印階段標記（`DEMO_MARK_STAGE <名稱> <epoch>`），字卡綁標記而非秒數。

只改字卡不必重錄——`record_demo.sh --keep-raw` 會留下 `build/demo/raw.mov`，直接重跑
`make_demo_video.sh` 即可（`--trim-start` / `--trim-duration` 用上一次 log 印的值）。

**已知畫面瑕疵**：這台 Mac 沒有音訊輸入裝置，問診頁會掛一條「語音功能無法使用」橫幅入鏡
（walkthrough 會印 `DEMO_NOTE` 提醒）。要乾淨畫面得換一台有麥克風的 Mac，或該段真機補拍。

## 注意

- `assets/locales/` 是 5 語言翻譯檔，**與 `frontend/src/i18n/locales/` 逐檔位元相同**。切換期新增 key 要同步改兩份；React 下線後這裡才成為唯一來源。
- 語言唯一權威是 URL 路徑段（`/zh-TW/...`），與 React 版同一條鐵律。裝置語系只在 URL 無語言段時當 seed。
