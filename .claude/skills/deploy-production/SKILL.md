---
name: deploy-production
description: GU Voice 生產部署（2026-11-15 起自架在 Mac：~/Services/gu-voice/deploy.sh，Cloudflare Tunnel gu.zymomed.com）與生產除錯。Use when 部署到生產、改 Dockerfile/start.sh/nginx、除錯生產連線或驗證上線結果時。
---

# 生產部署（自架 Mac）

- 上線：`~/Services/gu-voice/deploy.sh`（repo 須乾淨、在 main；會先備份再重建 backend/web 並驗 `https://gu.zymomed.com/api/v1/healthz/deep`）。
- 看狀態／log：`cd ~/Services/gu-voice && docker compose ps`、`docker compose logs backend --tail 200`；tunnel log 在 `~/Services/gu-voice/logs/cloudflared*.log`（launchd `com.gu-voice.tunnel`）。
- 環境變數真相＝`~/Services/gu-voice/.env`（chmod 600，不入庫）。改完 `docker compose up -d backend`。
- DB：`docker compose exec db psql -U gu -d gu_voice`；備份在 `~/Services/gu-voice/backups/`，還原指令寫在 `backup.sh` 開頭。
- iOS：`flutter_app/tool/build_ios_testflight.sh` 預設就連 gu.zymomed.com（`tool/env.production.sh`）。
- 舊的 Railway／Vercel／Supabase 流程已廢止；`docs/deployment_guide.md` 等只當歷史。
