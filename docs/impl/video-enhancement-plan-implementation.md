# Integrate Amazon Nova Reel — Implementation Plan

> **Source Plan:** [`docs/video-enhancement-plan.md`](../video-enhancement-plan.md)

This plan covers the precise code changes required to integrate Amazon Nova Reel into the NovaReel pipeline, replacing static FFmpeg `zoompan` animation with AI-generated video clips for `ai_generated` scenes.

---

## ⚠️ Prerequisites

> [!IMPORTANT]
> - **AWS Bedrock Quotas**: Verify sufficient concurrent invocation quota for `amazon.nova-reel-v1:0` in `us-east-1` before deploying to production. If quotas are low, batch size should be reduced to 2 at a time.
> - **Dedicated S3 Bucket**: A dedicated S3 bucket for Nova Reel output is **required** and must be separate from the primary `NOVAREEL_S3_BUCKET_NAME` production bucket. Provision this bucket before starting.

---

## Proposed Changes

### 1. Configuration

#### [MODIFY] `services/backend/.env` & `.env.production.example`
Add the new environment variables:
```
NOVAREEL_USE_NOVA_REEL=true
NOVAREEL_NOVA_REEL_OUTPUT_BUCKET=<dedicated-bucket-name>
```

#### [MODIFY] `services/backend/app/config/__init__.py`
Add two fields to the `Settings` class:
```python
# Nova Reel video generation
use_nova_reel: bool = False
nova_reel_output_bucket: str | None = None
```
Both are picked up automatically via the `NOVAREEL_` env prefix.

---

### 2. New Service: `nova_reel.py`

**File:** `services/backend/app/services/nova_reel.py`

Create a `NovaReelService` class with the following contract:

| Method | Behaviour |
|---|---|
| `generate_batch(tasks, project_id)` | Calls `StartAsyncInvoke` concurrently for every task, then runs a **single unified polling loop** (`GetAsyncInvoke`) until all are `Completed` or `Failed`. Downloads each `.mp4` from `nova_reel_output_bucket` to `data/storage/projects/<id>/clips/<job_id>/nova_reel_<scene_order>.mp4`. Returns `dict[int, Path]` (scene order → local clip path). |

Key implementation points:
- Use `asyncio` or `concurrent.futures.ThreadPoolExecutor` for concurrent `StartAsyncInvoke` calls.
- Log progress at each poll iteration (90–180 s typical wait).
- On any task `Failed`, preserve original storyboard segment (fallback — do not raise).

---

### 3. Pipeline Integration

**File:** `services/backend/app/services/pipeline.py`  
**Method:** `_fetch_stock_footage_with_director`

#### 3a — New `media_decision` branch
```python
if media_decision == 'nova_reel':
    nova_reel_tasks.append((i, scene_order, storyboard[i]))
```
After the loop, call:
```python
clip_map = await NovaReelService().generate_batch(nova_reel_tasks, project_id)
```

#### 3b — Storyboard segment
For each downloaded clip, create a `StoryboardSegment` with:
```python
StoryboardSegment(
    order=scene_order,
    media_type='video',
    video_path=str(clip_path),
    is_ai_generated=True,
    broll_query=f'[nova_reel] {image_prompt[:50]}',
    # ... other fields from original segment
)
```
`video.py` requires **zero changes** — Nova Reel clips flow through the existing `broll_segments` path.

#### 3c — Fallback
If `settings.use_nova_reel` is `False`, or if a task fails, the original zoompan segment is preserved unchanged.

---

### 4. New Test Utility: `validate_novareel.py`

**File:** `services/backend/validate_novareel.py`

Standalone script (not part of the worker) that:
1. Reads `.env` variables.
2. Calls `StartAsyncInvoke` for a single test image.
3. Polls until `Completed`.
4. Downloads the `.mp4` and verifies it is a valid video file.

Used to confirm IAM permissions (`bedrock:InvokeModelAsync`, `bedrock:GetAsyncInvoke`), S3 write/read access, and quota availability before enabling in production.

---

## Verification Plan

### Step 1 — Standalone Smoke Test
```bash
cd services/backend && source .venv/bin/activate
python validate_novareel.py
```
Expected: polls to completion, saves a valid `.mp4` locally, no errors.

### Step 2 — End-to-End Worker Test
1. Set `NOVAREEL_USE_NOVA_REEL=true` in `.env`.
2. Start worker and trigger a project generation.
3. Verify in worker logs:
   - Multiple concurrent `StartAsyncInvoke` calls.
   - Single unified polling loop running until all complete.
   - Final video contains fluid Nova Reel clips for `ai_generated` scenes.

### Step 3 — Fallback Test
1. Set `NOVAREEL_USE_NOVA_REEL=false`.
2. Run a full generation — pipeline must behave identically to pre-integration (zoompan for image scenes).

---

## Architectural Scope

| Component | Changed? |
|---|---|
| `config/__init__.py` | ✅ 2 new fields |
| `nova_reel.py` | ✅ New file |
| `pipeline.py` | ✅ New branch in `_fetch_stock_footage_with_director` |
| `video.py` | ❌ No changes needed |
| `validate_novareel.py` | ✅ New standalone test script |
| `EditingPlan` / `PlanCompiler` path | ❌ Out of scope for this phase |
