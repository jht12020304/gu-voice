---
name: deploy-production
description: GU Voice 生產部署（手動 railway up + vercel --prod，merge main 不會自動上線）與生產環境除錯守則（DB 連線、pooler、環境變數真相）。Use when 部署到生產、修改部署設定檔（railway.toml/vercel.json/Dockerfile/start.sh）、除錯生產 DB timeout 或連線問題、或驗證上線結果時。
---

# 生產部署與環境除錯

## Overview

**部署是手動兩步，merge 到 main 不會上線**——外加幾個一踩就炸的雷（start.sh 執行位、Vercel team 走錯、pooler idle、過期的 DB ref 文件）。本 skill 收斂部署動作與除錯順序；操作細節見 [docs/AGENTS.md](../../../docs/AGENTS.md) 與 [docs/supabase_connection_guide.md](../../../docs/supabase_connection_guide.md)。

## When to Use

- 要把 main 上的程式碼送上生產、或驗證部署結果
- 改 `backend/railway.toml`、`frontend/vercel.json`、兩邊 Dockerfile、`backend/scripts/start.sh`
- 生產 DB timeout / 連線 / cookie / CORS 問題
- NOT for：本機 docker compose 問題

## 生產環境真相（優先於任何 docs 內舊資訊）

- 生產 DB = Supabase 專案 **gu-voice-prod**，ref `xobxnlvtilezridrekdm`，ap-southeast-1，port 5432 session mode
- **環境變數真相 = Railway 的 `DATABASE_URL`**。docs 裡的舊 ref（udydl…）、.env 裡的舊 ref（nydhm…）都已過期，看到不符就是文件舊了，不是設定壞了
- 連線池：pool 2 + max_overflow 1（pooler idle 連線曾佔滿額度；直連 IPv4 add-on 已停用，無法靠直連清 idle）
- `COOKIE_SAMESITE` 必須 `lax`（跨站 refresh 雙路徑修復的一部分）
- backend 啟動腳本會自動跑 alembic migrate + 補建月分區（`ensure_partitions_on_startup`）
- ⚠️ **celery worker service 必須在跑**：2026-07-19 起 SOAP 生成改「建 GENERATING row → 派 Celery 任務」單一路徑，worker 掛掉 → 報告停在 GENERATING 出不來（不會像舊 inline 版無聲消失，但一樣看不到報告）。部署後除了 API/beat，確認 worker service 也 healthy

## 部署流程

> ⚠️ **merge 到 main 不會部署任何東西。** Railway 與 Vercel 的 GitHub App 裝在 repo 上，但它們的 check suite 在每一次 main merge 都永遠停在 `queued`、從不收斂（2026-07-26 對 #29/#30/#31/#32 逐一查證），Railway 每筆歷史部署的 `meta.cliCaller` 都是手動 CLI。舊文件寫「全自動」是錯的判斷；過去那些「已部署生產」成立是因為當天有人手動補跑。查證法：`gh api repos/jht12020304/gu-voice/commits/<sha>/check-suites`。

1. 程式碼先進 main（PR merge）
2. 若改了 `backend/scripts/start.sh`：`git update-index --chmod=+x backend/scripts/start.sh`，否則 Railway 起不來
3. 後端：`cd backend && railway up --detach --service gu-voice-app`（Dockerfile 在 `backend/`，cwd 錯會失敗；非互動 link 要在 repo 根目錄跑 `railway link -p gu-voice-api -s gu-voice-app -e production`）
4. 前端：`cd frontend && npm run build && vercel --prod`（專案 `gu-voice`，個人 team `chuns-projects-068de742`；新 clone 先 `vercel link --yes --project gu-voice`，`.vercel/` 不入庫）。
   ⚠️ **前端有兩份**：kiosk 現在開的是**已停用帳號** scope 下的 `project-9w0vq` / `gu-voice-jht12020304y-7696s-projects`（進不去、無法再部署）；現帳號重建的是 `gu-voice-chuns-projects-068de742.vercel.app`（2026-07-26 端到端驗證過）。三個 origin 都在 CORS 白名單，**切換 kiosk 與 `FRONTEND_BASE_URL` 待拍板**。
   ⚠️ 新 Vercel 專案預設開 Deployment Protection → 全站 **302 到 `vercel.com/sso-api`**（不是 401）。關法見 `docs/deployment_guide.md` 一、（dashboard 或 API PATCH `ssoProtection:null`）
   ⚠️ **絕不要在 `frontend/` 直接 `vercel --prod --yes` 而不指定專案**——目錄名 `frontend` 會撞到個人 team 既有的 `frontend` 專案（那是 AI_Investing），等於拿病歷系統覆蓋掉別的線上專案
5. 驗證：`curl https://gu-voice-app-production.up.railway.app/api/v1/healthz/deep` 回 `{"status":"ok"}` + Railway 部署 log。事故復原用 `railway up` 不要用 `railway redeploy`（實測後者不換容器）

## 生產 DB 除錯順序

1. **先查 Supabase 平台事故**（status page）——事故期間不要重啟專案、不要動連線設定，等平台恢復
2. 再走 [docs/supabase_connection_guide.md](../../../docs/supabase_connection_guide.md) §5 runbook
3. 懷疑連線字串時，以 Railway `DATABASE_URL` 為準比對，不要信本機 .env 或 docs

## Common Rationalizations

| 藉口 | 現實 |
|---|---|
| 「PR merge 進 main 了，所以已經上線」 | 沒有。要跑 `railway up` + `vercel --prod`。main 與生產可以差好幾週（2026-07-26 發現生產跑的是 07-06 的 build） |
| 「TODO/文件說 celery worker service 已 ACTIVE，所以 SOAP 沒問題」 | 那條記載曾是假的（2026-07-26 實查兩個 service 都不存在，SOAP 全卡 GENERATING）。現行做法＝同容器起 worker+beat（`RUN_CELERY_IN_API`）；部署後一律用 log 確認 `celery@... ready.` 與 `beat: Starting...` |
| 「CI 綠了就等於部署成功」 | GitHub Actions 只跑測試；`railway-app`／`vercel` 的 check suite 永遠停在 `queued`，那不是部署 |
| 「DB timeout，先重啟 Supabase 專案試試」 | 多次事故根因是 Supabase 平台端；事故期間重啟只會延長不可用 |
| 「docs 寫的 DB ref 跟 Railway 不一樣，改 Railway 對齊 docs」 | 方向反了：Railway 是真相，docs 是過期的 |
| 「pool 開大一點就不會 timeout」 | pooler 額度曾被 idle 連線佔滿，2+1 是刻意壓低的，加大會復發 |

## Verification

- [ ] health endpoint 回 200
- [ ] `railway up` 與 `vercel --prod` **都真的跑過**（沒跑就是沒上線，不論 main 上有什麼）
- [ ] Vercel 與 Railway build log 無錯、rollout 完成
- [ ] 若動了 migration：Railway 啟動 log 顯示 alembic 升級成功
- [ ] `railway logs` 看到 `celery@... ready.` 與 `beat: Starting...`（SOAP 生成是 Celery 單一路徑，worker 沒起＝報告永遠卡 GENERATING）
- [ ] 真功能驗收而非只看 health：`POST /auth/login` 拿到 token → `GET /auth/me` 200 → `GET /research/analytics` 200
