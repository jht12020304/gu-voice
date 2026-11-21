# GU_0410 Repository Guide

This project's Baseline target is Baseline Newly available. The frontend uses Chrome Modern Web Guidance (MWG); use feature detection and `@supports` progressive enhancement with graceful fallbacks for unsupported browsers.

## Maintained clients

iOS (`ios_native/`) and React web (`frontend/`) both remain maintained and share
`backend/`. Use [README.md](README.md) for the current scope and verification commands.
Since 2026-11-08 React web is doctor report viewing only; patient consultations run in the iOS app.

## Deployment

**Since 2026-11-15 production is self-hosted on an always-on Mac. Railway and Vercel were deleted;
data moved from Supabase to a local Postgres.** The pre-move cloud guide is archived at
[archive/cloud_2026-11/AGENTS_cloud.md](archive/cloud_2026-11/AGENTS_cloud.md) (history only).

- Single public origin: `https://gu.zymomed.com` (React reports + `/api/v1` + `wss://…/api/v1/ws`)
- Path: Cloudflare Tunnel `gu-voice` (`~/.cloudflared/gu.yml`, launchd `com.gu-voice.tunnel`)
  → `127.0.0.1:8005` → nginx (`web`) → `backend:8000`
- Host config lives **outside the repo** in `~/Services/gu-voice/` (the repo is public):
  `compose.yml` (compose project `gu-voice-host`: db / redis / backend / web), `.env` (secrets,
  chmod 600), `nginx.conf`, `deploy.sh`, `backup.sh`, `README.md`

**Merging to `main` does not ship anything.** To deploy, run on that Mac:

```bash
~/Services/gu-voice/deploy.sh   # clean repo → ff main → backup → rebuild backend+web → healthz/deep
```

- Env-only change: edit `~/Services/gu-voice/.env`, then `docker compose up -d backend`.
- A green healthz does NOT prove new code is serving; check `docker compose logs backend` for a
  fresh "Application startup complete", or probe `/openapi.json` from inside the container
  (`localhost:8000`, bearer `METRICS_TOKEN`). Ops endpoints are not reachable publicly — nginx only
  forwards `/api/`, everything else is the SPA.
- Do NOT script presence checks as `... | grep -c FIELD || echo 0` (yields `"0\n0"` on no match,
  which reads as a match). Let python decide; treat a parse failure as unknown.
- The repo-root `docker-compose.yml` is the **local dev** stack (compose project `gu-voice`).
  Never point it at, or run compose commands for, production from the repo.

Never report a change as live without having run `deploy.sh` and seen the health check pass.
GitHub Actions being green means the tests passed, not that anything shipped.

## Client IP

nginx writes only `CF-Connecting-IP` into `X-Forwarded-For`; the backend (`TRUST_PROXY_HEADERS=true`)
takes the last XFF hop. Do not switch back to `$proxy_add_x_forwarded_for` — the last hop would become
the docker gateway and every user would share one IP for login rate limiting.

## Deployment Config Files

- Production stack: `~/Services/gu-voice/compose.yml` + `nginx.conf` (not in repo)
- Backend container build: [backend/Dockerfile](../backend/Dockerfile)
- Backend startup entrypoint: [backend/scripts/start.sh](../backend/scripts/start.sh) (runs alembic,
  uvicorn, Celery worker + beat in one container; keep a single backend replica)
- Frontend container build: [frontend/Dockerfile](../frontend/Dockerfile)
- iOS production URLs: [ios_native/Config/Production.xcconfig](../ios_native/Config/Production.xcconfig)
- Local full-stack orchestration: [docker-compose.yml](../docker-compose.yml)

## Local Run

```bash
docker compose up -d   # frontend :80, backend :8000, postgres :5432, redis :6379
```

## Important Caution

If [backend/scripts/start.sh](../backend/scripts/start.sh) is edited, preserve its executable bit
(`git update-index --chmod=+x backend/scripts/start.sh`), or the backend container will not start.

## Source Documents

- [docs/deployment_guide.md](deployment_guide.md) — self-host ops, iOS TestFlight release, troubleshooting
- [docs/ios_release_settings.md](ios_release_settings.md) — signing / ASC settings and current build
