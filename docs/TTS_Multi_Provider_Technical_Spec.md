# Technical Spec: Multi-Provider TTS Engine

> **Status**: Ready for implementation
> **Author**: Lead Architect
> **Priority**: Critical — competitive differentiator
> **Estimated effort**: 1.5–2 weeks
> **Dependencies**: None (can start immediately)

---

## 1. Overview

Replace the current single-provider (AWS Polly) voice synthesis with a pluggable multi-provider system offering sellers three choices:

| Provider | Cost | Languages | Quality | Use Case |
|----------|------|-----------|---------|----------|
| **AWS Polly** | ~$4/1M chars | 30+ | Good | Default, existing infra |
| **EdgeTTS** | Free (Microsoft) | 50+ | Good | Free tier, max language coverage |
| **ElevenLabs** | ~$0.30/1K chars | 29 | Premium | Premium tier, natural-sounding |

---

## 2. Current State (AS-IS)

### How voice synthesis works today

1. **API Request** → `POST /v1/projects/{id}/generate` accepts `voice_style: "energetic" | "professional" | "friendly"` but this field is **never actually used** in the Polly call
2. **Pipeline** → `pipeline.py:93` calls `nova.synthesize_voice(script_lines, job.voice_style)`
3. **NovaService** → `nova.py:365-390` — always uses hardcoded `Polly(VoiceId='Joanna')` regardless of `voice_style`
4. **Output** → MP3 bytes stored at `projects/{project_id}/outputs/{job_id}.mp3`

### Key files involved

| File | Role | Lines of Interest |
|------|------|-------------------|
| `services/backend/app/models.py` | Pydantic models — `GenerateRequest` (L61-64), `GenerationJobRecord` (L67-85) | `voice_style` field defined here |
| `services/backend/app/config.py` | Settings — `polly_voice_id` (L40), `bedrock_model_voice` (L39, unused) | Add new provider config here |
| `services/backend/app/services/nova.py` | `synthesize_voice()` (L365-390) | Current Polly-only implementation |
| `services/backend/app/services/pipeline.py` | Pipeline narration stage (L79-95) | Calls `nova.synthesize_voice()` |
| `services/backend/app/api/v1.py` | `enqueue_generation()` (L146-209) | Passes voice_style to job |
| `services/backend/app/repositories/base.py` | `create_job()` (L56-65) | Abstract — takes `voice_style: str` |
| `services/backend/app/repositories/local.py` | `create_job()` (L168-201) | Stores voice_style in job record |
| `services/backend/app/repositories/dynamo.py` | `create_job()` (L129-160) | Same for DynamoDB |
| `services/backend/app/dependencies.py` | DI container — `get_nova_service()` (L26-29) | Add voice provider factory here |
| `apps/web/lib/contracts.ts` | TS types — `GenerationJob` (L20-39) | Add `voice_provider` field |
| `apps/web/lib/api.ts` | `generateProject()` (L82-91) | Sends generation request |
| `apps/web/components/project-studio.tsx` | UI form — voice style dropdown (L304-314) | Add provider dropdown here |

---

## 3. Target State (TO-BE)

### 3.1 New API Contract

**`GenerateRequest`** — add two new fields:

```
voice_provider: "polly" | "edge_tts" | "elevenlabs"  (default: "polly")
voice_gender:   "male" | "female"                     (default: "female")
```

Keep the existing `voice_style` field as-is for backward compatibility — it will be used by Polly for SSML style selection in the future. The new `voice_provider` determines which TTS engine is used. The `voice_gender` selects male/female voice variants.

**Example request:**
```json
POST /v1/projects/{id}/generate
{
  "aspect_ratio": "16:9",
  "voice_style": "energetic",
  "voice_provider": "edge_tts",
  "voice_gender": "female",
  "idempotency_key": "abc123"
}
```

**`GenerationJobRecord`** — add matching fields:
```
voice_provider: str = "polly"
voice_gender: str = "female"
```

### 3.2 Architecture

