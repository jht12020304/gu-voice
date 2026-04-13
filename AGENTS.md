# GU_0410 Repository Guide

## Deployment

This project uses GitHub-triggered automatic deployment.

- Frontend: `Vercel`
- Backend: `Railway`
- Local integration environment: `Docker Compose`

### Production Deployment Flow

After code is pushed to GitHub, deployment is automatic.

1. Make code changes locally.
2. Commit the changes.
3. Push to the tracked branch, normally `main`.

```bash
git add <files>
git commit -m "describe the change"
git push origin main
```

### What Happens After Push

- `Vercel` automatically builds and deploys the frontend from `frontend/`
- `Railway` automatically builds the backend Docker image from `backend/` and deploys it

Do not describe production deployment as a manual server release unless the GitHub-connected auto-deploy flow has been intentionally disabled in the platform dashboards.

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

- `https://gu-voice-api-production.up.railway.app/api/v1/health`

## Required Platform Assumptions

For automatic deployment to work, all of the following must already be true:

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

- [docs/deployment_guide.md](/Users/chun/Desktop/GU_0410/docs/deployment_guide.md)
- [docs/cloud_deployment.md](/Users/chun/Desktop/GU_0410/docs/cloud_deployment.md)
- [docs/vercel_deploy_guide.md](/Users/chun/Desktop/GU_0410/docs/vercel_deploy_guide.md)
