---
name: ios-testflight
description: GU Voice iOS 醫師端上 TestFlight 內部測試的完整管道（Apple 側前置、fvm 工具鏈、打包腳本、產物驗證）與已被實測推翻的常見錯誤修法。Use when 要把 iOS 包送 TestFlight／App Store Connect、動到 flutter_app/ios/ 底下任何檔案（Info.plist、Runner.entitlements、project.pbxproj、ExportOptions.plist、Podfile）、處理簽章／憑證／provisioning profile 問題、設定或除錯 APNs 推播、產生 App Icon 資產、或決定內測要發給誰時。
---

# iOS TestFlight 內部測試

## Overview

**「`flutter build ipa` exit 0」離「TestFlight 上跑得起來」還有一大段。** 中間卡的幾乎都不是程式碼：Apple 後台的 capability 沒勾、憑證沒有、圖示沒進 Assets.car、出口合規沒宣告、build number 沒遞增。本 skill 把「打包」與「Apple 側前置」分開講，並收錄**已經被對抗式查證推翻過的錯誤修法**——那幾條看起來都很合理，改下去只會浪費半天並弄髒 repo。

打包本身**不要手打指令**，一律走 [`flutter_app/tool/build_ios_testflight.sh`](../../../flutter_app/tool/build_ios_testflight.sh)（六道關卡，含產物驗證）。

> ⚠️ 這是醫療系統，內測包連的是**生產後端**（沒有 staging）。送測前務必先讀本文件的〈資料風險〉一節——**已拍板：第一版只裝使用者自己一台**。

## When to Use

- 要產出 .ipa 上傳 App Store Connect / 加內部測試員 / 重傳過期的 build
- 改 `flutter_app/ios/` 底下任何東西（Info.plist、entitlements、pbxproj、ExportOptions.plist、Podfile）
- 簽章、憑證、provisioning profile、`ITMS-9xxxx` 系列退件
- APNs 推播在 TestFlight 上收不到
- App Icon / LaunchImage 資產（`flutter_app/tool/gen_app_icons.py`）
- NOT for：Web 前端部署（用 `deploy-production` skill）、語音管線行為（用 `voice-pipeline-invariants`）

## 專案關鍵值

🔑 **值一律看 [`docs/ios_release_settings.md`](../../../docs/ios_release_settings.md)**——Team ID、bundle ID、App name／SKU／ASC app id、Flutter 與 Xcode 版本、deployment target、`ExportOptions.plist` 每個 key、dart-define 字串、憑證與金鑰位置、上傳指令、目前上線的那顆 build，全部在那一份。**這裡不重抄**：2026-08-21 就因為 Team ID 同時寫在四個地方而錯了很久，值只留一份。

本 skill 只講**怎麼做、為什麼、以及踩過什麼坑**。三件與值有關但屬於「會怎麼壞」的事仍留在這裡：

- **一律 `fvm flutter`**（`.fvmrc` 釘的版本）。PATH 上的裸 `flutter` 是 homebrew 較新版，SPM 預設開，會把 `.flutter-plugins-dependencies` 翻成 `swift_package_manager_enabled=true` 並動到 `ios/Podfile.lock`。
- **後端位址**：變數名是 `API_BASE` / `WS_BASE`（**不是** `*_BASE_URL`），值含 path 後綴。⚠️ `api-` 開頭的域名是死的。沒帶 dart-define 時預設是 `http://localhost:8000/api/v1`——那種包裝到 iPhone 上**永遠連不到後端**，UI 只會轉圈不告訴你原因。腳本第 3 關會擋（localhost／明文 `http://`／協定給錯都擋）。
- **APNs `.p8` 在 repo 之外**：絕不複製進 repo、絕不在任何檔案或訊息裡寫出內容。

## ⚠️ 資料風險（送測前必讀，這不是待辦，是已拍板的限制）

內測包打的是**生產資料庫**。逐行核實過的現況（**file:line 逐條佐證只放在 `docs/TODO.md` §V8**，這裡不重抄，避免兩邊漂移）：

1. **真實病患姓名會出現在測試者的 iPhone 鎖定畫面上——通道是 `report_ready`。** 「SOAP 報告已生成」通知的 body 帶 `{patient_name}`，原封不動送進 FCM。
   ❌ **不要再引用「`i18n_messages.py:587` 的 `session_complete`」那條說法**：`notify_session_complete` 的 docstring 明文寫「刻意不 fan-out」，呼叫端只在有 `doctor_id` 時才呼叫，而實測 DB 內 `sessions.doctor_id` 全為 NULL ⇒ **它目前根本不會發出去**。照那條去「補去識別化」會改到一條不會觸發的文案，真正的外洩通道原封不動。
