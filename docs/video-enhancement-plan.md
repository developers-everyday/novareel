# Amazon Nova Reel Integration Plan

## 1. Capabilities of Amazon Nova Models

Amazon has introduced a suite of state-of-the-art multimodal AI models under the "Nova" brand, which offer powerful capabilities for content analysis and generation:

*   **Amazon Nova Pro**: Provides advanced reasoning and multimodal analysis.
    *   **Document Analysis**: Can process large documents (like PDFs) to generate summaries and structured outputs, such as decision trees.
    *   **Video Analysis**: Capable of "watching" and describing video files (uploaded directly or via an S3 bucket). It can extract specific information like objects or text from the video, though it currently does not process the audio track.
*   **Amazon Nova Reel**: A state-of-the-art video generation model designed to produce high-quality, professional video content for marketing, advertising, and entertainment.
    *   **Text-to-Video & Image-to-Video**: Creates 6-second, 24fps videos from text prompts alone or by using a reference image to guide the generation.
    *   **Camera Control**: Supports specific camera actions like zooming in, zooming out, or panning (e.g., "drone view flying over a coastal landscape").
    *   **Asynchronous Processing**: Video generation is intensive, so the Bedrock API uses asynchronous operations (`StartAsyncInvoke`, `GetAsyncInvoke`) paired with an S3 bucket destination for the output video.
    *   **Safety & Watermarking**: Includes built-in safety controls and invisible watermarks for responsible AI usage.

---

## 2. Drawbacks in the Current Application

The NovaReel application currently has several limitations regarding its visual output quality:

*   **Static Image Animation**: When the pipeline relies on product images or AI-generated still images (via Nova Canvas), it animates them using a basic FFmpeg `zoompan` filter.
*   **Lack of Fluidity**: The `zoompan` effect is essentially a slow digital crop. It looks artificial and lacks the depth, parallax, and realistic lighting changes of true video motion.
*   **Inconsistent Visual Quality**: While stock footage (B-roll from Pexels) provides high-quality video, matching it perfectly to specific niche products is difficult. When the system falls back to the product image with a `zoompan`, the quality drop is noticeable and makes the final output feel less premium.

---

## 3. How Amazon Nova Reel Enhances Our Application

Integrating Amazon Nova Reel directly addresses these drawbacks and unlocks a new tier of quality:

*   **Cinematic Product Shots**: Instead of a flat Ken Burns zoom on a product photo, Nova Reel can take the static product image and generate a 6-second video showing real motion (e.g., water splashing around the product, dynamic lighting changes, or a 3D-like camera push).
*   **Enhanced Storytelling**: By prompting Nova Reel with the generated script's visual requirements, we can create hyper-specific, highly relevant B-roll that perfectly matches both the product and the narration, eliminating the reliance on generic stock footage.
*   **Premium SaaS Offering**: True AI video generation significantly elevates the perceived value of the marketing videos produced by the platform, giving users a much more engaging and professional result that justifies the SaaS pricing.

---

## 4. Implementation Plan

### Scope

This integration targets the **legacy rendering path** (`render_video` in `video.py`) and the **Vision Director path** (`_fetch_stock_footage_with_director` in `pipeline.py`). The `EditingPlan` / `PlanCompiler` path (gated by `use_editing_framework`) is **out of scope** for this phase and should be addressed in a follow-up.

---

### Step 1: Configuration & Setup

*   **Environment Variables**: Add the following to `services/backend/.env`:
    ```
    NOVAREEL_USE_NOVA_REEL=true
    NOVAREEL_NOVA_REEL_OUTPUT_BUCKET=<dedicated-bucket-name>
    ```
*   **Naming note**: The new bucket setting is named `nova_reel_output_bucket` (not `nova_reel_s3_bucket`) to clearly distinguish it from the existing `NOVAREEL_S3_BUCKET_NAME` (the main asset/production bucket). AWS requires Nova Reel to write to its own dedicated S3 bucket — these must never be the same bucket.
*   **Config Model**: Add two fields to `services/backend/app/config/__init__.py` inside the `Settings` class:
    ```python
    # Nova Reel video generation
    use_nova_reel: bool = False
    nova_reel_output_bucket: str | None = None
    ```
    Both fields pick up `NOVAREEL_` prefix automatically via `SettingsConfigDict(env_prefix='NOVAREEL_')`.

---

### Step 2: Create the Nova Reel Service (`services/backend/app/services/nova_reel.py`)

Implement a dedicated `NovaReelService` class responsible for interacting with the asynchronous Bedrock APIs.

