# Phase 2 Code Review — Findings & Action Items

> **Reviewer**: Lead Architect
> **Date**: 2026-03-10
> **Scope**: Features A (Translation & Dubbing), B (Word-Level Captions), C (Stock Footage), D (Video Transitions & Overlays), E (Script Templates)
> **Verdict**: Feature E fully compliant. Features A-D have blockers ranging from critical API validation failures to silent degradation.

---

## Overall Status

| Feature | Status | Blockers |
|---------|--------|----------|
| **A. Translation & Dubbing** | **BLOCKED** | DynamoDB result schema risk, claim_job wrong status |
| **B. Word-Level Captions** | **BLOCKED** | Frontend-backend caption_style mismatch |
| **C. Stock Footage** | PASS (1 bug) | Mock B-roll placeholder issue |
| **D. Video Transitions & Overlays** | **BLOCKED** | Frontend-backend transition_style mismatch, missing transitions |
| **E. Script Templates** | PASS | None |
| **Frontend (all)** | **BLOCKED** | 3 critical mismatches with backend |

---

## CRITICAL — Must Fix Before Deploy

### CR2-1: Frontend sends `'simple'` but backend Literal expects `'sentence'` for caption_style [Features B / Frontend]

**Severity**: CRITICAL — Users selecting "Simple subtitles" get a **422 validation error**

**Where**:
- Frontend: `apps/web/components/project-studio.tsx` — line 495
- Backend: `services/backend/app/models.py` — `GenerateRequest.caption_style` line 77

**Problem**: The frontend caption dropdown sends `'simple'` for the "Simple subtitles" option, but the backend Pydantic model only accepts `Literal['sentence', 'word_highlight', 'karaoke', 'none']`. Pydantic will reject `'simple'` with a 422 Unprocessable Entity error.

Additionally, the `generate_ass_subtitles()` function in `transcription.py` has no explicit `'sentence'` handler — it checks for `'karaoke'`, `'word_highlight'`, and falls through to `else` (line 265). So even if `'sentence'` reaches the renderer, it behaves identically to a generic "simple" style.

**Fix** (pick one):
- **Option A** (recommended): Change the backend Literal to match frontend: `Literal['none', 'simple', 'word_highlight', 'karaoke']`. Update default from `'sentence'` to `'none'`.
- **Option B**: Change the frontend `<option value="simple">` to `<option value="sentence">`.

Either way, ensure the value is consistent across: `GenerateRequest`, `JobCreateParams`, `GenerationJobRecord`, `VideoEffectsConfig`, and `generate_ass_subtitles()`.

---

### CR2-2: Frontend sends 13 transition styles but backend Literal only accepts 6 [Feature D / Frontend]

**Severity**: CRITICAL — 7 of 13 transition options return a **422 validation error**

**Where**:
- Frontend: `apps/web/components/project-studio.tsx` — lines 508-522
- Backend: `services/backend/app/models.py` — `GenerateRequest.transition_style` line 76
- Effects: `services/backend/app/services/effects.py` — `TRANSITION_STYLES` dict lines 10-24

**Problem**: Three-way mismatch:

| Value | Frontend dropdown | Backend Literal | TRANSITION_STYLES dict |
|-------|:-:|:-:|:-:|
| `none` | Yes (as "None (cut)") | No (`cut` instead) | Yes |
| `cut` | No | Yes | No |
| `crossfade` | Yes | Yes | Yes |
| `slide_left` | Yes | Yes | Yes |
| `slide_right` | Yes | No | Yes |
| `slide_up` | Yes | No | Yes |
| `slide_down` | Yes | No | Yes |
| `wipe_left` | Yes | No | Yes |
| `wipe_right` | Yes | Yes | Yes |
| `fade_black` | Yes | No | Yes |
| `fade_white` | Yes | No | Yes |
| `circle_open` | Yes | No | Yes |
| `circle_close` | Yes | No | Yes |
| `dissolve` | Yes | Yes | Yes |
| `zoom` | No | Yes | No |

