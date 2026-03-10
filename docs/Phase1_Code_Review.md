# Phase 1 Code Review — Findings & Action Items

> **Reviewer**: Lead Architect
> **Date**: 2026-03-10
> **Scope**: Features A (Multi-Provider TTS), B (Background Music), C (Multi-Language), D (Resumable Pipeline)
> **Verdict**: 3 of 4 features production-ready. Feature D has a **critical blocker** for S3 environments.

---

## Overall Status

| Feature | Status | Blockers |
|---------|--------|----------|
| **A. Multi-Provider TTS** | PASS | None |
| **B. Background Music** | PASS (1 bug) | None critical |
| **C. Multi-Language** | PASS (2 fixes needed) | None critical |
| **D. Resumable Pipeline** | **BLOCKED** | S3StorageService missing methods |
| **Frontend (all)** | PASS | Minor gaps |

---

## CRITICAL — Must Fix Before Deploy

### CR-1: S3StorageService missing `load_text()`, `exists()`, `delete_prefix()` [Feature D]

**Severity**: CRITICAL — Pipeline resume is **completely non-functional** in production S3 mode

**Where**: `services/backend/app/services/storage.py` — `S3StorageService` class

**Problem**: The resumable pipeline calls `storage.load_text()`, `storage.exists()`, and `storage.delete_prefix()` to check for cached intermediate artifacts. These methods are implemented in `LocalStorageService` but **NOT in `S3StorageService`**. The base class stubs return `None`/`False`/no-op, so:
- Cache checks always miss → every retry re-runs ALL stages (no cost savings)
- Intermediate artifacts written to S3 are never read back
- Intermediate artifacts are never cleaned up → S3 storage bloat

**Fix**:
```
S3StorageService needs 3 new method overrides:

load_text(key) → s3.get_object(Bucket=..., Key=key) → read body as UTF-8, return None on NoSuchKey
exists(key) → s3.head_object(Bucket=..., Key=key) → return True, except ClientError return False
delete_prefix(prefix) → s3.list_objects_v2(Prefix=prefix) + s3.delete_objects() for all matches
```

**Impact if not fixed**: Zero cost savings on retries in production. Pipeline behaves as if Feature D doesn't exist when `NOVAREEL_STORAGE_BACKEND=dynamodb` (S3 mode).

---

### CR-2: No cleanup of intermediate artifacts from failed jobs [Feature D]

**Severity**: CRITICAL — Storage bloat over time

**Where**: `services/backend/app/services/pipeline.py` — exception handler (~line 370)

**Problem**: `storage.delete_prefix()` is only called on **successful** completion (line 359). Failed jobs leave orphaned intermediate artifacts in storage forever. Over time, with retries and failures, this accumulates significant garbage data.

**Fix**: Add cleanup in the exception handler:
```python
except Exception as exc:
    # Clean up intermediate artifacts from failed attempt
    try:
        storage.delete_prefix(f'{prefix}/')
    except Exception:
        pass  # Don't mask the original error
    # ... existing error handling ...
```

**Alternative**: Add a periodic cleanup job that removes intermediate directories older than 24 hours.

---

## HIGH — Fix Soon After Deploy

### CR-3: ElevenLabs provider ignores `language` parameter [Feature C]

**Severity**: HIGH — ElevenLabs always uses the same English voice (Rachel/Adam) regardless of language

**Where**: `services/backend/app/services/voice/elevenlabs.py`

**Problem**: Polly and EdgeTTS both use `get_voice_name(language, provider, gender)` from `config/languages.py` to select language-appropriate voices. ElevenLabs uses a hardcoded `_VOICE_MAP = {'female': 'Rachel', 'male': 'Adam'}` and completely ignores the language parameter.

The `eleven_multilingual_v2` model can handle multilingual text, but an English-persona voice speaking Japanese sounds unnatural compared to a native Japanese voice.

**Fix**: Use `get_voice_name()` like the other providers, or at minimum, look up ElevenLabs voice IDs from the languages config. Since `elevenlabs_supported` is only `True` for 8 languages in the config, fall back to the generic Rachel/Adam for unsupported languages.

---

### CR-4: No validation of language codes in API [Feature C]

