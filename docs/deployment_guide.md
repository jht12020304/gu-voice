# GU-Voice 部署與設定操作手冊

2026-11-15 起正式環境**自架在一台常開的 Mac**，Railway、Vercel 已刪除，資料從 Supabase 搬回本機 Postgres。
舊的雲端版手冊在 [archive/cloud_2026-11/deployment_guide_cloud.md](archive/cloud_2026-11/deployment_guide_cloud.md)，只當歷史參考。

---

## 目前正式環境

| 項目 | 值 |
|------|----|
| **對外網址（唯一）** | `https://gu.zymomed.com`：React 報告網頁＋`/api/v1`＋`wss://…/api/v1/ws`（同源，沒有跨網域 cookie／CORS 問題） |
| **健康檢查** | `https://gu.zymomed.com/api/v1/healthz/deep`（同時驗 DB 與 Redis） |
| **入口** | Cloudflare Tunnel `gu-voice`（`~/.cloudflared/gu.yml`，launchd `com.gu-voice.tunnel`）→ `127.0.0.1:8005` |
| **主機設定** | `~/Services/gu-voice/`（repo 外：repo 是公開的，金鑰不能進來）：`compose.yml`、`.env`、`nginx.conf`、`deploy.sh`、`backup.sh`、`README.md` |
| **容器** | compose 專案 `gu-voice-host`：`db`（Postgres 17）、`redis`、`backend`（uvicorn＋Celery worker＋beat，`start.sh` 同容器起）、`web`（nginx） |
| **資料庫** | volume `gu-voice-host_db_data`；每日 03:40 備份到 `~/Services/gu-voice/backups/`（launchd `com.gu-voice.backup`，留 60 天） |
| **外部依賴** | OpenAI（STT／LLM／TTS）、Firebase FCM＋APNs（推播）、SMTP（重設密碼信），都是主機主動往外連 |

⚠️ repo 根的 `docker-compose.yml` 是**本機開發用**，compose 專案名是 `gu-voice`，跟正式環境 `gu-voice-host` 無關。不要在 repo 裡對正式環境下 compose 指令。

---

## 一、部署流程

**merge 到 `main` 不會上線**，要在那台 Mac 上手動跑：

```bash
~/Services/gu-voice/deploy.sh
```

這支腳本會依序做：
1. 確認 repo 沒有未提交的改動，切到 `main` 並 fast-forward 到 `origin/main`
2. 先跑 `backup.sh` 備份 DB
3. `docker compose up -d --build backend web`（`start.sh` 會先跑 `alembic upgrade head`）
4. 輪詢 `/api/v1/healthz/deep`，通過才印出上線的 commit

- 只改環境變數：編輯 `~/Services/gu-voice/.env`，再跑 `docker compose up -d backend`（不必重 build）。
- React 網頁的 API／WS 網址在 build 時寫死（`compose.yml` 的 `web.build.args`），改網域要重 build `web`。
- 回滾：`git -C <repo> checkout <舊 commit>` 之後在 `~/Services/gu-voice` 跑 `docker compose up -d --build backend web`。如果牽涉 migration，要用 `backup.sh` 開頭寫的指令還原 DB。
- **healthz 綠不代表新碼上線**。要確認的話，看 `docker compose logs backend` 裡有沒有「Application startup complete」，時間要對得上；或從容器內找這次新增的欄位：`docker compose exec backend sh -c 'curl -s -H "Authorization: Bearer $METRICS_TOKEN" localhost:8000/openapi.json'`。⚠️ 自動化判斷時不要用 `grep -c … || echo 0`：沒命中時會變成 `"0\n0"`，被誤判成命中。
- `/metrics`、`/docs`、`/openapi.json` 不在 nginx 的 `/api/` 轉發範圍內，對外一律拿到 SPA 的 index.html，不會曝光（2026-11-15 實測）。要看就從容器內打 `localhost:8000`。

> ⚠️ 改 `backend/scripts/start.sh` 後要保留執行位（`git update-index --chmod=+x backend/scripts/start.sh`），否則容器起不來。

### client IP（登入限流／稽核）

