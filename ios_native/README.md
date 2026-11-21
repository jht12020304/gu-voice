# UroSense 原生 iOS

這個 Xcode 專案是 GU Voice 的原生 SwiftUI 版，最低支援 iOS 17。現有功能包含醫師與管理員的報告、快速開單、場次與日曆、病患、紅旗、通知及管理工具。臨床人員可查本人操作的稽核與本人指派場次的研究統計。System admin 可管理帳號並查看全院稽核與研究。病患登入後可選主訴與醫師、填寫病史，以語音或文字完成問診，再查看自己的問診紀錄。

## 在本機建置與測試

使用支援 Swift 6 的 Xcode 16 或更新版本。從 repo 根目錄開啟 `ios_native/GUVoice.xcodeproj`，選 **GUVoice** scheme 和專用 simulator。專案已包含在 repo 中。修改 `project.yml` 後才需要在 `ios_native/` 執行 `xcodegen generate`。可用 `brew install xcodegen` 安裝。原生版測試在本機執行。Xcode 會由 Swift Package Manager 取得 Firebase Messaging。原生專案與 Flutter 共用既有 `GoogleService-Info.plist`。

Flutter 退役前，將 `../flutter_app/ios/Runner/GoogleService-Info.plist` 搬入原生專案，更新 `project.yml`、Xcode 專案與匯出驗證腳本的參照，並確認原生 IPA 順利打包同一份 Firebase 設定。將 `../flutter_app/ios/ExportOptions.plist` 移到原生 `Config/`，並將 `../flutter_app/tool/env.production.sh` 與 `../flutter_app/tool/build_ios_testflight.sh` 的產物驗證移到原生 `tool/`，更新打包腳本參照後再移除 Flutter。

1. 從 repo 根目錄啟動本機後端。若 `backend/.env` 不存在，先建立空檔。

   ```sh
   docker compose up -d backend
   curl -fsS http://127.0.0.1:8000/api/v1/health
   ```

2. 在專用 simulator 上建置和跑測試。將 `<unit-simulator-id>` 換成測試用 simulator 的 UDID。保留模擬器簽章，讓測試能使用 Keychain。若已佔用預設連接埠，為測試 Compose 使用獨立專案與資料庫，發佈後端到專用 loopback 埠。建置時以 `API_BASE`、`WS_BASE`、`WEB_BASE` 覆寫端點。

   ```sh
   xcodebuild -project ios_native/GUVoice.xcodeproj -scheme GUVoice \
     -destination 'generic/platform=iOS Simulator' build

   xcodebuild -project ios_native/GUVoice.xcodeproj -scheme GUVoice \
     -destination 'platform=iOS Simulator,id=<unit-simulator-id>' \
     -parallel-testing-enabled NO test
   ```

3. 如需檢查 Release 設定，在本機產出 unsigned archive。

   ```sh
   xcodebuild -project ios_native/GUVoice.xcodeproj -scheme GUVoice \
     -configuration Release -destination 'generic/platform=iOS' \
     -archivePath build/GUVoice.xcarchive CODE_SIGNING_ALLOWED=NO archive
   ```

### 環境設定

| 組態 | API_BASE | WS_BASE | WEB_BASE |
| --- | --- | --- | --- |
| Debug · `Config/Local.xcconfig` | `http://127.0.0.1:8000/api/v1` | `ws://127.0.0.1:8000/api/v1/ws` | `http://127.0.0.1` |
| Release · `Config/Production.xcconfig` | `https://gu.zymomed.com/api/v1` | `wss://gu.zymomed.com/api/v1/ws` | `https://gu.zymomed.com` |

Debug 允許 loopback HTTP。需要開啟本機 React 報告頁時，執行 `docker compose up -d frontend`。Web 連結帶 App 目前的語言與場次 ID。App 可切換繁體中文、英文、日文、韓文與越南文。首次啟動比照 Flutter，依裝置的主要語言比對，沒有相符項目時使用繁體中文。之後以 App 內選擇為準。

## 病患 kiosk

