---
name: novareel-quickstart
description: Quick-start context for any agent working on the NovaReel application. Read this first before touching any code.
---

# NovaReel — Agent Quick-Start

## What Is This App?

**NovaReel** is a private-beta SaaS that turns product photos into AI-generated marketing videos.
A user uploads product images, writes a short description, and the system delivers a 30-60 second MP4 with voice narration and SRT subtitles.

---

## Stack at a Glance

| Layer | Technology |
|---|---|
| Frontend | Next.js 14 (App Router), Clerk auth, TypeScript |
| Backend API | FastAPI (Python 3.12), Pydantic v2, Uvicorn |
| Async Worker | `services/backend/worker.py` — polls a local queue |
| AI — Orchestrator | **Nova Pro** (`amazon.nova-pro-v1:0`) — agentic pipeline orchestrator (tool-use loop) |
| AI — Script | Amazon Bedrock `amazon.nova-lite-v1:0` (called by orchestrator) |
| AI — Voice | **Nova 2 Sonic** (default TTS), Polly, EdgeTTS, ElevenLabs as fallbacks |
| AI — Matching | Embedding cosine-similarity via `amazon.nova-2-multimodal-embeddings-v1:0` (fallback: round-robin) |
| AI — B-Roll Director | Nova Vision plans per-scene media decisions + validates stock footage relevance |
| AI — Image Gen | **Nova Canvas** (`amazon.nova-canvas-v1:0`) generates brand campaign images from product photos |
| Video Render | ffmpeg (local image slideshow → MP4) |
| Storage (dev) | Local filesystem under `services/backend/data/storage/` |
| Storage (prod) | AWS S3 + DynamoDB |
| Auth | Clerk RS256 JWT, verified via JWKS |

---

## Repository Layout

```
marketting-tool/
  apps/web/                  # Next.js frontend
    app/                     # App Router pages
    components/project-studio.tsx   # Main generate form
    lib/api.ts               # All backend API calls
  services/backend/
    app/
      api/v1.py              # All REST endpoints
      auth.py                # Clerk JWT verification → AuthUser
      config.py              # All settings (pydantic-settings, @lru_cache)
      models.py              # Pydantic request/response models
      services/
        nova.py              # Bedrock script gen (returns ScriptScene list)
        broll_director.py    # Vision Director — plans/validates B-roll
        image_generator.py   # Nova Omni — AI image generation for brand campaigns
        nova_reel.py         # Nova Reel async video generation service [PENDING]
        video.py             # ffmpeg slideshow rendering
        pipeline.py          # Full job orchestration
        storage.py           # Local / S3 abstraction
      services/voice/
        factory.py           # Voice provider factory (nova_sonic, polly, edge_tts, elevenlabs)
        nova_sonic.py        # Nova 2 Sonic TTS provider (default)
      repositories/
        local.py             # JSON file-based repo (dev)
        dynamo.py            # DynamoDB repo (prod)
    worker.py                # Background job runner
    validate_novareel.py     # Standalone Nova Reel smoke test [PENDING]
  docs/
    *.md                     # High-level research/planning documents
    impl/
      *-implementation.md    # Detailed implementation plans (one per planning doc)
```

---

## Documentation Convention

Planning documents live in `docs/`. Each planning doc has a matching detailed implementation plan in `docs/impl/`, named after the source document:

| Planning doc | Implementation plan |
|---|---|
| `docs/video-enhancement-plan.md` | `docs/impl/video-enhancement-plan-implementation.md` |

**Rules for agents:**
- Before starting any feature work, check `docs/impl/` for an existing implementation plan matching the planning document you were given.
- When creating a new implementation plan, name it `<source-doc-name>-implementation.md` and save it to `docs/impl/`.
- Never save implementation plans to the artifact/brain directory — they belong in the project repo so any developer or agent can find them.

---

## How to Run Locally

```bash
# Terminal 1 — Backend API
cd services/backend && source .venv/bin/activate && cd ../.. && make dev-api

# Terminal 2 — Worker
cd services/backend && source .venv/bin/activate && python worker.py

# Terminal 3 — Frontend
make dev-web
# Visit http://localhost:3000
```

> **Always activate `.venv` before running any backend command** — otherwise `uvicorn`, `python`, etc. won't be found.

---

## Key Environment Variables (`services/backend/.env`)