nginx 只把 `CF-Connecting-IP` 寫進 `X-Forwarded-For`。後端 `TRUST_PROXY_HEADERS=true`，取 XFF 的最後一段當 client IP。只有本機的 cloudflared 連得到 `127.0.0.1:8005`，所以這個 header 可信。**不要改回 `$proxy_add_x_forwarded_for`**：改回去的話最後一段會變成 docker gateway IP，全院共用同一個 IP，登入限流會把所有人一起鎖住。

### iOS 打包連哪裡

`flutter_app/tool/env.production.sh` 是 App 的 `API_BASE`、`WS_BASE`、`WEB_BASE` 的唯一來源，目前都指向 `gu.zymomed.com`。`build_ios_testflight.sh` 預設就讀這份。2026-11-15 之前的所有 TestFlight build 連的是已刪除的 Railway，**都已經不能用**。

---

## 二、iOS TestFlight 發佈（2026-08-22 起：完整 App，含病患語音問診）

> ⚠️ 2026-08-22 平台分工推翻：iOS 不再是「醫師端」，是唯一的 App——kiosk iPad 跑
> 病患語音問診、醫師/管理員同一顆。所以**從這一天之後的 build 起，裝了 App 的
> 測試員都能進到病患問診入口**；加測試員前的 PHI 檢查（§V8）比以前更要緊。
> §7 最後已知的 production 內測包帶 KIOSK define；2026-10-03 staging 候選包不帶登入憑證。舊包的登入頁直接按「開始語音問診」便會以候診專用 patient
> 帳號自動登入，無須輸入帳密；閒置登出 180 秒照常生效。

> 已作廢的 2026-08-20 平台分工曾是「Web＝病患 kiosk、iOS＝醫師端」；現況以同一顆 iOS App 為準。
> iOS 這條線只走 TestFlight **內部測試**，不上架。管道現況與未解風險見 `docs/TODO.md` §V8（iOS 醫師端功能面見 §V7）。