2. **測試者會收到全院每一位病患的通知。** `report_ready` 在 `sessions.doctor_id IS NULL`（實測全院都是）時 **fan-out 給全體在職醫師**；「報告生成失敗」文案同樣帶姓名、同樣 fan-out。測試者一登入註冊 FCM token 就進入這個收件名單。
3. **休眠地雷：紅旗推播的 body 是 LLM 生成的醫師向臨床描述**（比姓名更敏感）。它走 `session.doctor_id`，目前全 NULL 所以不觸發——**「開始指派醫師」那天會自動解封，不需要任何人改碼**。
4. **iOS 端可達破壞性 API**：刪病患、停用帳號、重設密碼都可達（route_guard 只擋 `/patient` 問診子樹，`/patients` 醫師端清單是刻意開著的）。

> ⚠️ **遮蔽推播文案不會降低 PHI 暴露。** 測試者拿到的是**真實醫師帳號**，登進去就能讀到全部真實病患姓名與完整 SOAP 報告（後端**沒有 tenant／scope 隔離**）。推播文案只是鎖定畫面那一行。

**已拍板的處置：第一版只裝使用者自己一台，用途是驗證發佈管道。** 要加第 2 個測試人員之前，**先看 `docs/TODO.md` §V8 的兩條路**（第 2 人已獲授權接觸真實病歷 ⇒ 遮文案＋關破壞性入口＋記錄授權依據，約 3 小時；**未獲授權 ⇒ 唯一最小安全集是開 staging 環境**，4–8 小時）——**不要憑「先把姓名遮掉」就加人**。
✅ **`ios/ExportOptions.plist` 的 `testFlightInternalTestingOnly=true` 已證實會生效**（2026-08-21）：即使走 `destination=export` ＋ `xcrun altool` 上傳，那顆 build 在 App Store Connect 的 TestFlight 清單上還是標著「**內部**」。先前寫的「未經驗證／不可當技術護欄／要上傳後才知道」已經過期，**不必再用懷疑的語氣講它，也不要把那個 key 拿掉**。

🛑 **但這不改變 PHI 的結論，兩件事要分開講：**
- **它擋的是「散佈」**——external TestFlight 與上架這條路被 Apple 擋死了。
- **它擋不了「資料」**——對**任何一個被加進 internal 群組的人完全沒有作用**。那個人拿的是真實醫師帳號，登進去就讀得到全部真實病患姓名與完整 SOAP 報告。
⇒ **它不是 PHI 護欄。**擋 PHI 的仍然只有「第一版只裝自己一台」這個人為拍板，**加第 2 個人前要走完 `docs/TODO.md` §V8 的前置條件這件事一個字都沒放寬**。「旗標有效」≠「PHI 有護欄」。
⚠️ 唯一仍然成立的技術破口：**走 Xcode Organizer 上傳會自己重新 export，整份 ExportOptions（含這個 key）一起被繞過**，而且沒有任何機制會發現。這一條沒有被推翻——用 Organizer 就等於沒設。

## Apple 側前置（沒做會怎麼壞）

打包腳本檢查不到 Apple 後台的狀態，這些要人工確認。**完整清單（含業務端要拍板的隱私政策 URL、regulated medical device 申報、年齡分級問卷）在 [`docs/deployment_guide.md`](../../../docs/deployment_guide.md) 二、〈前置條件〉**——那份是唯一的操作清單，這裡只列工程側最常撞到的。