Issues:
1. Frontend sends `'none'` for "cut", but backend expects `'cut'` → **422 error**
2. Frontend sends `'slide_right'`, `'slide_up'`, `'slide_down'`, `'wipe_left'`, `'fade_black'`, `'fade_white'`, `'circle_open'`, `'circle_close'` → all **rejected by backend Literal**
3. Backend Literal accepts `'cut'` and `'zoom'` which don't exist in `TRANSITION_STYLES` → silently fall back to no transition

**Fix**: Align the backend Literal with the effects module's `TRANSITION_STYLES` dict. Replace the Literal on line 76 with:
```python
transition_style: Literal[
    'none', 'crossfade', 'slide_left', 'slide_right',
    'slide_up', 'slide_down', 'wipe_left', 'wipe_right',
    'fade_black', 'fade_white', 'circle_open', 'circle_close', 'dissolve',
] = 'crossfade'
```

Remove `'cut'` and `'zoom'` from the Literal (they were never implemented). The frontend already uses `'none'` for the "no transition" case.

---

### CR2-3: Default value mismatches between frontend and backend [Features B/D / Frontend]

**Severity**: CRITICAL — Silent behavior differences depending on which defaults take effect

**Where**:
- Frontend: `apps/web/components/project-studio.tsx` — lines 41-43
- Backend: `services/backend/app/models.py` — `GenerateRequest` lines 76-78

**Problem**: Three default values disagree:

| Field | Frontend default | Backend default |
|-------|-----------------|-----------------|
| `caption_style` | `'none'` (line 41) | `'sentence'` (line 77) |
| `transition_style` | `'none'` (line 42) | `'crossfade'` (line 76) |
| `show_title_card` | `false` (line 43) | `True` (line 78) |

Since the frontend always sends these fields explicitly, the backend defaults don't apply in the normal flow. However, any API consumer (scripts, tests, other integrations) using the backend directly gets different behavior than the UI.

**Fix**: Align backend defaults to match frontend:
```python
transition_style: Literal[...] = 'none'
caption_style: Literal[...] = 'none'
show_title_card: bool = False
```

---

### CR2-4: DynamoDB results table requires composite key migration [Feature A]

**Severity**: CRITICAL — Translation results **cannot be stored or retrieved** in production DynamoDB

**Where**: `services/backend/app/repositories/dynamo.py` — `get_result()` line 291, `set_result()` line 285

**Problem**: The `get_result()` method queries DynamoDB with a composite key:
```python
response = self._results.get_item(Key={'project_id': project_id, 'job_id': job_id})
```

Phase 2 requires per-job results (one project can have many results: original + translations). This means the DynamoDB results table needs `project_id` as the partition key AND `job_id` as the sort key. If the table was created in Phase 1 with just `project_id` as the primary key:
- `get_item` with `{'project_id': ..., 'job_id': ...}` throws a `ValidationException`
- Multiple `put_item` calls with different `job_id` values overwrite each other (same partition key)

**Impact if not fixed**: All translation result storage fails in production. Only local JSON storage works.

**Fix**:
1. Add a DynamoDB migration script to recreate the results table with composite key `(project_id, job_id)`
2. Or use a GSI (Global Secondary Index) on `job_id` and change the query pattern
3. Document the table schema requirement in deployment docs

---

## HIGH — Fix Soon After Deploy

### CR2-5: `claim_job()` sets SCRIPTING status for all job types [Feature A]

**Severity**: HIGH — Translation jobs show incorrect "scripting" stage in UI

**Where**:
- `services/backend/app/repositories/dynamo.py` — `claim_job()` lines 180-183
- `services/backend/app/repositories/local.py` — `claim_job()` lines 228-229

**Problem**: Both repositories hardcode `JobStatus.SCRIPTING` when claiming a job:
```python
return self.update_job(
    job_id,
    status=JobStatus.SCRIPTING,
    stage=JobStatus.SCRIPTING,
    ...
)
```