> 打包腳本預設仍連 production；2026-10-03 已建立獨立 staging 後端、DB、Redis 與 React preview，並產出明確指定 staging 的 iOS 候選包。網址、帳號位置與 Apple 協議阻擋狀態以 [發佈設定 §0](ios_release_settings.md#0-2026-10-03-staging-候選包與測試環境) 為準。以下臨床資料限制適用於 production 包。
> 2026-09-02 起病患在基本資料頁必須選醫師；已指派場次的問診完成、紅旗、報告成功／失敗
> 通知與 dashboard 即時事件都只送該醫師。doctor 與帶執照的臨床 admin 也只讀自己的
> 病患、場次、報告與紅旗；無執照的 system admin 保留全院稽核視野。
>
> ⚠️ 推播與報告仍含**被指派病患的 PHI**，system admin 仍可讀全院資料；這是臨床 scope，
> 不是 tenant 隔離。未獲授權的人不得加入 production 內測，工程／PM 測試仍須獨立 staging。
> 詳細邊界與 legacy 未指派場次的相容 fallback 見 `docs/TODO.md` §V8。

### 設定值一律看總表

Team ID、Bundle ID、SKU、ASC app id、Flutter／Xcode 版本、`ExportOptions.plist` 各 key、
dart-define 字串、憑證與金鑰位置、上傳指令、目前上線的那顆 build——**值全部在
[`ios_release_settings.md`](ios_release_settings.md)**，本手冊不重抄（重複的值會各自腐爛，
2026-08-21 就因為 Team ID 寫錯在四個地方而繞了一大圈）。本節只寫**怎麼做**與**為什麼**。

### ✅ 2026-08-21 首次上傳完成——Apple 側現況

第一顆 build 已上傳、通過 ASC 自動處理，狀態是**「準備測試」**，而且在 TestFlight 的
建置版本清單上標著「**內部**」。上傳前 `xcrun altool --validate-app` 先回
"VERIFY SUCCEEDED with no errors"，再 `--upload-app`，傳輸只花十秒出頭。
**build number、Delivery UUID、大小、到期日、群組與測試員狀態見
[`ios_release_settings.md`](ios_release_settings.md) §7。**

以下都是**實際點過、已完成**的，不用再做一次（值見總表 §1–§3、§5）：付費會籍與兩份協議、
App ID 已勾 Push Notifications、APNs 金鑰確認在正確 team 底下、App Store Connect 的 App 記錄、
以及上傳用的 App Store Connect API key。

⚠️ **ASC 首頁那條「《Apple Developer Program 許可協議》已更新且需要檢視」不是待簽阻擋**，
是「有新版本可看」的通知——協議狀態實際是已接受、「新的 App」按鈕可點。
別再把它當成第一道牆（2026-08-21 之前的文件版本寫錯了）。

✅ **這次沒有出現 "Missing Compliance"**——`Info.plist` 補 `ITSAppUsesNonExemptEncryption = false`
那一修確實生效，省掉了「上傳後還要到 ASC 網頁人工回答出口合規問卷」這一步。

**還沒做的事**（年齡分級問卷、隱私政策 URL、歐盟 DSA 貿易商狀態等；都不擋內部測試，
擋的是日後上架與外部測試）一律見 [`ios_release_settings.md`](ios_release_settings.md) §2／§9。
regulated medical device 申報＝**否**（2026-08-21 使用者拍板：本 App 未以醫療器材身分註冊）。

### 前置條件（Apple 側，缺任一項就停在原地）

> 依「第一次會撞到的順序」排。**前兩項不是簽章問題，是帳號／合約問題**——沒過的話連
> App Store Connect 的「＋ New App」都點不下去，後面的簽章步驟一步都輪不到。
>
> ✅ **2026-08-21：第 1–7 項全部已完成**（狀態值見 [`ios_release_settings.md`](ios_release_settings.md)
> §1–§3、§5）。下面保留的是**每一項沒做時會怎麼壞**——換一台機器、換一個人、或憑證過期時
> 還是會照這個順序再撞一次，所以不要因為現在都綠了就刪掉。第 8–10 項（業務／法規端）仍未做。

**A. 帳號與合約（第一次登入 App Store Connect 就會撞到）**

1. **App Store Connect → Business 區已簽署最新的 Paid Apps / Free Apps Agreement。**
   Apple 每改一次條款就要重簽，**沒簽時「＋ New App」是灰的**，而畫面上不會告訴你原因。
   這是第一次登入後**第一個會撞到的牆**，先去 Business 看有沒有待簽的協議。
2. **這個 Apple ID 在本專案 team（ID 見總表 §1）的角色要 ≥ App Manager。**
   Developer 角色**建不了 App 記錄、也產不了 Distribution 憑證**——症狀是選單裡根本沒有那些選項，
   看起來像「Xcode 壞了」。Account Holder 可在 Users and Access 調整角色。

**B. 簽章與 App 記錄**

3. **付費 Apple Developer Program 會籍**，且 team 正確（ID 見總表 §1）。
   Xcode → Settings… → Accounts 裡該 team 名稱後面**不能**標 `(Personal Team)`——
   標了就是免費帳號，**永遠拿不到 Distribution 憑證**，也上不了 TestFlight。
4. **Xcode 已登入該 Apple ID，並產生 Apple Distribution 憑證**
   （Accounts → 選 team → Manage Certificates… → ＋ → Apple Distribution）。
   驗證：`security find-identity -v -p codesigning` 要看得到 `Apple Distribution`／`iPhone Distribution`。
   ⚠️ 2026-08-21 20:04 實測：登入後 Xcode 只自動建了 Development 憑證，
   **Distribution 憑證不會自動產生**——登入本身不做這件事，要自己去 Manage Certificates… 建。
   ✅ 這一關當天已補建完成（憑證名稱見總表 §5），後續才打得出真簽章的 .ipa。

> ### ⚠️ Team ID 曾經是錯的（2026-08-21 修正）
>
> 這份文件與 `ExportOptions.plist`／打包腳本／skill 先前寫的 **`A73R7M7VB9` 是錯的**。
> 那個值從最初的基線 commit `2aa0ff9` 就寫死在 `project.pbxproj`，從未有人驗證過。
> 2026-08-21 使用者登入 Xcode 後，Xcode **自己把 pbxproj 三處的 `DEVELOPMENT_TEAM` 改寫成
> `K593X99M7G`**，且它產生的 provisioning profile 是 `K593X99M7G` 簽發的
> （`application-identifier = K593X99M7G.com.guvoice.guVoice`）。
> `~/Library/Developer/Xcode` 底下掃不到 `A73R7M7VB9` 的任何痕跡＝這個帳號與該 team 無關。
>
> **當時的下游疑慮：APNs 金鑰是哪個 team 產的？** `.p8` 檔本身不含 team ID，無法從檔案判斷；
> 若它屬於別的 team，**推播一定不會通**——APNs 金鑰必須與簽 App 的 team 相同。
> ✅ **2026-08-21 已到 developer.apple.com → Certificates, Identifiers & Profiles → Keys 實查，
> 那把金鑰確實在正確的 team 底下**（Key ID 與 scope 見總表 §5）。**日後換 team 就要重驗這一條。**
5. **App Store Connect 上已建立這個 bundle id 的 App 記錄**（首次上傳前必須先有；已建好的名稱、
   SKU、app id 見總表 §3）。
   ⚠️ App name **必須全球唯一**，很可能已被別人佔用——被佔用就要當場換名字。
   ⚠️ 換名字的後遺症：**App Store 上的名字與裝置主畫面顯示名稱（`CFBundleDisplayName`）會不一致**，
   測試者兩個都看得到。本專案目前就是這個狀態（兩個名字見總表 §3），尚未統一。
   ⚠️ **SKU 與 bundle id 建立後都不可更改**，第一次填錯是永久的，填之前想清楚。
6. **Apple Developer 後台的 App ID 已勾 Push Notifications capability**。
   ❌ **不要**去改 `flutter_app/ios/Runner/Runner.entitlements` 的 `aps-environment: development`——
   那個值由簽章時的 provisioning profile 決定（Apple TN2265），distribution profile 一律給 production，
   改檔案沒有任何作用。沒勾 capability 的症狀是上傳吃 **ITMS-90078** 且線上收不到推播。
   真正的驗法是對 export 出來的 .ipa 跑 `codesign -d --entitlements :- <Runner.app>` 看實際簽進去的值
   （打包腳本第 6 關已自動做這件事）。
7. **APNs `.p8` 金鑰已上傳到 Firebase Console**
   （Project Settings → Cloud Messaging → **Apple app configuration** → APNs Authentication Key）。
   金鑰檔放在 **repo 之外**（路徑、Key ID、scope 見 [`ios_release_settings.md`](ios_release_settings.md) §5）。
   ⚠️ **絕不複製進 repo、絕不把內容寫進任何檔案或訊息。**
   沒上傳的症狀最難查：**FCM `send` 回 200、後端 log 一切正常、手機一片安靜**。
   ⚠️ 這把 `.p8` 與 App Store Connect 的 API key 是**兩把不同的金鑰**，別互相拿去用。

**C. 業務端要拍板的（打包時生不出來，要先有人決定並提供）**

8. **隱私政策 URL**——App Store Connect 的 App Information **明文必填**，沒有就送不出去。
   ⚠️ **本 repo 目前沒有任何隱私政策頁面**。要在 `gu.zymomed.com` 加一頁 `/privacy`，至少涵蓋：
   語音錄音的蒐集與**保存期限**、病患姓名與主訴的處理、**推播內容含哪些個資**、
   以及資料流向（Firebase、OpenAI、院方自架主機）。這是一件要寫、要有人核可的事，不是填個網址。
9. **Regulated medical device 申報**（2026-03-26 起的新規）。
   觸發條件：主要或次要類別選 **Medical** 或 **Health & Fitness**，**或**年齡分級問卷的
   「Medical or Treatment Information」勾到 frequent／intense ⇒ 就必須在 App Store Connect 完成申報。
   答 Yes 之後還要提供 **EU Manufacturer SRN 或 FDA Owner/Operator Number**、
   **Instructions for Use URL**、**Use Statement**、**Safety Information**。
   ⚠️ **這是業務／法規端要拍板的事，工程打包時生不出來**，也不要為了繞過它去亂選類別。
   出處：<https://developer.apple.com/help/app-store-connect/manage-app-information/>
10. **新制年齡分級問卷**（2026-01-31 起必填）。與上一條**連動**——問卷裡的醫療資訊頻率答案
    會直接決定要不要做 regulated medical device 申報，兩件事一起想，不要分兩天填。

### 打包

```bash
cd flutter_app
./tool/build_ios_testflight.sh            # 預設打生產後端、build number 用 UTC 時間戳
./tool/build_ios_testflight.sh --help     # 參數：--skip-checks、--build-number=<最多三段句點分隔的非負整數>
```

腳本六關：① 前置檢查（fvm 存在／Flutter 是 3.41.3／`ExportOptions.plist` 存在且 `plutil -lint` 過／
App Icon 資產齊全／Distribution 簽章身分）② 決定 build number ③ `API_BASE`／`WS_BASE` 斷言
④ `pub get --enforce-lockfile` ＋ `analyze` ＋ `test` ⑤ `flutter build ipa` ⑥ 產物驗證。

- ⚠️ **一律 `fvm flutter`，不要用裸 `flutter`**：PATH 上的是 homebrew 3.47.0，它 SPM 預設開，
  會把 `.flutter-plugins-dependencies` 翻成 `swift_package_manager_enabled=true` 並動到 `ios/Podfile.lock`。
- 後端位址預設就是生產值（變數名是 `API_BASE`／`WS_BASE`，**不是** `*_BASE_URL`，值含 path 後綴；
  `api-` 開頭是死域名）。腳本會擋掉 localhost 與明文 `http://`／`ws://`（iOS ATS 會擋）。
- **build number**：`pubspec.yaml` **沒有任何遞增機制**；TestFlight 要求同一
  `CFBundleShortVersionString` 下 `CFBundleVersion` 單調遞增，重複的會被拒。腳本用
  `date -u +%Y%m%d%H%M` 覆寫。✅ **2026-08-21 已證實 ASC 收 12 位數整數**（首顆 build 就是這個格式，上傳通過），
  先前「超過 uint32 可能被退」的顧慮解除。腳本收的格式是**最多三段句點分隔的非負整數**，
  純數字與句點式兩種都放行——⚠️ **但兩種格式不可混用**（理由與唯一出路見
  [`ios_release_settings.md`](ios_release_settings.md) §4 的 build number 段）。
- **圖示**：`tool/gen_app_icons.py` 從 `frontend/public/logo.png` 產 15 張 App Icon ＋ 3 張 LaunchImage。
  單獨檢查：`../backend/venv/bin/python tool/gen_app_icons.py --check`（缺檔 exit 1）。
- 首次在乾淨 checkout 上打包前先跑一次
  `fvm flutter clean && rm -rf ios/Pods ios/.symlinks && fvm flutter pub get && (cd ios && pod install)`——
  缺 `ios/Pods/Manifest.lock` 會讓 Xcode 直接 Archive 在 `[CP] Check Pods Manifest.lock` 失敗。

### 產物驗證（腳本第 6 關自動做；**本機能驗的都擋在這裡**）

解開 .ipa 後逐條斷言，任何一條不過就不要上傳。⚠️ **「六關全綠」只等於「本機驗得到的都過了」**——
**ASC 上有沒有這個 bundle id 的 App 記錄、這次的 build number 是否與雲端歷史重複，本機一律驗不到**，
那兩種退件要等上傳完才會爆：

| 斷言 | 不過代表什麼 |
|---|---|
| `aps-environment == production` | App ID 沒勾 Push Notifications → ITMS-90078、線上收不到推播 |
| `get-task-allow != true` | 拿 development profile 簽的，上傳會被退 Invalid Signature |
| `Assets.car` 存在 | actool 沒編圖示 → ITMS-90713 |
| `CFBundleIcons.CFBundlePrimaryIcon.CFBundleIconName` 有值 | 同上（⚠️ **頂層沒有 `CFBundleIconName`**，Xcode 26.6 的 actool 只吐巢狀那份，照字面查頂層會誤擋正常 build） |
| `ITSAppUsesNonExemptEncryption == false` | 卡在 App Store Connect 的 "Missing Compliance"，內部測試也一起被擋 |
| `CFBundleIdentifier` 等於總表 §3 的 bundle id、`CFBundleVersion` 等於這次指定的值 | 打錯包／build number 沒吃進去 |

✅ **覆蓋現況（2026-08-21 20:26 起，六關全部端到端跑過真簽章）**：
產出 `build/ios/ipa/gu_voice.ipa`（24MB，build number 見總表 §7），第 6 關全綠——
`aps-environment = production`、`get-task-allow = false`、`Assets.car` 2,285,304 bytes、
`CFBundleIconName = AppIcon`、`ITSAppUsesNonExemptEncryption = false`、
bundle id 正確。archive 耗時 497s、export 53s。
**`aps-environment = production` 這一行同時證明 App ID 確實有 Push Notifications capability**
（那是它唯一的來源），所以推播鏈的簽章端已驗證無誤。

> ⚠️ **第一次跑會失敗一次，那是正常的。** codesign 首次使用剛建好的私鑰時，macOS 會跳鑰匙圈
> 授權對話框；在腳本這種非互動情境下 codesign 直接失敗，`flutter build ipa` 的錯誤只會顯示
> `exportArchive codesign command failed (... Flutter.framework: replacing existing signature`
> ——**那句「replacing existing signature」是 codesign 的正常訊息，不是失敗原因**，真正的原因被
> Flutter 截掉了。按下對話框的「允許」（建議選 Always Allow）之後就過得去：2026-08-21 實測
> 按完直接跑 `xcodebuild -exportArchive -allowProvisioningUpdates`（archive 已經在了，不必重編）
> 即成功匯出。**這一關每台新機器、每次重建私鑰都會再撞一次，別當成簽章壞了。**
> ⚠️ 同時注意：`flutter build ipa` 在 export 失敗時**仍然回傳 exit 0**（Flutter 原始碼註解自陳
> "Still count this as success"）。**唯一的成功判準是 `build/ios/ipa/*.ipa` 存不存在**，
> 腳本第 6 關就是靠這個擋下來的——這次它真的擋到了。

> ✅ **`testFlightInternalTestingOnly` 已證實生效（2026-08-21）**：本機確實掃不到痕跡——
> 匯出後產物旁的 `build/ios/ipa/ExportOptions.plist` 只記錄 xcodebuild **接受**了這個 key（`=> true`），
> **.ipa 內部與 `Packaging.log` 都沒有任何可檢查的殘跡**，所以第 6 關驗不到它是正常的。
> 但**上傳後在 App Store Connect 上看得到**：走 `destination=export` ＋ `xcrun altool`
> （既不是 xcodebuild 直傳、也不是 Organizer）上去的那顆 build，TestFlight 建置版本清單上
> 就標著「**內部**」。⇒ 旗標會被帶到 ASC，這件事不必再懷疑。
>
> ⚠️ **但「旗標有效」不等於「PHI 有護欄」，這兩件事要分開講**：它擋的是**散佈**
> （external TestFlight／App Store），**擋不了資料**——任何一個被加進 internal 群組的人，
> 拿到的仍是完整存取權。PHI 的結論一個字都沒變，見〈建內部測試群組〉與 §V8。
> ⚠️ 另外**走 Xcode Organizer 上傳仍然會自己重新 export**，整份 ExportOptions（含這個 key）
> 一起被繞過——這一條沒有被推翻，用 Organizer 就等於沒設。

### 上傳

✅ **現行做法＝App Store Connect API key ＋ `xcrun altool`**（2026-08-21 首次上傳就是這樣傳的）。
**指令與環境變數見 [`ios_release_settings.md`](ios_release_settings.md) §6**，這裡只講怎麼選路徑：

- **A) `xcrun altool`（建議）**：先 `--validate-app` 再 `--upload-app`。先驗那一步很便宜，
  而且它會在真正上傳前就把 bundle／簽章問題講清楚（這次回 "VERIFY SUCCEEDED with no errors"）。
  ⚠️ 旗標是 `--apiKey` / `--apiIssuer`；金鑰檔要放在 `~/.appstoreconnect/private_keys/` 底下
  altool 才找得到。⚠️ **不要重用 `firebase-secrets/` 那把 APNs `.p8`**——那是推播金鑰，
  不是 ASC API key，用途與權限都不同。
