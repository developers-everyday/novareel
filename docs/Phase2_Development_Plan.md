# NovaReel Phase 2 Enhancement — Development Plan

> **Status**: Reviewed & Updated — ready for implementation  
> **Predecessor**: Phase 1 (Multi-Provider TTS, Background Music, Multi-Language, Resumable Pipeline) — ✅ Complete  
> **Timeline**: 6 weeks (3 sprints)  
> **Team**: 2-3 backend devs, 1 frontend dev  
> **Start date**: After Phase 1 rollout stabilizes (est. mid-April 2026)

---

## Table of Contents

1. [Phase 1 Recap](#1-phase-1-recap)
2. [Phase 2 Scope](#2-phase-2-scope)
3. [Feature A: Video Translation & Dubbing](#3-feature-a-video-translation--dubbing)
4. [Feature B: Word-Level Caption Timing](#4-feature-b-word-level-caption-timing)
5. [Feature C: Stock Footage Integration (Pexels)](#5-feature-c-stock-footage-integration-pexels)
6. [Feature D: Advanced Video Transitions & Effects](#6-feature-d-advanced-video-transitions--effects)
7. [Feature E: Script Templates Library](#7-feature-e-script-templates-library)
8. [Prerequisite: JobCreateParams](#8-prerequisite-jobcreateparams)
9. [Frontend Changes (All Features)](#9-frontend-changes-all-features)
10. [Dependency & Infra Changes](#10-dependency--infra-changes)
11. [Testing Strategy](#11-testing-strategy)
12. [Sprint Plan](#12-sprint-plan)
13. [Acceptance Criteria](#13-acceptance-criteria)
14. [Risks & Mitigations](#14-risks--mitigations)

---

## 1. Phase 1 Recap

Phase 1 delivered 4 features that form the foundation Phase 2 builds upon:

| Feature | Status | What It Delivered |
|---------|--------|-------------------|
| **Multi-Provider TTS** | ✅ Done | Polly, EdgeTTS (free), ElevenLabs (premium) via pluggable `VoiceProvider` interface |
| **Background Music** | ✅ Done | Mood-based music mixing (upbeat, calm, corporate, luxury) behind narration at 12% volume |
| **Multi-Language Support** | ✅ Done | 20 languages with per-language TTS voice mappings; language-aware script generation |
| **Resumable Pipeline** | ✅ Done | Checkpoint/resume for ANALYZING → SCRIPTING → MATCHING → NARRATION stages |

**Key architecture assets from Phase 1:**
- `services/backend/app/services/voice/` — pluggable voice provider system
- `services/backend/app/config/languages.py` — language registry with voice mappings
- `services/backend/app/services/music.py` — music selection engine
- Intermediate artifact caching in pipeline for resume support

---

## 2. Phase 2 Scope

Phase 2 focuses on **content quality, variety, and global reach** — taking NovaReel from "basic product slideshow" to "professional marketing video platform."

| Feature | What | Why | Impact | Effort |
|---------|------|-----|--------|--------|
| **A. Video Translation & Dubbing** | Take an existing video and produce translated versions in other languages | 10x value multiplier — one video becomes 10+ | 🔴 Critical | 3-4 weeks |
| **B. Word-Level Captions** | Whisper-based word-level subtitle timing with animated highlight styles | Modern video standard; sentence-level subtitles look dated | 🟠 High | 1-2 weeks |
| **C. Stock Footage (Pexels)** | LLM-generated search queries → Pexels B-roll footage mixed with product images | Transforms slideshows into real commercials | 🟠 High | 2-3 weeks |
| **D. Video Transitions & Effects** | Scene transitions (crossfade, slide, wipe), text overlays, CTA end cards | Professional-grade video output | 🟠 High | 2-3 weeks |
| **E. Script Templates** | YAML-based prompt templates for different video styles (unboxing, comparison, how-to, etc.) | Content variety; same product → different narratives | 🟡 Medium | 1-2 weeks |

---

## 3. Feature A: Video Translation & Dubbing

> **Priority**: 🔴 Critical — the single highest-ROI feature in the roadmap  
> **Reference**: `docs/ShortGPT_Integration_Analysis.md` §3 — Video Translation & Dubbing Engine

### What It Does

A seller generates a product video in English, then clicks "Translate" → instantly gets that same video re-dubbed in Spanish, French, Japanese, etc. The script is translated contextually (not word-for-word), new narration is synthesized in the target language voice, and subtitles are regenerated — all without re-running image analysis or matching.

### New API Endpoint

```
POST /v1/projects/{project_id}/jobs/{job_id}/translate
```

**Request body:**
```json
{
  "target_languages": ["es", "fr", "de", "ja"],
  "voice_provider": "edge_tts",
  "voice_gender": "female"
}
```

**Response:** Returns an array of new `GenerationJobRecord` objects (one per target language), each queued for processing.

### Pipeline: Translation Job Flow

```
POST /translate
  → for each target_language:
      → create new job (type="translation", source_job_id=original)
      → queue for processing

worker.py polls →
  translation_pipeline():
    1. LOADING     (5%)  → Load source job's script_lines + storyboard from VideoResultRecord
    2. TRANSLATING (30%) → LLM-translate script lines to target language
    3. NARRATION   (60%) → Synthesize translated script via voice provider
    4. RENDERING   (90%) → Re-render video with new audio + translated SRT
    5. COMPLETED   (100%)
```

> **Note**: `LOADING` and `TRANSLATING` are new `JobStatus` enum values added for translation jobs. The frontend must handle these new stages in the progress UI.

**Key optimization**: Steps 1 (image analysis) and 3 (image matching) from the original pipeline are **completely skipped** — the translated video reuses the same storyboard and image assignments from the source job's `VideoResultRecord`. This cuts translation time and cost by ~50%.

> ⚠️ **Important**: The generation pipeline deletes intermediate artifacts (`storage.delete_prefix()`) on success. Translation therefore reads `script_lines` and `storyboard` from `VideoResultRecord` — **not** from intermediate cache. See [Prerequisite: Per-Job Result Storage](#prerequisite-per-job-result-storage) below.

### New Files

```
services/backend/app/services/translation.py    # LLM-based translation service
services/backend/app/services/pipeline_translate.py  # Translation pipeline orchestrator
```

### `translation.py` — LLM Translation

```python
class TranslationService:
    """Translate script lines using Amazon Bedrock Nova."""

    def __init__(self, bedrock_client, model_id: str):
        self.client = bedrock_client
        self.model_id = model_id

    def translate_script(
        self,
        script_lines: list[str],
        source_language: str,
        target_language: str,
        product_context: str,
    ) -> list[str]:
        """Translate script lines while preserving marketing tone and product terms."""
        # Uses Bedrock Nova Lite with a context-aware prompt:
        # - Keeps product names/brand terms untranslated
        # - Preserves marketing tone and urgency
        # - Maintains line count (1:1 mapping)
        # - Adjusts content length for languages that expand (German ~30% longer)
        ...
```

**Why LLM translation instead of AWS Translate?**
- LLM preserves marketing tone and persuasion techniques
- LLM keeps product-specific terms (brand names, model numbers) untranslated
- LLM can adjust for cultural context (e.g., different selling points resonate in different markets)
- AWS Translate is literal; marketing copy needs creative adaptation

### Prerequisite: Per-Job Result Storage

The current `set_result(project_id, result)` / `get_result(project_id)` is keyed by `project_id` only. A translation job would **overwrite** the original video's result. This must be refactored before Feature A can work.

**Required changes:**

| File | Change |
|------|--------|
| `models.py` | Add `script_lines: list[str] = Field(default_factory=list)` and `language: str = 'en'` to `VideoResultRecord`; add `job_id: str` to `VideoResultRecord` |
| `base.py` (repo) | Change `set_result(project_id, result)` → `set_result(project_id, job_id, result)` and `get_result(project_id)` → `get_result(project_id, job_id)` ; add `list_results(project_id)` to get all results for a project |
| `local.py` / `dynamo.py` | Implement the updated `set_result`, `get_result`, and new `list_results` |
| `pipeline.py` | Update `set_result` call to include `job_id`; store `script_lines` in the `VideoResultRecord` |
| `v1.py` | Update `get_result` to accept optional `job_id` query param; default to latest result for backward compatibility |

### Changes to Existing Files

| File | Change |
|------|--------|
| `models.py` | Add `TranslateRequest` model; add `LOADING` and `TRANSLATING` to `JobStatus` enum; add `job_type: str = 'generation'` and `source_job_id: str | None = None` to `GenerationJobRecord` |
| `v1.py` | Add `POST /v1/projects/{project_id}/jobs/{job_id}/translate` endpoint |
| `base.py` (repo) | `get_job()` already exists — no change needed. Translation pipeline uses it to load the source job, then calls `get_result(project_id, source_job_id)` to access `script_lines` and `storyboard` |
| `pipeline.py` | Keep existing — translation uses a separate pipeline function |
| `config/languages.py` | Already has all languages needed — no changes |

### Frontend Changes

- Add "Translate" button on completed video cards
- Modal dialog with language multi-select checkboxes and voice provider dropdown
- Show translation jobs as child items under the source video
- Progress tracking per translation job

### Mock AI Mode

When `use_mock_ai=True`:
```python
translated_lines = [f'MOCK-TRANSLATE::{target_lang}::{line}' for line in script_lines]
```

---

## 4. Feature B: Word-Level Caption Timing

> **Priority**: 🟠 High  
> **Reference**: `docs/ShortGPT_Integration_Analysis.md` §4 — Word-Level Caption Timing

### What It Does

After narration audio is synthesized, run a transcription service on it to get **word-level timestamps**. Use these timestamps to generate animated captions where each word highlights as it's spoken — the standard for modern short-form video (TikTok, Reels, YouTube Shorts).

### Transcription Backend

| Backend | When to Use | Pros | Cons |
|---------|-------------|------|------|
| **AWS Transcribe** (default) | Production, Docker | No extra dependencies, already using AWS, word-level timestamps native | Per-request cost (~$0.024/min) |
| **Whisper** (fallback) | Offline dev, CI | Free, runs locally | PyTorch adds ~1.5GB to Docker image |

Set via `NOVAREEL_TRANSCRIPTION_BACKEND=aws_transcribe` (default) or `whisper`.

### Caption Styles

Sellers choose from 3 caption styles:

| Style | Description |
|-------|-------------|
| `sentence` | Current behavior — full sentence shown for entire segment (default) |
| `word_highlight` | Words appear and highlight one-by-one as spoken |
| `karaoke` | All words visible, current word changes color |
| `none` | No captions |

### New Files

```
services/backend/app/services/transcription.py   # Pluggable: AWS Transcribe (default) + Whisper (fallback)
```

### `transcription.py`

```python
from abc import ABC, abstractmethod

class TranscriptionBackend(ABC):
    """Pluggable interface for word-level timestamp extraction."""

    @abstractmethod
    def get_word_timestamps(self, audio_path: str, language: str = 'en') -> list[dict]:
        """Return [{"word": "hello", "start": 0.0, "end": 0.5}, ...]"""
        ...

class AWSTranscribeBackend(TranscriptionBackend):
    """Default backend — uses AWS Transcribe for word-level timestamps."""

    def __init__(self, boto3_client):
        self.client = boto3_client

    def get_word_timestamps(self, audio_path: str, language: str = 'en') -> list[dict]:
        # Upload audio to S3 temp location → start transcription job
        # → poll until complete → parse word-level items from response
        ...

class WhisperBackend(TranscriptionBackend):
    """Offline fallback — uses OpenAI Whisper locally. Requires PyTorch."""

    def __init__(self):
        self._model = None  # Lazy-loaded, cached

    @property
    def model(self):
        import whisper_timestamped as whisper
        if self._model is None:
            self._model = whisper.load_model("base")  # ~150MB
        return self._model

    def get_word_timestamps(self, audio_path: str, language: str = 'en') -> list[dict]:
        import whisper_timestamped as whisper
        result = whisper.transcribe(self.model, audio_path, language=language)
        words = []
        for segment in result['segments']:
            for word_info in segment.get('words', []):
                words.append({
                    'word': word_info['text'].strip(),
                    'start': word_info['start'],
                    'end': word_info['end'],
                })
        return words

def build_transcription_backend(backend: str, settings) -> TranscriptionBackend:
    if backend == 'whisper':
        return WhisperBackend()
    return AWSTranscribeBackend(settings.get_boto3_client('transcribe'))
```

### Changes to Existing Files

| File | Change |
|------|--------|
| `models.py` | Add `caption_style: Literal['sentence', 'word_highlight', 'karaoke', 'none'] = 'sentence'` to `GenerateRequest` and `GenerationJobRecord` |
| `pipeline.py` | After NARRATION stage, if `caption_style != 'sentence'`, run transcription backend to get word timestamps; pass to video renderer |
| `video.py` | Update `render_video()` to accept `word_timestamps` and `caption_style`; generate ASS (Advanced SubStation Alpha) subtitles for animated captions instead of basic SRT |
| `v1.py` | Pass `caption_style` through to job creation |
| `config/__init__.py` | Add `transcription_backend: str = 'aws_transcribe'` setting |
| `base.py` / `local.py` / `dynamo.py` | Add `caption_style` to `JobCreateParams` (see [Prerequisite: JobCreateParams](#prerequisite-jobcreateparams)) |

### ASS Subtitle Generation for Animated Captions

The `word_highlight` style uses ASS subtitles with `\k` (karaoke) timing tags:
```
[V4+ Styles]
Style: Default,Inter,22,&H00FFFFFF,&H000078FF,&H00000000,&HBE000000,-1,0,0,0,100,100,0,0,1,2,0,2,10,10,20,1

[Events]
Dialogue: 0,0:00:00.00,0:00:02.50,Default,,0,0,0,,{\k50}Hello {\k30}and {\k70}welcome {\k40}to {\k60}NovaReel
```

This produces the "word-by-word highlight" effect that modern viewers expect.

> ⚠️ **FFmpeg requirement**: ASS subtitle rendering requires FFmpeg compiled with `libass` support. Like the existing `drawtext`/`libfreetype` issue, this must be feature-detected at runtime. If `libass` is unavailable, fall back to `sentence` style captions and log a warning.

### Transcription Backend Notes

**AWS Transcribe (default):**
- Supports word-level timestamps natively via `items` in the response
- Clean TTS audio = excellent accuracy, even for non-English
- No model caching needed — API-based

**Whisper (offline fallback, set `NOVAREEL_TRANSCRIPTION_BACKEND=whisper`):**
- Load the Whisper model once per worker process (lazy singleton)
- Use the `base` model (~150MB) for fastest inference; good enough for TTS audio
- For non-English languages, pass `language=job.language` to improve accuracy

### Mock AI Mode

When `use_mock_ai=True`, skip transcription entirely and generate evenly-spaced mock timestamps:
```python
mock_words = transcript.split()
duration = len(mock_words) * 0.3  # ~0.3s per word
word_timestamps = [
    {'word': w, 'start': i * 0.3, 'end': (i + 1) * 0.3}
    for i, w in enumerate(mock_words)
]
```

---

## 5. Feature C: Stock Footage Integration (Pexels)

> **Priority**: 🟠 High  
> **Reference**: `docs/ShortGPT_Integration_Analysis.md` §5 — Stock Footage & Image Sourcing

### What It Does

After script generation, use the LLM to generate search queries for each scene, fetch relevant stock video clips from Pexels, and interleave them with product images. This transforms product slideshows into dynamic commercials with lifestyle B-roll.

### Video Styles

| Style | Description |
|-------|-------------|
| `product_only` | Current behavior — product images only (default) |
| `product_lifestyle` | Alternate between product images and stock B-roll footage |
| `lifestyle_focus` | Primarily stock footage with product images as overlays |

### New Files

```
services/backend/app/services/stock_media.py   # Pexels API integration
```

### `stock_media.py`

```python
import httpx

PEXELS_API_URL = "https://api.pexels.com/videos/search"

class StockMediaService:
    """Fetch stock video clips from Pexels."""

    def __init__(self, api_key: str):
        self.api_key = api_key

    def search_videos(
        self,
        query: str,
        orientation: str = 'landscape',  # landscape | portrait | square
        min_duration: int = 3,
        max_duration: int = 15,
        per_page: int = 5,
    ) -> list[dict]:
        """Search Pexels for stock video clips.

        Returns:
            [{"id": 123, "url": "https://...", "duration": 8, "width": 1920, "height": 1080}, ...]
        """
        ...

    def download_clip(self, video_url: str, output_path: str) -> str:
        """Download a video clip to local filesystem. Returns output path."""
        ...

    def generate_search_queries(
        self,
        script_lines: list[str],
        product_description: str,
        bedrock_client,
    ) -> list[str]:
        """Use LLM to generate Pexels search queries for each scene.

        Example:
            Script line: "Transform your morning routine with our premium coffee maker"
            → Search query: "person making coffee morning kitchen"
        """
        ...
```

### Changes to Existing Files

| File | Change |
|------|--------|
| `models.py` | Add `video_style: Literal['product_only', 'product_lifestyle', 'lifestyle_focus'] = 'product_only'` to `GenerateRequest` and `GenerationJobRecord` |
| `config/__init__.py` | Add `pexels_api_key: str | None = None` |
| `pipeline.py` | After MATCHING stage, if `video_style != 'product_only'`, fetch stock clips and interleave with storyboard |
| `video.py` | Update `render_video()` to handle mixed content (images + video clips) in the storyboard |
| `models.py` | Extend `StoryboardSegment` with `media_type: Literal['image', 'video'] = 'image'` and `video_path: str | None = None` |
| `v1.py` | Pass `video_style` to job creation |
| `base.py` / `local.py` / `dynamo.py` | Add `video_style` to `JobCreateParams` (see [Prerequisite: JobCreateParams](#prerequisite-jobcreateparams)) |

### Storyboard with B-Roll

After stock footage integration, the storyboard alternates:
```
Segment 1: product_image_1.jpg  (image, 5s, Ken Burns)
Segment 2: "woman shopping online" (video clip, 4s, from Pexels)
Segment 3: product_image_2.jpg  (image, 5s, Ken Burns)
Segment 4: "unboxing package happy" (video clip, 4s, from Pexels)
Segment 5: product_image_3.jpg  (image, 5s, Ken Burns)
Segment 6: "satisfied customer smiling" (video clip, 4s, from Pexels)
```

### FFmpeg: Mixing Images and Video Clips

`video.py` needs to handle two segment types:
- **Image segments**: Existing Ken Burns animation (unchanged)
- **Video segments**: Extract a clip (`-ss`, `-t` flags), scale to target resolution, trim to segment duration

Each segment is rendered individually and then concatenated using the FFmpeg concat demuxer — same approach as current rendering, but with video inputs as well.

### Pexels API

- Free API key from [pexels.com](https://www.pexels.com/api/)
- **Free tier**: 200 requests/month (not per hour) — with ~6 queries/video, this limits to ~33 videos/month. Sufficient for private beta; plan to upgrade to paid (20,000 req/month) before scaling.
- All content is royalty-free, no attribution required for videos
- Implement search result caching (same query within 24h → use cached response) to reduce API usage

### Mock AI Mode

When `use_mock_ai=True`, skip Pexels API and use placeholder:
```python
# Use a solid color frame as mock B-roll
mock_broll = generate_solid_color_clip(duration=4, color='#1a1a2e', resolution=target_resolution)
```

---

## 6. Feature D: Advanced Video Transitions & Effects

> **Priority**: 🟠 High  
> **Reference**: `docs/ShortGPT_Integration_Analysis.md` §7 — Advanced Video Transitions & Effects

### What It Does

Add professional scene transitions, text overlays, and CTA end cards to generated videos. This is the final step in making NovaReel videos look like real commercials instead of slideshows.

### Transition Types

| Transition | FFmpeg Filter | Description |
|------------|---------------|-------------|
| `cut` | None (current default) | Hard cut between scenes |
| `crossfade` | `xfade=transition=fade:duration=0.5` | Smooth fade between scenes |
| `slide_left` | `xfade=transition=slideleft:duration=0.5` | Slide left transition |
| `wipe_right` | `xfade=transition=wiperight:duration=0.5` | Wipe right |
| `zoom` | `xfade=transition=circlecrop:duration=0.5` | Zoom/circle crop |
| `dissolve` | `xfade=transition=dissolve:duration=0.5` | Dissolve |

### Text Overlay Types

| Overlay | When | Content |
|---------|------|---------|
| **Product title** | First 3 seconds | Product name from `project.title` |
| **Feature callouts** | During each scene | Key feature text extracted by LLM |
| **Price tag** | Configurable | Price from `brand_prefs` or LLM-extracted |
| **CTA end card** | Last 3 seconds | "Shop Now" / "Link in Bio" / custom text |
| **Brand watermark** | Entire video | Small logo in corner (if brand logo uploaded) |

### New Files

```
services/backend/app/services/effects.py    # Transition + overlay configuration
```

### `effects.py`

```python
from dataclasses import dataclass

@dataclass
class TransitionConfig:
    effect: str = 'crossfade'
    duration: float = 0.5

@dataclass
class TextOverlay:
    text: str
    position: str = 'bottom_center'     # top_left, top_center, bottom_center, center
    start_time: float = 0.0
    end_time: float = 3.0
    font_size: int = 36
    color: str = '#FFFFFF'
    background_color: str = '#00000080'  # Semi-transparent black
    animation: str = 'fade_in'          # fade_in, slide_up, none

@dataclass
class VideoEffectsConfig:
    transition: TransitionConfig = TransitionConfig()
    title_overlay: TextOverlay | None = None
    cta_overlay: TextOverlay | None = None
    feature_callouts: list[TextOverlay] | None = None
    watermark_path: str | None = None
    watermark_opacity: float = 0.3
```

### Changes to Existing Files

| File | Change |
|------|--------|
| `models.py` | Add `transition_style: Literal['cut', 'crossfade', 'slide_left', 'wipe_right', 'zoom', 'dissolve'] = 'crossfade'` and `show_title_card: bool = True` and `cta_text: str | None = None` to `GenerateRequest` |
| `video.py` | Major refactor — apply `xfade` filter between segments, add `drawtext` overlays for title/CTA/features |
| `pipeline.py` | Build `VideoEffectsConfig` from job settings and pass to `video_service.render_video()` |
| `v1.py` | Pass new fields to job creation |
| `base.py` / `local.py` / `dynamo.py` | Add `transition_style`, `show_title_card`, `cta_text` to `JobCreateParams` (see [Prerequisite: JobCreateParams](#prerequisite-jobcreateparams)) |

> 💡 **Recommended**: Split the `video.py` refactor into a preparatory PR that restructures the current 214-line render function into a segment-based pipeline model _before_ adding transitions or stock footage. This reduces the risk of the Sprint 4 `video.py` changes.

### FFmpeg: Scene Transitions

Current rendering concatenates segments with hard cuts using the concat demuxer. To add transitions:

```bash
# Instead of concat, use xfade filter between each pair of segments
ffmpeg -i seg1.mp4 -i seg2.mp4 -i seg3.mp4 \
  -filter_complex "
    [0:v][1:v]xfade=transition=fade:duration=0.5:offset=4.5[v01];
    [v01][2:v]xfade=transition=fade:duration=0.5:offset=9.0[vout]
  " \
  -map "[vout]" output.mp4
```

The offset for each `xfade` = cumulative duration of previous segments minus accumulated transition durations.

### FFmpeg: Text Overlays

```bash
ffmpeg -i video.mp4 \
  -vf "drawtext=text='Shop Now':fontsize=48:fontcolor=white:x=(w-tw)/2:y=h-80:
       enable='between(t,25,30)':fontfile=/path/to/Inter-Bold.ttf" \
  output_with_cta.mp4
```

> **Note**: `drawtext` requires FFmpeg compiled with `--enable-libfreetype`. We previously removed `drawtext` due to Homebrew FFmpeg lacking it. Need to verify availability or provide a fallback (skip overlays if freetype unavailable). Similarly, ASS subtitle rendering (Feature B) requires `libass`. Both should be feature-detected at startup and capabilities logged.

---

## 7. Feature E: Script Templates Library

> **Priority**: 🟡 Medium  
> **Reference**: `docs/ShortGPT_Integration_Analysis.md` §10 — Script Variety & Content Templates

### What It Does

Replace the single hardcoded prompt in `nova.generate_script()` with a library of YAML prompt templates. Sellers choose a template that matches their video style.

### Available Templates

| Template | Narrative Style | Best For |
|----------|----------------|----------|
| `product_showcase` | "Discover... Featuring... Experience..." | Default, general products |
| `problem_solution` | "Tired of X? Product Y solves it" | Pain-point products (cleaning, organization) |
| `comparison` | "Product X vs competitors" | Products with clear competitive advantages |
| `unboxing` | "Let's unbox and explore..." | New/exciting products, tech gadgets |
| `testimonial` | "Here's what customers are saying..." | Products with strong reviews |
| `how_to` | "Step 1: ... Step 2: ..." | Tools, kitchen gadgets, DIY products |
| `seasonal` | "This holiday season..." | Sales, seasonal promotions |
| `luxury` | "Crafted for those who demand the finest..." | Premium/luxury products |

### New Directory

```
services/backend/prompt_templates/
├── product_showcase.yaml
├── problem_solution.yaml
├── comparison.yaml
├── unboxing.yaml
├── testimonial.yaml
├── how_to.yaml
├── seasonal.yaml
└── luxury.yaml
```

### YAML Template Format

```yaml
# prompt_templates/problem_solution.yaml
name: "Problem/Solution"
description: "Presents a pain point and positions the product as the solution"
scenes: 6
structure:
  - "Scene 1: Present the common problem/frustration"
  - "Scene 2: Amplify the pain point with relatable scenario"
  - "Scene 3: Introduce the product as the solution"
  - "Scene 4: Show key features that solve the problem"
  - "Scene 5: Demonstrate the transformation/result"
  - "Scene 6: Call-to-action with urgency"
tone: "empathetic, then confident and enthusiastic"
system_prompt: |
  You are a marketing copywriter specializing in problem/solution narratives.
  Create a 6-scene video script that first identifies a common frustration,
  then positions the product as the perfect solution.
  
  Structure:
  1. Open with a relatable problem statement
  2. Paint a vivid picture of the frustration
  3. Introduce the product with a "But what if..." transition
  4. Highlight 2-3 key features that directly address the problem
  5. Show the positive outcome / transformation
  6. Close with a compelling call-to-action
```

### Changes to Existing Files

| File | Change |
|------|--------|
| `models.py` | Add `script_template: str = 'product_showcase'` to `GenerateRequest` and `GenerationJobRecord` |
| `nova.py` | Refactor `generate_script()` to load prompt from YAML template instead of hardcoded string |
| `v1.py` | Pass `script_template` to job creation; validate template name exists |
| `base.py` / `local.py` / `dynamo.py` | Add `script_template` to `JobCreateParams` (see [Prerequisite: JobCreateParams](#prerequisite-jobcreateparams)) |
| `config/__init__.py` | Add `prompt_templates_dir: str` pointing to templates directory |

### Template Loading

```python
# In nova.py
import yaml
from pathlib import Path

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / 'prompt_templates'

def _load_template(template_name: str) -> dict:
    """Load a YAML prompt template by name."""
    path = TEMPLATES_DIR / f'{template_name}.yaml'
    if not path.exists():
        raise ValueError(f'Unknown script template: {template_name}')
    with open(path) as f:
        return yaml.safe_load(f)
```

---

## 8. Prerequisite: JobCreateParams

The current `create_job()` signature in `base.py` already has 10+ parameters after Phase 1. Phase 2 would add 8 more (`script_template`, `video_style`, `transition_style`, `caption_style`, `show_title_card`, `cta_text`, `job_type`, `source_job_id`). This is unmaintainable.

**Solution**: Introduce a `JobCreateParams` Pydantic model and refactor `create_job()` across all 3 files:

```python
# models.py — new model
class JobCreateParams(BaseModel):
    """All parameters for creating a generation or translation job."""
    aspect_ratio: str = '16:9'
    voice_style: str = 'energetic'
    voice_provider: str = 'polly'
    voice_gender: str = 'female'
    language: str = 'en'
    background_music: str = 'auto'
    idempotency_key: str | None = None
    # Phase 2
    script_template: str = 'product_showcase'
    video_style: str = 'product_only'
    transition_style: str = 'crossfade'
    caption_style: str = 'sentence'
    show_title_card: bool = True
    cta_text: str | None = None
    job_type: str = 'generation'
    source_job_id: str | None = None
```

**Changes:**

| File | Change |
|------|--------|
| `models.py` | Add `JobCreateParams` model |
| `base.py` | Refactor `create_job(self, project_id, owner_id, params: JobCreateParams)` |
| `local.py` | Update to use `JobCreateParams` |
| `dynamo.py` | Update to use `JobCreateParams` |
| `v1.py` | Build `JobCreateParams` from `GenerateRequest` in `enqueue_generation()` |

> This is a **prerequisite refactor** — do it before any feature work begins.

---

## 9. Frontend Changes (All Features)

### Updated Form Layout

```
┌──────────────────────┬──────────────────────┐
│ Aspect Ratio         │ Voice Style          │  (existing)
├──────────────────────┼──────────────────────┤
│ Voice Engine         │ Voice Gender         │  (Phase 1)
├──────────────────────┼──────────────────────┤
│ Language             │ Background Music     │  (Phase 1)
├──────────────────────┼──────────────────────┤
│ Script Style         │ Video Style          │  (Phase 2 — E, C)
├──────────────────────┼──────────────────────┤
│ Transition Effect    │ Caption Style        │  (Phase 2 — D, B)
├──────────────────────┼──────────────────────┤
│ □ Show Title Card    │ CTA Text [________]  │  (Phase 2 — D)
└──────────────────────┴──────────────────────┘
```

### New Dropdown Options

**Script Style** (`scriptTemplate`):
```
product_showcase  → "Product Showcase (Default)"
problem_solution  → "Problem / Solution"
comparison        → "Product Comparison"
unboxing          → "Unboxing Experience"
testimonial       → "Customer Testimonial"
how_to            → "How-To / Tutorial"
seasonal          → "Seasonal Promotion"
luxury            → "Luxury / Premium"
```

**Video Style** (`videoStyle`):
```
product_only       → "Product Images Only (Default)"
product_lifestyle  → "Product + Lifestyle B-Roll"
lifestyle_focus    → "Lifestyle-Focused"
```

**Transition Effect** (`transitionStyle`):
```
crossfade   → "Crossfade (Default)"
cut         → "Hard Cut"
slide_left  → "Slide Left"
wipe_right  → "Wipe Right"
zoom        → "Zoom"
dissolve    → "Dissolve"
```

**Caption Style** (`captionStyle`):
```
sentence        → "Full Sentence (Default)"
word_highlight  → "Word Highlight"
karaoke         → "Karaoke"
none            → "No Captions"
```

### Completed Video Card — Translation Button

On each completed video job card:
```
┌────────────────────────────────────────┐
│  ▶ Product Video — English             │
│  Duration: 32s · Polly · Crossfade     │
│                                        │
│  [Download]  [🌐 Translate]  [Delete]  │
└────────────────────────────────────────┘
```

Clicking "🌐 Translate" opens a modal:
```
┌─ Translate Video ────────────────────┐
│                                      │
│  Select languages:                   │
│  ☑ Spanish   ☑ French   ☐ German    │
│  ☐ Japanese  ☐ Hindi    ☐ Chinese   │
│  ☐ Arabic    ☐ Korean   ☐ Portuguese│
│                                      │
│  Voice: [Edge TTS ▾]  [Female ▾]    │
│                                      │
│  [Cancel]              [Translate]   │
└──────────────────────────────────────┘
```

---

## 10. Dependency & Infra Changes

### Python Dependencies (`pyproject.toml`)

```toml
# Phase 2 additions
"pyyaml>=6.0"                     # Feature E — YAML template loading
"whisper-timestamped>=1.15.0"     # Feature B — OPTIONAL, only if NOVAREEL_TRANSCRIPTION_BACKEND=whisper
```

> **Note**: `whisper-timestamped` is now an **optional** dependency. The default transcription backend is **AWS Transcribe** (no extra Python packages needed). Only install `whisper-timestamped` for offline development. This avoids the ~1.5GB PyTorch Docker image overhead in production.

### Environment Variables

```env
# Phase 2
NOVAREEL_PEXELS_API_KEY=                      # Feature C — free API key from pexels.com
NOVAREEL_TRANSCRIPTION_BACKEND=aws_transcribe  # Feature B — aws_transcribe (default) | whisper
NOVAREEL_WHISPER_MODEL=base                    # Feature B — only if using whisper backend
```

### Docker Considerations

- **Production image**: Uses AWS Transcribe — no PyTorch, no image size increase.
- **Dev image** (optional): Add `whisper-timestamped` for offline caption development.
- Pexels clips are downloaded to temp storage during rendering and cleaned up after — no persistent storage impact.

---

## 11. Testing Strategy

### Unit Tests

| Test | Feature | What to Assert |
|------|---------|----------------|
| `test_translate_script_preserves_line_count` | A | Translation returns same number of lines |
| `test_translate_script_keeps_product_name` | A | Brand/product names not translated |
| `test_word_timestamps_from_audio` | B | Transcription backend returns word-level timestamps with start/end times |
| `test_ass_subtitle_generation` | B | ASS subtitle file has correct `\k` timing tags |
| `test_pexels_search_returns_clips` | C | Mock API returns clip URLs with duration/resolution |
| `test_pexels_download_saves_file` | C | Downloaded clip exists at expected path |
| `test_search_query_generation` | C | LLM generates relevant search queries from script lines |
| `test_xfade_filter_graph` | D | FFmpeg filter string correctly chains segments with transitions |
| `test_text_overlay_positioning` | D | Drawtext filter string has correct coordinates |
| `test_load_yaml_template` | E | Valid YAML loaded with expected fields |
| `test_invalid_template_raises` | E | Unknown template name raises ValueError |
| `test_template_prompt_substitution` | E | Product context injected into template prompt |

### Integration Tests

| Test | What to Assert |
|------|----------------|
| Full translation pipeline (mock AI) | Source job → translate → new jobs created and completed |
| Generate with `caption_style=word_highlight` (mock AI) | Job completes, mock word timestamps in output |
| Generate with `video_style=product_lifestyle` (mock AI) | Job completes with mixed storyboard |
| Generate with `transition_style=crossfade` | Output video has transition effects |
| Generate with `script_template=problem_solution` | Different prompt used, job completes |

### Manual QA Checklist

- [ ] Generate English video → Translate to Spanish → verify Spanish audio + subtitles
- [ ] Generate video with `word_highlight` captions → verify words animate in output MP4
- [ ] Generate video with `product_lifestyle` → verify interleaved B-roll in output
- [ ] Generate video with `crossfade` transitions → verify smooth transitions between scenes
- [ ] Try each script template → verify different narrative styles
- [ ] Generate with all default options → verify backward compatibility

---

## 12. Sprint Plan

### Sprint 3 (Weeks 1-2): Translation Engine + Script Templates

> ℹ️ Translation is the highest-ROI feature and has the deepest architectural impact (new job type, new pipeline, per-job result storage refactor). Shipping it first maximizes bake time and de-risks the most complex feature.

| Day | Task | Feature | Depends On |
|-----|------|---------|------------|
| D1 | Prerequisite: Refactor `create_job()` to use `JobCreateParams` | Infra | — |
| D1 | Prerequisite: Refactor `set_result`/`get_result` to per-job storage | Infra | — |
| D1-D2 | Create `translation.py` — LLM-based contextual translation | A | — |
| D2-D3 | Create `pipeline_translate.py` — translation pipeline orchestrator | A | translation.py |
| D3-D4 | Add `POST /translate` endpoint, update models + repo layer | A | pipeline done |
| D4 | Update worker.py to handle translation jobs alongside generation jobs | A | endpoint done |
| D4-D5 | Create YAML prompt templates directory with 8 templates | E | — |
| D5 | Refactor `nova.generate_script()` to load from templates | E | templates |
| D5 | Frontend: translate button, translation modal, script template dropdown | A, E | API contract |
| D6-D7 | Integration testing, bug fixes | All | everything |

**Sprint 3 deliverable**: One-click video translation, `JobCreateParams` refactor, 8 script narrative styles.

### Sprint 4 (Weeks 3-4): Captions + Transitions

| Day | Task | Feature | Depends On |
|-----|------|---------|------------|
| D1 | Set up transcription backend (`transcription.py` with AWS Transcribe + Whisper) | B | — |
| D1-D2 | Implement word-level timestamp extraction + ASS subtitle generation | B | transcription.py |
| D2-D3 | Prep refactor: restructure `video.py` into segment-based pipeline | D | — |
| D3 | Create `effects.py` with transition/overlay config | D | video.py prep |
| D3-D4 | Implement `xfade` filter graph + `drawtext` overlays in `video.py` | D | effects.py |
| D4-D5 | Update models, repo, v1, pipeline for `caption_style` + `transition_style` | B, D | all above |
| D5 | Frontend: caption style + transition effect dropdowns, title/CTA options | B, D | API contract |
| D6-D7 | Integration testing, bug fixes | All | everything |

**Sprint 4 deliverable**: Word-by-word animated captions, professional transitions, text overlays, CTA end cards.

### Sprint 5 (Weeks 5-6): Stock Footage

> ℹ️ Stock footage depends on an external API and is the easiest feature to descope if sprints slip.

| Day | Task | Feature | Depends On |
|-----|------|---------|------------|
| D1 | Create `stock_media.py` with Pexels API integration + search cache | C | — |
| D1-D2 | Implement LLM search query generation for B-roll | C | stock_media.py |
| D2-D3 | Update `video.py` to handle mixed image+video storyboards | C | stock_media.py |
| D3-D4 | Update models, repo, v1, pipeline for `video_style` | C | all above |
| D4 | Frontend: video style dropdown | C | API contract |
| D4-D5 | Integration testing, end-to-end QA for all Phase 2 features | All | everything |
| D5-D7 | Final QA, performance testing, documentation | All | everything |

**Sprint 5 deliverable**: Stock B-roll integration, full Phase 2 QA sign-off.

---

## 13. Acceptance Criteria

### Feature A: Video Translation & Dubbing
- [ ] Seller clicks "Translate" on completed English video → selects Spanish → translation job queued
- [ ] Translated video has Spanish narration (not English voice reading Spanish)
- [ ] Translated video reuses original storyboard (no re-analysis or re-matching)
- [ ] Product name and brand terms remain untranslated in script
- [ ] Translation job shows progress in UI (same progress stages as generation)
- [ ] Multiple target languages → one job per language, all processed
- [ ] Mock AI mode works for translation pipeline

### Feature B: Word-Level Captions
- [ ] `caption_style=word_highlight` → words appear/highlight one at a time in output video
- [ ] `caption_style=karaoke` → all words visible, current word changes color
- [ ] `caption_style=sentence` → current behavior (backward compatible)
- [ ] `caption_style=none` → no subtitles in output
- [ ] Whisper/Transcribe timestamps are reasonably accurate (within 100ms of spoken words)
- [ ] Non-English languages produce correct word-level timestamps

### Feature C: Stock Footage
- [ ] `video_style=product_lifestyle` → video alternates product images and B-roll clips
- [ ] B-roll clips are relevant to product/scene context
- [ ] B-roll clips are properly scaled to target resolution
- [ ] `video_style=product_only` → current behavior (backward compatible)
- [ ] If Pexels API fails → graceful fallback to product_only style (no crash)
- [ ] No API key configured → `product_lifestyle` returns 422 with clear message

### Feature D: Transitions & Effects
- [ ] `transition_style=crossfade` → smooth crossfade between scenes in output video
- [ ] `transition_style=cut` → current behavior (backward compatible)
- [ ] Title card shows product name in first 3 seconds when enabled
- [ ] CTA end card shows custom text in last 3 seconds
- [ ] Transitions work correctly with both image and video segments (Feature C interaction)
- [ ] If FFmpeg lacks freetype → text overlays gracefully skipped (not a crash)

### Feature E: Script Templates
- [ ] `script_template=problem_solution` → script follows problem/solution narrative arc
- [ ] `script_template=product_showcase` → current behavior (backward compatible)
- [ ] Invalid template name → 422 with available templates listed
- [ ] Each template produces noticeably different narrative style for same product
- [ ] Templates work correctly with all languages (Feature C interaction from Phase 1)

---

## 14. Risks & Mitigations

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| **Whisper + PyTorch bloats Docker image** | Deployment complexity | Low (mitigated) | **Default to AWS Transcribe in production.** Whisper is opt-in for offline dev only. |
| **Pexels API rate limits (200/month free)** | Throttled video generation | Medium | Cache search results (24h TTL); upgrade to paid plan (~$10/month for 20K req) before scaling |
| **FFmpeg xfade compatibility** | Some FFmpeg builds lack xfade filter | Medium | Runtime feature detection; fall back to hard cuts if unsupported |
| **LLM translation quality** | Poor translations damage brand perception | Medium | Add "review before publish" UI; allow manual script editing |
| **drawtext/freetype + libass unavailability** | Text overlays and animated captions don't render | High (known issue) | Feature detection at startup; skip overlays/captions gracefully; document Homebrew install with `--with-libass` |
| **Transcription accuracy for non-English** | Caption timing off for CJK languages | Medium | AWS Transcribe handles CJK well; if using Whisper, use `medium` model; fall back to sentence captions |
| **Sprint scope too large** | Features delayed | Medium | Features are independent — any can be deprioritized without blocking others. Stock Footage (C) is easiest to descope. |
| **Per-job result storage migration** | Breaking change for existing data | Low | Add migration script; old single-result projects get auto-migrated on first read |

---

## Appendix: Full Model Changes (Phase 2 Final State)

```python
# models.py — JobCreateParams (new — prerequisite refactor)
class JobCreateParams(BaseModel):
    """All parameters for creating a generation or translation job."""
    aspect_ratio: str = '16:9'
    voice_style: str = 'energetic'
    voice_provider: str = 'polly'
    voice_gender: str = 'female'
    language: str = 'en'
    background_music: str = 'auto'
    idempotency_key: str | None = None
    # Phase 2
    script_template: str = 'product_showcase'
    video_style: str = 'product_only'
    transition_style: str = 'crossfade'
    caption_style: str = 'sentence'
    show_title_card: bool = True
    cta_text: str | None = None
    job_type: str = 'generation'
    source_job_id: str | None = None


# models.py — GenerateRequest (after Phase 2)
class GenerateRequest(BaseModel):
    # Phase 1 (existing)
    aspect_ratio: Literal['16:9', '1:1', '9:16'] = '16:9'
    voice_style: Literal['energetic', 'professional', 'friendly'] = 'energetic'
    voice_provider: Literal['polly', 'edge_tts', 'elevenlabs'] = 'polly'
    voice_gender: Literal['male', 'female'] = 'female'
    language: str = 'en'
    background_music: Literal['none', 'auto', 'upbeat', 'calm', 'corporate', 'luxury'] = 'auto'
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=128)

    # Phase 2 (new)
    script_template: str = 'product_showcase'                                                       # Feature E
    video_style: Literal['product_only', 'product_lifestyle', 'lifestyle_focus'] = 'product_only'   # Feature C
    transition_style: Literal['cut', 'crossfade', 'slide_left', 'wipe_right', 'zoom', 'dissolve'] = 'crossfade'  # Feature D
    caption_style: Literal['sentence', 'word_highlight', 'karaoke', 'none'] = 'sentence'            # Feature B
    show_title_card: bool = True                                                                      # Feature D
    cta_text: str | None = None                                                                       # Feature D


# models.py — TranslateRequest (new)
class TranslateRequest(BaseModel):
    target_languages: list[str]                                    # Feature A
    voice_provider: Literal['polly', 'edge_tts', 'elevenlabs'] = 'edge_tts'
    voice_gender: Literal['male', 'female'] = 'female'


# models.py — JobStatus (after Phase 2)
class JobStatus(str, Enum):
    QUEUED = 'queued'
    ANALYZING = 'analyzing'
    SCRIPTING = 'scripting'
    MATCHING = 'matching'
    NARRATION = 'narration'
    RENDERING = 'rendering'
    COMPLETED = 'completed'
    FAILED = 'failed'
    # Phase 2 — Feature A (Translation)
    LOADING = 'loading'
    TRANSLATING = 'translating'


# models.py — GenerationJobRecord (after Phase 2)
class GenerationJobRecord(BaseModel):
    # ... existing + Phase 1 fields ...
    job_type: str = 'generation'          # 'generation' | 'translation'    # Feature A
    source_job_id: str | None = None      # For translation jobs              # Feature A
    script_template: str = 'product_showcase'                                 # Feature E
    video_style: str = 'product_only'                                         # Feature C
    transition_style: str = 'crossfade'                                       # Feature D
    caption_style: str = 'sentence'                                           # Feature B
    show_title_card: bool = True                                              # Feature D
    cta_text: str | None = None                                               # Feature D


# models.py — VideoResultRecord (after Phase 2)
class VideoResultRecord(BaseModel):
    project_id: str
    job_id: str                                                               # NEW — per-job results
    video_s3_key: str
    video_url: str
    duration_sec: float
    resolution: str
    thumbnail_key: str | None = None
    transcript_key: str | None = None
    transcript_url: str | None = None
    subtitle_key: str | None = None
    subtitle_url: str | None = None
    storyboard: list[StoryboardSegment] = Field(default_factory=list)
    script_lines: list[str] = Field(default_factory=list)                     # NEW — for translation
    language: str = 'en'                                                       # NEW — for translation
    completed_at: datetime


# models.py — StoryboardSegment (after Phase 2)
class StoryboardSegment(BaseModel):
    order: int
    script_line: str
    image_asset_id: str
    start_sec: float
    duration_sec: float
    media_type: Literal['image', 'video'] = 'image'                           # NEW — Feature C
    video_path: str | None = None                                               # NEW — Feature C
```

## Appendix: New Files Summary

```
services/backend/
├── app/services/
│   ├── translation.py           # Feature A — LLM-based script translation
│   ├── pipeline_translate.py    # Feature A — translation pipeline
│   ├── transcription.py         # Feature B — pluggable: AWS Transcribe + Whisper
│   ├── stock_media.py           # Feature C — Pexels API integration
│   └── effects.py               # Feature D — transition + overlay config
└── prompt_templates/            # Feature E — YAML script templates
    ├── product_showcase.yaml
    ├── problem_solution.yaml
    ├── comparison.yaml
    ├── unboxing.yaml
    ├── testimonial.yaml
    ├── how_to.yaml
    ├── seasonal.yaml
    └── luxury.yaml
```
