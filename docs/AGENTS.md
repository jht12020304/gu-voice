# GU_0410 Repository Guide

## Deployment

**Deployment is manual. Merging to `main` does not ship anything.**

> Corrected 2026-07-26. Railway's and Vercel's GitHub Apps are installed on the repo, but their
> check suites sit at `queued` forever on every `main` merge and never trigger a deploy (verified
> across #29/#30/#31/#32); every Railway deployment in the project's history has
> `meta.cliCaller` set to a manual CLI invocation. Earlier revisions of this file claimed the flow
> was automatic — that was wrong. Past "shipped to production" claims held only because someone ran
> `railway up` by hand the same day. Verify yourself with
> `gh api repos/jht12020304/gu-voice/commits/<sha>/check-suites`.

- Frontend: `Vercel` — deploy with `vercel --prod`
- Backend: `Railway` — deploy with `railway up`
- Local integration environment: `Docker Compose`

### Production Deployment Flow

Landing code on `main` is step one of two. The deploy is a separate, deliberate action.

```bash
# 1. code onto main (PR merge, or push)
git push origin main

# 2. backend -> Railway
#    Railway CLI 5.41.2+ uploads the whole git root no matter the cwd or where you linked
#    (verified 2026-08-20; running inside backend/ still fails, and `railway up <path>` errors
#    with `prefix not found`). Export committed backend/ contents to a non-git dir first:
DEPLOY_DIR=$(mktemp -d)
git archive HEAD:backend | tar -x -C "$DEPLOY_DIR"
cd "$DEPLOY_DIR"
railway link -p gu-voice-api -s gu-voice-app -e production
railway up --detach
curl https://gu-voice-app-production.up.railway.app/api/v1/healthz/deep
#    A green healthz does NOT prove the new code is serving: it stays green while the previous
#    container is still up. Probe the OpenAPI schema for something this release added instead:
#    Since 2026-08-22 /openapi.json requires a token in production (/docs and /redoc are off).
#    Pull METRICS_TOKEN from Railway first and send it as a bearer token:
#      TOKEN=$(railway variables --service gu-voice-app --kv | sed -n 's/^METRICS_TOKEN=//p')
#    Anything missing or wrong returns 404 (deliberately not 401 — do not confirm the endpoint
#    exists to a scanner). NOTE: set METRICS_TOKEN *before* shipping this change, or the first
#    deploy leaves you with no way to verify it.
curl -s -H "Authorization: Bearer $TOKEN" \
  https://gu-voice-app-production.up.railway.app/openapi.json | python3 -c \
  "import json,sys; d=json.load(sys.stdin); print('<field added by this release>' in json.dumps(d))"
#    Do NOT script this as `... | grep -c FIELD || echo 0`: on no match grep prints "0" AND exits
#    non-zero, so `|| echo 0` appends a second "0" and the variable becomes "0\n0" != "0" — which
#    reads as a match. That exact bug made a watcher report "new code is live" while production was
#    still on the old build (2026-08-20). Let python decide; treat a parse failure as unknown.
#    Stuck in DEPLOYING? Check the new container's log for "Application startup complete"
#    (present = our code is fine), then status.railway.com for a platform incident.
#    During an incident do NOT re-run `railway up` — it only queues another stuck deployment.

# 3. React frontend -> Vercel (project lives in personal team `chuns-projects-068de742`)
cd frontend && npm run build && vercel --prod
#    The production alias gu-voice-chuns-projects-068de742.vercel.app does NOT follow --prod
#    automatically (it stays pinned to the old deployment; only gu-voice.vercel.app follows).
vercel alias set <new-deployment-url> gu-voice-chuns-projects-068de742.vercel.app
```

Flutter Web uses the same Vercel project but stays on the fixed staged alias
`https://gu-voice-flutter-preview.vercel.app` until real microphone/STT/TTS/VAD
validation passes. Build and promotion details are in `docs/flutter_web_cutover.md`.

Non-interactive Railway link: `railway link -p gu-voice-api -s gu-voice-app -e production` — run it inside the exported deploy dir as shown above. (Older guidance about running it from the repo root or from `backend/` predates CLI 5.41.2 and no longer changes what gets uploaded.)

During incident recovery use `railway up`, not `railway redeploy` — the latter was measured not to
actually replace the container.

Never report a change as live on production without having run the deploy commands above and seen
the health check pass. GitHub Actions being green means the tests passed, not that anything shipped.

## Deployment Config Files

- Frontend Vercel config: [frontend/vercel.json](/Users/chun/Desktop/GU_0410/frontend/vercel.json)
- Frontend container build: [frontend/Dockerfile](/Users/chun/Desktop/GU_0410/frontend/Dockerfile)
- Frontend reverse proxy config: [frontend/nginx.conf](/Users/chun/Desktop/GU_0410/frontend/nginx.conf)
- Backend Railway config: [backend/railway.toml](/Users/chun/Desktop/GU_0410/backend/railway.toml)
- Backend container build: [backend/Dockerfile](/Users/chun/Desktop/GU_0410/backend/Dockerfile)
- Backend startup entrypoint: [backend/scripts/start.sh](/Users/chun/Desktop/GU_0410/backend/scripts/start.sh)
- Local full-stack orchestration: [docker-compose.yml](/Users/chun/Desktop/GU_0410/docker-compose.yml)

## Local Run

Use Docker Compose when the task requires a full local stack with frontend, backend, PostgreSQL, and Redis.

```bash
docker compose up -d
```

Default local ports:

- Frontend: `http://localhost`
- Backend: `http://localhost:8000`
- PostgreSQL: `localhost:5432`
- Redis: `localhost:6379`

## Verification After Production Push

Check deployment status in:

- Vercel Dashboard for frontend build and deployment logs
- Railway Dashboard for backend build, rollout, and runtime logs

Health check endpoint:

- `https://gu-voice-app-production.up.railway.app/api/v1/health`

## Required Platform Assumptions

The following must be true for a deploy to succeed (note: none of this makes deployment automatic
— see the Deployment section above):

- Vercel is connected to the GitHub repository and points at the frontend app
- Railway is connected to the GitHub repository and points at the backend app
- Required environment variables are configured in both platforms
- Auto deploy is enabled on both platforms

## Important Caution

If [backend/scripts/start.sh](/Users/chun/Desktop/GU_0410/backend/scripts/start.sh) is edited, preserve its executable bit before pushing, or Railway deployment may fail.

```bash
git update-index --chmod=+x backend/scripts/start.sh
git add backend/scripts/start.sh
git commit -m "fix: restore executable bit on start.sh"
git push origin main
```

## Source Documents

Use these docs when more detail is needed:

- [docs/deployment_guide.md](/Users/chun/Desktop/GU_0410/docs/deployment_guide.md) — env 變數 / Railway・Vercel dashboard 操作
- [docs/supabase_connection_guide.md](/Users/chun/Desktop/GU_0410/docs/supabase_connection_guide.md) — DB 連線與事故 runbook