| 前置 | 沒做的具體徵兆 |
|---|---|
| **0a. App Store Connect → Business 已簽最新 Paid/Free Apps Agreement** | **「＋ New App」是灰的**，而畫面不告訴你原因。這是第一次登入後**第一個會撞到的牆**，比任何簽章問題都早 |
| **0b. Apple ID 在 team 的角色 ≥ App Manager** | Developer 角色**建不了 App 記錄、產不了 Distribution 憑證**——選單裡根本沒那些選項，看起來像「Xcode 壞了」 |
| **1. 付費 Apple Developer Program 會籍** | Xcode Accounts 裡 team 名稱後面標 `(Personal Team)`。免費帳號**永遠**拿不到 Distribution 憑證 → `security find-identity -v -p codesigning` 沒有 `Apple Distribution`，腳本第 1 關直接擋。這是「今天能不能上 TestFlight」的第一個岔路 |
| **2. App ID 勾選 Push Notifications capability** | 上傳後被退 **ITMS-90078**（Missing Push Notification Entitlement）；就算矇混上去，線上也**永遠收不到推播**。這是「aps-environment 為什麼不是 production」的**真正**根因——不要去改 entitlements 檔（見 Common Rationalizations 第一條） |
| **3. App Store Connect 上有這個 bundle ID 的 App 記錄** | 上傳時報找不到 app / bundle id 不匹配；Transporter 與 altool 都會在傳完之後才失敗，浪費一次上傳（.ipa 約 25MB；185MB 那個數字是 .xcarchive 不是上傳物） |
| **4. APNs `.p8` 金鑰已上傳到 Firebase Console**（Project Settings → Cloud Messaging → **Apple app configuration** → APNs Authentication Key；Key ID／scope／檔案位置見總表 §5）⚠️ **APNs 金鑰必須與簽 App 的 team 相同**，而 `.p8` 檔本身不含 team ID、從檔案判斷不出來——2026-08-21 已到 developer.apple.com → Keys 實查確認歸屬正確，**日後換 team 要重驗這一條** | FCM `send` 回 200 但裝置什麼都收不到——**後端 log 一切正常**，這是最難查的一種。金鑰放在 repo 之外，上傳到 Firebase 即可，**不要複製進 repo** |

⚠️ 第 4 項與 App Store Connect 的 API key 是**兩把不同的 `.p8`**，用途與權限都不同。不要拿 APNs 那把去做 `xcrun altool --api-key`。

## 打包流程

```bash
cd flutter_app
tool/build_ios_testflight.sh                       # 完整六關
tool/build_ios_testflight.sh --skip-checks         # 略過 analyze/test
tool/build_ios_testflight.sh --build-number=202608211930
```

**不要自己手打 `fvm flutter build ipa`**——會漏掉 dart-define、build number、與第 6 關的產物驗證。腳本的六關是：前置檢查（fvm／Flutter 版本／ExportOptions.plist／圖示資產／Distribution 簽章身分）→ build number → 後端位址斷言 → `pub get --enforce-lockfile` + analyze + test → `flutter build ipa` → 產物驗證。

> ⚠️ **在一台新機器上第一次跑一定會失敗一次，那是正常的。** codesign 首次使用剛建好的私鑰時 macOS 會跳**鑰匙圈授權對話框**；腳本是非互動情境，codesign 直接失敗，而 `flutter build ipa` 吐出來的錯誤只有 `exportArchive codesign command failed (... Flutter.framework: replacing existing signature`——**「replacing existing signature」是 codesign 的正常訊息、不是失敗原因**，真正的原因被 Flutter 截掉了。按對話框的「允許」（選 Always Allow）之後：archive 已經在了，**直接跑 `xcodebuild -exportArchive -allowProvisioningUpdates` 就會成功**，不必重編（2026-08-21 實測）。
> ⚠️ 而且 `flutter build ipa` 在 export 失敗時**仍然回傳 exit 0**（Flutter 原始碼註解自陳 "Still count this as success"）——**唯一的成功判準是 `build/ios/ipa/*.ipa` 存不存在**，第 6 關就是靠這個擋下來的。

需要重新產生 App Icon / LaunchImage 時（來源 `frontend/public/logo.png`）：

```bash
cd flutter_app && ../backend/venv/bin/python tool/gen_app_icons.py          # 產生
../backend/venv/bin/python tool/gen_app_icons.py --check                    # 只驗（腳本第 1 關會跑）
```

### build number 一定要遞增

`pubspec.yaml` 的版本**沒有任何遞增機制**。TestFlight 要求同一個 `CFBundleShortVersionString` 底下 `CFBundleVersion` 單調遞增，重複的 build number 會被 App Store Connect 直接拒收（而且是在上傳完之後才拒）。腳本預設用 `date -u +%Y%m%d%H%M`（12 位數）。

