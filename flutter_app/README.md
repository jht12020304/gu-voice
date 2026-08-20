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

## 現況

26 條路由與 React 版對齊（病患問診、醫師 dashboard／SOAP／紅旗／research、admin 四頁、auth 四頁）。語音管線核心（VAD 決策矩陣、TTS epoch 世代取消、PCM ring buffer）已移植並有單元測試。

已知缺口（2 blocker + 11 high，含 kiosk 閒置登出、醫師端全域紅旗提示、家族史欄位）見 [`docs/TODO.md`](../docs/TODO.md) §G。

## 跑法

```bash
flutter pub get
flutter run -d chrome                     # web，預設打 http://localhost:8000
flutter run                               # 接上的 iOS / Android 裝置
flutter analyze && flutter test           # 合併前必跑
```

後端位址用 `--dart-define` 覆寫。變數名是 `API_BASE` / `WS_BASE`（**不是** `*_BASE_URL`），且值要**含 path 後綴**——見 `lib/core/config/env.dart`：

```bash
# 打生產後端
flutter run \
  --dart-define=API_BASE=https://gu-voice-app-production.up.railway.app/api/v1 \
  --dart-define=WS_BASE=wss://gu-voice-app-production.up.railway.app/api/v1/ws
```

iOS Simulator（首次會跑 `pod install`，較久）：

```bash
xcrun simctl boot 'iPhone 17'; open -a Simulator
flutter build ios --simulator --debug --dart-define=API_BASE=... --dart-define=WS_BASE=...
xcrun simctl install booted build/ios/iphonesimulator/Runner.app
xcrun simctl launch booted com.example.guVoice
```

⚠️ Android emulator 上 `localhost` 是模擬器自己，要用 `10.0.2.2` 才連得到宿主機。

## Web 預覽與正式切換

Flutter SDK 由 [`.fvmrc`](.fvmrc) 固定版本。`./tool/build_vercel_output.sh` 會執行
analyze、test、release build，並產生 Vercel Build Output；公開版若偵測到 E2E
帳密會直接拒絕建置。暫存正式部署、實機語音驗證、promotion 與 rollback 步驟見
[`docs/flutter_web_cutover.md`](../docs/flutter_web_cutover.md)。

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