Translation jobs should start at `JobStatus.LOADING`, not `SCRIPTING`. The pipeline immediately overwrites this to `LOADING` (pipeline_translate.py line 60), but there's a brief window where the frontend sees "scripting" for a translation job.

**Fix**: Accept `job_type` context in `claim_job()` or set a generic status:
```python
initial_status = JobStatus.LOADING if job.job_type == 'translation' else JobStatus.SCRIPTING
```

---

### CR2-6: Translation pipeline doesn't apply effects or captions [Feature A]

**Severity**: HIGH — Translated videos lose transitions, title cards, CTAs, and captions

**Where**: `services/backend/app/services/pipeline_translate.py` — `render_video()` call lines 146-153

**Problem**: The translation pipeline calls `video_service.render_video()` without passing `effects_config` or `ass_subtitle_path`:
```python
video_key, duration_sec, resolution, thumbnail_key = video_service.render_video(
    project=project,
    job_id=job.id,
    aspect_ratio=job.aspect_ratio,
    storyboard=translated_storyboard,
    storage=storage,
    music_path=music_path,
)
```

The generation pipeline (pipeline.py lines 303-316) passes both `effects_config=effects_config` and `ass_subtitle_path=ass_subtitle_file`. Translated videos therefore render with:
- No transitions between segments
- No title card overlay
- No CTA overlay
- No ASS captions (even if `caption_style != 'none'`)

**Fix**: Add effects and caption generation to the translation pipeline, mirroring pipeline.py lines 268-316:
```python
# Build effects config
job._project_title = project.title
effects_config = VideoEffectsConfig.from_job(job)

# Generate captions if needed
ass_subtitle_file = None
if job.caption_style and job.caption_style != 'none':
    # ... transcription + ASS generation ...

video_key, duration_sec, resolution, thumbnail_key = video_service.render_video(
    ...,
    effects_config=effects_config,
    ass_subtitle_path=ass_subtitle_file,
)
```

---

### CR2-7: Admin debug endpoint doesn't handle translation jobs [Feature A]

**Severity**: HIGH — Admin endpoint silently runs wrong pipeline for translation jobs

**Where**: `services/backend/app/api/v1.py` — `process_single_job()` lines 496-498

**Problem**: The debug endpoint always calls `process_generation_job`:
```python
from app.services.pipeline import process_generation_job
process_generation_job(repo=repo, storage=storage, nova=nova, video_service=video_service, job=claimed or job)
```

The worker (worker.py line 34) correctly dispatches by `job_type`, but this endpoint doesn't. Running a translation job through the generation pipeline would fail (no source result to translate from).

**Fix**: Add the same dispatch logic as the worker:
```python
if (claimed or job).job_type == 'translation':
    from app.services.pipeline_translate import process_translation_job
    translation_service = get_translation_service()
    process_translation_job(repo=repo, storage=storage, translation_service=translation_service, video_service=video_service, job=claimed or job)
else:
    from app.services.pipeline import process_generation_job
    process_generation_job(repo=repo, storage=storage, nova=nova, video_service=video_service, job=claimed or job)
```

---

### CR2-8: No validation of target language codes in translate endpoint [Feature A]

**Severity**: HIGH — Invalid language codes silently degrade translation quality

**Where**: `services/backend/app/api/v1.py` — `translate_video()` lines 338-344

**Problem**: The endpoint validates that `target_languages` is non-empty (line 334-335) but never validates that each language code exists in `SUPPORTED_LANGUAGES`. A request with `target_languages: ["xyz"]` would create a translation job that produces gibberish.

**Fix**:
```python
from app.config.languages import SUPPORTED_LANGUAGES

for lang in payload.target_languages:
    if lang not in SUPPORTED_LANGUAGES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f'Unsupported language: {lang}. Supported: {", ".join(sorted(SUPPORTED_LANGUAGES.keys()))}'
        )
```

