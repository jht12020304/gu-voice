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

# 2. backend -> Railway (Dockerfile lives in backend/, so cwd matters)
cd backend && railway up --detach --service gu-voice-app
curl https://gu-voice-app-production.up.railway.app/api/v1/healthz/deep

# 3. frontend -> Vercel (project lives in team 7696s-projects, not the personal team)
vercel switch          # pick 7696s-projects
cd frontend && npm run build && vercel --prod
```

Non-interactive Railway link (must run from the repo root): `railway link -p gu-voice-api -s gu-voice-app -e production`.

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