```
                         ┌──────────────────┐
  GenerateRequest ──────>│  Pipeline        │
  (voice_provider,       │  (pipeline.py)   │
   voice_style,          │                  │
   voice_gender)         │  NARRATION stage │
                         │       │          │
                         └───────┼──────────┘
                                 │
                                 v
                    ┌─────────────────────────┐
                    │  build_voice_provider()  │
                    │  (factory function)      │
                    └────────┬────────────────┘
                             │
              ┌──────────────┼──────────────┐
              v              v              v
     ┌──────────────┐ ┌───────────┐ ┌──────────────┐
     │ PollyProvider │ │ EdgeTTS   │ │ ElevenLabs   │
     │              │ │ Provider  │ │ Provider     │
     │ boto3.polly  │ │ edge_tts  │ │ HTTP REST    │
     │ MP3 bytes    │ │ MP3 bytes │ │ MP3 bytes    │
     └──────────────┘ └───────────┘ └──────────────┘
```

### 3.3 File Structure (new files to create)

```
services/backend/app/services/voice/
├── __init__.py           # Re-exports
├── base.py               # Abstract VoiceProvider interface
├── polly.py              # AWS Polly implementation (extract from nova.py)
├── edge_tts.py           # Microsoft EdgeTTS implementation
├── elevenlabs.py         # ElevenLabs implementation
└── factory.py            # build_voice_provider(provider, settings) -> VoiceProvider
```

---

## 4. Detailed Implementation Guide

### Task 1: Abstract Voice Provider Interface

**File**: `services/backend/app/services/voice/base.py`

```python
from abc import ABC, abstractmethod

class VoiceProvider(ABC):
    """Abstract interface for TTS providers."""

    @abstractmethod
    def synthesize(self, text: str, voice_gender: str = 'female') -> bytes:
        """Convert text to speech audio.

        Args:
            text: The text to synthesize (max ~3000 chars).
            voice_gender: 'male' or 'female'.

        Returns:
            MP3 audio bytes.

        Raises:
            VoiceSynthesisError: If synthesis fails after retries.
        """
        ...

    @abstractmethod
    def provider_name(self) -> str:
        """Return the provider identifier string."""
        ...


class VoiceSynthesisError(Exception):
    """Raised when voice synthesis fails."""
    pass
```

**Key decisions:**
- Returns `bytes` (not file paths) — matches existing pipeline contract where `nova.synthesize_voice()` returns bytes
- `voice_gender` instead of explicit voice ID — keeps the UI simple while enabling male/female selection
- No async — the pipeline is synchronous; EdgeTTS async internals are hidden inside the provider

---

### Task 2: Polly Provider (refactor from nova.py)

**File**: `services/backend/app/services/voice/polly.py`

**What to do:**
- Extract lines 365-390 from `nova.py` → `PollyVoiceProvider.synthesize()`
- Use `voice_gender` to select voice: female → `Joanna`, male → `Matthew` (or make configurable via Settings)
- Keep the existing 3000-char truncation
- On failure, raise `VoiceSynthesisError` instead of returning mock bytes (let the caller decide fallback)

**Polly voice mapping (for `voice_gender`):**
```
female: "Joanna"  (en-US, Neural)
male:   "Matthew" (en-US, Neural)
```

**Constructor takes:** `Settings` (for `aws_region`)

---

### Task 3: EdgeTTS Provider

**File**: `services/backend/app/services/voice/edge_tts.py`

**What to do:**
- Port logic from ShortGPT's `shortGPT/audio/edge_voice_module.py` (at `/tmp/ShortGPT/`)
- Use the voice name mapping from ShortGPT's `shortGPT/config/languages.py` (EDGE_TTS_VOICENAME_MAPPING)
- For now, hardcode to English voices. Language support will be a separate task.
- EdgeTTS generates to a file; read the file bytes and return them. Use a `tempfile.NamedTemporaryFile`.

**EdgeTTS English voice mapping (for `voice_gender`):**
```
female: "en-AU-NatashaNeural"
male:   "en-AU-WilliamNeural"
```

**Important implementation details from ShortGPT reference:**
- `edge_tts` library is async — use `asyncio.new_event_loop()` + `loop.run_until_complete()` to run synchronously
- Stream audio chunks from `edge_tts.Communicate(text, voiceName).stream()` and write chunks where `chunk["type"] == "audio"` to file
- After generation, verify file exists and has size > 0, else raise `VoiceSynthesisError`

**Constructor takes:** Nothing (EdgeTTS is free, no API key needed)

**New dependency to add to `pyproject.toml`:**
```
"edge-tts>=6.1.0"
```

---

### Task 4: ElevenLabs Provider

**File**: `services/backend/app/services/voice/elevenlabs.py`