- **B) Transporter.app**（Mac App Store 免費）：登入 → 把腳本印出的那顆 .ipa 拖進去 → Deliver。
  沒有 API key 時走這條，傳的一樣是第 6 關驗過的那顆位元組。
- **C) Xcode Organizer**：⚠️ **不建議**。Organizer 會**自己重新 export 一次**，用的不是腳本驗過的
  那顆 .ipa，而且**整份 `ExportOptions.plist` 連同 `testFlightInternalTestingOnly` 一起被繞過**
  （這一條沒有被 2026-08-21 的驗證推翻）。

⚠️ `notarytool` 是 macOS 公證用的，**與 iOS 上架無關**，不要拿它傳 .ipa。

### App Store Connect：建內部測試群組

1. App Store Connect → 選 App → **TestFlight** tab，等這包跑完**自動處理**（簽章、entitlements、圖示、
   出口合規，通常數分鐘）。
2. **Internal Testing** → ＋ 建群組 → 把 build 加進去。
   **內部測試不需要 Beta App Review**（外部測試才需要），上限 100 人。
3. 測試者必須**先是 App Store Connect 的使用者**：Users and Access → 寄「使用者邀請」信 →
   對方建帳號並完成 2FA。⚠️ 這與 TestFlight 那封邀請信是**兩封不同的信**，順序不能顛倒。
