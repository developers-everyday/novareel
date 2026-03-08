# NovaReel - Phase 1 Implementation

This repository now contains a Phase 1-ready baseline for NovaReel:

- Next.js frontend (`apps/web`) with SEO landing pages, Clerk auth wiring, and a private beta dashboard.
- FastAPI backend (`services/backend`) with the required v1 APIs.
- Async worker (`services/backend/worker.py`) that processes queued jobs through scripting, matching, narration, and rendering states.
- Local-first development mode with optional AWS backends for DynamoDB/S3/SQS.

## Repository Structure

- `apps/web`: Next.js App Router frontend (Vercel-friendly)
- `services/backend`: FastAPI API + worker + tests
- `infra/docker-compose.yml`: local multi-service orchestrator
- `.github/workflows/ci.yml`: baseline CI for backend tests and web build/lint

## Implemented v1 API

- `POST /v1/projects`
- `GET /v1/projects`
- `POST /v1/projects/{project_id}/assets:upload-url`
- `POST /v1/projects/{project_id}/generate`
- `GET /v1/projects/{project_id}/jobs`
- `GET /v1/jobs/{job_id}`
- `GET /v1/projects/{project_id}/result`
- `GET /v1/usage`
- `POST /v1/analytics/events`
- `GET /v1/analytics/events`
- `GET /v1/admin/overview`
- `GET /v1/admin/dead-letters`

Additional local-dev helper endpoints:

- `PUT /v1/projects/{project_id}/assets/{asset_id}:upload` for local uploads
- `POST /v1/jobs/{job_id}:process` for local/manual processing

## Local Development

### 1) Backend

```bash
cd services/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
uvicorn app.main:app --reload --port 8000
```

In another terminal:

```bash
cd services/backend
source .venv/bin/activate
python worker.py
```

### 2) Frontend

```bash
cd apps/web
npm install
npm run dev
```

Open:

- Web: `http://localhost:3000`
- API docs: `http://localhost:8000/docs`

## Notes

- Default mode is local + mock AI. Switch to real Bedrock/Polly by setting `NOVAREEL_USE_MOCK_AI=false` and AWS credentials/env vars.
- Default auth is disabled (`NOVAREEL_AUTH_DISABLED=true`) for local development. Set to `false` in beta/prod and configure Clerk env vars.
- Video rendering uses `ffmpeg` when available and falls back to placeholder bytes if missing.
- Generation endpoint supports idempotency keys (`idempotency_key`) to prevent duplicate job creation.
- Worker now applies retry backoff and dead-letters jobs after `NOVAREEL_WORKER_MAX_ATTEMPTS`.