病患首頁提供最近五筆場次與完整歷史入口。進行中的場次可續問，已完成或因紅旗中止的場次可查看病患摘要。一般完成畫面八秒後回首頁。紅旗畫面請病患告知現場醫護，保留到按下返回或閒置登出。麥克風無法使用時仍可打字，音訊不寫入本機檔案。

病患在對話頁以外閒置 180 秒會登出，回到登入畫面。可在 Xcode build settings 覆寫 `KIOSK_IDLE_TIMEOUT_SECONDS`，`0` 停用。語音對話期間由後端判斷逾時。

### 模擬器雙路徑驗收

在 repo 根目錄執行以下命令，將 UDID 換成專用模擬器。測試 Compose 使用獨立資料庫與固定回答的本機模型替身，後端、紅旗偵測規則、WebSocket 和資料庫都參與驗證。測試建立合成帳號，使用文字代替真人講話。

```sh
docker compose -f ios_native/TestsSupport/kiosk-compose.yml up --build --wait -d
python3 ios_native/TestsSupport/seed-kiosk.py

xcrun simctl bootstatus <UDID> -b
xcrun simctl privacy <UDID> grant microphone com.guvoice.guVoice
TEST_RUNNER_KIOSK_UI_TEST=1 xcodebuild -project ios_native/GUVoice.xcodeproj -scheme GUVoice \
  -destination 'platform=iOS Simulator,id=<UDID>' -parallel-testing-enabled NO \
  API_BASE=http://127.0.0.1:18083/api/v1 WS_BASE=ws://127.0.0.1:18083/api/v1/ws build test

docker compose -f ios_native/TestsSupport/kiosk-compose.yml exec -T postgres \
  psql -U postgres -d kiosk -c 'select status, count(*) from sessions group by status'
docker compose -f ios_native/TestsSupport/kiosk-compose.yml stop
```

兩個 UI 案例各自從病患首頁開始，經過選主訴、生日、性別與指派醫師。一般案例等到 AI 回覆，再按結束並確認，預期 `completed`。紅旗案例輸入合成症狀，等伺服器中止，預期 `aborted_red_flag`。資料庫筆數隨重跑累加。

### 真 iPad 手動清單

使用授權的測試帳號與合成病患資料，記錄 iPad 型號、iPadOS、App build 與音訊輸出裝置。

- [ ] 第一次允許麥克風，以自然音量講話。確認開頭與停頓後的結尾都進逐字稿。播放 AI 語音或重播時靠近喇叭，確認逐字稿不出現喇叭回音，播完可回答下一題。
- [ ] 錄音中按暫停、手動結束一句、恢復收音。切換 TTS 靜音和語速。手動暫停期間播放或中斷 TTS，確認不會自行開麥。
- [ ] 在 iPad 設定拒絕麥克風後重新問診，確認畫面有提示，可用文字完成。在同一場次拔插耳機、切換藍牙、呼叫並關閉 Siri，核對恢復後的播放與收音。手動暫停時重做一次，確認麥克風維持暫停。
- [ ] 在問診中短暫關閉 Wi-Fi 再開啟，確認回到同一場次、逐字稿無重複。持續斷線時有可操作的返回入口。送出文字時斷網，確認重連後能核對或重送原句。說完最後一句、尚未自動停錄時按結束，先取消一次，再確認並核對最後一筆逐字稿與後端終態。
- [ ] 用合成紅旗案例確認中止畫面請病患告知現場醫護。等八秒後仍可看見提醒，醫師端同一場次顯示紅旗終態。
- [ ] 用兩個病患帳號交替登入，檢查姓名、主訴、病史、對話、紅旗和錄音狀態。四欄 intake 分別試未填、明確勾無、填入項目。核對場次紀錄及醫師端。
- [ ] 在首頁、基本資料與個人設定閒置至期限，確認返回登入畫面。問診中只講話不觸控，確認不被 kiosk 計時器登出。
- [ ] 切換繁中、英、日、韓、越語，核對主訴、對話、紅旗與歷史摘要。對話中切換語言需先確認結束。以橫向、放大字級與 VoiceOver 操作完一輪。

## 覆裝驗收與回滾

