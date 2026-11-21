# UroSense 原生 iOS

這個 Xcode 專案是 GU Voice 的原生 SwiftUI 版，最低支援 iOS 17。第一階段提供登入、登出換人，以及醫師的報告清單、病患姓名、紅旗、SOAP、逐字稿和網頁連結。管理員與病患 kiosk 會看到各自的占位頁。Flutter 在原生版追平前繼續服役。

## 在本機建置與測試

使用支援 Swift 6 的 Xcode 16 或更新版本。從 repo 根目錄開啟 `ios_native/GUVoice.xcodeproj`，選 **GUVoice** scheme 和專用 simulator。專案已包含在 repo 中。修改 `project.yml` 後才需要在 `ios_native/` 執行 `xcodegen generate`。可用 `brew install xcodegen` 安裝。原生版測試在本機執行。

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

Debug 允許 loopback HTTP。需要開啟本機 React 報告頁時，執行 `docker compose up -d frontend`。Web 連結帶 App 目前的語言與場次 ID。App 可切換繁體中文、英文、日文、韓文與越南文。首次啟動比照 Flutter，依裝置的主要語言比對，沒有相符項目時使用繁體中文。之後以 App 內選擇為準。

## 覆裝驗收與回滾

本專案使用 Flutter 版相同的 Team `K593X99M7G`、Bundle ID `com.guvoice.guVoice` 和 Automatic Signing。同 ID 安裝會取代裝置上的舊版。只在專用 simulator 做覆裝驗收，使用獨立本機 Compose 的合成資料。應在另一台 simulator 跑單元測試。禁止覆裝服役中的 kiosk、使用 production 資料測試、加入 `-allowProvisioningUpdates` 或上傳 TestFlight／App Store Connect。

以 `fvm flutter` 建置連線至同一個本機後端的 Flutter 版，登入測試醫師帳號。保留舊 App 的安裝，直接在同一台 simulator 安裝 SwiftUI 版。啟動後應進入醫師報告清單。開啟有紅旗的合成場次，核對病患姓名、紅旗、SOAP 和逐字稿。登出後重開 App，再換另一個測試醫師，確認只讀得到後端授權的資料。管理員與病患帳號應各自進入占位頁。

原生 App 從同一個 Keychain access group 讀取 Flutter 的 `flutter_secure_storage_service`。遷移成功後，原生格式以單筆紀錄保存 access 和 refresh token，並刪除 Flutter 項目。遷移寫入失敗會保留 Flutter 項目並顯示登入頁。暫時無法讀取 Keychain 時會回到登入頁，可在裝置解鎖後重試。若登出時清除失敗，須先完成清除才能換帳號。若裝回 Flutter，請重新登入。Simulator 驗收不能取代日後實機簽章與覆裝驗證。本期未加入 APNs、Time Sensitive Notifications 或 Firebase。

**實機切換前須清理舊推播註冊。** 同 ID 覆裝可能保留舊 Flutter 的裝置推播註冊。若原生版登出後註冊仍有效，前一位醫師的通知可能在同一台裝置的鎖定畫面顯示病患姓名。完成裝置層級的取消註冊與換人驗證後才可實機覆裝。

## 追平 Flutter

| 階段 | 工作 |
| --- | --- |
| C · 醫師與管理員 | 報告確認／退回、PDF、快速開單、醫師其餘頁、帳號管理與推播。臨床 admin 只讀指派給自己的報告。System admin 可看全院資料。 |
| D · 病患 kiosk | 原生語音問診、閒置登出和 kiosk 流程。語音使用 AVAudioEngine，問診連線使用 URLSession WebSocket。 |
| E · 切換 | 清理舊 Flutter 裝置的推播註冊，驗證換人後的鎖定畫面、簽章及實機覆裝。依 [iOS 發布設定](../docs/ios_release_settings.md) 的時間戳規則遞增 build 號，完成追平後切換並退役 Flutter。 |

## 本機驗收截圖

截圖來自專用 iPhone 17 Pro simulator，畫面中的資料皆為合成資料。

- [Flutter 已登入](Screenshots/01-flutter-signed-in.png) · [SwiftUI 覆裝後直接進入報告](Screenshots/02-native-after-upgrade.png)
- [報告與紅旗](Screenshots/03-native-report.png) · [SOAP 四段](Screenshots/04-native-soap.png) · [逐字稿](Screenshots/05-native-transcript.png)
- [換第二位醫師](Screenshots/06-native-second-doctor.png) · [管理員占位頁](Screenshots/07-native-admin.png) · [病患 kiosk 占位頁](Screenshots/08-native-kiosk.png)

## 正式切換時的人工驗收

這份清單在 C、D 追平且 E 完成舊推播清理後，由使用者在正式切換時執行。本期使用 simulator 驗收，禁止上傳 TestFlight 或 App Store Connect。

1. 在舊 Flutter 版登入一個醫師帳號，記下帳號名稱和一筆有權限查看的場次。保留登入，直接覆裝同 Bundle ID 的原生版。
2. **確認原地升級保留同一位醫師的登入。** 首次啟動應直接進入報告清單，不要求重新輸入帳密。檢查原有場次的病患姓名、紅旗、SOAP、逐字稿及網頁連結。
3. 等待 access token 過期後重開 App。確認仍可讀取報告。再登出、關閉並重開 App，確認停在登入頁。
4. 用第二位醫師登入，確認只顯示該帳號有權限的場次。再核對管理員、臨床管理員和病患 kiosk 的角色分流與權限。
5. 切換帳號後確認這台裝置的鎖定畫面沒有收到前一位醫師的通知。任何一項不符時，記下版本和重現步驟，先停止擴大切換。若裝回 Flutter，重新登入。
