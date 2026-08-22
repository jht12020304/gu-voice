# GU-Voice 部署與設定操作手冊

本文件說明如何修改 Railway、Vercel、Supabase 的設定，並成功部署到正式環境。

---

## 目前正式環境網址

| 服務 | 網址 |
|------|------|
| **正式前端／React** (Vercel) | `https://gu-voice-chuns-projects-068de742.vercel.app` |
| **Flutter Web staged preview** | `https://gu-voice-flutter-preview.vercel.app`（未通過實體語音驗證前不得 promote） |
| **後端 API** (Railway) | `https://gu-voice-app-production.up.railway.app` |
| **健康檢查** | `https://gu-voice-app-production.up.railway.app/api/v1/health` |
| **Supabase 資料庫** | 專案 `gu-voice-prod`，ref `xobxnlvtilezridrekdm`（region ap-southeast-1）；DB 連線 host `aws-1-ap-southeast-1.pooler.supabase.com`、**port 5432 session-mode**。⚠️ 舊 ref `udydlelmkusyjmegtviq`／`nydhmqtogqlwhuuolzos` 已過期，真相以 Railway `DATABASE_URL` 為準，故障排除見 `supabase_connection_guide.md` §5 |

---

## 一、部署流程（最重要）

> ⚠️ **2026-07-26 更正：部署是手動的。merge 到 `main` 不會讓任何東西上線。**
> Railway 與 Vercel 的 GitHub App 裝在 repo 上，但它們的 check suite 在**每一次** main merge 都永遠停在 `queued`（對 #29／#30／#31／#32 逐一查證），從不收斂成部署；Railway 每一筆歷史部署的 `meta.cliCaller` 都是手動 CLI。
> 過去文件寫的「已接上自動部署」是錯的判斷——那些「已部署生產」之所以成立，是因為當天有人手動補跑 `railway up`。
> 自己查證：`gh api repos/jht12020304/gu-voice/commits/<sha>/check-suites`

**程式碼上線 = merge 到 main，然後手動部署兩邊。**

```bash
# 1. 程式碼進 main（PR merge 或 push）
git push origin main

# 2. 後端 → Railway
#    ⚠️ 不可以直接在 repo 裡跑 railway up：CLI 5.41.2 起會上傳整個 git root（在 backend/ 裡跑也一樣），
#    Railpack 看到 monorepo 就 FAILED（2026-08-20 實測；帶路徑參數 `railway up <path>` 也會 `prefix not found`）。
#    正確做法＝把 backend/ 的「已 commit 內容」匯出到非 git 目錄再 up：
DEPLOY_DIR=$(mktemp -d)
git archive HEAD:backend | tar -x -C "$DEPLOY_DIR"
cd "$DEPLOY_DIR"
railway link -p gu-voice-api -s gu-voice-app -e production
railway up --detach
curl https://gu-voice-app-production.up.railway.app/api/v1/healthz/deep   # 期待 {"status":"ok",...}
#    ⚠️ healthz 綠**不代表新碼上線**（舊容器還活著時它照樣綠）。要證明流量已切到新版，
#    打 openapi 找這次新增的欄位／端點：
#    ⚠️ 2026-08-22 起 `/openapi.json` 在正式環境**要帶 token**（`/docs`、`/redoc` 直接關掉）。
#    先取出 Railway 上的 METRICS_TOKEN，再帶 `Authorization: Bearer`：
#      TOKEN=$(railway variables --service gu-voice-app --kv | sed -n 's/^METRICS_TOKEN=//p')
#    沒帶或帶錯一律回 **404**（刻意不回 401，避免對掃描者確認端點存在）。
#    ⚠️ 這代表 **METRICS_TOKEN 必須在部署這版之前就設好**，否則第一次部署完就沒有工具驗它。
curl -s -H "Authorization: Bearer $TOKEN" \
  https://gu-voice-app-production.up.railway.app/openapi.json | python3 -c \
  "import json,sys; d=json.load(sys.stdin); print('<本次新增的欄位名>' in json.dumps(d))"
#    ⚠️ 自動化時**不要**用 `... | grep -c 欄位 || echo 0` 判斷：grep 沒命中會「印 0 **且** 回傳非零」，
#    `|| echo 0` 於是再追加一個 0，變數變成 "0\n0" ≠ "0" → 判成「有命中」。2026-08-20 用這種寫法
#    的監看誤報「新碼已上線」，實際上生產仍跑舊碼。判定一律交給 python（解析失敗要當 unknown，不是 true）。
#    部署卡在 DEPLOYING 時：先看新容器 log 有沒有「Application startup complete」（有＝碼沒問題），
#    再查 status.railway.com 是否有平台事故——事故期間不要重送 railway up。

# 3a. 現行 React 前端 → Vercel（專案 gu-voice，個人 team chuns-projects-068de742）
cd frontend && npm run build && vercel --prod
#    ⚠️ 正式網址 gu-voice-chuns-projects-068de742.vercel.app 的 alias 不會隨 --prod 自動移動
#    （會釘在舊 deployment；gu-voice.vercel.app 才會自動跟上），要手動補：
vercel alias set <新deployment網址> gu-voice-chuns-projects-068de742.vercel.app

# 3b. Flutter Web staged build/deploy 見 docs/flutter_web_cutover.md

# 3c. iOS TestFlight（Flutter 醫師端）→ 見下方「二、iOS TestFlight 發佈」
```

