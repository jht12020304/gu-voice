# iOS 發佈設定值總表

> **這份是 iOS／TestFlight 所有設定值的唯一權威來源。** 其他文件只寫「怎麼做」與「為什麼」，
> 不重抄這裡的值——重複的值會各自腐爛，2026-08-21 就因為 Team ID 寫錯在四個地方而繞了一大圈。
>
> - 操作流程（打包、上傳、加測試員）→ [`deployment_guide.md`](deployment_guide.md) 二、
> - 決策、陷阱、被推翻過的錯誤修法 → [`.claude/skills/ios-testflight/SKILL.md`](../.claude/skills/ios-testflight/SKILL.md)
> - 現況、未解的資料風險、加第 2 個測試人員的前置條件 → [`TODO.md`](TODO.md) §V8
>
> 最後更新：2026-08-21（首次上傳完成並已加入內部測試員，等待實機安裝驗證）

---

## 1. Apple 帳號

| 項目 | 值 | 改這個要連帶動什麼 |
|---|---|---|
| Apple ID team | `Chao-Hsin Ding` | — |
| **Team ID** | **`K593X99M7G`** | `ios/ExportOptions.plist` 的 `teamID`、`tool/build_ios_testflight.sh` 的 `team_id`、`project.pbxproj` 三處 `DEVELOPMENT_TEAM`（Xcode 選 team 時會自動改） |
| 會籍 | 付費 Apple Developer Program，有效 | — |
| 角色 | 帳號持有人（Account Holder） | 加內部測試員、建 App 記錄都需要 ≥ App Manager |

> ⚠️ **`A73R7M7VB9` 是錯的，別再出現。** 那個值從基線 commit `2aa0ff9` 就寫死在 `project.pbxproj`，
> 從未有人驗證。2026-08-21 使用者登入 Xcode 後，Xcode 自行把 pbxproj 改寫成 `K593X99M7G`，
> 而 `~/Library/Developer/Xcode` 底下掃不到 `A73R7M7VB9` 的任何痕跡。

## 2. 協議與合規

| 項目 | 狀態（2026-08-21 實查） |
|---|---|
| Apple Developer Program License Agreement | Issued 2026-06-18 / **Accepted 2026-07-07** |
| 免費 App 協議 | 所有國家或地區，2026-07-06 – 2027-06-08，**有效**（另有新版可選擇性更新） |
| 付費 App 協議 | 未簽（本 App 免費，不需要） |
| regulated medical device 申報 | **否** — 2026-08-21 使用者拍板：本 App 未以醫療器材身分向 FDA／EU 註冊 |
| 年齡分級問卷 | ⬜ 未填。ASC 另有「社群媒體功能」新問題待確認。**不擋內部測試**，擋上架與外部測試 |
| 隱私政策 URL | ⬜ **不存在**——整個 repo 沒有任何隱私政策頁，要在 Vercel 站上加一頁 `/privacy` |
| 歐盟 DSA 貿易商狀態 | ⬜ 未填。只影響歐盟發佈，內部測試不需要 |

> ⚠️ ASC 首頁那條「《Apple Developer Program 許可協議》已更新且需要檢視」**不是待簽阻擋**，
> 是「有新版可看」的通知。協議狀態實際是已接受、「＋ 新的 App」按鈕可點。

## 3. App 識別

| 項目 | 值 | 可否更改 |
|---|---|---|
| Bundle ID | `com.guvoice.guVoice` | ❌ 永久不可改 |
| App ID（Developer 後台） | `XC com guvoice guVoice`，**Push Notifications 已勾** | capability 可改 |
| App Store Connect App name | **`UroSense`** | ✅ 可改（需全球唯一） |
| SKU | `guvoice-ios` | ❌ 永久不可改 |
| ASC app id | `6803904477` | 系統產生 |
| 主要語言 | 繁體中文 | ✅ 可改 |
| 裝置上顯示名稱 | `Gu Voice`（`Info.plist` → `CFBundleDisplayName`） | ✅ 可改 |

> ⚠️ **App Store 上叫 `UroSense`，裝置主畫面上叫 `Gu Voice`——兩個名字尚未統一。**
> 測試者會同時看到。要統一就改 `flutter_app/ios/Runner/Info.plist` 的 `CFBundleDisplayName`。

## 4. 建置設定