**What to do:**
- Port logic from ShortGPT's `shortGPT/audio/eleven_voice_module.py` and `shortGPT/api_utils/eleven_api.py`
- Use ElevenLabs REST API directly (no SDK needed — just `httpx` which is already a dependency)
- Model: `eleven_multilingual_v2`
- Before generating, check remaining character credits; raise `VoiceSynthesisError` if insufficient

**ElevenLabs API calls (from ShortGPT reference):**

1. **List voices**: `GET https://api.elevenlabs.io/v1/voices` → build `{name: voice_id}` map
2. **Check credits**: `GET https://api.elevenlabs.io/v1/user` → `subscription.character_limit - subscription.character_count`
3. **Generate**: `POST https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream`
   - Headers: `xi-api-key: {api_key}`, `Content-Type: application/json`
   - Body: `{"model_id": "eleven_multilingual_v2", "text": "...", "stability": 0.2, "similarity_boost": 0.1}`
   - Response: raw MP3 bytes (status 200)

**Voice selection by `voice_gender`:**
- Use the first available voice matching the gender from the voices list
- Or default to well-known voices: female → "Rachel", male → "Adam"

**Constructor takes:** `api_key: str` (from Settings)

**New dependency:** None (uses `httpx` already in deps)

---

### Task 5: Factory Function

**File**: `services/backend/app/services/voice/factory.py`

```python
def build_voice_provider(provider: str, settings: Settings) -> VoiceProvider:
    if provider == 'polly':
        return PollyVoiceProvider(settings)
    elif provider == 'edge_tts':
        return EdgeTTSVoiceProvider()
    elif provider == 'elevenlabs':
        api_key = settings.elevenlabs_api_key
        if not api_key:
            raise ValueError('ElevenLabs API key not configured (NOVAREEL_ELEVENLABS_API_KEY)')
        return ElevenLabsVoiceProvider(api_key)
    else:
        raise ValueError(f'Unknown voice provider: {provider}')
```

---

### Task 6: Update Settings (config.py)

**File**: `services/backend/app/config.py`

**Add:**
```python
elevenlabs_api_key: str | None = None    # env: NOVAREEL_ELEVENLABS_API_KEY
default_voice_provider: str = 'polly'    # env: NOVAREEL_DEFAULT_VOICE_PROVIDER
```

---

### Task 7: Update Pydantic Models (models.py)

**File**: `services/backend/app/models.py`

**GenerateRequest** — add two fields:
```python
class GenerateRequest(BaseModel):
    aspect_ratio: Literal['16:9', '1:1', '9:16'] = '16:9'
    voice_style: Literal['energetic', 'professional', 'friendly'] = 'energetic'
    voice_provider: Literal['polly', 'edge_tts', 'elevenlabs'] = 'polly'   # NEW
    voice_gender: Literal['male', 'female'] = 'female'                      # NEW
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=128)
```

**GenerationJobRecord** — add matching fields:
```python
voice_provider: str = 'polly'    # NEW
voice_gender: str = 'female'     # NEW
```

---

### Task 8: Update Repository Layer

Both `create_job()` signatures need the new fields passed through.

**base.py** — update abstract method signature:
```python
@abstractmethod
def create_job(
    self,
    project_id: str,
    owner_id: str,
    aspect_ratio: str,
    voice_style: str,
    voice_provider: str = 'polly',       # NEW
    voice_gender: str = 'female',        # NEW
    max_attempts: int = 3,
    idempotency_key: str | None = None,
) -> GenerationJobRecord:
```

**local.py** — update `create_job()` to accept and store the new fields in the job dict.

**dynamo.py** — same change.

Both implementations just pass the fields through to `GenerationJobRecord(...)` constructor — straightforward.

---

### Task 9: Update API Endpoint (v1.py)

**File**: `services/backend/app/api/v1.py`

In `enqueue_generation()` (line ~193), pass the new fields:

```python
queued_job = repo.create_job(
    project_id=project_id,
    owner_id=current_user.user_id,
    aspect_ratio=payload.aspect_ratio,
    voice_style=payload.voice_style,
    voice_provider=payload.voice_provider,    # NEW
    voice_gender=payload.voice_gender,        # NEW
    max_attempts=settings.worker_max_attempts,
    idempotency_key=payload.idempotency_key,
)
```

Also update the analytics properties dict (~line 207):
```python
properties={
    'aspect_ratio': payload.aspect_ratio,
    'voice_style': payload.voice_style,
    'voice_provider': payload.voice_provider,    # NEW
    'voice_gender': payload.voice_gender,        # NEW
}
```