4. ⚠️ production 群組只加**已獲授權接觸病歷的院內人員**；工程／PM 使用獨立 staging。
   ✅ `ExportOptions.plist` 的 `testFlightInternalTestingOnly=true` **確實有生效**——2026-08-21
   上傳的那顆 build 在 TestFlight 清單上標著「內部」（詳見上一節的 ⓘ 框）。
   🛑 **但它擋的是「散佈」，不是「資料」**：它讓這顆包不能拿去做 external TestFlight／上架，
   **對任何一個被加進 internal 群組的人完全沒有作用**。臨床帳號雖只看自己被指派的
   病患資料，仍會接觸真實 PHI；system admin 仍可全院稽核。
   ⇒ **它不是 PHI 護欄**；帳號授權、臨床 scope 與 staging 才是。「旗標有效」≠「PHI 有護欄」。

### 推播上機驗證（2026-09-02 已通過；換裝置時照這個順序重驗）

2026-09-03 複驗發現 FCM 回報成功不等於 iPhone 收到。build `202609030649` 會把原生
APNs token 與 FCM token 一起登記；後端有 APNs token 時優先直送 Apple，失敗才回退 FCM。
Apple 已標為 VALID 且掛入先行測試群組，待醫師手機更新並登入後複驗。
「裝上去打得開」仍不等於新裝置一定能收到推播；這條線上有四個獨立斷點，任何一個沒過，
症狀都是**手機一片安靜、後端 log 一切正常**：