| 項目 | 值 | 位置 |
|---|---|---|
| Flutter | **3.41.3**，一律 `fvm flutter` | `.fvmrc` |
| Xcode | 26.6（Build 17F113），iOS 26 SDK | — |
| `IPHONEOS_DEPLOYMENT_TARGET` | 15.0 | `project.pbxproj` 三處 |
| CocoaPods | 1.17.0 | `ios/Podfile.lock` |
| Firebase pods | 12.17.0（`firebase_core` 4.13.0 / `firebase_messaging` 16.5.0） | `ios/Podfile.lock` |
| `aps-environment` | `development` | `ios/Runner/Runner.entitlements` — **這是正確狀態，不要改**（值由簽章時的 profile 決定，見 SKILL） |
| `ITSAppUsesNonExemptEncryption` | `false` | `ios/Runner/Info.plist` |
| `UIBackgroundModes` | `remote-notification` | `ios/Runner/Info.plist` |
| App Icon 來源 | `frontend/public/logo.png`（1024²、無 alpha） | `tool/gen_app_icons.py` 自動裁盾牌、產 15 張 icon ＋ 3 張 LaunchImage |

### ExportOptions.plist

| key | 值 | 說明 |
|---|---|---|
| `method` | `app-store-connect` | Xcode 15.3 起的正名，`app-store` 已是 deprecated 別名 |
| `destination` | `export` | 只出本機 .ipa，不讓 xcodebuild 直接上傳（要先跑產物驗證） |
| `signingStyle` | `automatic` | |
| `testFlightInternalTestingOnly` | `true` | ✅ **2026-08-21 證實有效**——build 上傳後在 ASC 顯示「內部」標記 |
| `uploadSymbols` | `true` | 只救原生 crash，救不了 Dart 例外 |
| `manageAppVersionAndBuildNumber` | `false` | `destination=export` 下本來就不生效，設著是為了讓意圖明確 |

### 後端位址（dart-define）

變數名是 `API_BASE` / `WS_BASE`（**不是** `*_BASE_URL`），值含 path 後綴：

```
API_BASE=https://gu-voice-app-production.up.railway.app/api/v1
WS_BASE=wss://gu-voice-app-production.up.railway.app/api/v1/ws
```

⚠️ `api-` 開頭的域名是死的。沒帶 dart-define 時預設是 `http://localhost:8000/api/v1`，
裝到手機上永遠連不到後端而且被 ATS 擋，UI 只會轉圈不報原因。打包腳本第 3 關會擋。

### Build number

`pubspec.yaml` 是 `version: 1.0.0+1`，**沒有遞增機制**。打包腳本用 `date -u +%Y%m%d%H%M`（UTC 12 位數）。

⚠️ **兩種格式不可混用**：備援格式 `date -u +%Y.%m%d.%H%M`（→ `2026.0821.1930`）的首段
`2026` < `202608211213`，CFBundleVersion 是逐段比較的，換過去會被判成未遞增而永久拒收。

## 5. 憑證與金鑰

| 項目 | 值／位置 | 備註 |
|---|---|---|
| Distribution 憑證 | `Apple Distribution: Chao-Hsin Ding (K593X99M7G)` | Xcode → Settings → Accounts → Manage Certificates → ＋ |
| Development 憑證 | `Apple Development: Chao-Hsin Ding (LRHATKRR2A)` | 登入時自動產生 |
| Provisioning profile | Xcode Managed，`iOS Team Provisioning Profile: com.guvoice.guVoice` | 自動 |
| **APNs 金鑰** | `../firebase-secrets/AuthKey_<KeyID>.p8`（**repo 之外**） | Key ID 就是檔名裡那段。Team Scoped (All topics)，**Sandbox & Production**，在 team `K593X99M7G` 底下 ✅ |
| **ASC API key** | `~/.appstoreconnect/private_keys/AuthKey_<KeyID>.p8`（`600` 權限） | 名稱 `guvoice-upload`，角色「App 管理」。Key ID 與 Issuer ID **不寫進這個公開 repo**——Key ID 就是檔名裡那段，Issuer ID 在 ASC → 使用者與存取權限 → 整合 頁面。**APNs 那把同樣不寫**（2026-08-22 一併移除——原本留著的理由是「既有文件已散佈多處」，實查後全 repo 只剩那一處，理由不成立）。兩把金鑰的實際 Key ID 都只留在本機。 |

> 🔒 **這是公開 repo**（`github.com/jht12020304/gu-voice`）。
> `.gitignore` 已擋 `*.p8` `*.p12` `*.cer` `*.certSigningRequest` `*.mobileprovision` `AuthKey_*`。
> 兩把 `.p8` 都放在 repo 之外，**永遠不要複製進來，也不要把內容寫進任何檔案或訊息**。
> ⚠️ ASC API key 的 `.p8` **只能下載一次**，弄丟只能撤銷重開一把。
> ⚠️ 兩把 `.p8` 用途完全不同：APNs 那把是推播用，ASC 那把是上傳用，不可互換。

## 6. 上傳