---

### Task 10: Update Pipeline (pipeline.py)

**File**: `services/backend/app/services/pipeline.py`

Replace the narration stage (lines 92-94) to use the new voice provider system:

**Before:**
```python
audio_payload = nova.synthesize_voice(script_lines, job.voice_style)
```

**After:**
```python
from app.services.voice import build_voice_provider

transcript = ' '.join(script_lines)
if settings.use_mock_ai:
    audio_payload = f'MOCK-VOICE::{job.voice_provider}::{job.voice_gender}::{transcript}'.encode('utf-8')
else:
    provider = build_voice_provider(job.voice_provider, settings)
    audio_payload = provider.synthesize(transcript[:3000], voice_gender=job.voice_gender)
```

**Note:** The `process_generation_job` function signature needs to accept `settings` as a parameter. Currently it doesn't — it gets `nova`, `repo`, `storage`, `video_service`. Add `settings: Settings` to the signature and update the caller in `worker.py` to pass it.

**Alternative (simpler):** Import `get_settings` from `app.config` directly inside the function. This avoids changing the function signature and the worker caller.

---

### Task 11: Remove synthesize_voice from NovaService

**File**: `services/backend/app/services/nova.py`

After migration, the `synthesize_voice()` method (lines 365-390) is dead code. Remove it. (The mock AI check is now in the pipeline.)

Also remove `polly_voice_id` and `bedrock_model_voice` from `config.py` if you want — they become unused. Or keep `polly_voice_id` and have PollyProvider read it from settings.

---

### Task 12: Update Frontend — TypeScript Types

**File**: `apps/web/lib/contracts.ts`

Add to `GenerationJob` interface:
```typescript
voice_provider?: string;
voice_gender?: string;
```

---

### Task 13: Update Frontend — API Client

**File**: `apps/web/lib/api.ts`

Update `generateProject` input type (line 84):
```typescript
input: {
    aspect_ratio: string;
    voice_style: string;
    voice_provider: string;      // NEW
    voice_gender: string;        // NEW
    idempotency_key?: string;
}
```

---

### Task 14: Update Frontend — Project Studio Form

**File**: `apps/web/components/project-studio.tsx`

**Add state variables** (near line 32-33):
```typescript
const [voiceProvider, setVoiceProvider] = useState('polly');
const [voiceGender, setVoiceGender] = useState('female');
```

**Add two new dropdowns** in the form grid (after the existing voice style dropdown, around line 315):

**Voice Engine dropdown:**
```
Options:
- "polly"       → "Amazon Polly"
- "edge_tts"    → "Edge TTS (Free)"
- "elevenlabs"  → "ElevenLabs (Premium)"
```

**Voice Gender dropdown:**
```
Options:
- "female" → "Female"
- "male"   → "Male"
```

**Update the `generateProject` call** (around line 173-180) to include the new fields:
```typescript
const queuedJob = await generateProject(
    project.id,
    {
        aspect_ratio: aspectRatio,
        voice_style: voiceStyle,
        voice_provider: voiceProvider,    // NEW
        voice_gender: voiceGender,        // NEW
        idempotency_key: idempotencyKey,
    },
    token
);
```

**Layout suggestion:** Change the existing 2-column grid (`md:grid-cols-2`) to a 2x2 grid with 4 dropdowns:
```
┌─────────────────┬─────────────────┐
│ Aspect Ratio    │ Voice Style     │
├─────────────────┼─────────────────┤
│ Voice Engine    │ Voice Gender    │
└─────────────────┴─────────────────┘
```

---

## 5. Dependency Changes

**`services/backend/pyproject.toml`** — add to `dependencies`:
```
"edge-tts>=6.1.0"
```

No other new dependencies needed. ElevenLabs uses `httpx` (already present). Polly uses `boto3` (already present).

---

## 6. Environment Variables

Add to `.env` (and document):
```env
# Voice provider config
NOVAREEL_DEFAULT_VOICE_PROVIDER=polly
NOVAREEL_ELEVENLABS_API_KEY=           # Required only if sellers use ElevenLabs
```

---

## 7. Mock AI Mode

When `NOVAREEL_USE_MOCK_AI=true`, voice synthesis should bypass all providers and return mock bytes. Handle this in `pipeline.py` before calling the provider (see Task 10). The mock format:
```
b'MOCK-VOICE::{provider}::{gender}::{transcript_text}'
```

