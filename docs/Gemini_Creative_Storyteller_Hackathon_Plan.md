# NovaReel -> StoryWeaver: Gemini Live Agent Challenge - Creative Storyteller

## Feasibility Analysis & Technical Plan

**Hackathon**: [Gemini Live Agent Challenge](https://geminiliveagentchallenge.devpost.com/)
**Category**: Creative Storyteller - Multimodal Storytelling with Interleaved Output
**Deadline**: March 16, 2026 @ 5:00 PM PDT (4 days from today)
**Prize**: $10,000 + $1,000 GCP credits + Google Cloud Next 2026 tickets

---

## 1. Executive Summary

**Verdict: Highly Feasible - Fork & Adapt**

NovaReel's existing architecture (FastAPI + Next.js + FFmpeg pipeline) provides ~60% of the infrastructure needed. The core pivot is replacing Amazon Nova/Bedrock with Gemini's native interleaved output and reframing from "e-commerce video generator" to "creative storytelling agent." The tightest constraint is the 4-day timeline — this plan prioritizes the hackathon's highest-weighted judging criterion (Innovation & Multimodal UX at 40%) while leveraging maximum code reuse.

### What We're Building: "StoryWeaver"

An AI creative director agent that takes a concept (text, images, or voice) and produces a **rich, interleaved multimodal story** — streaming text narration interwoven with AI-generated illustrations, synthesized voiceover, and assembled video segments — all in a single fluid output. Think: you describe a product, a lesson, or a story idea, and StoryWeaver streams back a complete multimedia narrative in real-time.

---

## 2. Hackathon Requirements Checklist

| Requirement | Status | Implementation Path |
|---|---|---|
| **Gemini model** | Required | Gemini 3.1 Flash Image + Gemini 2.5 Flash Live |
| **Interleaved/mixed output** | **Mandatory** | `response_modalities=["TEXT", "IMAGE"]` for inline story+illustrations |
| **Google GenAI SDK or ADK** | Required | `google-genai` Python SDK + ADK for streaming agent |
| **Hosted on Google Cloud** | Required | Cloud Run (API) + Cloud Storage + Firestore |
| **At least 1 GCP service** | Required | Cloud Run, Cloud Storage, Firestore, Vertex AI |
| **Public code repo** | Required | Fork NovaReel → new GitHub repo |
| **Architecture diagram** | Required | Mermaid/draw.io diagram |
| **Demo video (< 4 min)** | Required | Screen recording with voiceover |
| **GCP deployment proof** | Required | Screen recording of Cloud Run deployment |

---

## 3. Reuse Analysis: What Stays, What Changes, What's New

### 3.1 What We Keep (saves ~2 days of work)

| Component | Files | Effort to Adapt |
|---|---|---|
| **Next.js frontend shell** | `apps/web/*` | Low — retheme + new streaming UI |
| **FastAPI backend structure** | `services/backend/app/main.py`, `api/`, `models.py` | Low — new routes, same patterns |
| **FFmpeg video rendering** | `services/backend/app/services/video.py` | None — direct reuse |
| **Subtitle/caption engine** | `services/backend/app/services/subtitle_utils.py`, `transcription.py` | None — direct reuse |
| **Stock media integration** | `services/backend/app/services/stock_media.py` (Pexels) | None — direct reuse |
| **Music selection** | `services/backend/app/services/music.py` | None — direct reuse |
| **Effects/transitions** | `services/backend/app/services/effects.py` | None — direct reuse |
| **Storage abstraction** | `services/backend/app/services/storage.py` | Low — swap S3 → Cloud Storage |
| **Project/job data models** | `services/backend/app/models.py` | Medium — extend for story types |
| **Docker setup** | `infra/docker-compose.yml` | Low — add GCP deploy configs |
| **Auth (Clerk)** | `apps/web/`, `services/backend/app/auth.py` | None — keep as-is |

### 3.2 What Changes (core swap)

| Component | Current (Nova) | Target (Gemini) | Effort |
|---|---|---|---|
| **Script/story generation** | `nova.py` → Nova Lite | New `gemini.py` → Gemini 3.1 Flash Image | **Medium** |
| **Image generation** | None (stock only) | Gemini native interleaved image gen | **Medium-High** |
| **Voice synthesis** | `voice/nova_sonic.py` | Gemini TTS or Gemini Live Audio | **Medium** |
| **Image analysis** | `nova.py` → Nova Vision | Gemini Vision (same SDK) | **Low** |
| **Embeddings** | Nova Embeddings | Gemini Embedding 2 | **Low** |
| **Pipeline orchestration** | `pipeline.py` (sequential) | New streaming pipeline | **High** |
| **Cloud storage** | S3 via boto3 | Cloud Storage via google-cloud-storage | **Low** |
| **Database** | DynamoDB / local JSON | Firestore / local JSON | **Medium** |

### 3.3 What's New (hackathon differentiators)

| Feature | Purpose | Effort |
|---|---|---|
| **Interleaved streaming UI** | Real-time text+image+audio stream in browser | **High** — key differentiator |
| **Story mode selector** | Marketing / Storybook / Educational / Social | **Low** — prompt templates |
| **Live voice input** | Speak your story concept via ADK bidi-streaming | **Medium** — nice-to-have |
| **Persona/voice system** | Distinct narrator voices per story type | **Low** — Gemini TTS config |
| **Cloud Run deployment** | GCP hosting requirement | **Medium** — Dockerize + deploy |

---

## 4. Proposed Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        StoryWeaver                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────┐    WebSocket/SSE     ┌──────────────────────┐ │
│  │  Next.js UI   │◄──────────────────►│  FastAPI Backend      │ │
│  │  (Cloud Run)  │                     │  (Cloud Run)          │ │
│  │               │                     │                       │ │
│  │ - Story input │                     │ - /v1/stories/create  │ │
│  │ - Streaming   │                     │ - /v1/stories/stream  │ │
│  │   renderer    │                     │ - /v1/stories/{id}    │ │
│  │ - Media player│                     │                       │ │
│  │ - Voice input │                     │  ┌─────────────────┐  │ │
│  └──────────────┘                     │  │ Gemini Service   │  │ │
│                                        │  │                  │  │ │
│                                        │  │ - Interleaved    │  │ │
│                                        │  │   generation     │  │ │
│                                        │  │ - Image gen      │  │ │
│                                        │  │ - TTS            │  │ │
│                                        │  │ - Vision         │  │ │
│                                        │  └────────┬────────┘  │ │
│                                        │           │           │ │
│                                        │  ┌────────▼────────┐  │ │
│                                        │  │ Story Pipeline   │  │ │
│                                        │  │                  │  │ │
│                                        │  │ 1. Concept parse │  │ │
│                                        │  │ 2. Story script  │  │ │
│                                        │  │ 3. Interleaved   │  │ │
│                                        │  │    gen (text+img)│  │ │
│                                        │  │ 4. TTS narration │  │ │
│                                        │  │ 5. Video compile │  │ │
│                                        │  └────────┬────────┘  │ │
│                                        │           │           │ │
│                                        └───────────┼───────────┘ │
│                                                    │             │
│  ┌─────────────────────────────────────────────────┼───────────┐ │
│  │                    Google Cloud                  │           │ │
│  │  ┌──────────┐  ┌──────────┐  ┌────────────────┐│           │ │
│  │  │Cloud     │  │Firestore │  │Gemini API      ││           │ │
│  │  │Storage   │  │(projects,│  │(GenAI SDK)     ││           │ │
│  │  │(media)   │  │ jobs)    │  │                ││           │ │
│  │  └──────────┘  └──────────┘  │- 3.1 Flash Img ││           │ │
│  │                               │- 2.5 Flash TTS ││           │ │
│  │                               │- Embedding 2   ││           │ │
│  │                               │- 2.5 Flash Live││           │ │
│  │                               └────────────────┘│           │ │
│  └─────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

### Model Selection

| Capability | Model | Why |
|---|---|---|
| **Story + inline images** | `gemini-3.1-flash-image-preview` | Native interleaved text+image output — the hackathon's mandatory feature |
| **Text-to-Speech** | `gemini-2.5-flash-tts-preview` | High-quality narration with controllable voice |
| **Live voice input** | `gemini-2.5-flash-live-preview` | Bidi-streaming for voice-driven story creation |
| **Embeddings** | `gemini-embedding-2` | Multimodal embedding for image-to-scene matching |
| **Video generation** | `veo-3.1-preview` (optional) | Short video clips per scene (stretch goal) |

---

## 5. The Key Differentiator: Interleaved Streaming Experience

This is the **#1 thing the judges care about** (40% weight). The UX must "break the text box paradigm."

### How It Works

1. **User inputs a concept** (text, uploaded images, or voice via microphone)
2. **Backend calls Gemini with `response_modalities=["TEXT", "IMAGE"]`**
3. **Gemini streams back interleaved parts**: paragraph of narration, then an illustration, then more text, then another image...
4. **Frontend renders each part as it arrives** via Server-Sent Events (SSE):
   - Text parts → animated typewriter text
   - Image parts → fade-in illustrations
   - Audio (TTS of text parts) → auto-playing narration
5. **Result**: A scrolling, multimedia story that builds itself in real-time

### Code Pattern (Backend - Core Interleaved Generation)

```python
from google import genai
from google.genai import types

client = genai.Client()  # Uses GOOGLE_API_KEY or Vertex AI

async def generate_story_interleaved(concept: str, style: str, images: list[bytes] = None):
    """Generate a story with interleaved text and illustrations."""

    system_prompt = STORY_TEMPLATES[style]  # marketing, storybook, educational, social

    contents = [system_prompt, f"Create a story about: {concept}"]
    if images:
        for img in images:
            contents.append(types.Part.from_bytes(data=img, mime_type="image/jpeg"))

    response = client.models.generate_content(
        model="gemini-3.1-flash-image-preview",
        contents=contents,
        config=types.GenerateContentConfig(
            response_modalities=["TEXT", "IMAGE"],
            temperature=0.8,
        ),
    )

    # Yield interleaved parts for streaming to frontend
    for part in response.candidates[0].content.parts:
        if part.text:
            yield {"type": "text", "content": part.text}
        elif part.inline_data:
            img_b64 = base64.b64encode(part.inline_data.data).decode()
            yield {"type": "image", "content": img_b64, "mime": part.inline_data.mime_type}
```

### Code Pattern (Frontend - Streaming Renderer)

```tsx
// Simplified streaming story renderer
function StoryStream({ storyId }: { storyId: string }) {
  const [parts, setParts] = useState<StoryPart[]>([]);

  useEffect(() => {
    const eventSource = new EventSource(`/api/stories/${storyId}/stream`);
    eventSource.onmessage = (event) => {
      const part = JSON.parse(event.data);
      setParts(prev => [...prev, part]);
    };
    return () => eventSource.close();
  }, [storyId]);

  return (
    <div className="story-canvas">
      {parts.map((part, i) => (
        part.type === 'text'
          ? <TextBlock key={i} content={part.content} animate />
          : part.type === 'image'
          ? <ImageBlock key={i} src={`data:${part.mime};base64,${part.content}`} fadeIn />
          : <AudioBlock key={i} src={part.audioUrl} autoPlay />
      ))}
    </div>
  );
}
```

---

## 6. Story Modes (Prompt Templates)

Reuse NovaReel's prompt template pattern (`prompt_templates/*.yaml`) with new story-oriented templates:

### 6.1 Marketing Asset Generator (closest to NovaReel)
- Input: Product images + description
- Output: Interleaved copy + hero images + social captions
- **Reuse**: 80% of existing pipeline logic

### 6.2 Interactive Storybook
- Input: Story concept (text or voice)
- Output: Illustrated story with narration, chapter by chapter
- **Reuse**: FFmpeg video compilation, subtitle engine

### 6.3 Educational Explainer
- Input: Topic + target audience
- Output: Step-by-step explanation with diagrams and narration
- **Reuse**: Caption system, voice synthesis

### 6.4 Social Content Creator
- Input: Brand/product + platform (Instagram, TikTok, YouTube)
- Output: Caption + image + hashtags + short video
- **Reuse**: Aspect ratio system (9:16, 1:1, 16:9), effects

---

## 7. Technical Implementation Plan (4 Days)

### Day 1 (March 12 - Today): Foundation Swap

**Morning: Fork + Gemini Service**
- [ ] Fork repo, rename to `storyweaver`
- [ ] Create `services/backend/app/services/gemini.py` — core Gemini service
  - `generate_story_interleaved()` — text + image generation
  - `analyze_images()` — image understanding (replaces Nova vision)
  - `generate_embeddings()` — multimodal embeddings
- [ ] Install `google-genai` SDK, remove `boto3` bedrock dependencies
- [ ] Test interleaved output locally with simple prompts

**Afternoon: Pipeline Adaptation**
- [ ] Create `services/backend/app/services/story_pipeline.py`
  - Adapt `pipeline.py` flow: concept → script → interleaved generation → TTS → video
  - Add SSE streaming endpoint for real-time output
- [ ] Swap voice provider: Nova Sonic → Gemini TTS (`gemini-2.5-flash-tts-preview`)
- [ ] Create 4 story prompt templates in `prompt_templates/`

### Day 2 (March 13): Streaming UI + Cloud Setup

**Morning: Frontend**
- [ ] Build `StoryCanvas` component — streaming interleaved renderer
  - Typewriter text animation
  - Fade-in image rendering
  - Inline audio player for narration segments
- [ ] Build `StoryInput` component — text + image upload + voice input
- [ ] Retheme: NovaReel branding → StoryWeaver branding
- [ ] Update landing page with hackathon-relevant copy

**Afternoon: Google Cloud**
- [ ] Set up GCP project + enable APIs (Vertex AI, Cloud Run, Cloud Storage, Firestore)
- [ ] Swap storage: S3 → Cloud Storage (adapt `storage.py`)
- [ ] Swap database: local JSON → Firestore (adapt `repositories/`)
- [ ] Create `Dockerfile` for Cloud Run (backend)
- [ ] Create `cloudbuild.yaml` or deploy script

### Day 3 (March 14): Integration + Polish

**Morning: End-to-End Flow**
- [ ] Test full pipeline: input → Gemini interleaved → streaming UI → video export
- [ ] Add video compilation: take interleaved images + TTS audio → FFmpeg → MP4
- [ ] Test all 4 story modes
- [ ] Add error handling and loading states

**Afternoon: Polish + Deploy**
- [ ] Deploy to Cloud Run (backend + frontend)
- [ ] Test deployed version end-to-end
- [ ] Add persona/voice selection UI
- [ ] Create architecture diagram

### Day 4 (March 15): Demo + Submit

**Morning: Demo Video**
- [ ] Script the demo (< 4 min):
  1. Problem statement (15s)
  2. Architecture overview with diagram (30s)
  3. Live demo — marketing asset generation (60s)
  4. Live demo — interactive storybook (60s)
  5. Cloud deployment proof (15s)
  6. Closing/impact (20s)
- [ ] Record screen capture with voiceover
- [ ] Edit video

**Afternoon: Submission**
- [ ] Write Devpost description
- [ ] Record GCP deployment proof
- [ ] Final architecture diagram
- [ ] Submit before 5:00 PM PDT March 16

---

## 8. Cloud Service Mapping (AWS → GCP)

| Function | Current (AWS) | Target (GCP) | Migration Effort |
|---|---|---|---|
| AI Models | Bedrock (Nova) | Gemini API (GenAI SDK) | **Core work** |
| Object Storage | S3 | Cloud Storage | Low — swap client |
| Database | DynamoDB | Firestore | Medium — different data model |
| Compute | Local / EC2 | Cloud Run | Medium — Dockerfile exists |
| Queue | SQS / Redis | Cloud Tasks (or keep Redis) | Low — can skip for hackathon |
| Auth | Clerk | Clerk (keep) | None |
| CDN | CloudFront | Cloud CDN (optional) | Skip for hackathon |

### Minimal GCP Setup (Hackathon Scope)

For the hackathon, we can simplify:
- **Cloud Run**: Host both frontend and backend as separate services
- **Cloud Storage**: Store generated media assets
- **Firestore**: Store projects/jobs (or even keep local JSON for simplicity — just needs to run on GCP)
- **Gemini API**: Via `google-genai` SDK (API key or Vertex AI)

---

## 9. Risk Assessment

| Risk | Impact | Likelihood | Mitigation |
|---|---|---|---|
| **Gemini interleaved output quality** | High | Medium | Test early Day 1; have fallback to sequential gen |
| **4-day timeline too tight** | High | Medium | Cut scope: skip video gen, focus on interleaved text+image |
| **Cloud Run cold starts** | Medium | High | Use min-instances=1; or use always-on |
| **FFmpeg on Cloud Run** | Medium | Medium | Use custom Docker image with FFmpeg pre-installed |
| **Gemini API rate limits** | Medium | Low | Use API key + Vertex AI as fallback |
| **TTS quality/latency** | Low | Medium | Gemini TTS is new; fallback to Edge TTS (already implemented) |
| **Firestore migration bugs** | Medium | Medium | Keep local JSON repo for hackathon; Firestore is nice-to-have |

### Minimum Viable Hackathon Submission (if time is tight)

If we run out of time, the absolute minimum is:
1. Gemini interleaved text+image generation (mandatory)
2. Streaming UI that renders the output in real-time
3. Running on Cloud Run
4. Demo video showing it working
5. One story mode (marketing asset generator — closest to NovaReel)

---

## 10. Scoring Strategy (Mapped to Judging Criteria)

### Innovation & Multimodal UX (40%) — GO BIG HERE

- **"Break the text box"**: The streaming interleaved canvas IS the product. No chat interface — a creative canvas that builds itself.
- **"See, Hear, Speak"**:
  - **See**: AI-generated illustrations inline with narrative
  - **Hear**: Auto-playing TTS narration as text streams
  - **Speak**: Voice input to describe your story concept (via ADK Live API)
- **"Distinct persona"**: Each story mode has a different narrator voice and visual style
- **"Live and context-aware"**: Streaming output, not batch. User sees the story materialize.

### Technical Implementation (30%)

- **GenAI SDK**: Direct use of `google-genai` for interleaved generation
- **ADK**: Bidi-streaming agent for voice interaction (stretch goal)
- **Cloud Run**: Robust containerized deployment
- **Error handling**: Existing NovaReel retry/fallback patterns carry over
- **Grounding**: Use Gemini's Google Search grounding for factual content in educational mode

### Demo & Presentation (30%)

- **Problem**: "Creating rich multimedia content requires multiple tools, multiple steps, multiple exports"
- **Solution**: "StoryWeaver does it in one fluid stream — describe it, watch it materialize"
- **Architecture diagram**: Clean, showing Gemini at center with Cloud Run + Cloud Storage + Firestore
- **Live demo**: Show 2 modes working in real-time
- **Deployment proof**: Cloud Run console + live URL

---

## 11. File Changes Summary

### New Files to Create

```
services/backend/app/services/gemini.py          # Core Gemini service (replaces nova.py)
services/backend/app/services/story_pipeline.py   # Story generation pipeline
services/backend/app/services/voice/gemini_tts.py  # Gemini TTS provider
services/backend/app/api/v1_stories.py            # Story-specific API routes
services/backend/prompt_templates/storybook.yaml
services/backend/prompt_templates/marketing_story.yaml
services/backend/prompt_templates/educational.yaml
services/backend/prompt_templates/social_content.yaml
apps/web/components/story-canvas.tsx               # Streaming renderer
apps/web/components/story-input.tsx                # Story creation form
apps/web/app/app/studio/page.tsx                   # Updated studio page
infra/Dockerfile.backend                           # Cloud Run backend
infra/Dockerfile.web                               # Cloud Run frontend
infra/deploy.sh                                    # GCP deployment script
```

### Files to Modify

```
services/backend/pyproject.toml                    # Add google-genai, remove boto3
services/backend/app/config/__init__.py            # Add Gemini config vars
services/backend/app/dependencies.py               # Wire up GeminiService
services/backend/app/services/storage.py           # Add Cloud Storage backend
services/backend/app/services/voice/factory.py     # Add Gemini TTS option
apps/web/package.json                              # Any new frontend deps
apps/web/app/layout.tsx                            # Rebrand
apps/web/app/page.tsx                              # New landing page copy
```

### Files That Stay Unchanged

```
services/backend/app/services/video.py             # FFmpeg rendering
services/backend/app/services/effects.py           # Transitions
services/backend/app/services/subtitle_utils.py    # Caption generation
services/backend/app/services/stock_media.py       # Pexels integration
services/backend/app/services/music.py             # Background music
services/backend/app/services/metadata.py          # Media metadata
services/backend/app/auth.py                       # Clerk auth
```

---

## 12. Key API Differences: Nova → Gemini

### Script Generation

**Before (Nova):**
```python
# nova.py
response = bedrock.converse(
    modelId="amazon.nova-lite-v1:0",
    messages=[{"role": "user", "content": [{"text": prompt}]}],
    toolConfig={"tools": [render_video_plan_tool]}
)
```

**After (Gemini):**
```python
# gemini.py
response = client.models.generate_content(
    model="gemini-3.1-flash-image-preview",
    contents=[prompt],
    config=types.GenerateContentConfig(
        response_modalities=["TEXT", "IMAGE"],
        temperature=0.8,
    )
)
# Response contains interleaved text AND generated images
for part in response.candidates[0].content.parts:
    if part.text: ...       # Narrative text
    if part.inline_data: ... # Generated illustration
```

### Voice Synthesis

**Before (Nova Sonic):**
```python
# voice/nova_sonic.py
response = bedrock.converse(
    modelId="amazon.nova-sonic-v1:0",
    messages=[...],
    inferenceConfig={"outputModalities": ["AUDIO"]}
)
```

**After (Gemini TTS):**
```python
# voice/gemini_tts.py
response = client.models.generate_content(
    model="gemini-2.5-flash-tts-preview",
    contents=text,
    config=types.GenerateContentConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Kore")
            )
        )
    )
)
```

### Image Analysis

**Before (Nova Vision):**
```python
response = bedrock.converse(
    modelId="amazon.nova-lite-v1:0",
    messages=[{"role": "user", "content": [
        {"image": {"source": {"bytes": img_bytes}}},
        {"text": "Analyze this product image..."}
    ]}]
)
```

**After (Gemini Vision):**
```python
response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents=[
        types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg"),
        "Analyze this product image..."
    ]
)
```

---

## 13. Stretch Goals (if time permits)

| Feature | Value | Effort |
|---|---|---|
| **ADK bidi-streaming** | Voice-in, story-out in real-time | High |
| **Veo video clips** | AI-generated video per scene (not just images) | Medium |
| **Multi-language stories** | Reuse NovaReel's translation pipeline | Low |
| **Google Search grounding** | Fact-check educational content | Low |
| **Gemini Embedding 2** | Semantic image-to-scene matching | Low |
| **Export as PDF storybook** | Downloadable illustrated book | Medium |
| **Music generation (Lyria)** | AI-generated background music | Medium |

---

## 14. Final Recommendation

**Fork the project.** The NovaReel codebase gives us a massive head start:

- Production-quality video rendering pipeline (FFmpeg, effects, transitions, captions)
- Mature FastAPI backend with proper error handling, retry logic, and job management
- Working Next.js frontend with auth, project management, and media display
- Multi-provider voice synthesis with fallback chain
- Stock media integration (Pexels)
- Docker setup ready for Cloud Run

The core new work is:
1. **`gemini.py`** — ~200 lines replacing `nova.py`
2. **`story_pipeline.py`** — ~300 lines adapting `pipeline.py` for streaming
3. **`story-canvas.tsx`** — ~200 lines for the streaming interleaved UI
4. **GCP deployment** — Dockerfile + Cloud Run deploy

This is achievable in 4 days. The existing codebase handles all the "boring but necessary" infrastructure, letting us focus entirely on the interleaved streaming experience that wins the 40% UX criterion.

---

## Sources

- [Gemini Live Agent Challenge - Devpost](https://geminiliveagentchallenge.devpost.com/)
- [Gemini Native Image Generation API](https://ai.google.dev/gemini-api/docs/image-generation)
- [Gemini Models Overview](https://ai.google.dev/gemini-api/docs/models)
- [ADK Gemini Live API Toolkit](https://google.github.io/adk-docs/streaming/)
- [ADK Streaming Dev Guide](https://google.github.io/adk-docs/streaming/dev-guide/part1/)
- [Google GenAI SDK Python Docs](https://googleapis.github.io/python-genai/)
- [Gemini Embedding 2 Announcement](https://blog.google/innovation-and-ai/models-and-research/gemini-models/gemini-embedding-2/)
- [Cloud Run Documentation](https://cloud.google.com/run/docs)