> **前端唯一活的網址＝`https://gu-voice-chuns-projects-068de742.vercel.app`**（2026-07-26 釐清＋切換）
>
> - Vercel 專案 `gu-voice`，個人 team `chuns-projects-068de742`。2026-07-26 建立並端到端驗證通過
>   （登入 → dashboard 解析出使用者 → /research 撈到真實生產資料）。
> - **舊網址已停用**：`project-9w0vq.vercel.app` 與 `gu-voice-jht12020304y-7696s-projects.vercel.app`
>   （同一 deployment 的兩個 alias）在**已停用的舊 Vercel 帳號** scope 下，現帳號完全進不去
>   （dashboard 404、`vercel inspect` 找不到），**無法再部署**；且 2026-07-26 已從
>   Railway `CORS_ORIGINS` 移除 → **那兩個網址現在打不到 API，開了會登入失敗**。
>   HTML 還是會載出來（Vercel 仍在服務靜態檔），所以症狀是「頁面正常但登入沒反應」。
> - ⚠️ **kiosk 裝置的書籤／首頁必須改指新網址**，否則現場無法問診。
> - ⚠️ `FRONTEND_BASE_URL` 仍指舊網址（影響重設密碼信的連結），待改。
> - 移除舊 origin 前先確認沒有 `in_progress` 場次（`select status, count(*) from sessions group by status`），
>   否則會把正在問診的病患打斷。回滾＝把舊 origin 加回 `CORS_ORIGINS`（env 改動約 1 分鐘 redeploy）。
>
> 新 clone 第一次要先 link（`.vercel/` 不入庫）：
> ```bash
> cd frontend && vercel link --yes --project gu-voice
> ```

> ⚠️ **Deployment Protection 會讓新專案回 302 到 `vercel.com/sso-api`**（不是 401）。
> dashboard 是 Settings → Deployment Protection → Vercel Authentication → Disabled；
> 無法開 dashboard 時用 API（token 讀 CLI 自己的 auth 檔，勿印出來）：
> ```bash
> python3 -c "
> import json,os,urllib.request
> tok=json.load(open(os.path.expanduser('~/Library/Application Support/com.vercel.cli/auth.json')))['token']
> pj=json.load(open('.vercel/project.json'))
> r=urllib.request.Request(f\"https://api.vercel.com/v9/projects/{pj['projectId']}?teamId={pj['orgId']}\",
>   data=json.dumps({'ssoProtection':None}).encode(), method='PATCH',
>   headers={'Authorization':f'Bearer {tok}','Content-Type':'application/json'})
> print(json.load(urllib.request.urlopen(r))['ssoProtection'])"
> ```

