# UroSense 原生 iOS

這個 Xcode 專案是 GU Voice 的原生 SwiftUI 版，最低支援 iOS 17。第一階段提供登入、登出換人，以及醫師的報告清單、病患姓名、紅旗、SOAP、逐字稿和網頁連結。管理員與病患 kiosk 會看到各自的占位頁。Flutter 在原生版追平前繼續服役。

## 在本機建置與測試

使用支援 Swift 6 的 Xcode 16 或更新版本。從 repo 根目錄開啟 `ios_native/GUVoice.xcodeproj`，選 **GUVoice** scheme 和專用 simulator。專案已包含在 repo 中。修改 `project.yml` 後才需要在 `ios_native/` 執行 `xcodegen generate`。

1. 從 repo 根目錄啟動本機後端。若 `backend/.env` 不存在，先建立空檔。

   ```sh
   docker compose up -d backend
   curl -fsS http://127.0.0.1:8000/api/v1/health
   ```

2. 在專用 simulator 上建置和跑測試。將 `<unit-simulator-id>` 換成測試用 simulator 的 UDID。

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

Debug 允許 loopback HTTP。需要開啟本機 React 報告頁時，執行 `docker compose up -d frontend`。Web 連結帶 App 目前的語言與場次 ID。App 可切換繁體中文、英文、日文、韓文與越南文。首次啟動優先採用裝置支援的語言，沒有相符項目時使用繁體中文。之後以 App 內選擇為準。

## 覆裝驗收與回滾

本專案使用 Flutter 版相同的 Team `K593X99M7G`、Bundle ID `com.guvoice.guVoice` 和 Automatic Signing。同 ID 安裝會取代裝置上的舊版。只在專用 simulator 做覆裝驗收，使用獨立本機 Compose 的合成資料。應在另一台 simulator 跑單元測試。禁止覆裝服役中的 kiosk、使用 production 資料測試、加入 `-allowProvisioningUpdates` 或上傳 TestFlight／App Store Connect。

以 `fvm flutter` 建置連線至同一個本機後端的 Flutter 版，登入測試醫師帳號。保留舊 App 的安裝，直接在同一台 simulator 安裝 SwiftUI 版。啟動後應進入醫師報告清單。開啟有紅旗的合成場次，核對病患姓名、紅旗、SOAP 和逐字稿。登出後重開 App，再換另一個測試醫師，確認只讀得到後端授權的資料。管理員與病患帳號應各自進入占位頁。

原生 App 從同一個 Keychain access group 讀取 Flutter 的 `flutter_secure_storage_service`。遷移成功後，原生格式以單筆紀錄保存 access 和 refresh token，並刪除 Flutter 項目。遷移寫入失敗會保留 Flutter 項目並顯示登入頁。暫時無法存取 Keychain 時，可在裝置解鎖後重試。若裝回 Flutter，請重新登入。Simulator 驗收不能取代日後實機簽章與覆裝驗證。本期未加入 APNs、Time Sensitive Notifications 或 Firebase。

## 追平 Flutter

| 階段 | 工作 |
| --- | --- |
| C · 醫師與管理員 | 報告確認／退回、PDF、快速開單、醫師其餘頁、帳號管理與推播。臨床 admin 與 system admin 的資料範圍沿用後端及 Flutter 規則。 |
| D · 病患 kiosk | 原生語音問診、閒置登出和 kiosk 流程。語音使用 AVAudioEngine，問診連線使用 URLSession WebSocket。 |
| E · 切換 | 驗證簽章與原地升級，完成追平後切換並退役 Flutter。 |