| Variable | Purpose |
|---|---|
| `NOVAREEL_AUTH_DISABLED` | Set `false` for prod, `true` to skip Clerk auth |
| `NOVAREEL_CLERK_JWKS_URL` | `https://<clerk-instance>.clerk.accounts.dev/.well-known/jwks.json` |
| `NOVAREEL_CLERK_ISSUER` / `NOVAREEL_CLERK_AUDIENCE` | Optional Clerk JWT issuer/audience validation in prod |
| `NOVAREEL_USE_MOCK_AI` | `false` = real Bedrock/Polly, `true` = mock strings |
| `NOVAREEL_QUOTA_EXEMPT_EMAILS` | JSON list of emails or Clerk user_ids that skip the monthly quota |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | Must be set in `~/.aws/credentials` for boto3 to pick up |
| `NOVAREEL_STORAGE_BACKEND` | `local` (dev) or `dynamodb` (prod) |
| `NOVAREEL_QUEUE_BACKEND` | `poll` (dev) or `sqs` (prod) |

> ⚠️ `get_settings()` is `@lru_cache` — **a full process restart is required** to pick up `.env` changes. Hot-reload alone is not enough.

---

## Generation Pipeline (Happy Path)

```
Browser → POST /v1/projects                              → create project record
Browser → POST /v1/projects/{id}/assets:upload-url       → get presigned S3 URL
Browser → PUT  <presigned_s3_url>                        → upload image DIRECTLY to S3
Browser → POST /v1/projects/{id}/assets/{aid}:confirm-upload → mark asset uploaded=True in DynamoDB
Browser → POST /v1/projects/{id}/generate                → enqueue job

worker.py polls queue →
  nova.generate_script()   → Bedrock Nova Lite → 6 ScriptScene (narration + visual_requirements)
  nova.match_images()      → embedding cosine-sim image assignment (fallback: round-robin)
  _fetch_stock_footage()   → Vision Director plans B-roll/AI-gen → Pexels fetch + Nova Omni → validation
  voice_provider.synthesize() → Nova Sonic (default) / Polly / EdgeTTS → MP3 audio
  video.render_video()     → ffmpeg slideshow → MP4 + thumbnail
  → save .mp4, .mp3, .srt, .txt to storage
  → mark job COMPLETED
```

---

## Known Gotchas

| Issue | Fix |
|---|---|
| `uvicorn: command not found` | Activate `.venv` first |
| 401 on asset upload | `uploadAsset` must pass Bearer token (already fixed in `api.ts`) |
| ffmpeg `drawtext` missing | Homebrew ffmpeg lacks libfreetype; drawtext removed, captions in `.srt` |
| Bedrock/Polly "no credentials" | Credentials must be in `~/.aws/credentials`, not just `.env` |
| 422 on project create | Check `models.py` field types; `brand_prefs` accepts dict or list |
| Quota 429 | Add email or Clerk `user_id` to `NOVAREEL_QUOTA_EXEMPT_EMAILS` in `.env` |
| Script includes `[shot directions]` | Already fixed in `nova.py` via `_clean_script_lines()` |
| **400 on generate — "Upload at least one asset"** | S3 presigned URL was using Signature V2 (rejected by S3). Fixed by adding `config=Config(signature_version='s3v4')` to S3 client in `services/storage.py`. Also requires the confirm-upload step below. |
| **`asset.uploaded` always `False` in prod** | S3 PUT goes directly browser→S3, backend never called. Fixed by `POST /v1/projects/{id}/assets/{aid}:confirm-upload` endpoint + frontend call after each successful S3 PUT. |
| **Clerk JWKS 404** | Old JWKS URL was `https://clerk.dev/.well-known/jwks.json` (dead). Use instance-specific URL: `https://<instance>.clerk.accounts.dev/.well-known/jwks.json`. Set `NOVAREEL_CLERK_JWKS_URL` and `NOVAREEL_CLERK_ISSUER` in ECS env. |

---

## Production Debugging (AWS)

