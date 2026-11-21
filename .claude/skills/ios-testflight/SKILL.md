---
name: ios-testflight
description: 原生 iOS TestFlight 內部發佈。修改 ios_native 的簽章、匯出、IPA 驗證或測試群組時使用。
---

# 原生 iOS TestFlight

發佈設定以 [iOS 設定總表](../../../docs/ios_release_settings.md) 為準。操作順序見 [部署手冊](../../../docs/deployment_guide.md#二原生-ios-testflight-發佈)。

1. 正式 build 使用最新 `origin/main` 的 App inputs 和已提交的發佈腳本。確認本機簽章身分、distribution profile、Push Notifications 和 Time Sensitive Notifications 能力皆可用。
2. 在 repo 根目錄執行 `ios_native/tool/build_ios_testflight.sh`。腳本唯讀查 ASC，再依 UTC 產生高於既有 build 的 12 位號碼。Xcode 以 Release archive，並用 `Config/ExportOptions.plist` 匯出本機 IPA。
3. 檢查 `verify.log`。已簽 IPA 的 Team、Bundle ID、版本、production APNs、Time Sensitive、無除錯、三個 production 端點、Firebase、AppIcon、五語、加密合規、內部測試旗標和測試憑證掃描都須過關。可獨立重跑 `ios_native/tool/build_ios_testflight.sh --verify-only "$IPA" "$BUILD"`。
4. 發佈人核對 IPA 的 SHA-256，再對同一顆檔案手動執行 `altool --validate-app` 和 `--upload-app`。使用原本的匯出檔，避免 Organizer 重新匯出時繞過匯出設定。
5. 核對 TestFlight 的「內部」標記，使用授權實機與合成資料完成驗收，再由發佈人決定群組指派。正式群組僅限獲授權院內人員。TestFlight 內部旗標限制散佈，資料授權仍由後端控制。

需要回裝舊版、確認群組與到期時間，或重建舊版時，依 [iOS 回滾手冊](../../../docs/runbook/ios_rollback.md)。遇到推播失敗，先查 [推播診斷手冊](../../../docs/push_troubleshooting.md)。