**Severity**: HIGH — Invalid language codes silently degrade instead of returning a helpful error

**Where**: `services/backend/app/api/v1.py` — `enqueue_generation()` and translate endpoint

**Problem**: The API accepts any string as `language` (e.g., `"xyz"`, `"klingon"`) without validating against `SUPPORTED_LANGUAGES`. The pipeline will silently fall back to English voices, but the script will be generated with an invalid language instruction, producing unpredictable results.

**Fix**: Add validation in `enqueue_generation()`:
```python
from app.config.languages import SUPPORTED_LANGUAGES

if payload.language not in SUPPORTED_LANGUAGES:
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=f'Unsupported language: {payload.language}. Supported: {", ".join(sorted(SUPPORTED_LANGUAGES.keys()))}'
    )
```

Same for `target_languages` in the translate endpoint.

---

### CR-5: `last_completed_stage` field defined but never used [Feature D]

**Severity**: HIGH — Dead code / incomplete implementation

**Where**: `services/backend/app/models.py` — `GenerationJobRecord.last_completed_stage`

**Problem**: The field exists in the model (as specified in the plan) but is never read or written anywhere in the pipeline. The resumable logic works entirely via storage checks (checking if intermediate files exist), not via the job record's stage tracking.

**Fix** (pick one):
- **Option A**: Remove the field — the storage-based cache check approach works fine without it
- **Option B**: Populate it after each stage so admins can see in the job record which stages were completed. Useful for debugging but not functionally required.

Recommend **Option A** for simplicity unless admin visibility is needed.

---

## MEDIUM — Fix In Next Sprint

### CR-6: Music mux condition prevents music on narration-less videos [Feature B]

**Where**: `services/backend/app/services/video.py` — music mux block (~line 272)

**Problem**: The condition is:
```python
if music_path and music_path.exists() and final_video != joined_video:
```
The `final_video != joined_video` check means music is only added if the narration audio mux succeeded. If narration fails or produces no audio, music is silently skipped.

**Expected behavior**: Music should be added regardless of narration status. A video with music but no narration is still better than a completely silent video.

**Fix**: Remove the `final_video != joined_video` check:
```python
if music_path and music_path.exists():
```

---

### CR-7: Translation modal only shows 12 of 20 supported languages [Feature C / Frontend]

**Where**: `apps/web/components/project-studio.tsx` — translation modal (~line 671-694)

**Problem**: The main generation form correctly shows all 20 languages, but the translation modal only offers 12 (missing: Dutch, Polish, Swedish, Thai, Vietnamese, Indonesian, Malay, Arabic).

**Fix**: Use the same 20-language list in both the generation dropdown and the translation modal. Consider extracting to a shared constant.

---

### CR-8: Translation service uses language codes instead of names in prompt [Feature C]

**Where**: `services/backend/app/services/translation.py`

**Problem**: The translation prompt says "from en to zh" instead of "from English to Chinese". LLMs perform better with full language names.

**Fix**: Import and use `get_language_name()` from `config/languages.py`:
```python
from app.config.languages import get_language_name

source_name = get_language_name(source_language)  # "English"
target_name = get_language_name(target_language)  # "Chinese"
# Use in prompt: f"Translate from {source_name} to {target_name}"
```

---

### CR-9: Transcription results not cached in resumable pipeline [Feature D]

**Where**: `services/backend/app/services/pipeline.py` — transcription stage (~line 271-293)

**Problem**: The pipeline caches image analysis, script, storyboard, and narration audio — but NOT transcription/word timings. If rendering fails after transcription, the (potentially expensive) Whisper transcription re-runs on retry.

**Fix**: Cache `word_timings` at `{prefix}/word_timings.json` with the same pattern as other stages.

---

### CR-10: Stock footage downloads not cached in resumable pipeline [Feature D]

**Where**: `services/backend/app/services/pipeline.py` — stock footage stage (~line 220-231)

**Problem**: Stock footage clips fetched from Pexels are downloaded fresh on every run. Should be cached to avoid redundant network requests on retries.

**Fix**: Cache the updated storyboard (with stock footage URLs) at `{prefix}/storyboard_with_broll.json`.

---