1. **生產 `~/Services/gu-voice/.env` 的 `FCM_CREDENTIALS_JSON` 要有值。**
   沒設時 `backend/app/core/firebase.py:39` 只 `logger.warning`、**API 照常起**，
   推播全部靜默。查法：`grep -c ^FCM_CREDENTIALS_JSON= ~/Services/gu-voice/.env` 看有沒有這個變數（**不要把值印出來**）。
   直接 APNs 備援另需 `APNS_AUTH_KEY_BASE64`、`APNS_KEY_ID`、`APNS_TEAM_ID`、`APNS_TOPIC`；
   `.p8` 只可放在 `~/Services/gu-voice/.env`（chmod 600），不得寫進 repo 或 log。
2. **`RUN_CELERY_IN_API` 要是 `true`。**
   推播是丟給 Celery 的（`notification_service.py:712` 的 `send_push_notification_task.delay()`），
   **worker 沒跑＝任務沒人消費，而錯誤會被吞掉**。啟動 log 裡要看得到 celery banner。
3. **生產 DB 要有一個能登入的 doctor／admin 帳號。**
   公開註冊一律降級成 `PATIENT`（`auth_service.py:234` 的 AUTH-3），而**病患帳號在 iOS 上會被導到
   `/patient-unsupported`**——拿病患帳號裝上去，整個 App 只看得到一頁「不支援」。
   沒有醫師帳號就照「三、維運」的 psql 用 SQL 改一個既有帳號的 `role`。