✅ **2026-08-21 已證實 ASC 接受 12 位數整數**（首顆 build 就是這個格式，上傳通過），先前「超過 uint32 可能被退」的殘留風險解除。腳本的格式斷言（最多三段句點分隔非負整數）另外放行 `date -u +%Y.%m%d.%H%M` 那種寫法——⚠️ **但兩種格式不可混用**，`CFBundleVersion` 是逐段比較的，換過去會被判成倒退而永久拒收（理由與唯一出路見總表 §4）。

### 上傳（腳本刻意不代勞）

腳本產出 .ipa 就停手，**上傳一律由人看過第 6 關驗證結果後手動執行**。✅ **現行做法是 App Store Connect API key ＋ `xcrun altool`**（2026-08-21 首次上傳就是這樣傳的；金鑰位置與完整指令見總表 §5／§6）：先 `--validate-app` 再 `--upload-app`，先驗那一步很便宜且會在真正上傳前就把問題講清楚。備援是 **Transporter.app**（沒有 API key 時走它，傳的一樣是第 6 關驗過的那顆位元組）。
⚠️ **不建議 Xcode Organizer**：它會自己重新 export，用的不是腳本驗過的那顆 .ipa，而且整份 ExportOptions（含 `testFlightInternalTestingOnly`）會一起被繞過。
⚠️ 不要拿 APNs 那把 `.p8` 去做 ASC 上傳，兩把金鑰用途與權限都不同。`notarytool` 是 macOS 公證用的，與 iOS 上架無關，不要拿來傳 .ipa。

## 產物驗證（第 6 關在驗什麼、為什麼）

腳本解開 .ipa 後逐項斷言。其中最重要的一條：

```bash
codesign -d --entitlements :- <Payload/Runner.app>   # 期望 aps-environment = production
```

**因果**：`aps-environment` 的實際值由**簽章時的 provisioning profile** 決定（Apple TN2265），不是由 `Runner.entitlements` 裡寫什麼決定。distribution profile 的 allowlist 一律是 production。所以這條斷言驗的其實是「Apple Developer 後台的 App ID 有沒有勾 Push Notifications capability」——沒勾就拿不到 production 的 aps-environment，上傳會吃 ITMS-90078，線上收不到推播。**修法在 Apple 後台，不在 repo 裡。**

其餘斷言與各自要抓的錯：

- `get-task-allow != true` — 抓「不小心拿 development profile 簽」，這種錯不擋的話會在 ASC 端才爆
- `Assets.car` 存在 — 圖示沒進包（改動前這個檔**完全不存在**，現在應為 ~2.28 MB）
- `CFBundleIconName` — ⚠️ 它在 **`CFBundleIcons.CFBundlePrimaryIcon.CFBundleIconName`**（與 `CFBundleIcons~ipad` 那份），**頂層沒有這個 key**。Xcode 26.6 的 actool 就只吐巢狀的。照字面寫 `plutil -extract CFBundleIconName` 會在一顆完全正常的 build 上誤擋
- `ITSAppUsesNonExemptEncryption == false` — 少了它 build 會卡在 App Store Connect 的 "Missing Compliance"，**內部測試也一樣被擋**
- bundle id 等於總表 §3 的值、`CFBundleVersion` == 這次指定的值

## TestFlight 內部測試的規則

- 內部測試（internal testing）**不需要 Beta App Review**；外部測試才需要。上限 100 人
- 內部測試員**必須先是 App Store Connect 的使用者**：要先收「使用者邀請」信、建帳號、完成 2FA——這與 TestFlight 那封邀請信是**兩封不同的信**，只寄後者對方會卡住
- 上傳後仍要通過 ASC 的**自動處理**（簽章、entitlements、圖示、出口合規），通常數分鐘
- ⚠️ **到期與相容性門檻**（build 90 天到期不可延長、build 不能刪只能過期、測試裝置要 iOS 16+ 而本專案 deployment target 是 15.0）：細節與處置一律見 [`docs/deployment_guide.md`](../../../docs/deployment_guide.md) 二、〈到期與相容性門檻〉。**唯一要在這裡記住的動作**：上傳當天就把 90 天到期日排進行事曆——寫進文件不會提醒任何人
- ⚠️ **第一次上傳的錯誤是永久的**：bundle id 與 SKU 建立後不可更改，App name 要全球唯一
- ✅ **2026-08-21 首顆 build 已上傳完成**，通過自動處理、狀態「準備測試」、標示「內部」，**沒有**卡 Missing Compliance。**內部測試群組與測試員都還沒建**——目前狀態一律以 [`docs/ios_release_settings.md`](../../../docs/ios_release_settings.md) §7 為準

