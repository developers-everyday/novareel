# NovaReel — Testing Guide

> Complete guide for starting the application and testing all features across Phases 1–4.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Environment Setup](#2-environment-setup)
3. [Starting the Application](#3-starting-the-application)
4. [Running Automated Tests](#4-running-automated-tests)
5. [Manual Testing — Core Workflow](#5-manual-testing--core-workflow)
6. [Manual Testing — Phase 2 Features](#6-manual-testing--phase-2-features)
7. [Manual Testing — Phase 3 Features](#7-manual-testing--phase-3-features)
8. [Manual Testing — Phase 4 Features](#8-manual-testing--phase-4-features)
9. [API Reference Quick List](#9-api-reference-quick-list)
10. [Troubleshooting](#10-troubleshooting)

---

## 1. Prerequisites

| Tool | Version | Required For |
|------|---------|-------------|
| Python | 3.11+ | Backend API + worker |
| Node.js | 20+ | Frontend |
| npm | 9+ | Frontend dependency management |
| ffmpeg | Any | Video rendering (optional — falls back to placeholder without it) |
| Docker + Docker Compose | Any | Container-based setup (alternative to local) |

**Optional** (for full feature testing):
- AWS credentials (for Bedrock/S3/DynamoDB — not needed in mock mode)
- Clerk account (for auth — disabled by default locally)
- Google OAuth credentials (for YouTube publishing)

---

## 2. Environment Setup

### Option A: Local Development (Recommended)

```bash
# 1. Clone and enter the project
cd marketting-tool

# 2. Create backend .env from template
cp .env.example .env

# 3. Create frontend .env
cp apps/web/.env.example apps/web/.env.local

# 4. Install backend dependencies
cd services/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
cd ../..

# 5. Install frontend dependencies
cd apps/web
npm install
cd ../..
```

The default `.env` uses **mock AI** and **local storage** — no AWS or external API keys needed.

### Option B: Docker Compose

```bash
cd infra
docker-compose up
```

This starts: **web** (:3000), **api** (:8000), **worker**, and **redis** (:6379).

To also start the Celery worker:
```bash
docker-compose --profile celery up
```

---

## 3. Starting the Application

You need **three terminals** for local development:

### Terminal 1 — Backend API
```bash
cd services/backend
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000
```
Verify: http://localhost:8000/healthz → `{"status": "ok"}`

### Terminal 2 — Worker
```bash
cd services/backend
source .venv/bin/activate
python worker.py
```
The worker polls for queued jobs and processes them.

### Terminal 3 — Frontend
```bash
cd apps/web
npm run dev
```
Verify: http://localhost:3000

### Quick Access URLs

| URL | Description |
|-----|-------------|
| http://localhost:3000 | Frontend app |
| http://localhost:3000/app/dashboard | Video Studio (main workspace) |
| http://localhost:3000/app/brand-kit | Brand Kit settings |
| http://localhost:3000/app/connections | Social media connections |
| http://localhost:3000/app/admin | Admin overview |
| http://localhost:8000/docs | Swagger API docs (interactive) |
| http://localhost:8000/redoc | ReDoc API docs |
| http://localhost:8000/healthz | Health check |

---

## 4. Running Automated Tests

### Backend Tests

```bash
cd services/backend
source .venv/bin/activate
pytest
```

Test files:
| File | Coverage |
|------|----------|
| `tests/test_repository.py` | Local repository CRUD (projects, jobs, results, usage) |
| `tests/test_api.py` | API endpoint integration tests |
| `tests/test_phase2.py` | Phase 2 features (multi-language, voice providers, transcription, stock media, translation) |
| `tests/test_phase3.py` | Phase 3 features (brand kit, library, storyboard, variants, effects, parallel rendering, CDN, worker mode) |
| `tests/test_editing_framework.py` | Phase 4 editing framework (schema, planner, compiler, LLM planner) |

Run a specific test file:
```bash
pytest tests/test_editing_framework.py -v
```

Run a specific test:
```bash
pytest tests/test_editing_framework.py::test_editing_plan_json_roundtrip -v
```

### Frontend Checks

```bash
cd apps/web
npm run lint        # ESLint
npm run build       # TypeScript + Next.js build
```

### CI Pipeline

The GitHub Actions CI (`.github/workflows/ci.yml`) runs:
- **Backend**: `pip install -e .[dev]` → `pytest`
- **Web**: `npm install` → `npm run lint` → `npm run build`

---

## 5. Manual Testing — Core Workflow

This is the end-to-end happy path for video generation.

### 5.1 Create a Project

1. Open http://localhost:3000/app/dashboard
2. Fill in:
   - **Title**: "Test Product Video"
   - **Product Description**: "A wireless Bluetooth speaker with 20-hour battery life"
3. Click **Create Project**
4. **Verify**: Project card appears in the dashboard

**API equivalent:**
```bash
curl -X POST http://localhost:8000/v1/projects \
  -H "Content-Type: application/json" \
  -d '{"title": "Test Product", "product_description": "A wireless speaker"}'
```

### 5.2 Upload Assets

1. In the project card, click **Upload Images**
2. Upload 3–5 product images (JPEG/PNG/WebP, under 10 MB each)
3. **Verify**: Images appear as thumbnails in the project

**API equivalent:**
```bash
# 1. Create upload URL
curl -X POST http://localhost:8000/v1/projects/{project_id}/assets:upload-url \
  -H "Content-Type: application/json" \
  -d '{"filename": "product.jpg", "content_type": "image/jpeg"}'

# 2. Upload bytes (local mode)
curl -X PUT "http://localhost:8000/v1/projects/{project_id}/assets/{asset_id}:upload" \
  -H "Content-Type: image/jpeg" \
  --data-binary @product.jpg
```

### 5.3 Generate Video

1. Configure generation options:
   - **Aspect Ratio**: 16:9 (default)
   - **Voice Style**: professional
   - **Language**: en (English)
   - **Caption Style**: basic
2. Click **Generate Video**
3. **Verify**: Job status progresses through: `queued` → `analyzing` → `scripting` → `matching` → `narrating` → `rendering` → `completed`
4. **Verify**: Video player appears with rendered video and download button

**API equivalent:**
```bash
curl -X POST http://localhost:8000/v1/projects/{project_id}/generate \
  -H "Content-Type: application/json" \
  -d '{"aspect_ratio": "16:9", "voice_style": "professional", "language": "en"}'

# Poll job status
curl http://localhost:8000/v1/jobs/{job_id}
```

### 5.4 View Results

1. Once generation completes, check:
   - Video playback works
   - Thumbnail is displayed
   - Script text is shown
   - Download button works
2. **Verify**: Usage counter incremented on the usage page

---

## 6. Manual Testing — Phase 2 Features

### 6.1 Multi-Language Generation

1. In the generation form, change **Language** to `es` (Spanish), `fr` (French), `ja` (Japanese), or `ar` (Arabic)
2. Generate a video
3. **Verify**: Script is in the selected language (mock mode generates English with language tag)
4. **Verify**: Arabic (`ar`) should use RTL caption rendering when ffmpeg is available

### 6.2 Voice Provider Selection

1. Change **Voice Provider** to `edge_tts` (free, no API key needed)
2. Generate a video
3. **Verify**: Job completes successfully
4. **Note**: `elevenlabs` requires `NOVAREEL_ELEVENLABS_API_KEY` in `.env`

### 6.3 Video Translation

1. After a video is generated, click **Translate**
2. Select target languages (e.g., `es`, `fr`)
3. Click **Translate**
4. **Verify**: Translation jobs are created and process through the pipeline
5. **Verify**: Each translation produces a new video result

### 6.4 Caption Styles

Generate videos with different caption styles: `none`, `basic`, `word_highlight`, `karaoke`

### 6.5 Stock B-roll

1. Set **Video Style** to `product_lifestyle` or `broll_heavy`
2. Generate a video
3. **Verify**: In mock mode, the pipeline still runs; with `NOVAREEL_PEXELS_API_KEY` set, real Pexels footage is fetched

### 6.6 Background Music

1. Set **Background Music** to `upbeat`, `calm`, `corporate`, or `auto`
2. Generate a video
3. **Verify**: Music is mixed into the final video when ffmpeg is available

---

## 7. Manual Testing — Phase 3 Features

### 7.1 Brand Kit

1. Navigate to http://localhost:3000/app/brand-kit
2. Set:
   - **Brand Name**: "My Brand"
   - **Primary Color**: `#FF5733`
   - **Secondary Color**: `#335BFF`
3. Upload a **logo** (PNG)
4. Upload a **font** (TTF/OTF)
5. Upload **intro/outro** clips (MP4)
6. Click **Save Brand Kit**
7. **Verify**: Brand kit is saved and displayed
8. **Verify**: Delete brand kit works

**API equivalent:**
```bash
# Save brand kit
curl -X POST http://localhost:8000/v1/brand-kit \
  -H "Content-Type: application/json" \
  -d '{"brand_name": "My Brand", "primary_color": "#FF5733"}'

# Get brand kit
curl http://localhost:8000/v1/brand-kit
```

### 7.2 Asset Library

1. On the Brand Kit page, scroll to **Library Assets**
2. Upload assets of different types: images, fonts, video clips, audio
3. **Verify**: Assets appear in the list with correct type and size
4. **Verify**: Delete asset works
5. **Verify**: Asset limit (50 by default) is enforced

**API equivalent:**
```bash
# Create library asset
curl -X POST http://localhost:8000/v1/library/assets \
  -H "Content-Type: application/json" \
  -d '{"filename": "intro.mp4", "content_type": "video/mp4", "asset_type": "intro_clip"}'

# Upload bytes
curl -X PUT "http://localhost:8000/v1/library/assets/{asset_id}:upload" \
  -H "Content-Type: video/mp4" \
  --data-binary @intro.mp4

# List assets
curl http://localhost:8000/v1/library/assets
```

### 7.3 Storyboard Editor (Auto-Approve Flow)

1. In the generation form, **uncheck** "Auto-approve storyboard"
2. Generate a video
3. **Verify**: Job pauses at `awaiting_approval` status (50% progress)
4. **Verify**: Storyboard editor appears with editable scenes
5. Edit a script line and click **Approve & Continue**
6. **Verify**: Job resumes and completes

**API equivalent:**
```bash
# Get storyboard
curl http://localhost:8000/v1/projects/{project_id}/jobs/{job_id}/storyboard

# Edit storyboard
curl -X PUT http://localhost:8000/v1/projects/{project_id}/jobs/{job_id}/storyboard \
  -H "Content-Type: application/json" \
  -d '{"scenes": [{"order": 0, "script_line": "Updated line", "duration_sec": 5.0}]}'

# Approve
curl -X POST http://localhost:8000/v1/projects/{project_id}/jobs/{job_id}/approve
```

### 7.4 YouTube Publishing

> **Requires**: `NOVAREEL_GOOGLE_CLIENT_ID` and `NOVAREEL_GOOGLE_CLIENT_SECRET` in `.env`

1. Navigate to http://localhost:3000/app/connections
2. Click **Connect** next to YouTube
3. Complete the Google OAuth flow
4. **Verify**: YouTube connection shows as connected
5. Go to a completed video → click **Publish**
6. Generate metadata → review title/description/tags
7. Click **Publish to YouTube**
8. **Verify**: Publish record is created

Without Google credentials, verify the UI renders and the connect button redirects to the auth endpoint.

### 7.5 A/B Variants

1. After a video is generated, click **Variants**
2. Set variant count (2–5)
3. Click **Generate Variants**
4. **Verify**: Multiple jobs are created with the same variant group
5. **Verify**: All variants complete independently

**API equivalent:**
```bash
curl -X POST http://localhost:8000/v1/projects/{project_id}/generate-variants \
  -H "Content-Type: application/json" \
  -d '{"variant_count": 3, "shared": {"aspect_ratio": "16:9"}, "overrides": [{"voice_style": "professional"}, {"voice_style": "casual"}]}'
```

---

## 8. Manual Testing — Phase 4 Features

### 8.1 Editing Framework (Feature Flag)

The editing framework is **off by default**. To test it:

1. Set `NOVAREEL_USE_EDITING_FRAMEWORK=true` in `.env`
2. Restart the API and worker
3. Generate a video
4. **Verify**: Video renders successfully (output should be identical to legacy path)
5. **Verify**: Editing plan JSON is persisted and accessible via API

```bash
# View the editing plan for a job
curl http://localhost:8000/v1/projects/{project_id}/jobs/{job_id}/editing-plan
```

**What to check in the plan JSON:**
- `version` is `"1.0"`
- `resolution` matches the aspect ratio
- `steps` array contains segment steps (image_segment / video_segment / color_segment)
- Post-processing steps (text_overlay, audio_mux, music_mix, thumbnail) are present
- Transition step present if a transition style was selected

### 8.2 Editing Framework + Mock AI (LLM Planner Fallback)

With `NOVAREEL_USE_MOCK_AI=true` (default), the LLM planner falls back to the deterministic planner. This is the expected behavior — the LLM planner only calls Bedrock when `use_mock_ai=false`.

**Verify**: Generation still works with both `USE_EDITING_FRAMEWORK=true` and `USE_MOCK_AI=true`.

---

## 9. API Reference Quick List

### Core
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/v1/projects` | Create project |
| GET | `/v1/projects` | List projects |
| POST | `/v1/projects/{id}/assets:upload-url` | Create asset upload |
| PUT | `/v1/projects/{id}/assets/{aid}:upload` | Upload asset bytes |
| POST | `/v1/projects/{id}/generate` | Start generation |
| GET | `/v1/projects/{id}/jobs` | List jobs |
| GET | `/v1/jobs/{id}` | Get job status |
| GET | `/v1/projects/{id}/result` | Get latest result |
| GET | `/v1/projects/{id}/results` | List all results |

### Phase 2
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/v1/projects/{id}/jobs/{jid}/translate` | Translate video |

### Phase 3
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/v1/brand-kit` | Save brand kit |
| GET | `/v1/brand-kit` | Get brand kit |
| DELETE | `/v1/brand-kit` | Delete brand kit |
| POST | `/v1/library/assets` | Create library asset |
| GET | `/v1/library/assets` | List library assets |
| DELETE | `/v1/library/assets/{id}` | Delete library asset |
| PUT | `/v1/library/assets/{id}:upload` | Upload library asset bytes |
| GET | `/v1/projects/{id}/jobs/{jid}/storyboard` | Get storyboard |
| PUT | `/v1/projects/{id}/jobs/{jid}/storyboard` | Edit storyboard |
| POST | `/v1/projects/{id}/jobs/{jid}/approve` | Approve storyboard |
| POST | `/v1/projects/{id}/jobs/{jid}/metadata` | Generate metadata |
| GET | `/v1/social/auth/youtube` | YouTube OAuth redirect |
| GET | `/v1/social/auth/youtube/callback` | YouTube OAuth callback |
| POST | `/v1/projects/{id}/jobs/{jid}/publish/youtube` | Publish to YouTube |
| GET | `/v1/social/connections` | List social connections |
| DELETE | `/v1/social/connections/{platform}` | Disconnect platform |
| POST | `/v1/projects/{id}/generate-variants` | Generate A/B variants |

### Phase 4
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/v1/projects/{id}/jobs/{jid}/editing-plan` | View editing plan JSON |

### Admin / Utility
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/v1/usage` | Usage summary |
| POST | `/v1/analytics/events` | Record analytics event |
| GET | `/v1/analytics/events` | List analytics events |
| GET | `/v1/admin/overview` | Admin overview |
| GET | `/v1/admin/dead-letters` | Dead-lettered jobs |
| POST | `/v1/jobs/{id}:process` | Manually process a job |
| GET | `/healthz` | Health check |

---

## 10. Troubleshooting

### "ffmpeg not found" warnings
- Video rendering falls back to placeholder bytes without ffmpeg
- Install: `brew install ffmpeg` (macOS) or `apt install ffmpeg` (Linux)
- Not required for testing the pipeline — only for actual video output

### Worker not picking up jobs
- Ensure the worker is running in a separate terminal: `python worker.py`
- Check that API and worker share the same `NOVAREEL_LOCAL_DATA_DIR`
- Check worker logs for errors

### Frontend 401 / auth errors
- Default config has `NOVAREEL_AUTH_DISABLED=true` — no Clerk needed
- If you see auth errors, ensure `.env` has `NOVAREEL_AUTH_DISABLED=true`

### "Module not found" errors
- Ensure you're in the virtualenv: `source .venv/bin/activate`
- Reinstall: `pip install -e .[dev]`

### Job stuck in "queued"
- The worker must be running to process jobs
- Alternatively, manually trigger: `curl -X POST http://localhost:8000/v1/jobs/{job_id}:process`

### Tests failing with import errors
- Run from the `services/backend` directory with the venv active
- Ensure `[tool.pytest.ini_options] pythonpath = ["."]` is in `pyproject.toml`

### Docker Compose issues
- Ensure ports 3000, 8000, and 6379 are free
- Run `docker-compose down -v` to reset volumes and start fresh