本專案使用 Flutter 版相同的 Team `K593X99M7G`、Bundle ID `com.guvoice.guVoice` 和 Automatic Signing。同 ID 安裝會取代裝置上的舊版。只在專用 simulator 做覆裝驗收，使用獨立本機 Compose 的合成資料。應在另一台 simulator 跑單元測試。禁止覆裝服役中的 kiosk、使用 production 資料測試、加入 `-allowProvisioningUpdates` 或上傳 TestFlight／App Store Connect。

以 `fvm flutter` 建置連線至同一個本機後端的 Flutter 版，登入測試醫師帳號。保留舊 App 的安裝，直接在同一台 simulator 安裝 SwiftUI 版。啟動後應進入醫師報告清單。開啟有紅旗的合成場次，核對病患姓名、紅旗、SOAP 和逐字稿。登出後重開 App，再換另一個測試醫師，確認只讀得到後端授權的資料。管理員應進入診間首頁，病患帳號應進入問診首頁。

原生 App 從同一個 Keychain access group 讀取 Flutter 的 `flutter_secure_storage_service`。遷移成功後，原生格式以單筆紀錄保存 access 和 refresh token，並刪除 Flutter 項目。遷移寫入失敗會保留 Flutter 項目並顯示登入頁。暫時無法讀取 Keychain 時會回到登入頁，可在裝置解鎖後重試。登出時先遮住帳號畫面，透過後端解除裝置綁定，然後清除憑證。斷網時重啟仍保留待解除狀態。舊憑證過期時，原帳號重新驗證只會完成解除綁定，接著回到登入頁。若裝回 Flutter，請重新登入。

同 Bundle ID 覆裝後，原生版會以既有 Firebase app 將 APNs token 與 FCM token 註冊至後端。後端會停用同 APNs token 上的舊綁定。若覆裝後尚未取得裝置憑證就登出，會使用 APNs 裝置 token 或 Firebase 快取的 FCM token 解除綁定。若兩種識別皆不可用，請依維運流程處理。系統通知與站內通知直接顯示伺服器文字，點擊後才透過有權限的 API 取得明細。正式切換前先部署支援裝置解除的後端，再發佈 App。後端須已改用通用通知文字。原生版會先確認後端支援裝置解除，再註冊新的推播綁定。

測試 bundle 會停用對外 Firebase 註冊。需要在專用 simulator 用 `simctl push` 驗證合成 payload 時，可用 `SIMCTL_CHILD_GUVOICE_DISABLE_REMOTE_PUSH=1 xcrun simctl launch <simulator-id> com.guvoice.guVoice` 啟動 App。模擬注入驗證顯示與導頁。本機 Docker 的換人回歸測試則使用真實推播 worker 選取收件裝置，並以本機替身記錄 APNs／FCM 傳送。部署後再按下方清單驗證供應商到鎖定畫面的送達。

### 無法辨識裝置時的維運復原

覆裝後若 APNs 和 Firebase 快取都無法提供這台裝置的識別，App 會顯示「請聯絡系統管理員」與復原編號。系統管理員只解除已核對的那台裝置。其他裝置繼續收通知。

1. 取得原帳號與畫面上的復原編號。透過維運紀錄核對這台實體裝置在 `fcm_devices` 的 iOS 登記 `id`。可以比對同一位使用者的 `device_name`、`created_at` 和 `updated_at`。若裝置名稱與時間無法唯一對應，請保持待解除狀態，先恢復 APNs 辨識或繼續查證。
2. 使用無執照的 system admin 憑證呼叫 `POST /api/v1/notifications/devices/recover`。指定原帳號 ID、已核對的登記 ID 與復原編號。

   ```json
   {
     "user_id": "<原帳號 UUID>",
     "registration_id": "<已核對的 fcm_devices.id>",
     "recovery_id": "<App 顯示的復原編號>"
   }
   ```

3. 確認回應 HTTP 200，並在稽核日誌核對 `push_device_recovery` 和該復原編號。請原使用者在 App 按 **重試**。若憑證已過期，先以原帳號重新驗證。App 查到解除紀錄後回到登入頁。

## 追平 Flutter

