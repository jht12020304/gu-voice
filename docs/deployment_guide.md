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

`ios_native/Config/Production.xcconfig` 設定 Release 的 `API_BASE`、`WS_BASE`、`WEB_BASE`，皆指向 `gu.zymomed.com`。2026-11-15 之前的所有 TestFlight build 連的是已刪除的 Railway，**都已經不能用**。

---

## 二、原生 iOS TestFlight 發佈

iOS App 供病患 kiosk、醫師與管理員使用。測試裝置需有 iOS 17 或更新版本。正式測試群組只限獲授權的院內人員，驗收使用合成資料。醫師及臨床 admin 只能讀獲指派的場次，system admin 保有全院稽核權限。舊未指派場次仍受後端相容規則約束。內部測試旗標限制散佈，資料存取由後端授權。

1. 核對 [簽章與能力設定](ios_release_settings.md#4-建置設定)。從乾淨的最新 `origin/main` 執行 `ios_native/tool/build_ios_testflight.sh`。它唯讀查詢 ASC build 號，再 archive、匯出並驗證。
2. 開啟 `ios_native/build/testflight/<build>/verify.log`。由發佈人核對簽章、旗標、三個正式端點、五語、Firebase 和 SHA-256。可在本機重跑 `ios_native/tool/build_ios_testflight.sh --verify-only "$IPA" "$BUILD"`。
3. 依 [原生發佈設定](ios_release_settings.md#61-原生-ios-發佈) 對同一顆 SHA-256 的 IPA 手動執行 Apple validate 和 upload。
4. 確認 build 顯示「內部」。先於授權群組按 [實機驗收清單](../ios_native/README.md#發佈前的實機驗收) 檢查（推播排錯見 [診斷手冊](push_troubleshooting.md)），再由發佈人決定指派至「先行測試」。
5. 回裝、到期與重建見 [iOS 回滾手冊](runbook/ios_rollback.md)。

### 舊版發佈紀錄

舊版簽章、上傳與 2026-09-02 推播實測步驟保留在 [當時的操作手冊](https://github.com/jht12020304/gu-voice/blob/27c10238e4aebc62920bdd83fd00f46cd6a4557f/docs/deployment_guide.md#推播上機驗證2026-09-02-已通過換裝置時照這個順序重驗)。

#### ✅ 2026-08-21 首次上傳完成——Apple 側現況

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
