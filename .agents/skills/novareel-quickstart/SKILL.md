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
| AI — Script | Amazon Bedrock `amazon.nova-lite-v1:0` |
| AI — Voice | **Nova 2 Sonic** (default TTS), Polly, EdgeTTS, ElevenLabs as fallbacks |
| AI — Matching | Embedding cosine-similarity via `amazon.nova-2-multimodal-embeddings-v1:0` (fallback: round-robin) |
| AI — B-Roll Director | Nova Vision plans per-scene media decisions + validates stock footage relevance |
| AI — Image Gen | **Nova 2 Omni** (`amazon.nova-omni-v2:0`) generates brand campaign images from product photos |
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
```

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
| `NOVAREEL_USE_MOCK_AI` | `false` = real Bedrock/Polly, `true` = mock strings |
| `NOVAREEL_QUOTA_EXEMPT_EMAILS` | JSON list of emails or Clerk user_ids that skip the monthly quota |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | Must be set in `~/.aws/credentials` for boto3 to pick up |
| `NOVAREEL_STORAGE_BACKEND` | `local` (dev) or `dynamodb` (prod) |

> ⚠️ `get_settings()` is `@lru_cache` — **a full process restart is required** to pick up `.env` changes. Hot-reload alone is not enough.

---

## Generation Pipeline (Happy Path)

```
Browser → POST /v1/projects          → create project record
Browser → POST /v1/projects/{id}/assets → get upload URL
Browser → PUT  <upload_url>          → upload image (auth token required)
Browser → POST /v1/projects/{id}/generate → enqueue job

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