| 階段 | 工作 |
| --- | --- |
| C · 醫師與管理員 | 已接上診間與系統管理功能。全院帳號目錄和特權操作限 system admin。Doctor 與臨床 admin 可讀指派給本人的場次及後端允許的舊未指派場次。臨床研究母體只含本人指派的場次。 |
| D · 語音與病患 kiosk | 已接上病患 kiosk、原生錄放音、閒置登出，以及醫師代病患開場與續問。 |
| E · 切換 | 驗證既有 Flutter 裝置綁定、換人後的鎖定畫面、簽章與實機覆裝。依 [iOS 發布設定](../docs/ios_release_settings.md) 的時間戳規則遞增 build 號，完成追平後切換並退役 Flutter。 |

## 本機驗收截圖

以下是第一階段的 iPhone 17 Pro simulator 截圖，畫面中的資料皆為合成資料。

- [Flutter 已登入](Screenshots/01-flutter-signed-in.png) · [SwiftUI 覆裝後直接進入報告](Screenshots/02-native-after-upgrade.png)
- [報告與紅旗](Screenshots/03-native-report.png) · [SOAP 四段](Screenshots/04-native-soap.png) · [逐字稿](Screenshots/05-native-transcript.png)
- [換第二位醫師](Screenshots/06-native-second-doctor.png) · [管理員占位頁](Screenshots/07-native-admin.png) · [病患 kiosk 占位頁](Screenshots/08-native-kiosk.png)

## 正式切換時的人工驗收

發佈用的簽章打包與 TestFlight 實機驗收見 [原生 iOS 切換版](../docs/ios_release_settings.md#61-原生-ios-切換版)。後端部署完成後，由使用者用測試帳號與合成資料執行下列清單。

1. 先確認 Apple Developer App ID 已開啟 Push Notifications 和 Time Sensitive Notifications。核對 Team `K593X99M7G` 與 Bundle ID `com.guvoice.guVoice`，並檢查已簽 App 的 APNs 環境、Time Sensitive entitlement 和 `remote-notification` 背景模式。
2. 在同一台驗收裝置的 Flutter 版登入醫師 A。保留登入，覆裝相同 Bundle ID 的 SwiftUI 版。確認保留 A 的登入。核對報告、紅旗、SOAP、逐字稿與網頁連結。讓 access token 過期後重開 App，確認可繼續查閱。
3. 準備兩份待審報告。核准第一份。退回第二份時先確認空白與全空格理由不能送出，再輸入理由並連點送出，確認只新增一次審核。重新開啟確認狀態及理由。匯出 PDF，確認含逐字稿。快速開單先提交勾選項目，再測空清單與重新開啟後的上一張醫囑。
4. 查看病患清單與歷史、紅旗清單與詳情。測單筆確認與全部確認。切換裝置時區，檢查跨午夜場次只出現在正確的本地日，並切換前後月份。切換 App 五語，核對報告、管理頁、錯誤與確認文案。
5. 以 doctor、臨床 admin、system admin 及 kiosk 帳號驗證分流。前兩種帳號查不到指派給其他人的資料，舊未指派場次依後端規則顯示。臨床帳號可用主訴模板及系統健康，也可查自己的稽核與研究。插入一場舊未指派的合成場次，確認它可出現在診間，但不計入臨床研究。System admin 可查全院稽核及研究統計，並可在合成帳號上驗證帳號新增、修改、啟停與密碼重置。
6. 給 A 建立合成報告通知與紅旗。檢查站內通知的已讀與全讀、前景橫幅、冷啟動點擊、背景點擊以及開啟專注模式時的 Time Sensitive 紅旗。鎖定畫面與站內文案應為通用文字。點入後只顯示當前帳號有權限的明細。
7. 斷網時讓 A 登出。確認立即遮住 A 畫面，重啟後仍鎖住換人入口。恢復連線完成解除綁定。若 A 的憑證已過期，應可以 A 重新驗證來完成解除，再登入 B。用 A 和 B 各觸發一個新的合成通知，確認共用裝置只收到 B 的新通知。核對 A 的其他裝置仍可接收 A 的通知。
8. 若裝回 Flutter，重新登入並再次驗證換人與通知。