- **Railway** 用 Docker build（`RAILWAY_DOCKERFILE_PATH=Dockerfile`，Dockerfile 在 `backend/`）。⚠️ **CLI 5.41.2 起 `railway up` 一律上傳 git root，cwd 與 link 位置都救不了**（舊版文件寫「從 backend/ 跑」「link 綁目錄」皆已失效）——只能用上面的 `git archive` 匯出法。失敗徵兆：build log 出現 `Railpack could not determine how to build the app`，且舊容器仍 Active——**healthz 綠不代表新碼上線**，要看 dashboard 最新 deployment 是否 Active 且時間吻合。
- **Vercel** 正確 team 是個人 team **`chuns-projects-068de742`**；舊 `jht12020304y-7696s-projects` 已停用，勿再切換過去。
- 只改環境變數（不改程式碼）時**不需重新 build**：Railway 會用既有 image 觸發 redeploy（約 1 分鐘）。
- 事故復原時用 `railway up` 而非 `railway redeploy`——後者實測不會真的換容器（見 `supabase_connection_guide.md` §5a）。

> ⚠️ 特別注意：如果修改了 `backend/scripts/start.sh`，每次編輯後都必須重新設定執行權限，否則 Railway 部署會失敗：
> ```bash
> git update-index --chmod=+x backend/scripts/start.sh
> git add backend/scripts/start.sh
> git commit -m "restore executable bit on start.sh"
> git push origin main
> ```

---

## 二、iOS TestFlight 發佈（2026-08-22 起：完整 App，含病患語音問診）

> ⚠️ 2026-08-22 平台分工推翻：iOS 不再是「醫師端」，是唯一的 App——kiosk iPad 跑
> 病患語音問診、醫師/管理員同一顆。所以**從這一天之後的 build 起，裝了 App 的
> 測試員都能進到病患問診入口**；加測試員前的 PHI 檢查（§V8）比以前更要緊。
> kiosk iPad 部署方式：用櫃檯發的 patient 帳號登入即可，閒置登出 180 秒自動生效，
> 不需要特別的 kiosk build。

> 平台分工（2026-08-20 拍板）：**Web＝病患語音問診 kiosk，iOS＝醫師端查看報告與通知**。
> iOS 這條線只走 TestFlight **內部測試**，不上架。管道現況與未解風險見 `docs/TODO.md` §V8（iOS 醫師端功能面見 §V7）。

> ⚠️⚠️ **內測包打的是生產後端，本專案沒有 staging**（本手冊只有 production 一組）。
> 唯一會打到測試者手機的是**「SOAP 報告已生成」通知**：body 帶**真實病患姓名**，而且在
> `sessions.doctor_id IS NULL`（實測全院都是）時**fan-out 給全體在職醫師**；「報告生成失敗」
> 同樣帶姓名同樣 fan-out。iOS 上刪病患／停用帳號／重設密碼的 API 也可達。
> **拍板：第一版只裝自己一台。**
>
> ⚠️ **遮蔽推播文案不會降低 PHI 暴露**——測試者拿的是真實醫師帳號，登進去就能讀到全部病患姓名
> 與完整 SOAP 報告（後端沒有 tenant／scope 隔離）。**加第 2 個測試人員之前**要走的兩條路與估時、
> 以及逐條佐證（含 file:line、含目前休眠但會自動解封的紅旗推播）**一律見 `docs/TODO.md` §V8**——
> 那裡是唯一持有這組行號的地方，本手冊刻意不抄。

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
   ⚠️ **本 repo 目前沒有任何隱私政策頁面**。要在 Vercel 站上加一頁 `/privacy`，至少涵蓋：
   語音錄音的蒐集與**保存期限**、病患姓名與主訴的處理、**推播內容含哪些個資**、
   以及資料流向（Firebase／Railway／Supabase）。這是一件要寫、要有人核可的事，不是填個網址。
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
4. ⚠️ 依現行拍板，**第一版只加使用者自己**；`docs/TODO.md` §V8 的前置條件補完前不要加第 2 個人。
   **這個結論沒有因為旗標被證實有效而放寬一分。**
   ✅ `ExportOptions.plist` 的 `testFlightInternalTestingOnly=true` **確實有生效**——2026-08-21
   上傳的那顆 build 在 TestFlight 清單上標著「內部」（詳見上一節的 ⓘ 框）。
   🛑 **但它擋的是「散佈」，不是「資料」**：它讓這顆包不能拿去做 external TestFlight／上架，
   **對任何一個被加進 internal 群組的人完全沒有作用**——那個人拿的是真實醫師帳號，
   登進去就讀得到全部真實病患姓名與完整 SOAP 報告（後端沒有 tenant／scope 隔離）。
   ⇒ **它不是 PHI 護欄。擋 PHI 的仍然只有「第一版只裝自己一台」這個人為拍板**，
   加第 2 個人之前一定要走完 `docs/TODO.md` §V8 的前置條件。「旗標有效」≠「PHI 有護欄」。