*   **Concurrent Generation**: Since each video takes 90–180 seconds, the service must accept a batch of tasks (e.g., all `ai_generated` scene segments for a video) and call `StartAsyncInvoke` for each one concurrently in a first pass.
*   **Polling Loop**: Implement a loop that periodically calls `GetAsyncInvoke` for all pending tasks until their status is `Completed` or `Failed`. Log progress at each poll iteration so the worker logs remain informative during the wait.
*   **S3 Download**: Once a task is `Completed`, use `boto3.client('s3')` to download the resulting `.mp4` file from `nova_reel_output_bucket` to local storage at `services/backend/data/storage/projects/<id>/clips/<job_id>/nova_reel_<scene_order>.mp4`.
*   **Return type**: Return a `dict[int, Path]` mapping scene order → downloaded clip path, so callers can update the storyboard directly.

---

### Step 3: Embed at the Pipeline Level (`services/backend/app/services/pipeline.py`)

> [!IMPORTANT]
> **Primary integration point is `pipeline.py`, not `video.py`**. Placing the Nova Reel polling loop inside `VideoService.render_video` would block the entire single-threaded worker queue for 3–5 minutes per job. Instead, Nova Reel generation must be triggered at the same lifecycle stage as `_fetch_stock_footage`, before the video rendering phase begins.

#### 3a: Add a new `media_decision` branch in `_fetch_stock_footage_with_director`

The Vision Director already dispatches `media_decision` values of `product_closeup`, `product_in_context`, `ai_generated`, and `broll`. Add a new `nova_reel` decision:

```python
if media_decision == 'nova_reel':
    # Queue this scene for Nova Reel generation
    nova_reel_tasks.append((i, scene_order, storyboard[i]))
```

After the loop, pass `nova_reel_tasks` to `NovaReelService.generate_batch(...)`, which handles all `StartAsyncInvoke` calls concurrently and blocks only once during a single unified polling loop for the entire batch.

#### 3b: Storyboard segment representation

Nova Reel clips are represented exactly like Pexels B-roll in the storyboard — this requires no new model fields:

```python
StoryboardSegment(
    order=scene_order,
    script_line=segment.script_line,
    image_asset_id=segment.image_asset_id,
    start_sec=segment.start_sec,
    duration_sec=segment.duration_sec,   # clip is always 6s; trim to match
    media_type='video',
    video_path=str(downloaded_clip_path),
    is_ai_generated=True,                # existing field — signals AI origin
    broll_query=f'[nova_reel] {image_prompt[:50]}',
)
```

This means `video.py` and the rest of the rendering pipeline require **zero changes** — Nova Reel clips flow through the existing `broll_segments` phase without modification.

#### 3c: Fallback behaviour

If `use_nova_reel` is `False`, or if any Nova Reel task fails, the original storyboard segment (product image → zoompan) is preserved. Nova Reel is strictly additive and the pipeline degrades gracefully.

---

### Step 4: Testing & Verification

*   **Standalone test**: Create `services/backend/validate_novareel.py` to test a single image-to-video generation step. Verifies Bedrock quotas, IAM permissions (`bedrock:InvokeModelAsync`, `bedrock:GetAsyncInvoke`), S3 write/read access on the output bucket, and that the resulting `.mp4` is valid.
*   **End-to-End**: Run a full project generation with `NOVAREEL_USE_NOVA_REEL=true`. Verify:
    1.  Worker logs show concurrent `StartAsyncInvoke` calls followed by a unified polling loop.
    2.  The final composed video features the new fluid Nova Reel clips for `ai_generated` scenes.
    3.  Jobs with `NOVAREEL_USE_NOVA_REEL=false` are unaffected.
*   **Update `SKILL.md`**: Once the integration is complete and verified, run the `/update-novareel-skill` workflow to record the new service, environment variables, and pipeline step in the agent quick-start file.

> [!IMPORTANT]
> **Quotas & Concurrency**: Generating 4–6 scenes concurrently via Nova Reel requires sufficient AWS Bedrock quotas for `amazon.nova-reel-v1:0` concurrent invocations. Review your AWS Bedrock service quotas in `us-east-1` before deploying to production. If quotas are low, `NovaReelService` should process tasks in smaller batches (e.g., 2 at a time) rather than all at once.

---

## 5. Architectural Summary

```
pipeline.py  (_fetch_stock_footage_with_director)
  ├── media_decision = 'product_closeup'  → keep image (zoompan in video.py)
  ├── media_decision = 'product_in_context' → keep image with focal override
  ├── media_decision = 'ai_generated'     → Nova Canvas → zoompan (existing)
  ├── media_decision = 'nova_reel'   [NEW]→ NovaReelService.generate_batch()
  │                                          └─ StartAsyncInvoke × N (concurrent)
  │                                          └─ Unified polling loop
  │                                          └─ S3 download → local .mp4 clips
  └── media_decision = 'broll'            → Pexels fetch + Vision validation

video.py  (render_video)
  ├── broll_segments   ← Pexels clips + Nova Reel clips  [NO CHANGES NEEDED]
  └── image_segments   ← product images → zoompan        [NO CHANGES NEEDED]
```

This approach preserves clean separation of concerns:
- `nova_reel.py` — pure Bedrock async I/O
- `pipeline.py` — orchestration and storyboard assembly
- `video.py` — local FFmpeg rendering only (unchanged)
