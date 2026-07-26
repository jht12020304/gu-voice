---
name: deploy-production
description: GU Voice 生產部署（git push 自動部署到 Vercel + Railway + Supabase）與生產環境除錯守則（DB 連線、pooler、環境變數真相）。Use when 部署到生產、修改部署設定檔（railway.toml/vercel.json/Dockerfile/start.sh）、除錯生產 DB timeout 或連線問題、或驗證上線結果時。
---

# 生產部署與環境除錯

## Overview

部署是 GitHub 觸發的全自動流程，但有幾個一踩就炸的雷（start.sh 執行位、pooler idle、過期的 DB ref 文件）。本 skill 收斂部署動作與除錯順序；操作細節見 [docs/AGENTS.md](../../../docs/AGENTS.md) 與 [docs/supabase_connection_guide.md](../../../docs/supabase_connection_guide.md)。

## When to Use

- push 到 main 觸發生產部署、或驗證部署結果
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

1. commit 後 `git push origin main` → Vercel 建 frontend、Railway 建 backend，無手動步驟
2. 若改了 `backend/scripts/start.sh`：push 前 `git update-index --chmod=+x backend/scripts/start.sh`，否則 Railway 起不來
3. 驗證：`curl https://gu-voice-app-production.up.railway.app/api/v1/health` + Vercel/Railway dashboard build log

## 生產 DB 除錯順序

1. **先查 Supabase 平台事故**（status page）——事故期間不要重啟專案、不要動連線設定，等平台恢復
2. 再走 [docs/supabase_connection_guide.md](../../../docs/supabase_connection_guide.md) §5 runbook
3. 懷疑連線字串時，以 Railway `DATABASE_URL` 為準比對，不要信本機 .env 或 docs

## Common Rationalizations

| 藉口 | 現實 |
|---|---|
| 「DB timeout，先重啟 Supabase 專案試試」 | 多次事故根因是 Supabase 平台端；事故期間重啟只會延長不可用 |
| 「docs 寫的 DB ref 跟 Railway 不一樣，改 Railway 對齊 docs」 | 方向反了：Railway 是真相，docs 是過期的 |
| 「pool 開大一點就不會 timeout」 | pooler 額度曾被 idle 連線佔滿，2+1 是刻意壓低的，加大會復發 |

## Verification

- [ ] health endpoint 回 200
- [ ] Vercel 與 Railway build log 無錯、rollout 完成
- [ ] 若動了 migration：Railway 啟動 log 顯示 alembic 升級成功