### 第一次上機驗證推播（沒人做過，照這個順序走）

「裝上去打得開」不等於「推播會到」。這條線上有四個獨立的斷點，任何一個沒過，
症狀都是**手機一片安靜、後端 log 一切正常**：

1. **生產 Railway 的 `FCM_CREDENTIALS_JSON` 要有值。**
   沒設時 `backend/app/core/firebase.py:39` 只 `logger.warning`、**API 照常起**，
   推播全部靜默。查法：`railway variables list` 看有沒有這個變數（**不要把值印出來**）。
2. **`RUN_CELERY_IN_API` 要是 `true`。**
   推播是丟給 Celery 的（`notification_service.py:712` 的 `send_push_notification_task.delay()`），
   **worker 沒跑＝任務沒人消費，而錯誤會被吞掉**。啟動 log 裡要看得到 celery banner。
3. **生產 DB 要有一個能登入的 doctor／admin 帳號。**
   公開註冊一律降級成 `PATIENT`（`auth_service.py:234` 的 AUTH-3），而**病患帳號在 iOS 上會被導到
   `/patient-unsupported`**——拿病患帳號裝上去，整個 App 只看得到一頁「不支援」。
   沒有醫師帳號就照「五、Supabase」用 SQL 改一個既有帳號的 `role`。
4. **怎麼觸發第一則推播**：唯一會打到手機的是 **report_ready 的 fan-out**，
   所以**必須有人在 Web kiosk 真的跑完一場問診並產出 SOAP 報告**，光登入 App 不會有任何推播。
   ✅ **建議用一個名字明顯是假的病患跑這一場**（例如「測試 勿用」）——這樣第一則推播的鎖定畫面上
   就是假名，**同時解決「要驗證」與「不要把真實 PHI 推到手機上」兩個需求**。

**怎麼確認 FCM token 真的註冊成功**：`push_service.dart` 的**所有失敗路徑都只有 `debugPrint`**，
TestFlight build 上看不到任何輸出。**唯一可靠的驗法是查 DB 的 `fcm_devices` 表**有沒有這台裝置的 token：

```sql
SELECT user_id, platform, created_at, updated_at FROM fcm_devices ORDER BY updated_at DESC LIMIT 5;
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

## 三、Railway — 後端設定

### 修改環境變數（最常用）

**方法一：Raiway Dashboard（推薦）**

1. 登入 [railway.app](https://railway.app)
2. 選擇專案 `gu-voice-api`
3. 點擊服務 `gu-voice-app`
4. 上方 tab 選 **Variables**
5. 找到要改的變數，直接點擊修改
6. 儲存後 Railway 會用**既有 image 觸發 redeploy**（約 1 分鐘，免重新 build）

**方法二：Railway CLI（Terminal）**

```bash
# 先確認連結到正確的專案（第一次使用才需要）
railway link --project gu-voice-api
railway service gu-voice-app

# 查看所有環境變數
railway variables list

# 修改單一變數
railway variables set 變數名稱='新的值'

