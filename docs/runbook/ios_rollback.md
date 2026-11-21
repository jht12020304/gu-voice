# iOS TestFlight 回滾

| Build | App | TestFlight 群組 |
|---|---|---|
| `202611211434` | 原生 iOS，五位測試員完成真機驗收 | 先行測試 |
| `202611141854` | 最後一版 Flutter | 先行測試 |

Flutter `202611141854` 的有效期限是 **2027-02-12 11:00:37 UTC−08:00**，即 **2027-02-13 03:00:37 台北時間（UTC+08:00）**。這是「先行測試」群組可回裝的舊版。更早的 build 使用已停用的 Railway 端點。

## 到期前回裝

1. 由獲授權的測試員在 TestFlight 開啟 UroSense 的先前版本，從「先行測試」所提供的版本選 `202611141854`。保留目前版的 build 號及回滾原因。
2. 回裝後重新登入。覆裝遷移已把憑證從舊版 Keychain 格式移到原生格式。
3. 用合成通知確認 APNs 已在回裝後重新綁到目前帳號。共用裝置由醫師 A 換到 B 時，給 A 和 B 各觸發一則新的合成通知。確認這台裝置只收到 B，且 A 的其他裝置仍收得到 A。也確認 B 讀不到 A 的明細。

## 到期後重建

1. 獨立 checkout `8f99a488df4ed4302e8b8bd4fc704f576a0aac2d`。原匯出時 HEAD 為 `801d98f7193a208dc0904bd44037a72bf4f810c3`，當時工作目錄已改用自架端點。前一個 SHA 包含後續提交的三個 `gu.zymomed.com` 端點，是可重建的已知來源。
2. 使用該 checkout 的 Flutter 3.41.3（FVM）及 `Podfile.lock` 記錄的 CocoaPods 1.17.0。原 IPA 記錄的 Xcode 是 27.2（27B52），iOS SDK 27.2。
3. 由發佈人確認 App Store Connect 現有最高 build 號。用該 checkout 的 `flutter_app/tool/build_ios_testflight.sh --build-number=<更新且更大的號碼>` 打包，帶入自架三端點及內部 TestFlight 匯出選項。驗收使用合成資料，勿帶入測試帳密。
4. 核對匯出 IPA 的簽章、推播權限、端點、內部測試匯出設定與 SHA-256。依 [人工發佈流程](../ios_release_settings.md#61-原生-ios-發佈) 對同一顆 IPA 手動驗證與上傳。確認「內部」標記，再依既有授權流程指派至「先行測試」。裝到實機後按上節驗證登入、APNs 與換人隔離。