**Note**: This was also flagged in Phase 1 review (CR-4) for the generation endpoint. Both endpoints need this fix.

---

## MEDIUM — Fix In Next Sprint

### CR2-9: Translation uses language codes instead of names in LLM prompt [Feature A]

**Severity**: MEDIUM — LLMs perform better with full language names

**Where**: `services/backend/app/services/translation.py` — `_build_prompt()` line 53-54

**Problem**: The translation prompt says `"from en to es"` instead of `"from English to Spanish"`. LLMs produce better translations when given full language names.

**Fix**:
```python
from app.config.languages import get_language_name

source_name = get_language_name(source_language)  # "English"
target_name = get_language_name(target_language)   # "Spanish"
# Use in prompt: f"from {source_name} to {target_name}"
```

**Note**: Also flagged in Phase 1 review (CR-8).

---

### CR2-10: Translation modal only shows 12 of 20 supported languages [Feature A / Frontend]

**Severity**: MEDIUM — 8 languages unavailable for translation from the UI

**Where**: `apps/web/components/project-studio.tsx` — translation modal lines 671-694

**Problem**: The main generation form shows all 20 languages (lines 414-434), but the translation modal only offers 12. Missing: Dutch (nl), Polish (pl), Swedish (sv), Thai (th), Vietnamese (vi), Indonesian (id), Malay (ms), plus Arabic is included in translation but order differs.

**Fix**: Extract the language list to a shared constant and use it in both the generation dropdown and translation modal. Consider importing from a shared config:
```typescript
const SUPPORTED_LANGUAGES = [
  { code: 'en', label: 'English' },
  { code: 'es', label: 'Spanish (Español)' },
  // ... all 20 ...
] as const;
```

**Note**: Also flagged in Phase 1 review (CR-7).

---

### CR2-11: Mock B-roll writes placeholder bytes, not actual video [Feature C]

**Severity**: MEDIUM — Video rendering fails silently on mock B-roll segments

**Where**: `services/backend/app/services/pipeline.py` — `_fetch_stock_footage()` line 125

**Problem**: In mock mode, B-roll clips are written as 22 bytes of text:
```python
clip_path.write_bytes(b'MOCK_VIDEO_PLACEHOLDER')
```

The video renderer checks `broll_path.stat().st_size > 100` (video.py line 116), so these 22-byte files fail the size check and fall back to image rendering. The stock footage feature is effectively untestable in mock mode.

**Fix**: Either:
- **Option A**: Generate a minimal valid MP4 (use ffmpeg to create a 1-second color video)
- **Option B**: Skip B-roll entirely in mock mode by returning the original storyboard, and log it
- **Option C**: Lower the size threshold check (but then ffmpeg would fail on invalid video data)

Recommend **Option B** for simplicity.

---

### CR2-12: `caption_style='sentence'` declared in model but not implemented [Feature B]

**Severity**: MEDIUM — Backend's default caption style has no dedicated rendering logic

**Where**: `services/backend/app/services/transcription.py` — `generate_ass_subtitles()` lines 239-269

**Problem**: The function handles three named styles:
- `'karaoke'` — line 239
- `'word_highlight'` — line 251
- `else` (fallback) — line 265

The backend model declares `'sentence'` as a valid option and default, but `generate_ass_subtitles()` has no `caption_style == 'sentence'` branch. The value `'sentence'` falls through to the `else` branch which renders word-by-word simple subtitles, identical to what `'simple'` would produce.

If `'sentence'` was intended to show full sentences (grouped text without word-level timing), it needs its own implementation.

**Fix**: Either implement a distinct `'sentence'` style or rename it to `'simple'` everywhere (see CR2-1).

---

### CR2-13: Stock footage stage not cached in resumable pipeline [Feature C / Phase 1 Feature D]

**Severity**: MEDIUM — Stock footage re-fetched from Pexels on every retry

**Where**: `services/backend/app/services/pipeline.py` — `_fetch_stock_footage()` call lines 221-231