# 例如更新 CORS
railway variable set CORS_ORIGINS='["https://gu-voice-chuns-projects-068de742.vercel.app","https://gu-voice-flutter-preview.vercel.app","http://localhost:5175"]'
```

### 重要環境變數說明

| 變數 | 用途 | 注意事項 |
|------|------|----------|
| `CORS_ORIGINS` | 允許的前端網域（JSON 陣列） | **必須包含 Vercel 的完整網址**，否則瀏覽器會擋住 |
| `DB_HOST` | Supabase 資料庫主機 | 不要改，改了會連不到 DB |
| `OPENAI_API_KEY` | OpenAI API 金鑰 | 若過期或額度不足，問診功能會失效 |
| `JWT_SECRET_KEY` | JWT 簽名密鑰 | 改了會讓所有人的 token 失效（需重新登入） |
| `REDIS_URL` | Redis 連線（快取/BlackList） | 改了 logout/token 黑名單會失效 |
| `LOG_LEVEL` | 日誌等級 | 設定為 `INFO`（大寫）即可，腳本會自動轉小寫 |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | DB 連線池大小 | 用 session-mode pooler 時連線數有限，設 `5` / `5` |

> ⚠️ **Gotcha 1：`CORS_ORIGINS` 的格式**
> pydantic-settings v2 對 `list[str]` 欄位會在 source 層先 `json.loads()`。目前 code（`app/core/config.py`）已對 `CORS_ORIGINS` 與 `MULTILANG_DISABLED_LANGUAGES` 加上 `Annotated[list[str], NoDecode]`，讓 `field_validator` 接到原始字串、**「逗號分隔字串」與「JSON 陣列」兩種格式都能接受**。
> 但若部署的是**舊 code**，把 `CORS_ORIGINS` 注入逗號分隔字串（如 `https://a.com,https://b.com`）會 `SettingsError` → 容器一啟動就 crash → healthcheck 永遠失敗 → Railway 顯示 offline。保險起見統一用合法 **JSON 陣列**。

> ⚠️ **Gotcha 2：Supabase pooler 模式（務必用 session-mode，port 5432）**
> 常駐的 Railway 容器要用 **session-mode pooler（port `5432`）**，不要用 transaction-mode（`6543`）。6543 的 PgBouncer 會讓 asyncpg 的 JSONB codec 型別 introspection 用的 prepared statement 跨 backend 失效，造成特定端點 500（錯誤訊息：`prepared statement "__asyncpg_stmt_*__" does not exist`）。session-mode 每個 client 連線對應專屬 backend，prepared statement 才會持久。
> code（`app/core/database.py`）已修：`_is_supabase` 改從 `ASYNC_DATABASE_URL` 解析 host 來偵測；先前只看 `settings.DB_HOST`，但以完整 `DATABASE_URL` 注入時 `DB_HOST` 仍是預設 `localhost` → mitigation 全失效。

### 查看後端 Log

```bash
railway logs
```

或在 Railway Dashboard → 服務 → **Logs** tab。

---

## 四、Vercel — 前端設定

### 修改環境變數