## LOW — Nice To Have

### CR-11: No `default_voice_provider` in Settings [Feature A]

**Where**: `services/backend/app/config/__init__.py`

**Problem**: The plan specified a `default_voice_provider` config setting, but it wasn't implemented. The default comes from the Pydantic model's `Literal` type default (`'polly'`).

**Impact**: Negligible — the model default achieves the same thing. But if an admin wants to change the default without a code deploy, they can't.

**Fix**: Add `default_voice_provider: str = 'polly'` to Settings and use it as the model default.

---

### CR-12: Mock audio returns encoded strings, not valid MP3 bytes [Feature A]

**Where**: All voice providers + `pipeline.py` mock mode

**Problem**: Mock mode returns `f'MOCK-VOICE::polly::female::text'.encode('utf-8')` which is not valid MP3. Any downstream code that tries to parse or probe this as audio will fail.

**Impact**: Only affects mock mode testing. Production unaffected.

**Fix**: Return a minimal valid MP3 frame (a few bytes of valid MP3 header + silence) or keep as-is with documentation.

---

### CR-13: No logging of language/voice selection in providers [Feature A/C]

**Where**: Voice provider implementations

**Problem**: When a voice provider falls back from a requested language to English, there's no log message. Makes debugging "why does my Japanese video have an English voice?" difficult.

**Fix**: Add `logger.info('Selected voice: %s for language=%s provider=%s gender=%s', voice_name, language, provider, gender)` in each provider.

---

### CR-14: Polly has no male voice for 5 languages [Feature C]

**Where**: `services/backend/app/config/languages.py`

**Problem**: Arabic, Hindi, Chinese, Korean, and Swedish have `polly_male: None`. If a user selects Polly + male + one of these languages, it falls back to English `Matthew`.

**Impact**: Low — EdgeTTS covers all languages with both genders. Polly is the legacy provider.

**Fix**: Document as known limitation, or log a warning when fallback occurs.

---

## What Was Done Well

- **Clean factory pattern** for voice providers — easy to add new providers later
- **Language config** is comprehensive with 20 languages and per-provider voice mappings
- **Music implementation** is solid — auto-mapping, looping, graceful degradation all work
- **Frontend** is fully integrated with all 4 features, proper state management, good UX
- **Backward compatibility** maintained — existing requests without new fields use sensible defaults
- **Nova `synthesize_voice()` properly removed** — clean migration to voice providers
- **EdgeTTS async handling** is correct — runs async internally but exposes sync interface
- **Pipeline stage caching** (for local storage) works correctly with proper cleanup

---

## Action Items Summary

| ID | Severity | Feature | Effort | Description |
|----|----------|---------|--------|-------------|
| CR-1 | **CRITICAL** | D | 2-3 hrs | Implement S3StorageService `load_text()`, `exists()`, `delete_prefix()` |
| CR-2 | **CRITICAL** | D | 30 min | Add intermediate artifact cleanup for failed jobs |
| CR-3 | HIGH | C | 1 hr | Make ElevenLabs provider use language-aware voice selection |
| CR-4 | HIGH | C | 30 min | Add language code validation in API endpoints |
| CR-5 | HIGH | D | 15 min | Remove unused `last_completed_stage` field (or populate it) |
| CR-6 | MEDIUM | B | 15 min | Fix music mux condition to work without narration |
| CR-7 | MEDIUM | C | 30 min | Expand translation modal to show all 20 languages |
| CR-8 | MEDIUM | C | 15 min | Use language names in translation prompt |
| CR-9 | MEDIUM | D | 1 hr | Cache transcription results |
| CR-10 | MEDIUM | D | 1 hr | Cache stock footage downloads |
| CR-11 | LOW | A | 15 min | Add `default_voice_provider` to Settings |
| CR-12 | LOW | A | 15 min | Improve mock audio format |
| CR-13 | LOW | A/C | 30 min | Add voice selection logging |
| CR-14 | LOW | C | 15 min | Document Polly male voice gaps |

**Total estimated fix effort**: ~8-9 hours

**Recommended priority**: CR-1 → CR-2 → CR-4 → CR-3 → CR-6 → CR-7 → CR-8 → rest
