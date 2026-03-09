# NovaReel Phase 1 Enhancement — Development Handoff Document

> **Status**: Ready for development
> **Timeline**: 4 weeks (2 sprints)
> **Team**: 1-2 backend devs, 1 frontend dev
> **Prerequisite reading**: Skim the existing codebase structure below before starting any task

---

## Table of Contents

1. [Project Context](#1-project-context)
2. [Codebase Map](#2-codebase-map)
3. [Current Generation Pipeline](#3-current-generation-pipeline)
4. [Phase 1 Scope](#4-phase-1-scope)
5. [Feature A: Multi-Provider TTS Engine](#5-feature-a-multi-provider-tts-engine)
6. [Feature B: Background Music Engine](#6-feature-b-background-music-engine)
7. [Feature C: Multi-Language Support](#7-feature-c-multi-language-support)
8. [Feature D: Resumable Pipeline](#8-feature-d-resumable-pipeline)
9. [Frontend Changes (All Features)](#9-frontend-changes-all-features)
10. [Dependency & Infra Changes](#10-dependency--infra-changes)
11. [Testing Strategy](#11-testing-strategy)
12. [Sprint Plan](#12-sprint-plan)
13. [Acceptance Criteria](#13-acceptance-criteria)

---

## 1. Project Context

**NovaReel** is an AI-powered product video generator for e-commerce sellers. Sellers upload product images + description → the system generates a 30-60 second marketing video with narration and subtitles.

**Tech stack**: Next.js 14 frontend, FastAPI backend, FFmpeg video rendering, Amazon Bedrock (Nova models) for AI, AWS Polly for TTS, DynamoDB/JSON for storage.

**What this phase delivers**: 4 features that transform NovaReel from a basic English-only Polly-only video generator into a multi-language, multi-voice, music-enabled platform with crash-resilient pipeline.

---

## 2. Codebase Map

You'll be working across these files. Read them before starting.

### Backend (`services/backend/`)

| File | What It Does | You'll Change It For |
|------|-------------|---------------------|
| `app/models.py` | Pydantic request/response models | A, B, C — new fields on `GenerateRequest` and `GenerationJobRecord` |
| `app/config.py` | Settings loaded from env vars | A, B, C — new config keys |
| `app/api/v1.py` | All REST endpoints | A, B, C — pass new fields through `enqueue_generation()` |
| `app/services/nova.py` | AI operations: image analysis, script gen, TTS | A — remove `synthesize_voice()`. C — modify `generate_script()` prompt |
| `app/services/pipeline.py` | Worker pipeline: 6 stages from ANALYZING → COMPLETED | A, B, C, D — narration stage, music mixing, language, checkpointing |
| `app/services/video.py` | FFmpeg video rendering, Ken Burns, subtitle burn-in | B — add music muxing step |
| `app/repositories/base.py` | Abstract repository interface | A, C — update `create_job()` signature |
| `app/repositories/local.py` | JSON file-based repository | A, C — pass new fields through `create_job()` |
| `app/repositories/dynamo.py` | DynamoDB repository | A, C — same |
| `app/dependencies.py` | Dependency injection (lru_cache singletons) | Possibly add voice provider factory |
| `worker.py` | Poll-based worker loop | D — pass settings to pipeline |
| `pyproject.toml` | Python dependencies | A — add `edge-tts` |

### Frontend (`apps/web/`)

| File | What It Does | You'll Change It For |
|------|-------------|---------------------|
| `lib/contracts.ts` | TypeScript type definitions | A, B, C — new fields on `GenerationJob` |
| `lib/api.ts` | API client functions | A, B, C — update `generateProject()` input type |
| `components/project-studio.tsx` | Main form + video preview UI | A, B, C — new dropdown controls |

---

## 3. Current Generation Pipeline

Understanding the current flow is critical. Read `pipeline.py` (175 lines) in full.

```
API Request                    Worker Pipeline (pipeline.py)
─────────                      ──────────────────────────────
POST /generate
  → create_job()               process_generation_job():
  → queue.enqueue()              │
                                 ├─ ANALYZING (10%)  → nova.analyze_images()
                                 ├─ SCRIPTING (25%)  → nova.generate_script()
                                 ├─ MATCHING  (45%)  → nova.match_images()
                                 ├─ NARRATION (70%)  → nova.synthesize_voice()  ← POLLY ONLY
                                 ├─ RENDERING (90%)  → video_service.render_video()
                                 └─ COMPLETED (100%) → store results
```

**Key current limitations this phase fixes:**
- `synthesize_voice()` always uses Polly `VoiceId='Joanna'` — ignores `voice_style` param entirely
- No background music — video has narration audio only
- Script always generated in English — hardcoded prompt
- On failure, entire pipeline restarts from scratch (no stage checkpointing)

---

## 4. Phase 1 Scope

| Feature | What | Why | Effort |
|---------|------|-----|--------|
| **A. Multi-Provider TTS** | 3 TTS engines: Polly, EdgeTTS (free), ElevenLabs (premium) | Voice quality is #1 video differentiator. EdgeTTS gives 50+ languages for free | 1.5 weeks |
| **B. Background Music** | Mix royalty-free music into video at low volume behind narration | Narration-only videos feel amateur. Massive perceived quality boost | 1 week |
| **C. Multi-Language** | Generate scripts and narration in any of 50+ languages | Amazon has sellers in 20+ countries. Immediate competitive moat | 1 week |
| **D. Resumable Pipeline** | Save intermediate artifacts; on retry, skip completed stages | Saves Bedrock API costs on retries, reduces retry latency by 30-60s | 1 week |

---

## 5. Feature A: Multi-Provider TTS Engine

> **Detailed spec**: See `docs/TTS_Multi_Provider_Technical_Spec.md` for complete task-by-task breakdown with line numbers.
>
> **Summary below** — refer to the detailed spec for implementation.

### What Changes

**New files to create:**
```
services/backend/app/services/voice/
├── __init__.py          # Re-exports
├── base.py              # Abstract VoiceProvider with synthesize(text, voice_gender) -> bytes
├── polly.py             # Extract from nova.py L365-390, add male/female voice mapping
├── edge_tts.py          # Microsoft EdgeTTS — free, 50+ languages, async internally
├── elevenlabs.py        # ElevenLabs REST API — premium quality, httpx-based
└── factory.py           # build_voice_provider(provider_name, settings) -> VoiceProvider
```

**Files to modify:**

| File | Change |
|------|--------|
| `models.py` L61-64 | Add `voice_provider: Literal['polly', 'edge_tts', 'elevenlabs'] = 'polly'` and `voice_gender: Literal['male', 'female'] = 'female'` to `GenerateRequest` |
| `models.py` L67-85 | Add `voice_provider: str = 'polly'` and `voice_gender: str = 'female'` to `GenerationJobRecord` |
| `config.py` L39-40 | Add `elevenlabs_api_key: str \| None = None` |
| `base.py` (repo) L56-65 | Add `voice_provider` and `voice_gender` params to `create_job()` |
| `local.py` L168-201 | Pass new fields through `create_job()` |
| `dynamo.py` L129-160 | Same |
| `v1.py` L193-200 | Pass `payload.voice_provider` and `payload.voice_gender` to `repo.create_job()` |
| `pipeline.py` L92-94 | Replace `nova.synthesize_voice()` with voice provider factory call |
| `nova.py` L365-390 | Remove `synthesize_voice()` method (dead code after migration) |
| `pyproject.toml` | Add `"edge-tts>=6.1.0"` to dependencies |

### Voice Mappings

**Polly:**
- female → `Joanna` (en-US Neural)
- male → `Matthew` (en-US Neural)

**EdgeTTS (English default — full language mapping in Feature C):**
- female → `en-AU-NatashaNeural`
- male → `en-AU-WilliamNeural`

**ElevenLabs:**
- female → `Rachel` (or first available female voice from API)
- male → `Adam` (or first available male voice from API)
- API: `POST https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream`
- Model: `eleven_multilingual_v2`
- Headers: `xi-api-key`, `Content-Type: application/json`

### Mock AI Mode

When `use_mock_ai=True`, bypass all providers in `pipeline.py`:
```python
audio_payload = f'MOCK-VOICE::{job.voice_provider}::{job.voice_gender}::{transcript}'.encode()
```

---

## 6. Feature B: Background Music Engine

### What It Does

Adds low-volume royalty-free background music to generated videos. Music plays behind the narration, not replacing it.

### New Files

```
services/backend/app/services/music.py       # Music selection logic
services/backend/assets/music/               # Directory for royalty-free MP3 files
  ├── upbeat.mp3
  ├── calm.mp3
  ├── corporate.mp3
  └── luxury.mp3
```

### Music Source

Curate 4-6 royalty-free tracks (~60 seconds each, loopable). Recommended sources:
- [Pixabay Music](https://pixabay.com/music/) (free, no attribution needed)
- [Mixkit](https://mixkit.co/free-stock-music/) (free)

Name them by mood: `upbeat.mp3`, `calm.mp3`, `corporate.mp3`, `luxury.mp3`.

### Changes to `models.py`

**`GenerateRequest`** — add:
```python
background_music: Literal['none', 'auto', 'upbeat', 'calm', 'corporate', 'luxury'] = 'auto'
```

**`GenerationJobRecord`** — add:
```python
background_music: str = 'auto'
```

### Changes to Repository Layer

Same pattern as Feature A — add `background_music` param to `create_job()` in `base.py`, `local.py`, `dynamo.py`. Pass through from `v1.py`.

### Music Selection Logic (`music.py`)

```python
# services/backend/app/services/music.py

from pathlib import Path
import random

MUSIC_DIR = Path(__file__).resolve().parents[2] / 'assets' / 'music'

# Auto-select mapping based on voice_style
AUTO_MAPPING = {
    'energetic': 'upbeat',
    'professional': 'corporate',
    'friendly': 'calm',
}

def select_music_path(background_music: str, voice_style: str) -> Path | None:
    """Return the path to a music file, or None if 'none'."""
    if background_music == 'none':
        return None

    if background_music == 'auto':
        mood = AUTO_MAPPING.get(voice_style, 'calm')
    else:
        mood = background_music

    music_file = MUSIC_DIR / f'{mood}.mp3'
    if music_file.exists():
        return music_file

    # Fallback: pick any available track
    available = list(MUSIC_DIR.glob('*.mp3'))
    return available[0] if available else None
```

### Changes to `video.py` — Music Muxing

In `render_video()`, after the existing audio mux step (L161-176), add a **music mux step**.

**Current audio mux** (L161-176): Combines video + narration → `muxed.mp4`

**New music mux** (add after L176): Combines muxed video + background music at low volume.

```
Location: After the existing "Mux audio" block, before "Thumbnail"
```

**Logic:**
1. `render_video()` needs a new parameter: `music_path: Path | None = None`
2. If `music_path` is not None and exists:
   ```
   ffmpeg -y -i muxed.mp4 -i music.mp3 \
     -filter_complex "[1:a]aloop=loop=-1:size=2e+09,volume=0.12[bg];[0:a][bg]amix=inputs=2:duration=first" \
     -c:v copy -c:a aac \
     final_with_music.mp4
   ```
   - `aloop=loop=-1` — loops the music track to match video length
   - `volume=0.12` — music at 12% volume so narration stays clear
   - `amix=inputs=2:duration=first` — output duration matches video, not music
   - `-c:v copy` — don't re-encode video, just re-encode audio
3. If music mux fails, fall back to the version without music (graceful degradation)

### Changes to `pipeline.py`

In the RENDERING stage (L106-112), pass the music path:

```python
from app.services.music import select_music_path

music_path = select_music_path(job.background_music, job.voice_style)

video_key, duration_sec, resolution, thumbnail_key = video_service.render_video(
    project=project,
    job_id=job.id,
    aspect_ratio=job.aspect_ratio,
    storyboard=storyboard,
    storage=storage,
    music_path=music_path,       # NEW
)
```

### Changes to `video.py` Signature

```python
def render_video(
    self,
    *,
    project: ProjectRecord,
    job_id: str,
    aspect_ratio: str,
    storyboard: list[StoryboardSegment],
    storage: StorageService,
    music_path: Path | None = None,     # NEW
) -> tuple[str, float, str, str | None]:
```

### Mock AI Mode

No special handling needed — background music works regardless of `use_mock_ai` since it doesn't use AI. The music files are static assets.

---

## 7. Feature C: Multi-Language Support

### What It Does

Sellers can generate scripts and narration in 50+ languages. The LLM generates the script directly in the target language, and the TTS engine uses language-appropriate voices.

### Changes to `models.py`

**`GenerateRequest`** — add:
```python
language: str = 'en'    # ISO 639-1 code: en, es, fr, de, ja, hi, ar, zh, etc.
```

**`GenerationJobRecord`** — add:
```python
language: str = 'en'
```

### Changes to Repository Layer

Add `language` param to `create_job()` in `base.py`, `local.py`, `dynamo.py`. Pass through from `v1.py`.

### Language Config (`services/backend/app/config/languages.py`)

Create a new config file with language metadata and EdgeTTS voice mappings.

```
services/backend/app/config/languages.py
```

**Contents** — a flat dict mapping ISO code → display name + EdgeTTS voices:

```python
SUPPORTED_LANGUAGES: dict[str, dict] = {
    'en': {
        'name': 'English',
        'edge_tts_female': 'en-AU-NatashaNeural',
        'edge_tts_male': 'en-AU-WilliamNeural',
        'polly_female': 'Joanna',
        'polly_male': 'Matthew',
        'elevenlabs_supported': True,
    },
    'es': {
        'name': 'Spanish',
        'edge_tts_female': 'es-AR-ElenaNeural',
        'edge_tts_male': 'es-AR-TomasNeural',
        'polly_female': 'Lucia',
        'polly_male': 'Sergio',
        'elevenlabs_supported': True,
    },
    'fr': {
        'name': 'French',
        'edge_tts_female': 'fr-CA-SylvieNeural',
        'edge_tts_male': 'fr-CA-AntoineNeural',
        'polly_female': 'Lea',
        'polly_male': 'Mathieu',
        'elevenlabs_supported': True,
    },
    'de': {
        'name': 'German',
        'edge_tts_female': 'de-DE-KatjaNeural',
        'edge_tts_male': 'de-DE-ConradNeural',
        'polly_female': 'Vicki',
        'polly_male': 'Daniel',
        'elevenlabs_supported': True,
    },
    'ar': {
        'name': 'Arabic',
        'edge_tts_female': 'ar-AE-FatimaNeural',
        'edge_tts_male': 'ar-AE-HamdanNeural',
        'polly_female': 'Zeina',
        'polly_male': None,            # Polly has limited Arabic male
        'elevenlabs_supported': True,
        'rtl': True,                    # Right-to-left script
    },
    'hi': {
        'name': 'Hindi',
        'edge_tts_female': 'hi-IN-SwaraNeural',
        'edge_tts_male': 'hi-IN-MadhurNeural',
        'polly_female': 'Aditi',
        'polly_male': None,
        'elevenlabs_supported': False,
    },
    'ja': {
        'name': 'Japanese',
        'edge_tts_female': 'ja-JP-NanamiNeural',
        'edge_tts_male': 'ja-JP-KeitaNeural',
        'polly_female': 'Mizuki',
        'polly_male': 'Takumi',
        'elevenlabs_supported': False,
    },
    'zh': {
        'name': 'Chinese',
        'edge_tts_female': 'zh-CN-XiaoxiaoNeural',
        'edge_tts_male': 'zh-CN-YunxiNeural',
        'polly_female': 'Zhiyu',
        'polly_male': None,
        'elevenlabs_supported': False,
    },
    'ko': {
        'name': 'Korean',
        'edge_tts_female': 'ko-KR-SunHiNeural',
        'edge_tts_male': 'ko-KR-InJoonNeural',
        'polly_female': 'Seoyeon',
        'polly_male': None,
        'elevenlabs_supported': False,
    },
    'pt': {
        'name': 'Portuguese',
        'edge_tts_female': 'pt-BR-FranciscaNeural',
        'edge_tts_male': 'pt-BR-AntonioNeural',
        'polly_female': 'Camila',
        'polly_male': 'Thiago',
        'elevenlabs_supported': True,
    },
    'it': {
        'name': 'Italian',
        'edge_tts_female': 'it-IT-ElsaNeural',
        'edge_tts_male': 'it-IT-DiegoNeural',
        'polly_female': 'Bianca',
        'polly_male': 'Adriano',
        'elevenlabs_supported': True,
    },
    'ru': {
        'name': 'Russian',
        'edge_tts_female': 'ru-RU-SvetlanaNeural',
        'edge_tts_male': 'ru-RU-DmitryNeural',
        'polly_female': 'Tatyana',
        'polly_male': 'Maxim',
        'elevenlabs_supported': False,
    },
    'tr': {
        'name': 'Turkish',
        'edge_tts_female': 'tr-TR-EmelNeural',
        'edge_tts_male': 'tr-TR-AhmetNeural',
        'polly_female': 'Filiz',
        'polly_male': None,
        'elevenlabs_supported': False,
    },
    'nl': {
        'name': 'Dutch',
        'edge_tts_female': 'nl-NL-FennaNeural',
        'edge_tts_male': 'nl-NL-MaartenNeural',
        'polly_female': 'Lotte',
        'polly_male': 'Ruben',
        'elevenlabs_supported': False,
    },
    'pl': {
        'name': 'Polish',
        'edge_tts_female': 'pl-PL-ZofiaNeural',
        'edge_tts_male': 'pl-PL-MarekNeural',
        'polly_female': 'Ewa',
        'polly_male': 'Jacek',
        'elevenlabs_supported': True,
    },
    'sv': {
        'name': 'Swedish',
        'edge_tts_female': 'sv-SE-SofieNeural',
        'edge_tts_male': 'sv-SE-MattiasNeural',
        'polly_female': 'Astrid',
        'polly_male': None,
        'elevenlabs_supported': False,
    },
    'th': {
        'name': 'Thai',
        'edge_tts_female': 'th-TH-PremwadeeNeural',
        'edge_tts_male': 'th-TH-NiwatNeural',
        'polly_female': None,
        'polly_male': None,
        'elevenlabs_supported': False,
    },
    'vi': {
        'name': 'Vietnamese',
        'edge_tts_female': 'vi-VN-HoaiMyNeural',
        'edge_tts_male': 'vi-VN-NamMinhNeural',
        'polly_female': None,
        'polly_male': None,
        'elevenlabs_supported': False,
    },
    'id': {
        'name': 'Indonesian',
        'edge_tts_female': 'id-ID-GadisNeural',
        'edge_tts_male': 'id-ID-ArdiNeural',
        'polly_female': None,
        'polly_male': None,
        'elevenlabs_supported': False,
    },
    'ms': {
        'name': 'Malay',
        'edge_tts_female': 'ms-MY-YasminNeural',
        'edge_tts_male': 'ms-MY-OsmanNeural',
        'polly_female': None,
        'polly_male': None,
        'elevenlabs_supported': False,
    },
}

def get_language_name(code: str) -> str:
    """Return display name for a language code, or the code itself if unknown."""
    lang = SUPPORTED_LANGUAGES.get(code)
    return lang['name'] if lang else code

def get_voice_name(code: str, provider: str, gender: str) -> str | None:
    """Return the TTS voice name for a language/provider/gender combination."""
    lang = SUPPORTED_LANGUAGES.get(code)
    if not lang:
        return None
    key = f'{provider}_{gender}'
    return lang.get(key)

def is_rtl(code: str) -> bool:
    """Return True if the language uses right-to-left script."""
    lang = SUPPORTED_LANGUAGES.get(code)
    return lang.get('rtl', False) if lang else False
```

**Note:** EdgeTTS supports ALL 50+ languages listed. Polly supports ~20. ElevenLabs supports ~8. If a seller picks a language + provider combination that isn't supported (e.g., Polly + Thai), the API should return a 422 with a clear message. Alternatively, auto-fallback to EdgeTTS — decide at implementation time.

### Changes to Script Generation (`nova.py`)

Modify `generate_script()` (L104-207) to accept and use a `language` parameter.

**Change the method signature:**
```python
def generate_script(
    self,
    project: ProjectRecord,
    image_analysis: list[dict] | None = None,
    language: str = 'en',          # NEW
) -> list[str]:
```

**Modify the prompt** (currently at L134-140):

**Before:**
```python
prompt = (
    'You are an expert video director and copywriter. '
    'Create a 6-scene marketing video script for this product. '
    ...
)
```

**After:**
```python
from app.config.languages import get_language_name

lang_name = get_language_name(language)

lang_instruction = ''
if language != 'en':
    lang_instruction = (
        f' Write ALL spoken narration text in {lang_name}. '
        f'The narration must be entirely in {lang_name} — do not use English. '
    )

prompt = (
    'You are an expert video director and copywriter. '
    'Create a 6-scene marketing video script for this product. '
    'You must use the render_video_plan tool to structure your output. '
    f'{lang_instruction}'
    f'Product: {project.title}. Description: {project.product_description}'
    f'{image_context}'
)
```

**Important**: The product title and description stay in whatever language the seller wrote them. The prompt tells the LLM to generate the narration in the target language. Amazon Nova Lite supports multilingual generation natively.

### Changes to Voice Provider (integrates with Feature A)

The voice providers from Feature A need to accept `language` to select the correct voice.

Update the `VoiceProvider.synthesize()` interface:
```python
def synthesize(self, text: str, voice_gender: str = 'female', language: str = 'en') -> bytes:
```

Each provider uses the language config to pick the right voice:
```python
from app.config.languages import get_voice_name

voice_name = get_voice_name(language, 'edge_tts', voice_gender)
# Returns e.g. 'ja-JP-NanamiNeural' for Japanese female EdgeTTS
```

### Changes to Pipeline (`pipeline.py`)

Pass `language` when calling `generate_script()` (L65) and `synthesize()`:

```python
script_lines = nova.generate_script(project, image_analysis=image_analysis, language=job.language)
```

```python
provider = build_voice_provider(job.voice_provider, settings)
audio_payload = provider.synthesize(transcript[:3000], voice_gender=job.voice_gender, language=job.language)
```

### Changes to `v1.py`

Pass `language` through from request to job creation. Same pattern as Feature A.

### RTL Subtitle Handling (Future — not in Phase 1 scope)

Arabic/Hebrew/Urdu right-to-left text in FFmpeg `drawtext` is complex. For Phase 1, RTL languages will still get narration but subtitles may render incorrectly. This is acceptable — mark as known limitation.

---

## 8. Feature D: Resumable Pipeline

### What It Does

Currently, if video rendering fails after narration completes, the retry re-runs ALL stages — re-calling Bedrock for image analysis, script generation, and matching. This wastes ~$0.10+ per retry and adds 30-60 seconds.

The fix: save intermediate results after each stage. On retry, skip stages that already have saved results.

### Changes to `GenerationJobRecord` (`models.py`)

Add a field to track the last successfully completed stage:
```python
last_completed_stage: str | None = None
```

### Changes to Pipeline (`pipeline.py`)

**The core idea:** Before each stage, check if the result already exists. After each stage, save the result.

**Storage keys for intermediate artifacts:**
```
projects/{project_id}/intermediate/{job_id}/image_analysis.json
projects/{project_id}/intermediate/{job_id}/script_lines.json
projects/{project_id}/intermediate/{job_id}/storyboard.json
projects/{project_id}/intermediate/{job_id}/narration.mp3
```

**Modified pipeline flow (pseudocode):**

```python
def process_generation_job(..., job: GenerationJobRecord) -> None:
    started = time.perf_counter()
    timings: dict[str, float] = {}
    prefix = f'projects/{project.id}/intermediate/{job.id}'

    # ── ANALYZING ──
    existing_analysis = storage.load_json(f'{prefix}/image_analysis.json')
    if existing_analysis:
        image_analysis = existing_analysis
        logger.info('Resuming: skipped ANALYZING (cached)')
    else:
        repo.update_job(job.id, status=JobStatus.ANALYZING, ...)
        image_analysis = nova.analyze_images(assets)
        storage.store_text(f'{prefix}/image_analysis.json', json.dumps(image_analysis))
        timings['analyzing_sec'] = ...

    # ── SCRIPTING ──
    existing_script = storage.load_json(f'{prefix}/script_lines.json')
    if existing_script:
        script_lines = existing_script
        logger.info('Resuming: skipped SCRIPTING (cached)')
    else:
        repo.update_job(job.id, status=JobStatus.SCRIPTING, ...)
        script_lines = nova.generate_script(project, image_analysis=image_analysis, language=job.language)
        storage.store_text(f'{prefix}/script_lines.json', json.dumps(script_lines))
        timings['scripting_sec'] = ...

    # ── MATCHING ──
    existing_storyboard = storage.load_json(f'{prefix}/storyboard.json')
    if existing_storyboard:
        storyboard = [StoryboardSegment(**s) for s in existing_storyboard]
        logger.info('Resuming: skipped MATCHING (cached)')
    else:
        repo.update_job(job.id, status=JobStatus.MATCHING, ...)
        storyboard = nova.match_images(script_lines, assets)
        storage.store_text(f'{prefix}/storyboard.json',
            json.dumps([s.model_dump() for s in storyboard]))
        timings['matching_sec'] = ...

    # ── NARRATION ──
    audio_key = f'projects/{project.id}/outputs/{job.id}.mp3'
    if storage.exists(audio_key) and storage.size(audio_key) > 100:
        logger.info('Resuming: skipped NARRATION (cached)')
    else:
        repo.update_job(job.id, status=JobStatus.NARRATION, ...)
        # ... synthesize and store audio ...
        timings['narration_sec'] = ...

    # ── RENDERING ── (always re-run — it's the most failure-prone step)
    repo.update_job(job.id, status=JobStatus.RENDERING, ...)
    # ... render video ...
```

### StorageService Changes

The `StorageService` interface (`services/storage.py`) needs two new methods:

```python
def load_text(self, key: str) -> str | None:
    """Load text content by key, return None if not found."""

def exists(self, key: str) -> bool:
    """Check if a key exists in storage."""
```

For `LocalStorageService`: check if file exists, read it.
For `S3StorageService`: use `head_object` to check existence, `get_object` to read.

### Cleanup

After a job completes successfully, delete the intermediate artifacts:
```python
# At the end of process_generation_job(), after COMPLETED:
storage.delete_prefix(f'projects/{project.id}/intermediate/{job.id}/')
```

For `LocalStorageService`: `shutil.rmtree()` the directory.
For `S3StorageService`: `list_objects_v2` + `delete_objects`.

### What NOT to Cache

- **Rendering** is always re-run. It's the step most likely to fail (FFmpeg OOM, disk space, etc.) and also the cheapest to re-run (no AI API calls).
- **Intermediate artifacts are per-job**, not per-project. Different jobs for the same project get different scripts.

---

## 9. Frontend Changes (All Features)

All 3 user-facing features (A, B, C) require frontend dropdown controls. Feature D is backend-only.

### New State Variables (`project-studio.tsx`)

Add near L32-33:
```typescript
const [voiceProvider, setVoiceProvider] = useState('polly');
const [voiceGender, setVoiceGender] = useState('female');
const [backgroundMusic, setBackgroundMusic] = useState('auto');
const [language, setLanguage] = useState('en');
```

### Updated Form Layout

Change the current 2-column grid (L290) to accommodate 6 controls:

```
┌──────────────────────┬──────────────────────┐
│ Aspect Ratio         │ Voice Style          │  (existing)
├──────────────────────┼──────────────────────┤
│ Voice Engine         │ Voice Gender         │  (Feature A)
├──────────────────────┼──────────────────────┤
│ Language             │ Background Music     │  (Feature B + C)
└──────────────────────┴──────────────────────┘
```

### Dropdown Options

**Voice Engine** (`voiceProvider`):
```
polly       → "Amazon Polly (Default)"
edge_tts    → "Edge TTS (Free · 50+ languages)"
elevenlabs  → "ElevenLabs (Premium)"
```

**Voice Gender** (`voiceGender`):
```
female → "Female"
male   → "Male"
```

**Language** (`language`):
```
en → "English"
es → "Spanish (Español)"
fr → "French (Français)"
de → "German (Deutsch)"
ar → "Arabic (العربية)"
hi → "Hindi (हिन्दी)"
ja → "Japanese (日本語)"
zh → "Chinese (中文)"
ko → "Korean (한국어)"
pt → "Portuguese (Português)"
it → "Italian (Italiano)"
ru → "Russian (Русский)"
tr → "Turkish (Türkçe)"
nl → "Dutch (Nederlands)"
pl → "Polish (Polski)"
sv → "Swedish (Svenska)"
th → "Thai (ไทย)"
vi → "Vietnamese (Tiếng Việt)"
id → "Indonesian (Bahasa)"
ms → "Malay (Melayu)"
```

**Background Music** (`backgroundMusic`):
```
auto       → "Auto (match voice style)"
upbeat     → "Upbeat"
calm       → "Calm"
corporate  → "Corporate"
luxury     → "Luxury"
none       → "No music"
```

### Updated API Call (`project-studio.tsx` ~L173)

```typescript
const queuedJob = await generateProject(
    project.id,
    {
        aspect_ratio: aspectRatio,
        voice_style: voiceStyle,
        voice_provider: voiceProvider,
        voice_gender: voiceGender,
        language: language,
        background_music: backgroundMusic,
        idempotency_key: idempotencyKey,
    },
    token
);
```

### Updated API Client (`api.ts` L84)

```typescript
input: {
    aspect_ratio: string;
    voice_style: string;
    voice_provider: string;
    voice_gender: string;
    language: string;
    background_music: string;
    idempotency_key?: string;
}
```

### Updated Types (`contracts.ts`)

Add to `GenerationJob` interface:
```typescript
voice_provider?: string;
voice_gender?: string;
language?: string;
background_music?: string;
```

---

## 10. Dependency & Infra Changes

### Python Dependencies (`pyproject.toml`)

Add to `dependencies` array:
```
"edge-tts>=6.1.0"
```

No other new dependencies. ElevenLabs uses `httpx` (already present). Music files are static assets.

### Environment Variables

Add to `.env`:
```env
# TTS Providers
NOVAREEL_ELEVENLABS_API_KEY=           # Only needed if offering ElevenLabs

# Optional defaults
NOVAREEL_DEFAULT_VOICE_PROVIDER=polly
```

### Docker (`infra/docker-compose.yml`)

If using Docker, mount the `assets/music/` directory or copy it into the image. Add to the api/worker service:
```yaml
volumes:
  - ../services/backend/assets:/app/assets:ro
```

### Music Assets

Create directory and add 4-6 royalty-free MP3 tracks:
```
services/backend/assets/music/
├── upbeat.mp3       (~60s, energetic background)
├── calm.mp3         (~60s, gentle ambient)
├── corporate.mp3    (~60s, professional/modern)
└── luxury.mp3       (~60s, elegant/premium feel)
```

---

## 11. Testing Strategy

### Unit Tests

| Test | Feature | What to Assert |
|------|---------|---------------|
| `test_polly_provider_returns_bytes` | A | Mock boto3, verify MP3 bytes returned |
| `test_edge_tts_provider_returns_bytes` | A | Mock edge_tts, verify MP3 bytes returned |
| `test_elevenlabs_provider_returns_bytes` | A | Mock httpx, verify MP3 bytes returned |
| `test_elevenlabs_insufficient_credits` | A | Mock API returning low credits, verify exception |
| `test_factory_builds_correct_provider` | A | Verify each string maps to correct class |
| `test_factory_elevenlabs_no_key_raises` | A | Settings without key → ValueError |
| `test_select_music_auto` | B | Auto maps energetic→upbeat, professional→corporate, friendly→calm |
| `test_select_music_none` | B | Returns None |
| `test_select_music_explicit` | B | Returns correct file path |
| `test_language_config_get_voice` | C | Verify voice name lookups for various lang/provider/gender combos |
| `test_language_config_rtl` | C | Arabic returns True, English returns False |
| `test_pipeline_skips_cached_stages` | D | Pre-populate intermediate files, verify stages skipped |

### Integration Tests

| Test | What to Assert |
|------|---------------|
| `GenerateRequest` with all new fields accepted | 202 response with fields stored in job |
| `GenerateRequest` with invalid `voice_provider` | 422 validation error |
| `GenerateRequest` with defaults only | Backward compatible, uses polly/female/en/auto |
| Mock AI full pipeline with `voice_provider=edge_tts` | Job completes, mock bytes stored |
| Music mux with actual FFmpeg | Output video has 2 audio streams mixed |

### Manual QA Checklist

- [ ] Generate video with Polly (male + female)
- [ ] Generate video with EdgeTTS (male + female)
- [ ] Generate video with ElevenLabs (if API key configured)
- [ ] Generate video in Spanish (EdgeTTS)
- [ ] Generate video in Japanese (EdgeTTS)
- [ ] Generate video with background music (each mood)
- [ ] Generate video with `background_music=none` — verify no music
- [ ] Trigger a rendering failure, verify retry skips AI stages
- [ ] Verify old jobs (without new fields) still display correctly in UI

---

## 12. Sprint Plan

### Sprint 1 (Week 1-2): TTS + Music

| Day | Task | Owner | Depends On |
|-----|------|-------|------------|
| D1 | Read codebase: `pipeline.py`, `nova.py`, `video.py`, `models.py` | All | — |
| D1-D2 | Feature A: Create `voice/base.py`, `voice/polly.py`, `voice/factory.py` | Backend | — |
| D2-D3 | Feature A: Create `voice/edge_tts.py`, `voice/elevenlabs.py` | Backend | base.py |
| D3 | Feature A: Update `models.py`, `config.py`, repo layer, `v1.py` | Backend | providers done |
| D4 | Feature A: Update `pipeline.py`, remove `nova.synthesize_voice()` | Backend | all above |
| D4 | Feature A: Unit tests for all 3 providers + factory | Backend | providers done |
| D3-D4 | Feature B: Source music files, create `music.py` | Backend | — |
| D5 | Feature B: Update `video.py` — music mux step | Backend | music.py |
| D5 | Feature B: Update `models.py`, repo layer, `pipeline.py` | Backend | music.py |
| D3-D5 | Frontend: Add all new dropdowns (A + B) | Frontend | API contract finalized |
| D6-D7 | Integration testing, bug fixes | All | everything |

**Sprint 1 deliverable**: Sellers can choose TTS engine (Polly/EdgeTTS/ElevenLabs), male/female voice, and background music mood.

### Sprint 2 (Week 3-4): Language + Resilience

| Day | Task | Owner | Depends On |
|-----|------|-------|------------|
| D1 | Feature C: Create `config/languages.py` | Backend | — |
| D1-D2 | Feature C: Update `nova.generate_script()` prompt | Backend | languages.py |
| D2 | Feature C: Wire language into voice providers | Backend | Feature A done |
| D2 | Feature C: Update `models.py`, repo layer, `v1.py`, `pipeline.py` | Backend | languages.py |
| D3 | Feature C: Frontend language dropdown | Frontend | API contract |
| D3-D4 | Feature D: Add `load_text()`, `exists()` to StorageService | Backend | — |
| D4-D5 | Feature D: Modify `pipeline.py` — caching + skip logic | Backend | storage methods |
| D5 | Feature D: Intermediate artifact cleanup on success | Backend | caching done |
| D6-D7 | Full integration testing, QA, bug fixes | All | everything |

**Sprint 2 deliverable**: Sellers can generate videos in 20 languages. Pipeline retries skip completed AI stages.

---

## 13. Acceptance Criteria

### Feature A: Multi-Provider TTS
- [ ] Seller selects "Edge TTS" → video has Edge TTS narration (not Polly)
- [ ] Seller selects "ElevenLabs" → video has ElevenLabs narration
- [ ] Seller selects "Male" → male voice used (for all 3 providers)
- [ ] No API key for ElevenLabs → clear error message, not a crash
- [ ] Existing requests without `voice_provider` → defaults to Polly (backward compatible)
- [ ] Mock AI mode still works for all providers

### Feature B: Background Music
- [ ] Generated video has audible background music at low volume
- [ ] Narration remains clearly audible over music
- [ ] `background_music=none` → no music in output
- [ ] `background_music=auto` → mood matches voice style
- [ ] Music loops if video is longer than music track
- [ ] If music mux fails → video still outputs (without music, graceful degradation)

### Feature C: Multi-Language
- [ ] Seller selects "Spanish" → script narration is in Spanish
- [ ] Seller selects "Japanese" → script narration is in Japanese
- [ ] EdgeTTS uses Japanese voice for Japanese language (not English voice speaking Japanese)
- [ ] English remains the default when no language specified
- [ ] Subtitles are in the selected language (they come from script lines)

### Feature D: Resumable Pipeline
- [ ] First run: all 5 stages execute normally
- [ ] If rendering fails and job retries: ANALYZING, SCRIPTING, MATCHING, NARRATION stages are skipped (logs say "skipped (cached)")
- [ ] Retry completes 30-60 seconds faster than a fresh run
- [ ] After successful completion, intermediate files are cleaned up
- [ ] No behavior change for first-attempt jobs

---

## Appendix: Quick Reference — All Model Changes

```python
# models.py — GenerateRequest (final state after Phase 1)
class GenerateRequest(BaseModel):
    aspect_ratio: Literal['16:9', '1:1', '9:16'] = '16:9'
    voice_style: Literal['energetic', 'professional', 'friendly'] = 'energetic'
    voice_provider: Literal['polly', 'edge_tts', 'elevenlabs'] = 'polly'    # Feature A
    voice_gender: Literal['male', 'female'] = 'female'                       # Feature A
    language: str = 'en'                                                      # Feature C
    background_music: Literal['none', 'auto', 'upbeat', 'calm', 'corporate', 'luxury'] = 'auto'  # Feature B
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=128)

# models.py — GenerationJobRecord (final state after Phase 1)
class GenerationJobRecord(BaseModel):
    # ... existing fields ...
    voice_style: str = 'energetic'
    voice_provider: str = 'polly'          # Feature A
    voice_gender: str = 'female'           # Feature A
    language: str = 'en'                   # Feature C
    background_music: str = 'auto'         # Feature B
    last_completed_stage: str | None = None # Feature D
    # ... existing fields ...
```

## Appendix: New Files Summary

```
services/backend/
├── app/
│   ├── config/
│   │   └── languages.py                  # Feature C — language + voice mappings
│   └── services/
│       ├── voice/
│       │   ├── __init__.py               # Feature A — re-exports
│       │   ├── base.py                   # Feature A — abstract VoiceProvider
│       │   ├── polly.py                  # Feature A — AWS Polly provider
│       │   ├── edge_tts.py              # Feature A — Microsoft EdgeTTS provider
│       │   ├── elevenlabs.py            # Feature A — ElevenLabs provider
│       │   └── factory.py               # Feature A — build_voice_provider()
│       └── music.py                      # Feature B — music selection
└── assets/
    └── music/
        ├── upbeat.mp3                    # Feature B — royalty-free tracks
        ├── calm.mp3
        ├── corporate.mp3
        └── luxury.mp3
```