## Common Rationalizations

| 藉口 | 現實 |
|---|---|
| 「`Runner.entitlements` 的 `aps-environment` 是 `development`，上 TestFlight 要改成 `production`」 | **錯，不要改。** 該值由簽章時的 provisioning profile 決定（TN2265），distribution profile 一律給 production。全世界 Flutter 專案的 `Runner.entitlements` 都躺著 `development`，這是正確狀態。（`Runner.entitlements` 的中文註解**曾經**就是這條錯誤說法，2026-08-21 已改正；若再看到誰把它改回去，那是回歸。）真正要驗的是 App ID 有沒有勾 Push Notifications，驗法是對 export 出來的 .ipa 跑 `codesign -d --entitlements :-` |
| 「pbxproj 裡的 `CODE_SIGN_IDENTITY[sdk=iphoneos*] = "iPhone Developer"` 看起來過時，刪掉／改成 Apple Distribution」 | **不要動 pbxproj。** 那與 Flutter 官方 template 一字不差，自動簽章 archive 時本來就會被覆寫。改它風險遠大於收益 |
| 「Podfile.lock 一直變動、SPM 與 CocoaPods 半切換，要做架構決策」 | 根因只是跑到 PATH 上 homebrew 的 **Flutter 3.47.0**（SPM 預設開，會把 `.flutter-plugins-dependencies` 翻成 `swift_package_manager_enabled=true`）。用 `fvm flutter`（3.41.3）就沒事——實測 `clean` + 重裝 Pods 後 `git diff ios/Podfile.lock` **零變動** |
| 「用裸 `flutter` 就好，反正版本差不多」 | 差很多。iOS 端一碰到 3.47 就動 Podfile.lock。**一律 `fvm flutter`**，腳本第 1 關會強制擋 |
| 「順手把 iOS build 加進 `.github/workflows/ci.yml`」 | 不要。該檔 `:124-127` 有明文註解「iOS/Android builds and integration_test stay local」，這是專案既有決定。而且 CI 跑不動需要憑證的簽章 |
| 「`flutter build ipa` exit 0 了，所以包沒問題」 | 只證明編得過。圖示沒進 `Assets.car`、出口合規沒宣告、build number 重複、aps-environment 不是 production——這四種全都能在 exit 0 的包上發生，全都在上傳之後才爆。要跑腳本第 6 關 |
| 「後端 healthz 綠、build 也綠，所以可以送測了」 | 兩件事無關。healthz 是後端服務健康，跟 .ipa 能不能被 ASC 接受完全正交（後端部署驗證另見 `deploy-production` skill） |
| 「`xcodebuild -help \| grep -A40 exportOptionsPlist` 查 key 清單」 | 查不到。那個 grep 只命中第 81 行的旗標說明。真正的清單在 -help 輸出**最末段**（共 212 行，標題「Available keys for -exportOptionsPlist:」），正確查法是 `xcodebuild -help \| tail -80`。`man xcodebuild` 沒有清單 |
| 「用 `--export-method app-store` 就好，不必弄 ExportOptions.plist」 | Flutter 3.41.3 的 `--export-method` 只列 `app-store/ad-hoc/development/enterprise`，**全是 Xcode 26.6 已標 deprecated 的舊名**（正名是 `app-store-connect` / `release-testing` / `debugging`）。走 `--export-options-plist` |
| 「Xcode Organizer 按 Distribute 就等於傳了驗過的那包」 | Organizer 會**自己重新 export 一次**，用的不是腳本驗過的 .ipa。要嚴格對應就用 Transporter 拖腳本產出的那顆 |
| 「先發給團隊兩三個人一起測比較快」 | **已拍板：第一版只裝使用者自己一台。** 而且**遮蔽推播文案不足以放行**——測試者拿的是真實醫師帳號，登進去就能讀到全部病患姓名與完整 SOAP（後端無 tenant／scope 隔離）。未獲授權者要加人**只有開 staging 一條路**（見〈資料風險〉與 `docs/TODO.md` §V8） |
| 「`testFlightInternalTestingOnly` 已經證實生效了，Apple 會擋外流，可以多加一個人」 | **把兩件事混在一起了。** 那個旗標擋的是**散佈**（external TestFlight／上架），**擋不了資料**——被加進 internal 群組的人拿的是真實醫師帳號，登進去就讀得到全部病患姓名與完整 SOAP。**「旗標有效」≠「PHI 有護欄」**，加第 2 個人前照樣要走完 `docs/TODO.md` §V8 的前置條件 |
| 「把 `AuthKey_*.p8` 複製進 repo 比較好管理」 | 絕對不要。`.gitignore` 已排除 `*.p8 *.p12 *.cer *.certSigningRequest *.mobileprovision AuthKey_*`，但那是最後一道防線不是許可。金鑰留在 `../firebase-secrets/`，內容不寫進任何檔案、不貼進任何對話 |

