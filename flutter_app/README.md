# flutter_app — GU Voice 單一碼庫前端

取代 `frontend/`（React + Vite）的 Flutter 實作，一份碼庫出 **web + iOS + Android**。**backend 完全不動**，打的是同一組 REST / WebSocket API。

兩套前端目前並存：`frontend/` 仍是正式網址在跑的版本；Flutter Web 已部署到
`https://gu-voice-flutter-preview.vercel.app` 做 staged production 驗證，尚未 promote。
release build、78 tests、五語 deep link、CORS 與測試病患登入已過，實體麥克風／STT／TTS／VAD 仍待驗。

## ⚠️ 尚未驗證的部分（讀這份之前先看這裡）

**病患端非語音全流程已真跑驗畢（2026-07-27，文字代替語音）；麥克風／VAD 路徑仍是零實測。**
每一條都是「沒人試過」，不是「試過有問題」。`flutter analyze` 與 `flutter test` 全綠
**不代表**這些能用（這輪就有兩次靜態全綠但 app 在真機一片紅）。

| 未驗證 | 為什麼要緊 |
|---|---|
| **麥克風路徑一次都沒跑過** | 這是 app 的存在理由。四條語音修法（AI 回音被當病患答話、TTS chain 洩漏→VAD 卡死、pause 順序讓半句症狀消失、硬鎖 re-assert）全靠單元測試與讀碼推論。文字流程繞過 VAD，驗不到這四條 |
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
**仍未驗**：真機安裝、醫師端實際操作、APNs 推播端到端（見上表）。

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
**內測包打的是生產後端**（唯一會打到手機的是「SOAP 報告已生成」通知，body 帶真實病患姓名
且 fan-out 給全體在職醫師 → 去識別化補完前只裝自己一台）。

⚠️ **遮蔽推播文案不會降低 PHI 暴露**：測試者拿到的是真實醫師帳號，登進去就能讀到全部真實
病患姓名與 SOAP 報告（後端沒有 tenant/scope 隔離）。推播文案只是鎖定畫面那一行——
完整的兩條路與估時見 [`docs/TODO.md`](../docs/TODO.md) §V8。

## 測試分層

- `test/`（78 項，純函式 + 少量 widget）——CI 會跑（`flutter analyze` 對 info 級也 exit 1）。
- `integration_test/`（**需要真 simulator，不在 CI**；`flutter test` 不帶參數只跑 `test/`，天然排除）：
  - `login_smoke_test.dart` — 登入冒煙，驗 dio／iOS Keychain 持久化／bootstrap 還原／導向
  - `kiosk_idle_logout_test.dart` — 真等逾時驗病患被登出＋token 清除
  - `patient_text_flow_test.dart` — **病患全流程（文字代替語音）**，打真後端＋真 OpenAI，見上方「已驗過的」
- 憑證一律只從 `--dart-define` 讀，沒給就 skip。

## 注意

- `assets/locales/` 是 5 語言翻譯檔，**與 `frontend/src/i18n/locales/` 逐檔位元相同**。切換期新增 key 要同步改兩份；React 下線後這裡才成為唯一來源。
- 語言唯一權威是 URL 路徑段（`/zh-TW/...`），與 React 版同一條鐵律。裝置語系只在 URL 無語言段時當 seed。
