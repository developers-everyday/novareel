# NovaReel Phase 3 Enhancement — Development Plan

> **Status**: Draft — awaiting review  
> **Predecessor**: Phase 2 (Translation, Word-Level Captions, Stock Footage, Transitions, Script Templates) — 🔲 In Progress  
> **Timeline**: 8 weeks (4 sprints)  
> **Team**: 2-3 backend devs, 1 frontend dev, 1 DevOps (part-time)  
> **Start date**: After Phase 2 rollout stabilizes (est. late-June 2026)

---

## Table of Contents

1. [Phase 2 Recap](#1-phase-2-recap)
2. [Phase 3 Vision & Scope](#2-phase-3-vision--scope)
3. [Feature A: Brand Kit & Asset Library](#3-feature-a-brand-kit--asset-library)
4. [Feature B: Audio Processing Pipeline](#4-feature-b-audio-processing-pipeline)
5. [Feature C: Social Media Distribution](#5-feature-c-social-media-distribution)
6. [Feature D: Video Editor & Preview](#6-feature-d-video-editor--preview)
7. [Feature E: A/B Video Variants](#7-feature-e-ab-video-variants)
8. [Feature F: Performance & Scalability](#8-feature-f-performance--scalability)
9. [Frontend Changes (All Features)](#9-frontend-changes-all-features)
10. [Dependency & Infra Changes](#10-dependency--infra-changes)
11. [Testing Strategy](#11-testing-strategy)
12. [Sprint Plan](#12-sprint-plan)
13. [Acceptance Criteria](#13-acceptance-criteria)
14. [Risks & Mitigations](#14-risks--mitigations)

---

## 1. Phase 2 Recap

Phase 2 (when complete) will have delivered 5 features that take NovaReel from "slideshow generator" to "marketing video platform":

| Feature | Status | What It Delivers |
|---------|--------|-----------------|
| **Video Translation & Dubbing** | 🔲 P2 | One-click translation to 20+ languages; per-job result storage; `LOADING`/`TRANSLATING` pipeline stages |
| **Word-Level Captions** | 🔲 P2 | AWS Transcribe (default) + Whisper; `word_highlight` and `karaoke` ASS subtitle styles |
| **Stock Footage (Pexels)** | 🔲 P2 | LLM-generated search queries → B-roll interleaved with product images |
| **Video Transitions & Effects** | 🔲 P2 | `xfade` transitions, `drawtext` title cards, CTA end cards |
| **Script Templates** | 🔲 P2 | 8 YAML prompt templates (problem/solution, unboxing, comparison, etc.) |

**Key architecture assets from Phase 2:**
- `services/backend/app/models.py` — `JobCreateParams` model (clean parameter passing)
- `services/backend/app/services/transcription.py` — pluggable transcription backend (AWS Transcribe / Whisper)
- `services/backend/app/services/translation.py` — LLM-based contextual translation
- `services/backend/app/services/effects.py` — `VideoEffectsConfig` dataclass system
- Per-job `VideoResultRecord` with `script_lines`, `language`, `job_id`
- `services/backend/prompt_templates/` — YAML template library

---

## 2. Phase 3 Vision & Scope

Phase 3 focuses on **platform maturity, distribution, and scale** — turning NovaReel from "a tool that makes videos" into "a platform that grows sellers' businesses."

> **Strategic theme**: After Phase 2, sellers can create professional videos in 20+ languages. Phase 3 answers: *"Now that I have great videos, how do I use them effectively?"*

| Feature | What | Why | Impact | Effort |
|---------|------|-----|--------|--------|
| **A. Brand Kit & Asset Library** | Shared assets (logos, fonts, music, intros) reusable across projects | Brand consistency without repeated uploads | 🔴 Critical | 2-3 weeks |
| **B. Audio Processing Pipeline** | Normalization, silence trimming, ducking, speed adjustment | Professional audio quality | 🟠 High | 1-2 weeks |
| **C. Social Media Distribution** | Auto-generated metadata + direct publishing to YouTube/TikTok/Instagram | End-to-end workflow: generate → publish | 🔴 Critical | 3-4 weeks |
| **D. Video Editor & Preview** | In-browser video preview, script editing before render, regenerate individual scenes | Seller control over output quality | 🟠 High | 3-4 weeks |
| **E. A/B Video Variants** | Generate multiple video variants (different scripts, styles) from same product | Data-driven content optimization | 🟡 Medium | 1-2 weeks |
| **F. Performance & Scalability** | Parallel segment rendering, async TTS, Celery task queue, CDN delivery | 10x throughput, sub-60s generation | 🟠 High | 2-3 weeks |

> **Reference**: `docs/ShortGPT_Integration_Analysis.md` — §§9, 11, 12, 13, 14 cover the remaining features from the competitor analysis.

---

## 3. Feature A: Brand Kit & Asset Library

> **Priority**: 🔴 Critical  
> **Reference**: `docs/ShortGPT_Integration_Analysis.md` §11 — Asset Library System

### What It Does

Sellers create a **Brand Kit** once — uploading their logo, selecting brand colors and fonts, adding custom music tracks, and optionally uploading intro/outro video clips. All future video generations for that seller automatically incorporate these brand assets, ensuring visual consistency across dozens of product videos.

### Brand Kit Components

| Component | Type | How It's Used |
|-----------|------|---------------|
| **Logo** | Image (PNG/SVG) | Watermark overlay in corner of every video (uses `effects.py` `watermark_path`) |
| **Brand colors** | Hex colors (primary, secondary, accent) | Title card text, CTA background, caption highlight color |
| **Brand font** | TTF/OTF file | `drawtext` font in title cards, CTA, feature callouts |
| **Intro clip** | Video (MP4, ≤5s) | Prepended to every video as a branded opening |
| **Outro clip** | Video (MP4, ≤5s) | Appended after CTA end card |
| **Custom music** | Audio (MP3) | Available alongside built-in mood music; overrides `background_music=auto` |

### New API Endpoints

```
POST   /v1/brand-kit                     Create/update brand kit (one per user)
GET    /v1/brand-kit                     Get current brand kit
DELETE /v1/brand-kit                     Reset brand kit

POST   /v1/library/assets               Upload a reusable asset to library
GET    /v1/library/assets                List library assets (filterable by type)
DELETE /v1/library/assets/{asset_id}     Remove asset from library
```

**Brand Kit request body:**
```json
{
  "brand_name": "TechGadgets Pro",
  "primary_color": "#1E40AF",
  "secondary_color": "#F59E0B",
  "accent_color": "#10B981",
  "logo_asset_id": "lib-asset-001",
  "font_asset_id": "lib-asset-002",
  "intro_clip_asset_id": "lib-asset-003",
  "outro_clip_asset_id": "lib-asset-004",
  "custom_music_asset_ids": ["lib-asset-005", "lib-asset-006"]
}
```

### New Files

```
services/backend/app/models.py           # BrandKitRecord, LibraryAssetRecord models
services/backend/app/services/brand.py   # Brand kit resolution + merge logic
```

### `brand.py`

```python
class BrandService:
    """Resolve brand kit assets for a given user and merge into video pipeline."""

    def __init__(self, storage: StorageService):
        self.storage = storage

    def resolve_brand_kit(self, owner_id: str, repo: Repository) -> BrandKitConfig | None:
        """Load the user's brand kit and resolve all asset paths.
        
        Returns a BrandKitConfig with local paths to logo, font, intro/outro clips.
        Returns None if the user has no brand kit configured.
        """
        ...

    def build_effects_config(
        self,
        brand_kit: BrandKitConfig | None,
        job_params: JobCreateParams,
        project: ProjectRecord,
    ) -> VideoEffectsConfig:
        """Merge brand kit assets with per-job settings to build final VideoEffectsConfig.
        
        Priority: per-job settings > brand kit defaults > system defaults.
        """
        ...
```

### Changes to Existing Files

| File | Change |
|------|--------|
| `models.py` | Add `BrandKitRecord`, `LibraryAssetRecord` models |
| `base.py` / `local.py` / `dynamo.py` | Add CRUD methods: `set_brand_kit()`, `get_brand_kit()`, `create_library_asset()`, `list_library_assets()`, `delete_library_asset()` |
| `v1.py` | Add brand kit + library asset endpoints |
| `pipeline.py` | Before RENDERING, resolve brand kit → build `VideoEffectsConfig` with brand assets |
| `pipeline_translate.py` | Same brand kit resolution for translation jobs |
| `video.py` | Accept `intro_clip` and `outro_clip` paths; prepend/append to segment list before rendering |
| `effects.py` | Add `intro_clip_path`, `outro_clip_path`, `brand_colors` to `VideoEffectsConfig` |
| `config/__init__.py` | Add `max_library_assets: int = 50` (per user limit) |

### Storage Layout

```
data/storage/
└── users/{owner_id}/
    ├── brand-kit.json               # Brand kit metadata
    └── library/
        ├── lib-asset-001/logo.png
        ├── lib-asset-002/font.ttf
        ├── lib-asset-003/intro.mp4
        └── lib-asset-005/music.mp3
```

### Mock AI Mode

No AI involved — brand kit is pure storage and composition. Works identically in mock mode.

---

## 4. Feature B: Audio Processing Pipeline

> **Priority**: 🟠 High  
> **Reference**: `docs/ShortGPT_Integration_Analysis.md` §13 — Audio Processing Pipeline

### What It Does

Post-process all narration and music audio to achieve broadcast-quality output. Currently, raw TTS audio goes directly into the video — different TTS providers produce different volume levels, some have leading/trailing silence, and music volume is a static 12% with no awareness of speech patterns.

### Processing Chain

```
TTS Output → Silence Trim → Normalize → Speed Adjust (if needed) → final narration.mp3
                                                                        ↓
Music Track → Loop to Duration → Duck Under Speech → Mix with Narration → final_audio.mp3
```

### Processing Steps

| Step | What | FFmpeg Filter | When |
|------|------|---------------|------|
| **Silence trim** | Remove leading/trailing silence from TTS output | `silenceremove=start_periods=1:stop_periods=1:start_threshold=-50dB` | Always |
| **Normalize** | Consistent volume across all narration segments | `loudnorm=I=-16:TP=-1.5:LRA=11` | Always |
| **Speed adjust** | If narration exceeds target duration, speed up slightly | `atempo=1.1` (max 1.25x) | When segment narration > segment duration |
| **Audio ducking** | Lower music volume when speech is active | `sidechaincompress` or envelope-based | When `background_music != 'none'` |
| **Crossfade mix** | Smooth fade-in/fade-out of music at video start/end | `afade=t=in:d=2,afade=t=out:d=3` | When `background_music != 'none'` |

### New Files

```
services/backend/app/services/audio.py    # Audio processing pipeline
```

### `audio.py`

```python
from pathlib import Path
import subprocess

class AudioProcessor:
    """Post-process narration and music audio for broadcast quality."""

    def trim_silence(self, audio_path: Path) -> Path:
        """Remove leading/trailing silence. Returns path to trimmed file."""
        ...

    def normalize(self, audio_path: Path, target_lufs: float = -16.0) -> Path:
        """Normalize audio to target LUFS level."""
        ...

    def adjust_speed(self, audio_path: Path, target_duration: float) -> Path:
        """Speed up/slow down audio to fit target duration (max 1.25x)."""
        ...

    def duck_music(
        self,
        narration_path: Path,
        music_path: Path,
        output_path: Path,
        music_volume: float = 0.12,
        duck_volume: float = 0.05,
    ) -> Path:
        """Mix narration and music with ducking (music lowers during speech)."""
        ...

    def process_narration(
        self,
        raw_audio_path: Path,
        target_duration: float | None = None,
    ) -> Path:
        """Full narration processing chain: trim → normalize → speed adjust."""
        trimmed = self.trim_silence(raw_audio_path)
        normalized = self.normalize(trimmed)
        if target_duration and self._get_duration(normalized) > target_duration * 1.05:
            return self.adjust_speed(normalized, target_duration)
        return normalized
```

### Changes to Existing Files

| File | Change |
|------|--------|
| `pipeline.py` | After NARRATION stage, run `AudioProcessor.process_narration()` on each segment's audio; replace static music mixing with `AudioProcessor.duck_music()` |
| `pipeline_translate.py` | Same audio post-processing for translated narration |
| `music.py` | Add `loop_to_duration()` and `crossfade_music()` methods |
| `video.py` | Accept pre-processed audio path instead of raw TTS output |

### Mock AI Mode

Audio processing uses FFmpeg, not AI. Works identically in mock mode — the mock TTS bytes still go through the processing chain.

---

## 5. Feature C: Social Media Distribution

> **Priority**: 🔴 Critical  
> **Reference**: `docs/ShortGPT_Integration_Analysis.md` §12 — Social Media Auto-Publishing

### What It Does

After a video is generated, NovaReel auto-generates platform-specific metadata (titles, descriptions, hashtags, captions) and lets sellers publish directly to YouTube, TikTok, and Instagram — without leaving the app.

### Three-Phase Rollout

| Sub-Phase | What | Scope |
|-----------|------|-------|
| **C1: Metadata Generation** | LLM generates platform-optimized titles, descriptions, hashtags | Backend only — no OAuth needed |
| **C2: Direct Publishing** | OAuth integration → publish to YouTube, TikTok, Instagram | Backend + Frontend OAuth flows |
| **C3: Scheduling & Analytics** | Schedule posts, track views/engagement | Full platform feature (future, beyond Phase 3) |

> **Phase 3 scope**: C1 (Metadata Generation) + C2 (YouTube publishing only). TikTok and Instagram defer to Phase 4 due to API complexity.

### C1: Metadata Generation

#### New API Endpoint

```
POST /v1/projects/{project_id}/jobs/{job_id}/metadata
```

**Request body:**
```json
{
  "platforms": ["youtube", "tiktok", "instagram"],
  "product_keywords": ["wireless earbuds", "noise cancelling", "bluetooth 5.3"]
}
```

**Response:**
```json
{
  "youtube": {
    "title": "Premium Noise-Cancelling Wireless Earbuds | 48H Battery Life",
    "description": "Experience crystal-clear audio with our premium wireless earbuds...\n\n🎧 Key Features:\n• Active Noise Cancellation\n• 48-hour battery life...",
    "tags": ["wireless earbuds", "noise cancelling", "bluetooth earbuds", "best earbuds 2026"],
    "category": "Science & Technology"
  },
  "tiktok": {
    "caption": "These earbuds just changed everything 🎧✨ #wirelessearbuds #techreview #novareel",
    "hashtags": ["#wirelessearbuds", "#techreview", "#novareel", "#gadgets"]
  },
  "instagram": {
    "caption": "Say goodbye to tangled wires ✨\n\nOur premium wireless earbuds deliver...",
    "hashtags": ["#wirelessearbuds", "#techgadgets", "#productreview"]
  }
}
```

#### New Files (C1)

```
services/backend/app/services/metadata.py   # LLM-based metadata generation
```

### C2: YouTube Publishing

#### New API Endpoints

```
GET  /v1/social/auth/youtube              → Redirect to Google OAuth consent
GET  /v1/social/auth/youtube/callback     → Handle OAuth callback, store tokens
POST /v1/projects/{project_id}/jobs/{job_id}/publish/youtube  → Upload video to YouTube
GET  /v1/social/connections                → List connected social accounts
DELETE /v1/social/connections/{platform}   → Disconnect account
```

#### New Files (C2)

```
services/backend/app/services/social/
├── __init__.py
├── base.py              # Abstract SocialPublisher interface
├── youtube.py           # YouTube Data API v3 integration
└── oauth.py             # OAuth flow handling + token storage
```

### `social/base.py`

```python
from abc import ABC, abstractmethod

class SocialPublisher(ABC):
    """Abstract interface for social media publishing."""

    @abstractmethod
    def publish_video(
        self,
        video_path: str,
        metadata: dict,
        thumbnail_path: str | None = None,
    ) -> dict:
        """Publish a video to the platform. Returns platform-specific response (video ID, URL, etc.)."""
        ...

    @abstractmethod
    def get_auth_url(self, redirect_uri: str) -> str:
        """Generate OAuth authorization URL."""
        ...

    @abstractmethod
    def handle_callback(self, code: str) -> dict:
        """Exchange OAuth code for tokens. Returns token data."""
        ...
```

### Changes to Existing Files

| File | Change |
|------|--------|
| `models.py` | Add `SocialConnectionRecord`, `PublishRecord`, `MetadataResponse` models |
| `base.py` / `local.py` / `dynamo.py` | Add `set_social_connection()`, `get_social_connection()`, `list_social_connections()`, `delete_social_connection()`, `create_publish_record()` |
| `v1.py` | Add metadata generation + YouTube publish + social auth endpoints |
| `config/__init__.py` | Add `google_client_id`, `google_client_secret`, `social_redirect_base_url` |

### OAuth Token Security

- Tokens stored encrypted in repo (use `cryptography.fernet` with a per-deployment key)
- Refresh tokens auto-renewed before expiry
- Users can revoke access from the connections UI

### Mock AI Mode

When `use_mock_ai=True`:
```python
metadata = {
    "youtube": {"title": f"MOCK: {project.title}", "description": "Mock description", "tags": ["mock"]},
    "tiktok": {"caption": f"MOCK: {project.title} #mock"},
    "instagram": {"caption": f"MOCK: {project.title}"},
}
```

YouTube publishing is skipped entirely in mock mode — returns a fake video ID.

---

## 6. Feature D: Video Editor & Preview

> **Priority**: 🟠 High

### What It Does

After script generation (but before rendering), sellers see a **storyboard preview** in the browser showing each scene's image, script line, and timing. They can:
1. **Edit script lines** — fix wording, shorten/lengthen narration
2. **Reorder scenes** — drag-and-drop scene order
3. **Swap images** — assign a different uploaded image to a scene
4. **Regenerate a single scene** — re-run LLM on one specific scene
5. **Preview audio** — play TTS sample for each line before full render
6. **Approve and render** — only render after seller approval

This transforms the workflow from "black box → download" into "generate → review → edit → render → download."

### Pipeline Change: Two-Stage Generation

#### Current Pipeline (Phases 1-2):
```
ANALYZING → SCRIPTING → MATCHING → NARRATION → RENDERING → COMPLETED
```

#### New Pipeline (Phase 3):
```
ANALYZING → SCRIPTING → MATCHING → AWAITING_APPROVAL → (seller edits) → NARRATION → RENDERING → COMPLETED
```

The new `AWAITING_APPROVAL` stage pauses the pipeline after matching. The job status changes to `awaiting_approval` and the frontend shows the storyboard editor. When the seller clicks "Approve & Render," the pipeline resumes from NARRATION.

### New API Endpoints

```
GET  /v1/projects/{project_id}/jobs/{job_id}/storyboard   → Get editable storyboard
PUT  /v1/projects/{project_id}/jobs/{job_id}/storyboard   → Save edited storyboard
POST /v1/projects/{project_id}/jobs/{job_id}/approve       → Resume pipeline from NARRATION
POST /v1/projects/{project_id}/jobs/{job_id}/scenes/{order}/regenerate → Re-run LLM for one scene
POST /v1/projects/{project_id}/jobs/{job_id}/scenes/{order}/preview-audio → Get TTS sample for one line
```

### Storyboard Editor UI

```
┌─ Storyboard Editor ───────────────────────────────────────────────┐
│                                                                     │
│  Scene 1/6                                          [⟳ Regenerate] │
│  ┌──────────┐  ┌─────────────────────────────────────────────┐     │
│  │          │  │ Discover the future of wireless audio —     │     │
│  │  [IMG]   │  │ premium sound meets all-day comfort.        │     │
│  │          │  │                                    [▶ Play] │     │
│  └──────────┘  └─────────────────────────────────────────────┘     │
│  [Change Image ▾]                    Duration: 5.2s                │
│                                                                     │
│  ─── ─── ─── ─── ─── ─── ─── ─── ─── ─── ─── ─── ─── ─── ───   │
│                                                                     │
│  Scene 2/6                                          [⟳ Regenerate] │
│  ┌──────────┐  ┌─────────────────────────────────────────────┐     │
│  │          │  │ Featuring industry-leading noise cancellation│     │
│  │  [IMG]   │  │ that blocks out the world around you.        │     │
│  │          │  │                                    [▶ Play] │     │
│  └──────────┘  └─────────────────────────────────────────────┘     │
│  [Change Image ▾]                    Duration: 4.8s                │
│                                                                     │
│  ... (scenes 3-6) ...                                               │
│                                                                     │
│  [Cancel]                                    [✓ Approve & Render]  │
└─────────────────────────────────────────────────────────────────────┘
```

### New Files

```
services/backend/app/services/storyboard_editor.py   # Storyboard edit/validate logic
```

### Changes to Existing Files

| File | Change |
|------|--------|
| `models.py` | Add `AWAITING_APPROVAL` to `JobStatus` enum; add `auto_approve: bool = True` to `GenerateRequest` / `JobCreateParams` (backward compat: defaults to auto-approve, preserving current behavior) |
| `pipeline.py` | After MATCHING, if `auto_approve=False`, save storyboard as intermediate artifact and set status to `AWAITING_APPROVAL`; add `resume_from_approval()` function |
| `v1.py` | Add storyboard GET/PUT, approve, regenerate-scene, and preview-audio endpoints |
| `base.py` / `local.py` / `dynamo.py` | Add `auto_approve` to `JobCreateParams` |

### Backward Compatibility

**`auto_approve=True` (default)**: Pipeline behaves exactly as today — no pause, no editor. Existing integrations and API callers are unaffected.

**`auto_approve=False`**: Pipeline pauses at `AWAITING_APPROVAL`. Frontend shows the storyboard editor. Resume via POST `/approve`.

---

## 7. Feature E: A/B Video Variants

> **Priority**: 🟡 Medium

### What It Does

Generate **multiple video variants** from the same product in one click. Each variant uses a different script template, voice style, or transition — letting sellers test which style performs best on each platform.

### How It Works

```
POST /v1/projects/{project_id}/generate-variants
```

**Request body:**
```json
{
  "variants": [
    {"script_template": "product_showcase", "voice_style": "energetic", "transition_style": "crossfade"},
    {"script_template": "problem_solution", "voice_style": "professional", "transition_style": "slide_left"},
    {"script_template": "testimonial", "voice_style": "friendly", "transition_style": "dissolve"}
  ],
  "shared": {
    "aspect_ratio": "9:16",
    "language": "en",
    "voice_provider": "edge_tts",
    "caption_style": "word_highlight",
    "background_music": "auto"
  }
}
```

**Response:** Array of 3 `GenerationJobRecord` objects, one per variant. All share the same ANALYZING and MATCHING stages (optimization: analyze images once, reuse across variants).

### Optimization: Shared Image Analysis

```
Variant 1 ──┐
Variant 2 ──┼── Shared ANALYZING → Shared MATCHING → Per-variant SCRIPTING → NARRATION → RENDERING
Variant 3 ──┘
```

The first variant performs image analysis and caches it. Subsequent variants skip ANALYZING and load from cache. This cuts 2/3 of the AI cost for a 3-variant generation.

### New Files

```
services/backend/app/services/pipeline_variants.py   # Variant generation orchestrator
```

### Changes to Existing Files

| File | Change |
|------|--------|
| `models.py` | Add `GenerateVariantsRequest` model; add `variant_group_id: str | None = None` to `GenerationJobRecord` |
| `v1.py` | Add `POST /v1/projects/{project_id}/generate-variants` endpoint |
| `pipeline.py` | Accept optional `cached_analysis_prefix` to skip ANALYZING for variant jobs |

---

## 8. Feature F: Performance & Scalability

> **Priority**: 🟠 High  
> **Reference**: `docs/ShortGPT_Integration_Analysis.md` §14 — Performance Optimizations

### What It Does

Optimize the video generation pipeline for throughput and latency. Current state: single-threaded worker, sequential segment rendering, no parallelism. Target state: **3-5x faster generation** and **10x throughput** via Celery task distribution.

### Performance Improvements

| Optimization | Current | Target | How |
|-------------|---------|--------|-----|
| **Segment rendering** | Sequential (1 segment at a time) | Parallel (all segments concurrently) | `concurrent.futures.ProcessPoolExecutor` |
| **TTS synthesis** | Sequential (1 line at a time) | Parallel (all lines concurrently) | `asyncio.gather()` for async TTS providers (EdgeTTS, ElevenLabs) |
| **Worker architecture** | Polling loop (`worker.py`) | Celery + Redis/SQS task queue | Celery workers auto-scale, distributed |
| **FFmpeg preset** | `medium` (default) | `veryfast` for draft, `medium` for final | Configurable via `NOVAREEL_FFMPEG_PRESET` |
| **CDN delivery** | Direct S3/local URLs | CloudFront CDN with edge caching | CloudFront distribution for `video_url` |
| **Image caching** | Re-download per render | Cache resolved images in temp dir | Skip S3 GET if image already local |

### Celery Task Architecture

```
                    ┌─────────────┐
  API Server ──────→│  Redis/SQS  │
                    │   Broker    │
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              ↓            ↓            ↓
        ┌──────────┐ ┌──────────┐ ┌──────────┐
        │ Worker 1 │ │ Worker 2 │ │ Worker 3 │
        │ (Celery) │ │ (Celery) │ │ (Celery) │
        └──────────┘ └──────────┘ └──────────┘
```

#### Migration Path

The current `worker.py` polling loop is replaced by Celery tasks **without changing the pipeline logic**:

```python
# tasks.py — Celery task wrapper
from celery import Celery

app = Celery('novareel', broker=settings.celery_broker_url)

@app.task(bind=True, max_retries=3)
def process_generation(self, job_id: str):
    """Wraps existing process_generation_job() as a Celery task."""
    from app.services.pipeline import process_generation_job
    # ... same logic, but Celery handles retry/DLQ/concurrency
    ...

@app.task(bind=True, max_retries=3)
def process_translation(self, job_id: str):
    """Wraps existing translation pipeline as a Celery task."""
    ...
```

### New Files

```
services/backend/app/tasks.py              # Celery task definitions
services/backend/celery_config.py          # Celery configuration
services/backend/app/services/parallel.py  # Parallel segment rendering utility
```

### Changes to Existing Files

| File | Change |
|------|--------|
| `worker.py` | Add `--mode` flag: `--mode=polling` (current) or `--mode=celery` (new). Default remains polling for backward compat. |
| `pipeline.py` | Refactor RENDERING stage to use `parallel.py` for concurrent segment rendering |
| `video.py` | Extract single-segment rendering into `render_segment()` method callable in parallel |
| `config/__init__.py` | Add `celery_broker_url`, `ffmpeg_preset`, `cdn_base_url`, `worker_mode` settings |
| `v1.py` | Use `cdn_base_url` prefix for video/asset URLs when configured |

### CDN Delivery

```python
# In pipeline.py, after rendering
if settings.cdn_base_url:
    video_url = f'{settings.cdn_base_url}/{video_key}'
else:
    video_url = storage.get_public_url(video_key)
```

CloudFront configuration is handled via Terraform/CDK (out of scope for this plan, but the app code must support it).

---

## 9. Frontend Changes (All Features)

### Brand Kit Settings Page

New page at `/dashboard/brand-kit`:
```
┌─ Brand Kit ──────────────────────────────────────────────────┐
│                                                                │
│  Brand Name: [TechGadgets Pro          ]                       │
│                                                                │
│  Colors:                                                       │
│  Primary [■ #1E40AF]  Secondary [■ #F59E0B]  Accent [■ #10B981]│
│                                                                │
│  Logo:      [logo.png]     [Change]  [Remove]                  │
│  Font:      [Inter-Bold]   [Change]  [Remove]                  │
│  Intro:     [intro.mp4]    [Change]  [Remove]                  │
│  Outro:     [outro.mp4]    [Change]  [Remove]                  │
│                                                                │
│  Music Library:                                                │
│  ♫ corporate_theme.mp3    [Remove]                             │
│  ♫ upbeat_jingle.mp3      [Remove]                             │
│  [+ Add Music]                                                 │
│                                                                │
│  [Save Brand Kit]                                              │
└────────────────────────────────────────────────────────────────┘
```

### Storyboard Editor (Feature D)

As shown in [Feature D section](#6-feature-d-video-editor--preview). New component: `StoryboardEditor.tsx`.

### Generation Form Updates

```
┌──────────────────────┬──────────────────────┐
│ ... Phase 2 fields ...                       │  (existing)
├──────────────────────┼──────────────────────┤
│ □ Review before      │ □ Generate A/B       │  (Phase 3 — D, E)
│   rendering          │   variants (3)       │
└──────────────────────┴──────────────────────┘
```

### Completed Video Card — Social Publishing

```
┌────────────────────────────────────────────────────┐
│  ▶ Product Video — English                          │
│  Duration: 32s · Polly · Crossfade                  │
│                                                      │
│  [Download]  [🌐 Translate]  [📤 Publish]  [Delete] │
└────────────────────────────────────────────────────┘
```

Clicking "📤 Publish" opens:
```
┌─ Publish Video ──────────────────────────────┐
│                                                │
│  YouTube    [✓ Connected]    [Publish]          │
│  TikTok    [Connect Account]                   │
│  Instagram [Connect Account]                   │
│                                                │
│  ── Generated Metadata ──────────────────────  │
│  Title: [Premium Wireless Earbuds | 48H Batt]  │
│  Description: [Experience crystal-clear...]     │
│  Tags: [wireless earbuds, noise cancelling]     │
│                                                │
│  [✏️ Edit Metadata]         [Publish to YouTube]│
└────────────────────────────────────────────────┘
```

### Social Connections Page

New page at `/dashboard/connections`:
```
┌─ Connected Accounts ─────────────────────────────┐
│                                                    │
│  YouTube    rajatsingh@gmail.com    [Disconnect]    │
│  TikTok    Not connected           [Connect]       │
│  Instagram Not connected           [Connect]       │
└────────────────────────────────────────────────────┘
```

---

## 10. Dependency & Infra Changes

### Python Dependencies (`pyproject.toml`)

```toml
# Phase 3 additions
"celery[redis]>=5.3"              # Feature F — distributed task queue
"redis>=5.0"                       # Feature F — Celery broker (local dev)
"google-api-python-client>=2.0"   # Feature C2 — YouTube Data API
"google-auth-oauthlib>=1.0"       # Feature C2 — Google OAuth
"cryptography>=41.0"              # Feature C — OAuth token encryption
```

### Environment Variables

```env
# Phase 3
NOVAREEL_WORKER_MODE=polling                # Feature F — polling (default) | celery
NOVAREEL_CELERY_BROKER_URL=redis://localhost:6379/0  # Feature F — Celery broker
NOVAREEL_FFMPEG_PRESET=medium               # Feature F — ultrafast|veryfast|medium
NOVAREEL_CDN_BASE_URL=                      # Feature F — CloudFront URL (empty = direct S3)
NOVAREEL_GOOGLE_CLIENT_ID=                  # Feature C2 — Google OAuth
NOVAREEL_GOOGLE_CLIENT_SECRET=              # Feature C2 — Google OAuth
NOVAREEL_SOCIAL_REDIRECT_BASE_URL=http://localhost:3000  # Feature C2 — OAuth callback
NOVAREEL_ENCRYPTION_KEY=                    # Feature C — Fernet key for token encryption
NOVAREEL_MAX_LIBRARY_ASSETS=50             # Feature A — per-user asset limit
```

### Docker Considerations

- Redis container for Celery broker (dev: `docker run -d redis:7-alpine`)
- Celery workers container (same image as API, different entrypoint: `celery -A app.tasks worker`)
- CDN configuration via CloudFormation/CDK (production only)

---

## 11. Testing Strategy

### Unit Tests

| Test | Feature | What to Assert |
|------|---------|----------------|
| `test_brand_kit_crud` | A | Create, read, update, delete brand kit |
| `test_brand_kit_merges_with_job_effects` | A | Per-job settings override brand kit defaults |
| `test_library_asset_upload_and_list` | A | Upload asset to library, list filtered by type |
| `test_library_asset_limit` | A | Exceeding `max_library_assets` returns 422 |
| `test_silence_trim` | B | Trimmed audio has no leading/trailing silence |
| `test_normalize_lufs` | B | Output audio is within 1dB of target LUFS |
| `test_speed_adjust_within_bounds` | B | Speed adjustment capped at 1.25x |
| `test_duck_music_lowers_during_speech` | B | Music volume drops when narration is active |
| `test_metadata_generation_per_platform` | C | YouTube gets title+desc+tags, TikTok gets caption+hashtags |
| `test_metadata_mock_mode` | C | Mock AI returns mock metadata |
| `test_youtube_publish_mock` | C2 | Mock publish returns fake video ID |
| `test_oauth_token_encryption` | C2 | Tokens encrypted at rest, decryptable with key |
| `test_storyboard_edit_validates_line_count` | D | Edited storyboard preserves scene count |
| `test_storyboard_approve_resumes_pipeline` | D | POST /approve transitions job to NARRATION |
| `test_auto_approve_true_skips_editor` | D | Default behavior: pipeline doesn't pause |
| `test_variant_generation_reuses_analysis` | E | Second variant job skips ANALYZING |
| `test_parallel_segment_rendering` | F | All segments rendered, output matches sequential |
| `test_celery_task_wraps_pipeline` | F | Celery task calls process_generation_job correctly |

### Integration Tests

| Test | What to Assert |
|------|----------------|
| Full generation with brand kit (mock AI) | Brand logo + intro/outro in output video |
| Audio processing pipeline end-to-end | Output audio normalized, silence-trimmed |
| Metadata generation + YouTube publish flow (mock) | Metadata generated, mock publish returns success |
| Storyboard edit → approve → render (mock AI) | Edit persisted, pipeline resumes, job completes |
| A/B variant generation (mock AI) | 3 jobs created, shared analysis, all completed |
| Celery task queue processing (mock AI) | Job enqueued, worker picks up, completes |

### Manual QA Checklist

- [ ] Upload logo + set brand colors → generate video → verify logo watermark + colored title card
- [ ] Upload custom intro clip → generate video → verify intro plays at start
- [ ] Generate video → check audio volume consistency across scenes
- [ ] Generate video → click Publish → verify metadata populated → publish to YouTube (staging)
- [ ] Generate with `auto_approve=false` → verify storyboard editor appears → edit a script line → approve → verify edited line in final video
- [ ] Generate 3 A/B variants → verify different scripts/styles in each
- [ ] Compare generation time: polling worker vs. Celery worker (should be <10% overhead)

---

## 12. Sprint Plan

### Sprint 6 (Weeks 1-2): Brand Kit + Audio Processing

| Day | Task | Feature | Depends On |
|-----|------|---------|------------|
| D1 | Define `BrandKitRecord`, `LibraryAssetRecord` models | A | — |
| D1-D2 | Implement brand kit + library asset CRUD in repo layer | A | models |
| D2 | Add brand kit + library API endpoints | A | repo layer |
| D2-D3 | Create `brand.py` — brand kit resolution + effects merge | A | endpoints |
| D3 | Integrate brand kit into generation pipeline (logo, colors, intro/outro) | A | brand.py |
| D3-D4 | Create `audio.py` — silence trim, normalize, speed adjust | B | — |
| D4 | Implement audio ducking + music crossfade | B | audio.py |
| D5 | Integrate audio processing into pipeline (replace static mixing) | B | audio.py |
| D5 | Frontend: brand kit settings page | A | API done |
| D6-D7 | Integration testing, bug fixes | All | everything |

**Sprint 6 deliverable**: Brand Kit system with logo/intro/outro, professional audio processing.

### Sprint 7 (Weeks 3-4): Social Media Distribution

| Day | Task | Feature | Depends On |
|-----|------|---------|------------|
| D1 | Create `metadata.py` — LLM-based metadata generation for YouTube/TikTok/Instagram | C1 | — |
| D1-D2 | Add metadata generation endpoint + mock AI mode | C1 | metadata.py |
| D2-D3 | Create `social/youtube.py` — YouTube Data API v3 integration | C2 | — |
| D3 | Create `social/oauth.py` — Google OAuth flow + encrypted token storage | C2 | youtube.py |
| D3-D4 | Add YouTube publish endpoint, OAuth endpoints | C2 | oauth.py |
| D4-D5 | Frontend: publish modal, metadata editor, social connections page | C1, C2 | API done |
| D5-D6 | YouTube end-to-end testing (staging credentials) | C2 | frontend done |
| D6-D7 | Integration testing, bug fixes | All | everything |

**Sprint 7 deliverable**: Auto-generated metadata, YouTube publishing, social account management.

### Sprint 8 (Weeks 5-6): Video Editor + A/B Variants

| Day | Task | Feature | Depends On |
|-----|------|---------|------------|
| D1 | Add `AWAITING_APPROVAL` status, `auto_approve` flag to models | D | — |
| D1-D2 | Implement storyboard pause/resume in pipeline | D | models |
| D2-D3 | Add storyboard GET/PUT, approve, regenerate-scene, preview-audio endpoints | D | pipeline |
| D3-D4 | Frontend: `StoryboardEditor.tsx` component | D | API done |
| D4 | Create `pipeline_variants.py` — shared analysis + per-variant generation | E | — |
| D4-D5 | Add generate-variants endpoint, `variant_group_id` tracking | E | pipeline_variants.py |
| D5 | Frontend: A/B variant toggle in generation form + variant comparison UI | E | API done |
| D6-D7 | Integration testing, bug fixes | All | everything |

**Sprint 8 deliverable**: Storyboard editor with pre-render review, A/B video variants.

### Sprint 9 (Weeks 7-8): Performance & Scalability

| Day | Task | Feature | Depends On |
|-----|------|---------|------------|
| D1 | Extract `render_segment()` from `video.py` for parallel execution | F | — |
| D1-D2 | Implement parallel segment rendering with `ProcessPoolExecutor` | F | render_segment |
| D2-D3 | Create `tasks.py` — Celery task wrappers for generation/translation | F | — |
| D3 | Create `celery_config.py` + Docker Compose for Redis | F | tasks.py |
| D3-D4 | Add async TTS synthesis for EdgeTTS/ElevenLabs (parallel all lines) | F | — |
| D4-D5 | CDN URL support: `cdn_base_url` prefix in pipeline + API responses | F | — |
| D5-D6 | Performance benchmarking: sequential vs. parallel rendering, polling vs. Celery | F | all above |
| D6-D7 | Final QA, documentation, Phase 3 sign-off | All | everything |

**Sprint 9 deliverable**: 3-5x faster rendering, Celery-based worker architecture, CDN delivery.

---

## 13. Acceptance Criteria

### Feature A: Brand Kit & Asset Library
- [ ] Seller uploads logo → generates video → logo appears as watermark in corner
- [ ] Seller sets brand colors → title card and CTA use brand colors
- [ ] Seller uploads intro clip → video starts with branded intro
- [ ] Seller uploads custom music → music used when `background_music=auto`
- [ ] Library enforces max asset limit (50) per user
- [ ] Brand kit works with translations (logo/intro persists across languages)

### Feature B: Audio Processing
- [ ] Generated narration has no leading/trailing silence in final video
- [ ] Volume consistent across all narration segments (within 2dB)
- [ ] Music ducks under speech (noticeably lower during narration)
- [ ] If narration exceeds segment duration, auto-sped up (max 1.25x)
- [ ] Audio processing works with all TTS providers (Polly, EdgeTTS, ElevenLabs)

### Feature C: Social Media Distribution
- [ ] Click "Generate Metadata" → platform-specific titles/descriptions/hashtags generated
- [ ] Generated metadata is relevant to product (not generic)
- [ ] YouTube OAuth flow: connect → publish → video appears on channel
- [ ] OAuth tokens stored encrypted at rest
- [ ] Users can disconnect social accounts
- [ ] Mock AI mode works for metadata generation

### Feature D: Video Editor & Preview
- [ ] `auto_approve=false` → pipeline pauses after MATCHING → storyboard editor shown
- [ ] Seller edits script line → final video uses edited text
- [ ] Seller clicks "Regenerate" on a scene → only that scene re-runs LLM
- [ ] Seller clicks "Play" on a scene → hears TTS preview for that line
- [ ] `auto_approve=true` (default) → pipeline runs uninterrupted (backward compat)

### Feature E: A/B Video Variants
- [ ] Generate 3 variants → 3 different jobs created, all from same project
- [ ] Variants reuse image analysis (only first variant runs ANALYZING)
- [ ] All 3 variants complete successfully with noticeably different scripts
- [ ] Variant group visible in frontend (grouped under same project)

### Feature F: Performance & Scalability
- [ ] Parallel rendering: 3-5x faster than sequential for 6-segment video
- [ ] Celery workers: jobs processed correctly via Redis broker
- [ ] CDN URLs: video plays correctly from CloudFront URL (when configured)
- [ ] `NOVAREEL_WORKER_MODE=polling` → current behavior (backward compat)
- [ ] Async TTS: all 6 narration segments synthesized in parallel where provider supports it

---

## 14. Risks & Mitigations

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| **YouTube API quota limits** | Publishing throttled (10,000 units/day default) | Medium | Apply for quota increase; batch uploads; implement rate-limit retry |
| **Google OAuth review** | YouTube publishing requires Google app verification (may take weeks) | High | Start OAuth verification process in Sprint 6 (before C2 development); use "testing" mode for internal users |
| **Celery + Redis complexity** | New infrastructure dependency | Medium | Keep `worker.py` polling mode as fallback; Celery is opt-in via `NOVAREEL_WORKER_MODE` |
| **Parallel rendering stability** | FFmpeg segfaults under concurrent execution | Medium | Use process pool (not threads) for isolation; cap concurrency at `min(cpu_count, 4)` |
| **Brand kit storage costs** | Users upload large video intro/outro clips | Low | Enforce 5s max duration + 50MB max file size for video assets; 5MB for images |
| **Storyboard editor UX complexity** | Feature too complex for MVP | Medium | Ship minimal editor first (edit text only); add drag-and-drop and image swap in follow-up |
| **OAuth token security** | Token leak = unauthorized publishing | High | Fernet encryption at rest; refresh token rotation; audit log for all publish actions |
| **A/B variant cost** | 3 variants = 3x AI cost | Low | Shared ANALYZING saves ~30% cost; clearly show cost estimate in UI before generation |

---

## Appendix: Feature Coverage Map (Phase 1 → Phase 3)

This table maps every feature from the ShortGPT Integration Analysis to its delivery phase:

| ShortGPT Analysis Section | Feature | Phase |
|---|---|---|
| §1 Multi-Language Video Generation | Multi-Language Support | ✅ P1 |
| §2 Multiple TTS Engines | Multi-Provider TTS | ✅ P1 |
| §3 Video Translation & Dubbing | Translation Engine | 🔲 P2 |
| §4 Word-Level Caption Timing | Word-Level Captions | 🔲 P2 |
| §5 Stock Footage & Image Sourcing | Stock Footage (Pexels) | 🔲 P2 |
| §6 Background Music Engine | Background Music | ✅ P1 |
| §7 Advanced Video Transitions | Video Transitions & Effects | 🔲 P2 |
| §8 Resumable Pipeline | Resumable Pipeline | ✅ P1 |
| §9 LLM-Oriented Editing Framework | Video Editor & Preview (D) | 🔲 **P3** |
| §10 Script Variety & Templates | Script Templates | 🔲 P2 |
| §11 Asset Library System | Brand Kit & Asset Library (A) | 🔲 **P3** |
| §12 Social Media Distribution | Social Media Distribution (C) | 🔲 **P3** |
| §13 Audio Processing Pipeline | Audio Processing (B) | 🔲 **P3** |
| §14 Performance Optimizations | Performance & Scalability (F) | 🔲 **P3** |
| — (new) | A/B Video Variants (E) | 🔲 **P3** |

> After Phase 3, **all 14 features** from the ShortGPT analysis will be addressed, plus one original feature (A/B variants) not in the competitor.

## Appendix: New Files Summary

```
services/backend/
├── app/
│   ├── services/
│   │   ├── brand.py                # Feature A — brand kit resolution
│   │   ├── audio.py                # Feature B — audio processing pipeline
│   │   ├── metadata.py             # Feature C — LLM platform metadata
│   │   ├── social/
│   │   │   ├── __init__.py
│   │   │   ├── base.py             # Feature C — abstract publisher
│   │   │   ├── youtube.py          # Feature C — YouTube Data API
│   │   │   └── oauth.py            # Feature C — OAuth flow + tokens
│   │   ├── storyboard_editor.py    # Feature D — edit/validate logic
│   │   ├── pipeline_variants.py    # Feature E — variant orchestrator
│   │   └── parallel.py             # Feature F — parallel rendering
│   └── tasks.py                    # Feature F — Celery task definitions
├── celery_config.py                # Feature F — Celery configuration
└── docker-compose.redis.yml        # Feature F — Redis for local dev
```

## Appendix: Full Model Additions (Phase 3)

```python
# models.py — Brand Kit
class BrandKitRecord(BaseModel):
    owner_id: str
    brand_name: str = ''
    primary_color: str = '#1E40AF'
    secondary_color: str = '#F59E0B'
    accent_color: str = '#10B981'
    logo_asset_id: str | None = None
    font_asset_id: str | None = None
    intro_clip_asset_id: str | None = None
    outro_clip_asset_id: str | None = None
    custom_music_asset_ids: list[str] = Field(default_factory=list)
    updated_at: datetime


# models.py — Library Asset
class LibraryAssetRecord(BaseModel):
    id: str
    owner_id: str
    asset_type: Literal['logo', 'font', 'intro_clip', 'outro_clip', 'music', 'image']
    filename: str
    content_type: str
    file_size: int
    object_key: str
    created_at: datetime


# models.py — Social Connection
class SocialConnectionRecord(BaseModel):
    id: str
    owner_id: str
    platform: Literal['youtube', 'tiktok', 'instagram']
    platform_user_id: str
    platform_username: str
    encrypted_access_token: str
    encrypted_refresh_token: str
    token_expires_at: datetime
    connected_at: datetime


# models.py — Publish Record
class PublishRecord(BaseModel):
    id: str
    owner_id: str
    job_id: str
    platform: str
    platform_video_id: str
    platform_url: str
    metadata_used: dict[str, Any] = Field(default_factory=dict)
    published_at: datetime


# models.py — JobStatus additions
class JobStatus(str, Enum):
    # ... existing ...
    AWAITING_APPROVAL = 'awaiting_approval'    # Feature D


# models.py — GenerateVariantsRequest
class GenerateVariantsRequest(BaseModel):
    variants: list[dict[str, Any]]   # Each dict is a partial JobCreateParams override
    shared: dict[str, Any]           # Shared params applied to all variants


# models.py — JobCreateParams additions
class JobCreateParams(BaseModel):
    # ... existing Phase 2 fields ...
    auto_approve: bool = True                   # Feature D
    variant_group_id: str | None = None         # Feature E
```