**Problem**: The pipeline caches image analysis, script, storyboard, and narration audio, but the stock footage stage runs unconditionally. If a job fails during rendering and retries, all Pexels API calls and video downloads re-execute.

The Pexels search has its own 24-hour file cache (`StockMediaService._load_from_cache()`), so API calls are mitigated. But the actual video downloads are not cached at the pipeline level.

**Fix**: Cache the updated storyboard (with B-roll paths) at `{prefix}/storyboard_with_broll.json` and check for it before calling `_fetch_stock_footage()`:
```python
existing_broll = storage.load_text(f'{prefix}/storyboard_with_broll.json')
if existing_broll:
    storyboard = [StoryboardSegment(**s) for s in json.loads(existing_broll)]
elif job.video_style and job.video_style != 'product_only':
    storyboard = _fetch_stock_footage(...)
    storage.store_text(f'{prefix}/storyboard_with_broll.json', json.dumps([s.model_dump() for s in storyboard]))
```

---

### CR2-14: `_to_srt_timestamp()` function duplicated across pipeline files

**Severity**: MEDIUM — Code duplication, maintenance burden

**Where**:
- `services/backend/app/services/pipeline.py` — lines 19-27
- `services/backend/app/services/pipeline_translate.py` — lines 18-26

**Problem**: The `_to_srt_timestamp()` function and `_build_srt()` function are copy-pasted identically between the two pipeline files.

**Fix**: Extract to a shared utility module (e.g., `services/backend/app/services/subtitle_utils.py`) and import from both pipelines.

---

## LOW — Nice To Have

### CR2-15: Translation narration synthesizes full transcript, not per-line [Feature A]

**Where**: `services/backend/app/services/pipeline_translate.py` — lines 114-132

**Problem**: The translation pipeline concatenates all lines and synthesizes as one blob:
```python
transcript = '\n'.join(translated_lines)
audio_payload = provider.synthesize(transcript[:3000], ...)
```

This produces a single audio track with all lines spoken sequentially. The per-segment timing in the storyboard may not match the actual audio timing, leading to audio-video drift.

The generation pipeline has the same approach, so this isn't a regression — but it's a design limitation worth noting.

**Impact**: Low for short videos (30-60 sec). More noticeable for longer translations.

**Fix**: Consider per-segment synthesis and concatenation for better timing control. Non-trivial change — recommend tracking as a future improvement.

---

### CR2-16: Translation service uses `invoke_model()` instead of `converse()` [Feature A]

**Where**: `services/backend/app/services/translation.py` — `_call_llm()` lines 83-88

**Problem**: The translation service uses the older `invoke_model()` API:
```python
response = self._client.invoke_model(
    modelId=self._model_id,
    body=body,
    contentType='application/json',
    accept='application/json',
)
```

While the stock media service uses the newer `converse()` API (stock_media.py line 231):
```python
response = bedrock_client.converse(
    modelId=model_id,
    messages=[...],
    inferenceConfig={...},
)
```

Both work, but `converse()` is the recommended API for Bedrock and handles model-specific formatting internally.

**Fix**: Migrate translation service to use `converse()` for consistency. Low priority.

---

### CR2-17: No error handling for storyboard/script_lines length mismatch in translation [Feature A]

**Where**: `services/backend/app/services/pipeline_translate.py` — line 99

**Problem**: The loop assumes `translated_lines` has at least as many entries as `storyboard`:
```python
script_line=translated_lines[i] if i < len(translated_lines) else segment.script_line,
```

The fallback `segment.script_line` preserves the original (untranslated) text, which is correct for safety but produces a mixed-language video without any warning.

**Fix**: Add a warning log when lengths don't match:
```python
if len(translated_lines) != len(storyboard):
    logger.warning('Translation returned %d lines but storyboard has %d segments', len(translated_lines), len(storyboard))
```

---

## What Was Done Well