```bash
export ASC_API_KEY_ID=<檔名裡那段>
export ASC_API_ISSUER_ID=<ASC 整合頁面上的 Issuer ID>

cd flutter_app
xcrun altool --validate-app -f build/ios/ipa/gu_voice.ipa -t ios \
  --apiKey "$ASC_API_KEY_ID" --apiIssuer "$ASC_API_ISSUER_ID"   # 先驗
xcrun altool --upload-app  -f build/ios/ipa/gu_voice.ipa -t ios \
  --apiKey "$ASC_API_KEY_ID" --apiIssuer "$ASC_API_ISSUER_ID"   # 再傳
```

`notarytool` 是 macOS 公證用的，與 iOS 上架無關，不要拿來傳 .ipa。

## 7. 目前上線狀態

| 項目 | 值 |
|---|---|
| Build | `202608211213`（版本 1.0.0） |
| 狀態 | **準備測試**，標記為「**內部**」 |
| 上傳時間 | 2026-08-21 20:46 |
| 到期 | **2026-11-19**（上傳日 +90 天，無法延長）⚠️ 現在就排進行事曆 |
| 大小 | 25,440,529 bytes |
| Delivery UUID | `b37056bb-0b50-453c-a015-b0e390d3bdbd` |
| 內部測試群組 | ✅ **內部測試（僅限已授權接觸病歷者）**，group id `17215977-9c5d-472d-9414-4798d3b6e11e` |
| 群組自動分發 | ❌ **刻意關閉，且此設定永久不可更改**——每顆新 build 都要手動掛上群組，是刻意保留的人為檢查點 |
| 已掛上的 build | `202608211213` |
| 測試員 | ✅ 2 位已在群組（狀態「已邀請」，2026-08-21） |
| 待加入 | ⏳ 另 2 位已寄出 **ASC 使用者邀請**（角色「行銷」、App 權限**只有 UroSense**）。**對方接受並完成 2FA 之後，還要再手動加進測試群組**，那時才會收到第二封 TestFlight 邀請信 |
| 測試員說明文件 | 已做成一頁式安裝指南（兩封信的先後、Apple ID 必須等於被邀請的 email、四個常見卡點）。**網址不寫進這個公開 repo**，由專案負責人另行轉發 |

⚠️ **90 天到期不能延長，build 也不能刪只能過期。** 內測要持續就得排「每 90 天至少重傳一版」——
這件事應該當場排進行事曆，不是寫進文件就算。

⚠️ **TestFlight App 本身要求 iOS 16+**，而本 App 的 deployment target 是 15.0。
iOS 15 的裝置永遠裝不到測試包（那是測試者的裝置門檻，不是上架門檻）。

## 8. 加測試員

⚠️ **本 team 的帳號持有人不是日常操作者本人**（持有人身分見 ASC →「使用者與存取權限」，這裡不抄）。
日常操作者是 team 成員（存取範圍「所有 App」），不是持有人——建 App 記錄、簽協議這類需要持有人的動作要找持有人。
（2026-08-21 一度誤記為「操作者即帳號持有人」，已更正。）

**加已是 ASC 使用者的人**：直接在群組的「新增測試人員」清單裡勾選即可，不需要走邀請流程。
⚠️ 但對方的 **App 權限必須包含 UroSense**，否則**不會出現在候選清單裡**（症狀是「人明明在，
就是選不到」）。2026-08-21 就遇到一位——角色「行銷」符合資格，但 App 權限只有另一支 App，補加 UroSense 後才出現。改法：使用者與存取權限 → 點該使用者 → 管理 App → 勾 → 儲存。

**邀請新的 ASC 使用者**：需要**名字＋姓氏＋email**。角色建議用 **行銷**——那是符合內部測試員
資格的角色（管理／App 管理／開發者／行銷）裡權限最小的一個：能管 TestFlight 內部測試，
但**不能上傳 build、不碰憑證與 API 金鑰**。App 權限只勾這支 App，不要給「所有 App」。

⚠️ **邀請信會過期**（使用者清單上已經有一筆「已過期的邀請」為證），過期就在該列按「重新傳送邀請」。

⚠️ **這是兩封不同的信，順序不能顛倒**：第一封是 App Store Connect 的「使用者邀請」
（對方要建 Apple 帳號、完成 2FA），對方接受**之後**才能加進測試群組，那時才會收到第二封
TestFlight 邀請信。只寄第二封對方會卡住——這是這條流程最常見的卡點。

⚠️ **測試員會困惑的一件事**：App Store 上叫 `UroSense`，但裝到手機主畫面上的圖示名稱是
`Gu Voice`（見 §3）。先講會少一輪來回。