### Infrastructure identifiers
| Resource | Value |
|---|---|
| ECS Cluster | `novareel-production` |
| ECS Task Definition | `novareel-production-api` |
| ALB URL | `http://novareel-production-alb-146756903.us-east-1.elb.amazonaws.com` |
| S3 Bucket | `novareel-production-assets-347502780376` |
| CloudFront | `https://dh4r7i40jtqy6.cloudfront.net` |
| Amplify App | `https://master.dawy33xcd35b4.amplifyapp.com` |
| Region | `us-east-1` |
| DynamoDB tables | `novareel-production-projects`, `novareel-production-projects-assets`, `novareel-production-jobs`, `novareel-production-results`, `novareel-production-usage` |

### Step 1 — Check recent API logs
```bash
# Last 5 minutes of all non-healthcheck traffic
aws logs filter-log-events \
  --log-group-name /novareel/production/api \
  --region us-east-1 \
  --start-time $(date -v-5M +%s000) \
  --filter-pattern "POST" \
  --query 'events[*].message' --output text

# Worker logs
aws logs filter-log-events \
  --log-group-name /novareel/production/worker \
  --region us-east-1 \
  --start-time $(date -v-5M +%s000) \
  --query 'events[*].message' --output text
```

### Step 2 — Check ECS task environment
```bash
# View all env vars for the running task definition
aws ecs describe-task-definition \
  --task-definition novareel-production-api:4 \
  --region us-east-1 \
  --query 'taskDefinition.containerDefinitions[0].environment' \
  --output json
```

### Step 3 — Check DynamoDB state for a project
```bash
# List all assets and their uploaded status
aws dynamodb scan \
  --table-name novareel-production-projects-assets \
  --region us-east-1 \
  --output json | python3 -c "
import sys, json
def flatten(v):
    if 'L' in v: return [flatten(i) for i in v['L']]
    if 'M' in v: return {k2: flatten(v2) for k2, v2 in v['M'].items()}
    if 'BOOL' in v: return v['BOOL']
    return list(v.values())[0]
data = json.load(sys.stdin)
for item in data.get('Items', []):
    flat = {k: flatten(v) for k, v in item.items()}
    print(f\"id={flat.get('id')} uploaded={flat.get('uploaded')} filename={flat.get('filename')}\")
"
```

### Step 4 — Verify S3 file actually landed
```bash
aws s3api head-object \
  --bucket novareel-production-assets-347502780376 \
  --key "projects/<project_id>/assets/<asset_id>-<filename>" \
  --region us-east-1
# 404 = S3 PUT never succeeded; 200 = file is there
```

### Step 5 — Check S3 bucket has files at all
```bash
aws s3api list-objects-v2 \
  --bucket novareel-production-assets-347502780376 \
  --region us-east-1 --max-items 10 \
  --query 'Contents[*].[Key,Size]' --output table
```

### Step 6 — Verify presigned URL signature version
Inspect the presigned URL returned by `POST /assets:upload-url`.
- **V2 (broken):** contains `AWSAccessKeyId=...&Signature=...&Expires=...`
- **V4 (correct):** contains `X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=...`

If V2, the fix is `config=Config(signature_version='s3v4')` in `S3StorageService.__init__()`.

### Step 7 — Check Amplify env vars
```bash
aws amplify list-apps --region us-east-1 \
  --output json | python3 -c "
import sys, json
apps = json.load(sys.stdin).get('apps', [])
for a in apps:
    print(a.get('appId'), a.get('name'), json.dumps(a.get('environmentVariables', {})))
"
# Must have: NOVAREEL_API_ORIGIN, NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY
```

### Step 8 — Deploy
```bash
# Backend (ECS) + frontend (triggers Amplify via git push)
./infra/scripts/deploy.sh

# Frontend only (Amplify auto-builds on push)
git push
```

### Root-cause checklist for "400 on generate"
1. Check backend logs — is `POST /generate` reaching ECS? If not, error is before generate.
2. Check DynamoDB assets — is `uploaded=True`? If false, upload step failed.
3. Check S3 — is the file there? If not, S3 PUT failed.
4. Inspect the presigned URL — is it V4? If V2, apply `s3v4` fix.
5. Check browser DevTools Network — look at the S3 PUT response status + XML body.

---

## Pending Work

- **TikTok + Instagram Publishing** — Phase 4 Gap B.

---

## Update Rule

> **Update this file whenever a major change happens to the application:**
> - New AWS service integrated
> - New API endpoint added
> - Pipeline step added or changed
> - New environment variable introduced
> - Known gotcha resolved or discovered
>
> Run the workflow: `/update-novareel-skill`