4. **怎麼觸發驗證推播**：在病患基本資料頁選定要驗證的醫師，跑完一場問診並產出 SOAP；
   已指派場次的通知只送該醫師，光登入 App 不會產生推播。
   ✅ **建議用一個名字明顯是假的病患跑這一場**（例如「測試 勿用」）——這樣第一則推播的鎖定畫面上
   就是假名，**同時解決「要驗證」與「不要把真實 PHI 推到手機上」兩個需求**。

**怎麼確認 FCM token 真的註冊成功**：`push_service.dart` 的**所有失敗路徑都只有 `debugPrint`**，
TestFlight build 上看不到任何輸出。**唯一可靠的驗法是查 DB 的 `fcm_devices` 表**有沒有這台裝置的 token：

```sql
SELECT user_id, platform, apns_token IS NOT NULL AS has_apns_token, created_at, updated_at
FROM fcm_devices ORDER BY updated_at DESC LIMIT 5;
```

⚠️ **`flutter build ipa` 失敗時仍會回 exit 0**（Flutter 原始碼註解自陳 "Still count this as success"）。
**唯一的成功判準是 `build/ios/ipa/*.ipa` 到底存不存在。** 打包腳本第 6 關已經擋住這件事，
但手動跑 `flutter build ipa` 的人一定要知道——不要看到 exit 0 就以為有包。