1. 登入 [vercel.com](https://vercel.com)
2. team 選 `chuns-projects-068de742`（chun's projects）
   > 舊文件寫的 `jht12020304y-7696s-projects` 是**已停用帳號**下的 scope，現帳號進不去（404）。
   > kiosk 現在還是開那份舊部署，但無法再對它部署——見「一、部署流程」的說明。
3. 選擇專案 `gu-voice`
4. 左側選 **Settings** → **Environment Variables**
5. 修改後點 **Save**
6. 回到 **Deployments**，點選最新的部署 → **Redeploy**（環境變數不會自動重新部署）

### 重要環境變數說明

| 變數 | 目前值 | 用途 |
|------|--------|------|
| `VITE_API_BASE_URL` | `https://gu-voice-app-production.up.railway.app/api/v1` | 前端呼叫後端 API 的網址 |
| `VITE_WS_BASE_URL` | `wss://gu-voice-app-production.up.railway.app/api/v1/ws` | WebSocket 連線網址 |
| `VITE_SUPABASE_URL` | `https://xobxnlvtilezridrekdm.supabase.co` | Supabase 連線（舊 ref `udydlelmkusyjmegtviq` 已過期） |
| `VITE_SUPABASE_ANON_KEY` | `eyJhbGci...` | Supabase 公開金鑰 |

> ⚠️ 如果 Railway 的 API 網址改了，記得同步更新 `VITE_API_BASE_URL` 和 `VITE_WS_BASE_URL`。
>
> ℹ️ `VITE_API_BASE_URL` / `VITE_WS_BASE_URL` 以 **Vercel dashboard 的環境變數**為準，會**覆寫 repo 內的 `frontend/.env.production`**；要改正式環境請在 Vercel dashboard 改，並 Redeploy。

### Deployment Protection（重要）

Vercel 預設會開啟 Deployment Protection，讓網站只有登入 Vercel 的人才能訪問。若不小心開啟，網站會變成 401：

1. Vercel Dashboard → `gu-voice` 專案 → **Settings**
2. 找到 **Deployment Protection**
3. 確認 **Vercel Authentication** 是 **Disabled**

---

## 五、Supabase — 資料庫

### 查看資料

1. 登入 [supabase.com](https://supabase.com)
2. 選擇專案 `gu-voice-prod`（ref `xobxnlvtilezridrekdm`）
3. 左側 **Table Editor** → 選擇資料表（如 `users`、`sessions`）

### 常用資料表

| 資料表 | 說明 |
|--------|------|
| `users` | 所有使用者（病患、醫師、管理員） |
| `sessions` | 問診場次紀錄 |
| `messages` | 問診對話內容 |
| `soap_reports` | SOAP 病歷報告 |

### 新增/修改使用者（直接操作 DB）

在 Supabase **SQL Editor** 執行：

```sql
-- 查詢所有 admin 帳號
SELECT id, email, name, role, is_active, created_at FROM users WHERE role = 'ADMIN';

-- 停用某個帳號
UPDATE users SET is_active = false WHERE email = 'someone@example.com';

-- 刪除測試帳號
DELETE FROM users WHERE email = 'test_probe_delete@gu-voice.com';
```

> ⚠️ 直接操作資料庫要謹慎，建議先備份或在 SQL Editor 用 `SELECT` 確認再執行 `UPDATE`/`DELETE`。

---

## 六、常見問題排查

### 問題：前端顯示「登入失敗」或網路錯誤

**原因最可能是 CORS 設定錯誤。**

確認步驟：
1. 打開瀏覽器開發者工具（F12）→ **Network** tab
2. 點登入，找到失敗的請求
3. 如果看到 `CORS error` 或 `Access-Control-Allow-Origin` 缺少，就是 CORS 問題

修復：
```bash
railway variable set 'CORS_ORIGINS=["https://gu-voice-chuns-projects-068de742.vercel.app","https://gu-voice-flutter-preview.vercel.app","http://localhost:5175"]'
```

---

### 問題：Railway 部署失敗 — "We don't have permission to execute your start command"

`start.sh` 缺少執行權限（每次用編輯器修改這個檔案後就會發生）：

```bash
git update-index --chmod=+x backend/scripts/start.sh
git add backend/scripts/start.sh
git commit -m "fix: restore executable bit on start.sh"
git push origin main
```

---

### 問題：Railway 部署失敗 — uvicorn log-level 錯誤

已修復（`start.sh` 會自動把 LOG_LEVEL 轉小寫）。若再次出現，確認 `start.sh` 第 43 行是：
```bash
LOG_LEVEL="$(echo "${LOG_LEVEL:-info}" | tr '[:upper:]' '[:lower:]')"
```

---

### 問題：Vercel build 失敗 — TypeScript 錯誤

查看 Vercel Dashboard → Deployments → 失敗的部署 → **Build Logs**，找到錯誤行數，修復後 push 即可。

---

### 問題：後端健康檢查失敗

```bash
# 直接查看 Railway log
railway logs | tail -50
```

常見原因：
- 資料庫連線失敗（Supabase 暫時不可用）
- 環境變數缺少或錯誤
- Python 套件安裝失敗（查看 build log）

---

## 七、本地開發啟動

```bash
# 後端
cd backend
source venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

# 前端（另開一個 terminal）
cd frontend
npm run dev -- --host 127.0.0.1 --port 3000
```

本地前端會使用 `frontend/.env`（指向 `localhost:8000`），不影響正式環境。

---

## 八、GitHub Repo

所有程式碼：`https://github.com/jht12020304/gu-voice`

- `main` branch → 直接部署到正式環境
- 建議：重大修改先開新 branch 測試，確認沒問題再 merge 到 main