## Verification

打包完成（腳本綠燈）之後，上傳**之前**：

- [ ] `security find-identity -v -p codesigning` 看得到 **Apple Distribution**（不是只有 Development，也不是 `0 valid identities found`）
- [ ] Xcode → Settings → Accounts 裡的 team 是總表 §1 那一個，且**沒有** `(Personal Team)` 標記
- [ ] `codesign -d --entitlements :- <Payload/Runner.app>` → `aps-environment` = **`production`**（不是 development；不是就去 Apple 後台勾 Push Notifications，不要改 entitlements 檔）
- [ ] 同一份輸出裡 `get-task-allow` **不是** `true`
- [ ] `Payload/Runner.app/Assets.car` 存在且非空（~2.28 MB）
- [ ] `CFBundleIcons.CFBundlePrimaryIcon.CFBundleIconName` = `AppIcon`（巢狀路徑，頂層沒有）
- [ ] `ITSAppUsesNonExemptEncryption` = `false` 已進 bundle
- [ ] `CFBundleIdentifier` = 總表 §3 的 bundle id；`CFBundleVersion` = 這次指定的值，且**大於**上一次上傳過的（上一顆的號碼見總表 §7）
- [ ] `API_BASE` / `WS_BASE` 是生產位址（`https://` + `wss://`，含 `/api/v1` 路徑後綴，非 localhost、非 `api-` 死域名）
- [ ] App Store Connect 上已有這個 bundle id 的 App 記錄
- [ ] Firebase Console → Cloud Messaging 已有那把 APNs key，且 team 與簽 App 的 team 相同（Key ID 見總表 §5）
- [ ] `git status --short` 沒有多出 `.p8` / `.p12` / `.mobileprovision` / `.cer`

上傳之後：

- [ ] ASC 自動處理跑完，build 狀態不是 "Missing Compliance" 也不是 Invalid Binary
- [ ] 內部測試員清單**只有使用者自己**（`docs/TODO.md` §V8 的前置條件補完前不加人）
- [ ] App Store Connect → TestFlight → 該 build 旁邊有「**內部**」標記（＝`testFlightInternalTestingOnly`
      有生效；**2026-08-21 首顆 build 已確認有**）。⚠️ **有標記不代表 PHI 有護欄**——它擋散佈不擋資料，
      加人的門檻完全不變，見〈資料風險〉
- [ ] 裝上真機後**先確認 App 不是白畫面**：`main.dart` 沒有 `FlutterError.onError`、沒有
      `runZonedGuarded`，pubspec 也沒有 Sentry/Crashlytics——任何 Dart 例外的表現就是一片空白，
      而且**哪裡都查不到**（`uploadSymbols=true` 只救得了原生 crash，救不了 Dart 例外）
- [ ] FCM token 有註冊成功：`push_service.dart` 的失敗路徑全是 `debugPrint`，TestFlight build 上
      看不到，**唯一驗法是查生產 DB 的 `fcm_devices` 表**有沒有這台裝置
- [ ] 測試裝置是 **iOS 16+**（deployment target 15.0，但 TestFlight App 要 16+）
- [ ] 裝上去後實際驗一次：登入 → 收得到推播 → 開得了 SOAP 報告
      （⚠️ 用**病患帳號**登入只會看到 `/patient-unsupported` 一頁；**唯一會打到手機的推播是 report_ready**，
      必須有人在 Web kiosk 真的跑完一場問診——**建議用明顯假名的病患**跑那一場。
      完整步驟與四個靜默斷點見 `docs/deployment_guide.md` 二、〈第一次上機驗證推播〉）
- [ ] token 有沒有註冊成功**只能查 DB 的 `fcm_devices` 表**（`push_service.dart` 失敗路徑只有 `debugPrint`，TestFlight build 上看不到）
- [ ] 記下這顆 build 的 **90 天到期日**，**當場排進行事曆**