- **Translation pipeline architecture** is clean — separate `pipeline_translate.py` with proper stage progression (LOADING → TRANSLATING → NARRATION → RENDERING → COMPLETED)
- **TranslationService** has robust LLM output parsing — strips accidental numbering, pads/truncates to exact line count
- **Transcription module** is well-structured with proper abstraction (MockBackend, WhisperBackend, AWSTranscribeBackend) and factory function
- **ASS subtitle generation** is sophisticated — supports karaoke, word highlight, and simple modes with proper timing
- **Stock media service** has good caching (24-hour TTL), proper error handling, and graceful degradation when Pexels API is unavailable
- **Effects module** is cleanly designed — `TransitionConfig.from_style()` with fallback, `VideoEffectsConfig.from_job()` factory
- **Script templates** are fully compliant — all 8 YAML templates present, `nova.py` correctly loads them, frontend dropdown matches
- **Video rendering** handles mixed image+video storyboards correctly with B-roll scaling, Ken Burns on images, and xfade transition chains
- **Worker** correctly dispatches by `job_type` with proper retry/dead-letter logic for both job types
- **Frontend** has translate modal with proper state management and polling for translation job status
- **Pexels API validation** in the generate endpoint (v1.py lines 180-185) prevents stock footage styles when API key is missing

---

## Action Items Summary

| ID | Severity | Feature | Effort | Description |
|----|----------|---------|--------|-------------|
| CR2-1 | **CRITICAL** | B/FE | 30 min | Align caption_style values: frontend 'simple' vs backend 'sentence' |
| CR2-2 | **CRITICAL** | D/FE | 30 min | Align transition_style Literal with TRANSITION_STYLES and frontend |
| CR2-3 | **CRITICAL** | B/D/FE | 15 min | Align default values between frontend and backend |
| CR2-4 | **CRITICAL** | A | 2 hrs | DynamoDB results table composite key migration |
| CR2-5 | HIGH | A | 30 min | Fix claim_job() to set correct initial status per job_type |
| CR2-6 | HIGH | A | 1.5 hrs | Add effects_config + captions to translation pipeline |
| CR2-7 | HIGH | A | 15 min | Add job_type dispatch to admin debug endpoint |
| CR2-8 | HIGH | A | 30 min | Add language code validation in translate endpoint |
| CR2-9 | MEDIUM | A | 15 min | Use language names instead of codes in translation prompt |
| CR2-10 | MEDIUM | A/FE | 30 min | Expand translation modal to all 20 languages |
| CR2-11 | MEDIUM | C | 30 min | Fix mock B-roll to skip or generate valid video |
| CR2-12 | MEDIUM | B | 30 min | Implement or rename 'sentence' caption style |
| CR2-13 | MEDIUM | C/D | 1 hr | Cache stock footage stage in resumable pipeline |
| CR2-14 | MEDIUM | A | 15 min | Extract shared SRT utilities |
| CR2-15 | LOW | A | — | Per-segment narration synthesis (future) |
| CR2-16 | LOW | A | 30 min | Migrate translation to converse() API |
| CR2-17 | LOW | A | 15 min | Add warning log for line count mismatch |

**Total estimated fix effort**: ~9-10 hours

**Recommended priority**: CR2-1 → CR2-2 → CR2-3 → CR2-4 → CR2-6 → CR2-5 → CR2-8 → CR2-7 → CR2-12 → rest

---

## Cross-Reference with Phase 1 Review

Several Phase 1 findings remain relevant or overlap:

| Phase 1 ID | Phase 2 ID | Status |
|------------|------------|--------|
| CR-4 (language validation) | CR2-8 | Still unfixed — now affects translate endpoint too |
| CR-7 (translation modal languages) | CR2-10 | Still unfixed |
| CR-8 (language codes in prompt) | CR2-9 | Still unfixed — now affects translation service too |
| CR-1 (S3 storage methods) | — | Must also be fixed for translation results storage |
| CR-2 (intermediate cleanup) | — | Translation pipeline also lacks cleanup on failure |