---

## 8. Error Handling

| Scenario | Behavior |
|----------|----------|
| EdgeTTS network failure | Raise `VoiceSynthesisError` → job fails, retries per existing backoff |
| ElevenLabs insufficient credits | Raise `VoiceSynthesisError` with message "Insufficient ElevenLabs credits" |
| ElevenLabs API key not configured | Fail at factory level with clear error message |
| Invalid provider string | Pydantic validation rejects at API layer (Literal type) |
| Polly boto3 not available | Raise `VoiceSynthesisError` (same as current silent fallback, but explicit) |

---

## 9. Backward Compatibility

- Existing jobs with no `voice_provider` field will default to `"polly"` (Pydantic default)
- Existing `voice_style` field is preserved and still stored — no breaking change
- API clients that don't send `voice_provider` get Polly (current behavior, unchanged)
- The local JSON store (`local_store.json`) doesn't need migration — new fields have defaults

---

## 10. Testing Checklist

- [ ] Unit test: `PollyVoiceProvider.synthesize()` returns MP3 bytes (mock boto3)
- [ ] Unit test: `EdgeTTSVoiceProvider.synthesize()` returns MP3 bytes (mock edge_tts)
- [ ] Unit test: `ElevenLabsVoiceProvider.synthesize()` returns MP3 bytes (mock httpx)
- [ ] Unit test: `ElevenLabsVoiceProvider` raises on insufficient credits
- [ ] Unit test: `build_voice_provider()` returns correct provider for each string
- [ ] Unit test: `build_voice_provider('elevenlabs')` raises when no API key
- [ ] Integration test: `GenerateRequest` with `voice_provider='edge_tts'` accepted
- [ ] Integration test: `GenerateRequest` with `voice_provider='invalid'` returns 422
- [ ] Integration test: Mock AI mode returns mock bytes regardless of provider
- [ ] E2E test: Generate video with each of the 3 providers (can use mock AI)
- [ ] Verify existing jobs (no voice_provider field) still work after deploy

---

## 11. Implementation Order

Execute these tasks in order — each builds on the previous:

```
Task 1  → base.py (interface)               [30 min]
Task 2  → polly.py (extract from nova.py)    [30 min]
Task 3  → edge_tts.py (port from ShortGPT)  [1 hour]
Task 4  → elevenlabs.py (port from ShortGPT)[1 hour]
Task 5  → factory.py                         [15 min]
Task 6  → config.py (new settings)           [15 min]
Task 7  → models.py (new fields)             [15 min]
Task 8  → base.py, local.py, dynamo.py       [30 min]
Task 9  → v1.py (API endpoint)               [15 min]
Task 10 → pipeline.py (use new providers)    [30 min]
Task 11 → nova.py (remove old method)        [10 min]
Task 12 → contracts.ts                       [10 min]
Task 13 → api.ts                             [10 min]
Task 14 → project-studio.tsx                 [30 min]
─────────────────────────────────────────────
Total estimated:                              ~6 hours
+ Testing:                                    ~3 hours
```

---

## 12. Reference Material

All ShortGPT source files have been cloned to `/tmp/ShortGPT/` for reference:

| What | Path |
|------|------|
| Abstract voice interface | `/tmp/ShortGPT/shortGPT/audio/voice_module.py` |
| EdgeTTS implementation | `/tmp/ShortGPT/shortGPT/audio/edge_voice_module.py` |
| ElevenLabs implementation | `/tmp/ShortGPT/shortGPT/audio/eleven_voice_module.py` |
| ElevenLabs REST API wrapper | `/tmp/ShortGPT/shortGPT/api_utils/eleven_api.py` |
| Language enum + voice mappings | `/tmp/ShortGPT/shortGPT/config/languages.py` |

---

## 13. Future Enhancements (Out of Scope)

These are explicitly **NOT** part of this task but are enabled by this architecture:

1. **Multi-language TTS** — add `language` field to request, use `EDGE_TTS_VOICENAME_MAPPING` from ShortGPT's `languages.py` to pick language-specific voices
2. **Custom voice ID** — let premium users specify an ElevenLabs voice by name/ID
3. **Voice preview** — API endpoint to generate a 5-second sample before committing to full generation
4. **Polly Neural voices** — use SSML `<amazon:effect>` tags with the `voice_style` field for truly different styles
5. **Voice cloning** — ElevenLabs voice cloning API for brand-specific voices