### 到期與相容性門檻

- **TestFlight build 90 天到期，且無法延長；build 也不能刪，只能等它過期。**
  ⚠️ **2026-08-21 首次上傳已經讓這個倒數開始跑了**（到期日見總表 §7）——內測要持續就必須排
  「**每 90 天至少重傳一版**」，重傳時 build number 一定要比上一顆大（用腳本預設的時間戳就自動成立）。
  這件事**當場排進行事曆**才算數，寫進文件不會提醒任何人。
- **TestFlight App 本身要求 iOS 16+，而本專案 `IPHONEOS_DEPLOYMENT_TARGET = 15.0`。**
  ⇒ iOS 15 的裝置**永遠裝不到測試包**（正式上架不受此限）。挑測試機時先確認 iOS 版本。

---

## 三、維運

所有指令都在 `~/Services/gu-voice/` 底下跑。

```bash
docker compose ps                                   # 四個容器都要 Up（backend 要 healthy）
docker compose logs backend --tail 200 -f           # 後端＋Celery log
docker compose exec db psql -U gu -d gu_voice       # 直接操作生產 DB
./backup.sh                                         # 手動備份（每日 03:40 也會自動跑）
tail ~/Services/gu-voice/logs/cloudflared-error.log # tunnel 連線狀態
launchctl kickstart -k gui/$(id -u)/com.gu-voice.tunnel   # 重啟 tunnel
```

- **環境變數真相＝`~/Services/gu-voice/.env`**（chmod 600）。值一律用單引號包起來，compose 才不會展開 `$`。PEM 的換行寫成字面 `\n`，`config.py` 會自己還原。
- 常用資料表：`users`、`patients`、`sessions`、`conversations`（月分區）、`soap_reports`、`red_flag_alerts`、`audit_logs`（月分區）。分區由 `partition_manager` 在啟動時和排程中自動補建。
- 改使用者角色：`docker compose exec db psql -U gu -d gu_voice -c "update users set role='doctor' where email='…'"`。
- 還原備份：`docker compose exec -T db pg_restore -U gu -d gu_voice --clean --no-owner < backups/<檔>.dump`
- 主機停電或重開機：Docker Desktop 由 `com.drugpilot.mac-mini.docker` 開機啟動，容器設了 `restart: unless-stopped`，tunnel 由 launchd 的 KeepAlive 維持。開機後跑一次 healthz 確認即可。

### 常見問題

| 症狀 | 查法 |
|------|------|
| App／網頁連不上 | 先打 `curl https://gu.zymomed.com/api/v1/healthz/deep`。打不到就看 tunnel log 和 `launchctl list \| grep gu-voice`；回 502 就看 `docker compose ps` |
| SOAP 一直卡在 GENERATING | Celery worker 掛了。看 `docker compose logs backend \| grep -i celery`，再 `docker compose restart backend` |
| 收不到推播 | 見 [push_troubleshooting.md](push_troubleshooting.md) |
| 全院同時被登入限流鎖住 | nginx 的 XFF 設定被改壞了（見上面「client IP」） |

### 已知限制

- 單機、單點：Mac、Docker 或網路任一個掛掉，Kiosk 就不能問診。
- 備份只存在本機硬碟。病歷資料應該再加一份異地複本，例如加密外接碟。

---

## 四、本地開發啟動

```bash
# 後端
cd backend && source venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

# 前端（另開一個 terminal）
cd frontend && npm run dev -- --host 127.0.0.1 --port 3000
```

本地前端會讀 `frontend/.env`（指向 `localhost:8000`），不影響正式環境。全端可用 repo 根的 `docker compose up -d`（開發用，見上面的 ⚠️）。

---

## 五、GitHub Repo

`https://github.com/jht12020304/gu-voice`（**公開**：任何主機設定、金鑰、Key ID 都不得入庫）。`main` 不會自動部署，上線一律跑 `deploy.sh`。
