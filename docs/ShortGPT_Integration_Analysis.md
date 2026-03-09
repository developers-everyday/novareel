# ShortGPT → NovaReel Integration Analysis

> **Purpose**: Identify features from [ShortGPT](https://github.com/RayVentura/ShortGPT) that can be integrated into NovaReel to make it a superior product.

---

## Executive Summary

ShortGPT is an open-source AI video automation framework focused on short-form content (TikTok/YouTube Shorts). NovaReel is an e-commerce product video generator using Amazon Bedrock. While they serve different audiences, ShortGPT has **13 major capability areas** that would significantly enhance NovaReel's offering — particularly in multilingual support, audio quality, video effects, content variety, and social media optimization.

**Impact Rating Scale**: 🔴 Critical (competitive differentiator) | 🟠 High (major UX improvement) | 🟡 Medium (nice-to-have) | 🟢 Low (future consideration)

---

## 1. 🔴 Multi-Language Video Generation (80+ Languages)

### What ShortGPT Has
- Full support for 80+ languages (English, Spanish, French, Arabic, Hindi, Chinese, Japanese, Korean, etc.)
- Language-specific handling (Arabic RTL text, caption size adjustments)
- Per-language TTS voice mappings (male/female variants)
- Content length reduction for Arabic (2/3 of original)

### What NovaReel Lacks
- **English-only** script generation and narration
- No multilingual support at all
- No RTL text handling

### Integration Recommendation
```
Priority: CRITICAL
Effort: Medium (2-3 weeks)
```

**What to Build**:
1. Add a `language` field to the generation request (`POST /v1/projects/{id}/generate`)
2. Extend Nova script generation prompts to output in the target language
3. Add language-aware TTS voice selection (see EdgeTTS integration below)
4. Add RTL caption rendering for Arabic/Hebrew/Urdu in FFmpeg subtitle generation
5. Port ShortGPT's `LANGUAGE_ACRONYM_MAPPING` and voice name mappings

**Why It Matters**: Amazon has sellers worldwide. Multilingual video generation is an immediate competitive moat — no major competitor offers 80+ language product videos.

**Key Files to Reference**:
- `/tmp/ShortGPT/shortGPT/config/languages.py` — Language enum + acronym mappings
- `/tmp/ShortGPT/shortGPT/audio/edge_voice_module.py` — EdgeTTS voice-per-language mapping
- `/tmp/ShortGPT/shortGPT/editing_utils/captions.py` — Caption rendering with language awareness

---

## 2. 🔴 Multiple TTS Engines (ElevenLabs + EdgeTTS)

### What ShortGPT Has
- **ElevenLabs**: Premium, natural-sounding voices (8 languages), eleven_multilingual_v2 model
- **EdgeTTS**: Free Microsoft voices (50+ languages), async generation
- Abstract `VoiceModule` interface for swappable providers
- Voice gender detection via LLM

### What NovaReel Lacks
- **Amazon Polly only** — limited voice quality and naturalness
- No voice selection or customization beyond 3 style presets
- No abstract voice interface for adding providers

### Integration Recommendation
```
Priority: CRITICAL
Effort: Medium (1-2 weeks)
```

**What to Build**:
1. Create an abstract `VoiceProvider` interface in `services/`:
   ```python
   class VoiceProvider(ABC):
       async def synthesize(self, text: str, language: str, voice_id: str) -> bytes: ...
       def list_voices(self, language: str) -> list[VoiceOption]: ...
   ```
2. Implement `PollyVoiceProvider` (existing), `ElevenLabsVoiceProvider`, `EdgeTTSVoiceProvider`
3. Add voice provider + voice ID selection to generation request
4. EdgeTTS is **free** — immediately available for all languages without API costs
5. ElevenLabs for premium tier users who want higher-quality voices

**Why It Matters**: Voice quality is the #1 differentiator in product videos. Polly sounds robotic compared to ElevenLabs. EdgeTTS is free and covers 50+ languages.

**Key Files to Reference**:
- `/tmp/ShortGPT/shortGPT/audio/voice_module.py` — Abstract interface
- `/tmp/ShortGPT/shortGPT/audio/eleven_voice_module.py` — ElevenLabs implementation
- `/tmp/ShortGPT/shortGPT/audio/edge_voice_module.py` — EdgeTTS implementation (async)

---

## 3. 🔴 Video Translation & Dubbing Engine

### What ShortGPT Has
- Complete translation pipeline: Transcribe → Translate → Re-dub → Re-render
- Uses Whisper for word-level transcription with timestamps
- LLM-based translation (not just Google Translate)
- Audio timing alignment for translated speech
- Multi-target-language support (one source → many translations)

### What NovaReel Lacks
- No ability to take an existing video and translate it
- No transcription capabilities
- No dubbing/re-voicing

### Integration Recommendation
```
Priority: CRITICAL
Effort: High (3-4 weeks)
```

**What to Build**:
1. New endpoint: `POST /v1/projects/{id}/translate`
   ```json
   {
     "source_job_id": "existing-completed-job",
     "target_languages": ["es", "fr", "de", "ja"],
     "voice_provider": "edge_tts"
   }
   ```
2. Integrate Whisper (or AWS Transcribe) for audio transcription
3. Use Nova/Claude for context-aware translation (better than raw translation APIs)
4. Re-synthesize audio per target language with timing alignment
5. Re-render video with translated subtitles + new audio

**Why It Matters**: A seller creates one product video, then instantly gets it in 10 languages. This is a **10x multiplier** on the value of each generated video. Amazon operates in 20+ marketplaces.

**Key Files to Reference**:
- `/tmp/ShortGPT/shortGPT/engine/content_translation_engine.py` — Full translation pipeline
- `/tmp/ShortGPT/shortGPT/gpt/gpt_translate.py` — LLM-based translation

---

## 4. 🟠 Word-Level Caption Timing (Whisper Integration)

### What ShortGPT Has
- **whisper-timestamped**: Word-level timing from audio
- Precise caption placement synced to speech
- Language-aware caption sizing (vertical: 15 chars, landscape: 30 chars)
- Arabic-specific caption styling and positioning

### What NovaReel Has
- Basic SRT subtitle generation from storyboard segments
- Subtitles burned via FFmpeg `drawtext` filter (when libfreetype available)
- No word-level timing — entire script line shown for full segment duration

### Integration Recommendation
```
Priority: HIGH
Effort: Medium (1-2 weeks)
```

**What to Build**:
1. After narration synthesis, run Whisper on the generated audio to get word-level timestamps
2. Generate word-by-word or phrase-by-phrase SRT/ASS subtitles
3. Implement animated caption styles (word highlight, karaoke-style)
4. Add caption style options to generation request: `"caption_style": "word_highlight" | "sentence" | "none"`

**Why It Matters**: Word-level captions are the standard for modern short-form video. TikTok/Reels viewers expect animated captions. Static sentence subtitles look dated.

**Key Files to Reference**:
- `/tmp/ShortGPT/shortGPT/editing_utils/captions.py` — `getTimestampMapping()`, `getCaptionAssetByTime()`

---

## 5. 🟠 Stock Footage & Image Sourcing

### What ShortGPT Has
- **Pexels API**: Stock video clips with resolution/duration filtering
- **Bing Images API**: Stock image sourcing with dimension filtering
- Smart clip extraction (random 15%-85% of video duration)
- Background video selection from asset library
- Automatic search query generation via LLM

### What NovaReel Lacks
- **User-uploaded images only** — no supplementary stock footage
- No ability to add B-roll or lifestyle footage
- No stock media integration

### Integration Recommendation
```
Priority: HIGH
Effort: Medium (2-3 weeks)
```

**What to Build**:
1. Integrate Pexels API for supplementary B-roll footage
2. After script generation, use LLM to generate search queries for each scene
3. Offer "Product + Lifestyle" mode:
   - Scenes alternate between product images and relevant lifestyle B-roll
   - Example: Kitchen gadget video → product close-up → person cooking → product feature → happy family
4. Add to generation options: `"style": "product_only" | "product_lifestyle" | "lifestyle_focus"`
5. Free Pexels API means no additional cost

**Why It Matters**: Product-only videos feel like slideshows. Adding lifestyle B-roll makes videos feel professional and engaging — like real commercials.

**Key Files to Reference**:
- `/tmp/ShortGPT/shortGPT/api_utils/pexels_api.py` — Video search + extraction
- `/tmp/ShortGPT/shortGPT/api_utils/image_api.py` — Image search
- `/tmp/ShortGPT/shortGPT/gpt/gpt_editing.py` — LLM-generated search queries

---

## 6. 🟠 Background Music Engine

### What ShortGPT Has
- Background music selection from asset library
- Audio mixing (voiceover + background music with volume control)
- Looping music to match video duration
- Music stored as remote assets (YouTube URLs) or local files

### What NovaReel Lacks
- **No background music at all** — videos have narration only
- No audio mixing capabilities
- No music library

### Integration Recommendation
```
Priority: HIGH
Effort: Low (1 week)
```

**What to Build**:
1. Curate a royalty-free music library (categorized: upbeat, calm, luxury, tech, etc.)
2. Add FFmpeg audio mixing to the render pipeline:
   ```bash
   ffmpeg -i video.mp4 -i music.mp3 \
     -filter_complex "[1:a]volume=0.15[bg];[0:a][bg]amix=inputs=2" \
     output.mp4
   ```
3. Auto-select music based on product category or voice style
4. Add to generation options: `"background_music": "upbeat" | "calm" | "none"`
5. Allow custom music upload as a project asset

**Why It Matters**: Background music dramatically improves perceived video quality. Silent product videos (narration only) feel amateur. This is low-effort, high-impact.

**Key Files to Reference**:
- `/tmp/ShortGPT/shortGPT/editing_framework/editing_steps/` — `ADD_BACKGROUND_MUSIC.json`
- `/tmp/ShortGPT/shortGPT/editing_framework/core_editing_engine.py` — Audio composition logic

---

## 7. 🟠 Advanced Video Transitions & Effects

### What ShortGPT Has
- Background video compositing
- Subscribe button animations (overlay)
- Text watermark overlays
- Image display with precise timing
- Reddit post mockup rendering
- Composite layering with z-index

### What NovaReel Has
- **Ken Burns zoom only** (alternating zoom-in/zoom-out)
- No transition effects between scenes
- No overlays or animations

### Integration Recommendation
```
Priority: HIGH
Effort: Medium (2-3 weeks)
```

**What to Build**:
1. **Scene Transitions**: Implement crossfade, slide, wipe, and zoom transitions between segments
   ```python
   TRANSITIONS = {
     "crossfade": "xfade=transition=fade:duration=0.5",
     "slide_left": "xfade=transition=slideleft:duration=0.5",
     "wipe_right": "xfade=transition=wiperight:duration=0.5",
     "zoom_in": "xfade=transition=circlecrop:duration=0.5",
   }
   ```
2. **Text Overlays**: Product name, price, features as animated text
3. **Logo/Watermark**: Brand logo overlay (from `brand_prefs`)
4. **CTA Overlay**: "Shop Now", "Link in Bio" end cards
5. **Price Tag Animation**: Show pricing with animated callout

**Why It Matters**: Professional product videos need transitions and overlays. Ken Burns zoom alone makes videos look like basic slideshows. Text overlays showing product features/price are standard in e-commerce video ads.

**Key Files to Reference**:
- `/tmp/ShortGPT/shortGPT/editing_framework/editing_steps/` — JSON-defined editing operations
- `/tmp/ShortGPT/shortGPT/editing_framework/core_editing_engine.py` — MoviePy rendering

---

## 8. 🟠 Resumable Pipeline with State Persistence

### What ShortGPT Has
- Database-backed state for every pipeline step
- `_db_` attribute magic for automatic persistence
- Resume from last completed step after crash/interruption
- UUID-based content tracking
- `last_completed_step` tracking

### What NovaReel Has
- Job status tracking (stages: analyzing → scripting → matching → narration → rendering)
- Retry with exponential backoff (max 3 attempts)
- But: **full pipeline restart on failure** — no partial resume

### Integration Recommendation
```
Priority: HIGH
Effort: Medium (1-2 weeks)
```

**What to Build**:
1. Store intermediate artifacts in S3 after each stage:
   - After ANALYZING: save image analysis results
   - After SCRIPTING: save generated script + storyboard
   - After MATCHING: save image-to-scene assignments
   - After NARRATION: save audio file + transcript
2. On retry, check for existing artifacts and skip completed stages
3. Add `resume_from_stage` field to job record
4. This reduces AWS Bedrock costs on retries (no re-running expensive AI calls)

**Why It Matters**: Video rendering is the most failure-prone step (FFmpeg issues, memory, etc.). Re-running the entire AI pipeline on a rendering failure wastes ~$0.10+ per retry in Bedrock API calls and adds 30-60 seconds of unnecessary latency.

---

## 9. 🟡 LLM-Oriented Editing Framework (JSON Schema)

### What ShortGPT Has
- JSON-based editing schema that LLMs can generate/understand
- Composable editing steps (each step is a JSON template)
- Editing flows (chains of steps)
- Variable substitution in templates
- Core rendering engine interprets JSON → MoviePy operations

### What NovaReel Has
- Hardcoded FFmpeg commands in `video.py`
- No abstraction layer for video editing operations

### Integration Recommendation
```
Priority: MEDIUM
Effort: High (3-4 weeks)
```

**What to Build**:
1. Define a JSON schema for video editing operations:
   ```json
   {
     "steps": [
       {"type": "background_video", "source": "segment_1.mp4", "duration": 5.0},
       {"type": "text_overlay", "text": "50% OFF", "position": "bottom", "start": 2.0, "end": 4.0},
       {"type": "transition", "effect": "crossfade", "duration": 0.5},
       {"type": "audio_mix", "tracks": [{"src": "narration.mp3", "volume": 1.0}, {"src": "music.mp3", "volume": 0.15}]}
     ]
   }
   ```
2. Build an interpreter that converts JSON → FFmpeg filter graphs
3. **Future unlock**: Let the LLM generate custom editing plans per video, making each video unique

**Why It Matters**: This is an architectural investment. It decouples video generation logic from rendering, enabling future features like user-customizable templates, LLM-driven creative direction, and A/B testing different editing styles.

---

## 10. 🟡 Script Variety & Content Templates

### What ShortGPT Has
- Multiple script engines: Reddit stories, facts, custom chat-based
- YAML prompt templates with variable substitution
- Interactive script refinement via chatbot
- Realism scoring and filtering
- YouTube metadata generation (titles, descriptions)

### What NovaReel Has
- Single script format: 6-scene product marketing script
- Hardcoded prompt in Nova service
- No script templates or customization

### Integration Recommendation
```
Priority: MEDIUM
Effort: Low-Medium (1-2 weeks)
```

**What to Build**:
1. Create YAML prompt templates for different video styles:
   - `product_showcase.yaml` — Current 6-scene format
   - `problem_solution.yaml` — "Tired of X? Product Y solves it"
   - `comparison.yaml` — "Product X vs competitors"
   - `unboxing.yaml` — Unboxing narrative style
   - `testimonial.yaml` — Customer review style
   - `how_to.yaml` — Tutorial/demo format
   - `seasonal.yaml` — Holiday/sale promotional style
2. Add `script_template` to generation options
3. Store templates in `services/backend/prompt_templates/`
4. Generate platform-optimized metadata (YouTube descriptions, TikTok captions)

**Why It Matters**: Sellers need variety. Running the same 6-scene format gets stale. Different products work better with different narrative styles.

**Key Files to Reference**:
- `/tmp/ShortGPT/shortGPT/prompt_templates/` — YAML template format

---

## 11. 🟡 Asset Library System

### What ShortGPT Has
- Persistent asset database (local files + YouTube URLs)
- Asset type classification (video, audio, image)
- Add/remove/browse interface in UI
- Assets reusable across multiple content creations

### What NovaReel Has
- Per-project asset uploads (images only)
- No shared asset library
- No reusability across projects

### Integration Recommendation
```
Priority: MEDIUM
Effort: Medium (2 weeks)
```

**What to Build**:
1. New entity: `AssetLibrary` — user-level shared assets
2. Asset types: brand logos, background music, intro/outro clips, brand fonts
3. API endpoints:
   ```
   POST   /v1/library/assets          Upload to shared library
   GET    /v1/library/assets          List library assets
   DELETE /v1/library/assets/{id}     Remove asset
   ```
4. During generation, pull brand assets from library automatically
5. Support "Brand Kit" concept: logo + colors + fonts + music = consistent brand identity

**Why It Matters**: Sellers with multiple products want consistent branding. Uploading the same logo and selecting the same music for every project is tedious.

---

## 12. 🟡 Social Media Auto-Publishing

### What ShortGPT Has
- YouTube metadata generation (titles + descriptions)
- Format-aware output (vertical for TikTok, landscape for YouTube)
- Videos marked as "ready to upload" in database

### What NovaReel Has
- Download-only workflow
- No publishing integration

### Integration Recommendation
```
Priority: MEDIUM
Effort: High (3-4 weeks, per platform)
```

**What to Build**:
1. **Phase 1**: Auto-generate platform-specific metadata
   - YouTube: Title (60 chars), description (5000 chars), tags
   - TikTok: Caption (150 chars), hashtags
   - Instagram: Caption (2200 chars), hashtags
   - Amazon: A+ Content text, bullet points
2. **Phase 2**: Direct publishing via platform APIs
   - YouTube Data API v3
   - TikTok Content Posting API
   - Instagram Graph API
3. **Phase 3**: Scheduling and analytics
   - Schedule posts for optimal times
   - Track view/engagement metrics

**Why It Matters**: The seller workflow is: generate video → download → open each platform → upload → write caption → publish. Automating this saves 15-30 minutes per video per platform.

---

## 13. 🟡 Audio Processing Pipeline

### What ShortGPT Has
- Audio speed adjustment (for fitting content into time limits)
- Background audio separation (Spleeter, 2-stem)
- Audio duration detection (ffprobe + yt-dlp)
- Volume control and mixing
- Characters-per-second constant for timing

### What NovaReel Has
- Basic Polly synthesis → direct use
- No post-processing

### Integration Recommendation
```
Priority: MEDIUM
Effort: Low (1 week)
```

**What to Build**:
1. **Audio normalization**: Ensure consistent volume across narration segments
2. **Speed adjustment**: If narration exceeds target duration, speed up slightly (FFmpeg atempo)
3. **Silence trimming**: Remove leading/trailing silence from TTS output
4. **Audio ducking**: Lower music volume when narration is active
   ```bash
   ffmpeg -i narration.mp3 -i music.mp3 \
     -filter_complex "[0:a]asplit=2[voice][sc];[sc]sidechaincompress=threshold=0.03[compressed];[1:a][compressed]amix" \
     output.mp3
   ```

---

## 14. 🟢 Performance Optimizations

### What ShortGPT Has
- Global Whisper model caching
- Async TTS generation (ThreadPoolExecutor)
- FFmpeg "veryfast" preset for speed
- Random clip extraction (avoids full re-encoding)

### What NovaReel Could Adopt
```
Priority: LOW (Phase 2+)
Effort: Low (1 week)
```

1. **Parallel segment rendering**: Render each video segment in parallel, then concatenate
2. **Pre-computed assets**: Cache frequently-used elements (fonts, music, overlays)
3. **FFmpeg preset optimization**: Use hardware acceleration (NVENC) in production
4. **Async voice synthesis**: Generate narration for all segments concurrently

---

## Priority Integration Roadmap

### Sprint 1 (Week 1-2): Quick Wins
| Feature | Effort | Impact |
|---------|--------|--------|
| Background Music Engine | 1 week | 🟠 High |
| EdgeTTS Integration (free, 50+ languages) | 1 week | 🔴 Critical |
| Audio Post-Processing | 1 week | 🟡 Medium |

### Sprint 2 (Week 3-4): Core Differentiators
| Feature | Effort | Impact |
|---------|--------|--------|
| Multi-Language Script Generation | 2 weeks | 🔴 Critical |
| Word-Level Captions (Whisper) | 1-2 weeks | 🟠 High |
| Resumable Pipeline | 1-2 weeks | 🟠 High |

### Sprint 3 (Week 5-7): Premium Features
| Feature | Effort | Impact |
|---------|--------|--------|
| Stock Footage Integration (Pexels) | 2-3 weeks | 🟠 High |
| Video Transitions & Effects | 2-3 weeks | 🟠 High |
| ElevenLabs Premium Voices | 1 week | 🔴 Critical |

### Sprint 4 (Week 8-10): Platform Expansion
| Feature | Effort | Impact |
|---------|--------|--------|
| Script Templates Library | 1-2 weeks | 🟡 Medium |
| Video Translation & Dubbing | 3-4 weeks | 🔴 Critical |
| Asset Library System | 2 weeks | 🟡 Medium |

### Sprint 5 (Week 11-14): Distribution
| Feature | Effort | Impact |
|---------|--------|--------|
| Social Media Metadata Generation | 1 week | 🟡 Medium |
| LLM-Oriented Editing Framework | 3-4 weeks | 🟡 Medium |
| Direct Publishing APIs | 3-4 weeks | 🟡 Medium |

---

## Architecture Considerations

### New Dependencies to Add
```
# Free / Open Source
edge-tts              # Free Microsoft TTS (50+ languages)
whisper-timestamped   # Word-level audio transcription
spleeter              # Audio separation (optional)

# Paid APIs (optional premium features)
elevenlabs            # Premium voice synthesis
pexels-api            # Free stock footage (API key required, no cost)
```

### Backend Service Changes
```
services/backend/
├── app/services/
│   ├── voice_provider.py          # Abstract voice interface (NEW)
│   ├── polly_voice_provider.py    # Existing Polly (REFACTOR)
│   ├── edge_tts_provider.py       # EdgeTTS (NEW)
│   ├── elevenlabs_provider.py     # ElevenLabs (NEW)
│   ├── stock_media.py             # Pexels integration (NEW)
│   ├── transcription.py           # Whisper/Transcribe (NEW)
│   ├── translation.py             # LLM translation (NEW)
│   ├── audio_processor.py         # Post-processing (NEW)
│   └── music_library.py           # Background music (NEW)
├── prompt_templates/              # YAML templates (NEW)
│   ├── product_showcase.yaml
│   ├── problem_solution.yaml
│   └── ...
└── assets/
    └── music/                     # Royalty-free music (NEW)
```

### API Contract Extensions
```python
# Extended generation request
class GenerateRequest(BaseModel):
    aspect_ratio: str = "16:9"
    voice_style: str = "energetic"
    language: str = "en"                    # NEW
    voice_provider: str = "polly"           # NEW: polly | edge_tts | elevenlabs
    voice_id: str | None = None             # NEW: specific voice
    script_template: str = "product_showcase"  # NEW
    video_style: str = "product_only"       # NEW: product_only | product_lifestyle
    background_music: str = "auto"          # NEW: auto | upbeat | calm | none
    caption_style: str = "sentence"         # NEW: word_highlight | sentence | none
    transition_style: str = "crossfade"     # NEW: crossfade | slide | cut | zoom

# New translation endpoint
class TranslateRequest(BaseModel):
    source_job_id: str
    target_languages: list[str]
    voice_provider: str = "edge_tts"
```

---

## Competitive Advantage After Integration

| Capability | NovaReel (Current) | ShortGPT | NovaReel (Post-Integration) |
|---|---|---|---|
| Languages | 1 (English) | 80+ | 80+ |
| Voice Quality | Basic (Polly) | Good (ElevenLabs/Edge) | Premium (Polly + ElevenLabs + Edge) |
| Video Effects | Ken Burns only | Basic compositing | Transitions + overlays + effects |
| Background Music | None | Yes | Yes + auto-selection |
| Captions | Basic SRT | Word-level timing | Animated word-level |
| Stock Footage | None | Pexels + Bing | Pexels B-roll integration |
| Translation | None | Full pipeline | One-click multi-language |
| Script Styles | 1 template | 3 engines | 7+ templates |
| Resume on Failure | Full restart | Per-step resume | Per-stage resume |
| Publishing | Download only | Download only | Metadata + direct publish |
| Target Audience | E-commerce sellers | Content creators | E-commerce + Content + Global sellers |

---

## Key Takeaway

The highest-ROI integrations are:
1. **EdgeTTS** — Free, instant 50+ language support, 1 week to integrate
2. **Background Music** — Transforms video quality perception, 1 week to integrate
3. **Multi-language scripts** — Opens global markets, 2 weeks to integrate
4. **Video Translation** — 10x value multiplier per video, 3-4 weeks to integrate

These four features alone would make NovaReel **categorically better** than ShortGPT while maintaining its e-commerce focus and cloud-native architecture.