**加別人**：兩段流程，順序不能顛倒——
1. ASC →「使用者與存取權限」→ 邀請對方成為 ASC 使用者（對方要建 Apple 帳號、完成 2FA）
2. 對方接受之後，才能加進內部測試群組（TestFlight 邀請是**另一封信**）

> 📋 **名單以 App Store Connect 為準，不抄進這個公開 repo**（真人的姓名與 email 是個資，
> 而且這裡是 `github.com/jht12020304/gu-voice`）。要看目前有誰：
> ASC → UroSense → TestFlight → 內部測試群組。
>
> ⚠️ **2026-08-21 決策變更：使用者拍板加入 4 位測試員，PHI 前置條件未做。**
> 原本的「第一版只裝自己一台」已被推翻。使用者的理由是**帳號發放由他自己控制**——
> 即 App 一打開就是登入頁，沒有醫師帳號就什麼都看不到，PHI 暴露發生在「發出真實醫師帳號」
> 那一刻而不是「加進 TestFlight」那一刻。**這個控制點是人為的，沒有任何技術機制在擋。**
> §V8 的前置條件（推播文案去識別化、關掉 iOS 破壞性入口、staging 環境）**仍然全部未做**。
>
> 🛑 **原始風險評估（仍然成立，只是被接受了）：**
> 內測包打的是**生產後端**（沒有 staging），測試者拿到的是**真實醫師帳號**——
> 登進去就讀得到全部真實病患姓名與完整 SOAP 報告（後端沒有 tenant／scope 隔離）。
> **遮蔽推播文案不會降低 PHI 暴露**，那只是鎖定畫面那一行。

## 8.5 2026-08-22 轉向：iOS 單一 App（語音問診開通）

平台分工推翻（詳見 `docs/TODO.md` §V7 開頭與 CLAUDE.md）：iOS 不再是醫師專用，
kiosk iPad 跑病患語音問診、醫師/管理員同一顆 App、網頁走向除役。對這份文件的影響：

- **下一顆 build 起，App 內含完整病患問診流程。** `testFlightInternalTestingOnly=true`
  照舊（擋散佈不擋資料），但測試員名單的意義變了——**裝了 App 的人現在可能接觸到
  病患問診入口**，加人前的 PHI 檢查照 §V8 不變。
- **kiosk iPad 要用 kiosk 帳號（patient 角色）登入**，閒置登出 180 秒起效；
  醫師裝置用醫師帳號，兩者同一顆 binary。
- **kiosk iPad 不會註冊推播**（`shouldEnablePush` 對病患帳號恆 false——共用機
  不得成為任何醫師的推播端點）。
- ⚠️ **語音管線在真麥克風上仍是零實測**（§V1 紅字）。在 kiosk iPad 上第一次
  實測通過之前，**不要把 App 拿給真病患用**。驗證清單見 `flutter_app/README.md`
  「剩下的最小驗證路徑」。

## 9. 還沒做的事

- ⬜ 在 iPhone（iOS 16+）上實際安裝並確認**打得開、功能能用**
  （2026-08-21 已有兩位測試員顯示「已安裝」，但沒有人回報過實際使用結果——
  「裝得起來」不等於「打得開」）
  ⚠️ 2026-08-22 起 `lib/core/error_boundary.dart` 會把 Dart 例外顯示成一行可讀訊息、
  堆疊寫進 stderr（裝置接著 Mac 時 `flutter logs` 看得到），所以「一片空白且查不到」
  已不是預期症狀。**但仍然沒有 Sentry/Crashlytics**——錯誤不會自己送出來，
  請測試者遇到問題時直接截圖
- ⬜ 驗證推播：唯一會打到手機的是 `report_ready` 的 fan-out，必須有人在 Web kiosk
  真的跑完一場問診並產出 SOAP。**建議用名字明顯是假的病患（例如「測試 勿用」）跑一場**，
  這樣第一則推播的鎖定畫面上就是假名，同時解決驗證需求與 PHI 風險
- ⬜ 確認 FCM token 有註冊成功：`push_service.dart` 的失敗路徑全是 `debugPrint`，
  TestFlight build 上看不到，**唯一驗法是查生產 DB 的 `fcm_devices` 表**
- ⬜ 確認生產 Railway 的 `FCM_CREDENTIALS_JSON` 有值、`RUN_CELERY_IN_API` 開著
- ⬜ 統一 App name 與裝置顯示名稱
- 🛑 **§V8 的 PHI 前置條件全部未做，而測試員已加到 4 位**——目前唯一的控制點是
  「不發真實醫師帳號給未授權者」這個人為約定。發帳號前請再確認一次對方的授權狀態
- ⬜ 年齡分級問卷、隱私政策 URL（擋上架與外部測試，不擋內部測試）
