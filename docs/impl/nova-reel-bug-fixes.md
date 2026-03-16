# Nova Reel Integration — Bug Fix Plan

> **Branch:** `feature/nova-reel-integration`
> **Commit to fix:** `6e0a8a3` — "feat: Integrate Amazon Nova Reel AI video generation"
> **Validated against:** [`docs/video-enhancement-plan.md`](../video-enhancement-plan.md) and [`docs/impl/video-enhancement-plan-implementation.md`](video-enhancement-plan-implementation.md)

This document lists every issue found during the post-commit review. Work through the fixes **in order** — the critical bugs must be done first, as they would cause complete failure at runtime before the deviations even matter.

---

## Priority 1 — Critical Bugs (nothing works without these)

These four issues mean the feature is completely non-functional even with `NOVAREEL_USE_NOVA_REEL=true`. Fix all four before testing anything.

---

### Fix 1 — Wrong Boto3 client name

**File:** `services/backend/app/services/nova_reel.py`, line 23

**Problem:** `start_async_invoke` and `get_async_invoke` are methods on the `bedrock-runtime` client, not the `bedrock` client. The current code uses `'bedrock'`, so every API call will raise `AttributeError: 'BedrockClient' object has no attribute 'start_async_invoke'`.

**Fix:** Change the client name in `__init__`:

```python
# BEFORE (line 23)
self._bedrock_client = boto3.client(
    'bedrock',
    region_name=settings.aws_region,
)

# AFTER
self._bedrock_client = boto3.client(
    'bedrock-runtime',
    region_name=settings.aws_region,
)
```

---

### Fix 2 — Store the full ARN; stop stripping and reconstructing it

**File:** `services/backend/app/services/nova_reel.py`, lines 113–116 and line 165

**Problem:** The code strips the full invocation ARN returned by `start_async_invoke` down to just the trailing ID fragment, then later tries to reconstruct an ARN in an invalid format. The reconstructed string is not a valid Bedrock ARN, so `get_async_invoke` will fail.

**Step 1 — Keep the full ARN in `_start_async_invocation`:**

```python
# BEFORE (lines 113–118)
invocation_id = response.get('invocationArn')
if invocation_id:
    # Extract just the ID from the ARN for easier handling
    invocation_id = invocation_id.split('/')[-1]
    logger.info('Started Nova Reel invocation for scene %d: %s', scene_order, invocation_id)
    return invocation_id

# AFTER — store the full ARN, rename variable for clarity
invocation_arn = response.get('invocationArn')
if invocation_arn:
    logger.info('Started Nova Reel invocation for scene %d: %s', scene_order, invocation_arn)
    return invocation_arn
```

**Step 2 — Pass the ARN directly in `_poll_and_download`:**

The type hints and variable names that say `invocation_id` should become `invocation_arn` throughout `_poll_and_download` and `_download_clip`. The key change is on line 164:

```python
# BEFORE (line 164)
response = self._bedrock_client.get_async_invoke(
    invocationArn=f'arn:aws:bedrock:us-east-1:amazon.nova-reel-v1:0/invocation/{invocation_id}'
)

# AFTER — pass the original ARN directly
response = self._bedrock_client.get_async_invoke(
    invocationArn=invocation_arn
)
```

Also update the type hints in `_poll_and_download` and `_download_clip` to use `invocation_arn: str` instead of `invocation_id: str` for clarity.

---

### Fix 3 — Fix the S3 key mismatch (upload target ≠ download path)

**File:** `services/backend/app/services/nova_reel.py`, lines 100–104 and line 211

**Problem:** The invocation request tells Nova Reel to write its output to `nova-reel-output/{scene_order:03d}.mp4`. But `_download_clip` tries to download from `nova-reel-output/{invocation_id}.mp4`. These keys will never match, so every download fails with `NoSuchKey`.

Additionally, Nova Reel itself decides exactly where to write inside the prefix you provide — you cannot reliably predict the final key. The correct approach is to read the output S3 URI from the `get_async_invoke` response once the status is `Completed`.

**Step 1 — Set a per-invocation output prefix (not a full filename) in the request body:**

```python
# BEFORE (lines 100–105)
"outputConfig": {
    "s3Location": {
        "bucketName": self._settings.nova_reel_output_bucket,
        "objectKey": f"nova-reel-output/{scene_order:03d}.mp4"
    }
}

# AFTER — provide a prefix folder; Nova Reel writes the actual file inside it
"outputDataConfig": {
    "s3OutputDataConfig": {
        "s3Uri": f"s3://{self._settings.nova_reel_output_bucket}/nova-reel-output/scene-{scene_order:03d}/"
    }
}
```

> Note: the top-level key is `outputDataConfig`, not `outputConfig`. Check the [AWS Nova Reel API reference](https://docs.aws.amazon.com/bedrock/latest/userguide/nova-reel-start-async-invoke.html) to confirm the exact field name for the SDK version you are using.

**Step 2 — Read the actual output URI from the `GetAsyncInvoke` response:**

```python
# In _poll_and_download, when status == 'Completed':
if status == 'Completed':
    # Get the actual S3 URI Nova Reel wrote to
    output_uri = response.get('outputDataConfig', {}) \
                         .get('s3OutputDataConfig', {}) \
                         .get('s3Uri', '')
    clip_path = clips_dir / f'nova_reel_{scene_order:03d}.mp4'
    success = await self._download_clip_from_uri(output_uri, clip_path)
```

**Step 3 — Rewrite `_download_clip` to accept the S3 URI:**

```python
async def _download_clip_from_uri(self, s3_uri: str, output_path: Path) -> bool:
    """Download a completed Nova Reel clip using the S3 URI from the response."""
    try:
        # Parse s3://bucket/key
        without_scheme = s3_uri.removeprefix('s3://')
        bucket, _, key = without_scheme.partition('/')
        # Nova Reel outputs a file named 'output.mp4' inside the prefix folder
        if not key.endswith('.mp4'):
            key = key.rstrip('/') + '/output.mp4'

        self._s3_client.download_file(
            Bucket=bucket,
            Key=key,
            Filename=str(output_path),
        )
        if output_path.exists() and output_path.stat().st_size > 1000:
            logger.info('Downloaded Nova Reel clip: %s', output_path.name)
            return True
        logger.error('Downloaded Nova Reel clip is empty or missing: %s', output_path)
        return False
    except ClientError as e:
        logger.error('Failed to download Nova Reel clip %s: %s', s3_uri, e)
        return False
```

---

### Fix 4 — Add `nova_reel` to the Vision Director tool schema and prompt

**File:** `services/backend/app/services/broll_director.py`

**Problem:** The Vision Director LLM tool schema only lists `['product_closeup', 'broll', 'product_in_context', 'ai_generated']` as valid `media_type` values. `nova_reel` is not in the enum and not mentioned in the prompt. The LLM will never return `nova_reel`, so the pipeline branch added in `pipeline.py` is permanently unreachable.

**Step 1 — Add `nova_reel` to the tool schema enum (line ~43):**

```python
# BEFORE
'enum': ['product_closeup', 'broll', 'product_in_context', 'ai_generated'],
'description': (
    'product_closeup: keep the uploaded product image with tight framing. '
    'broll: replace with stock footage — provide a search_query. '
    ...
    'ai_generated: generate a new contextual image using AI (Nova Omni) — '
    ...
),

# AFTER — add nova_reel as an option
'enum': ['product_closeup', 'broll', 'product_in_context', 'ai_generated', 'nova_reel'],
'description': (
    'product_closeup: keep the uploaded product image with tight framing. '
    'broll: replace with stock footage — provide a search_query. '
    ...
    'ai_generated: generate a new contextual image using AI — only as a last resort. '
    'nova_reel: generate a short AI video clip from the product image — '
    'use this for dynamic lifestyle/action scenes where motion adds real value. '
    'Requires an image_prompt describing the desired motion and scene.'
),
```

**Step 2 — Update the director's system prompt (lines ~235–245) to explain when to use `nova_reel`:**

Find the block that explains each `media_type` and add:

```
- "nova_reel": Generate a 6-second AI video clip using Amazon Nova Reel. Use this when
  the scene calls for dynamic motion around the product (e.g. liquid splashing, lighting
  sweep, camera pull-back). Requires an image_prompt. Use sparingly — 1-2 scenes maximum.
```

Also make sure the `image_prompt` tool input field description mentions it is required for both `ai_generated` and `nova_reel`.

---

## Priority 2 — Plan Deviations

These issues mean the feature works but does not match the design. Fix after Priority 1.

---

### Fix 5 — Implement image-to-video (not text-only)

**File:** `services/backend/app/services/nova_reel.py`, method `_start_async_invocation`

**Problem:** The entire value of Nova Reel described in the plan is animating the **product image** into a video. The current implementation sends a text-only prompt. The product image is never passed to Nova Reel.

**How to fix:** `generate_batch` receives the `StoryboardSegment` for each scene. The segment has `image_asset_id`. Before calling `_start_async_invocation`, resolve the image to bytes and include it in the request body as an `image` reference.

The Nova Reel image-to-video request body looks like:

```python
request_body = {
    "taskType": "IMAGE_VIDEO",
    "imageToVideoParams": {
        "text": image_prompt,
        "images": [
            {
                "format": "jpeg",  # or "png"
                "source": {
                    "bytes": base64.b64encode(image_bytes).decode("utf-8")
                }
            }
        ]
    },
    "videoGenerationConfig": {
        "durationSeconds": 6,
        "fps": 24,
        "dimension": "1280x720",
    },
}
```

To get `image_bytes`: use `VideoService._resolve_asset_path(image_asset_id, project_id)` (same pattern as the existing `ai_generated` branch in `pipeline.py` around line 349) and then `open(path, 'rb').read()`.

Pass the resolved image bytes into `generate_batch` tasks or resolve them inside the service before calling `_start_async_invocation`.

> Verify the exact field names against the [Nova Reel API docs](https://docs.aws.amazon.com/bedrock/latest/userguide/nova-reel-start-async-invoke.html). The task type for image-to-video may be `IMAGE_VIDEO` or `IMAGE_TO_VIDEO` depending on SDK version.

---

### Fix 6 — Change duration from 5 s to 6 s

**File:** `services/backend/app/services/nova_reel.py`, line 97

```python
# BEFORE
"durationSeconds": 5,

# AFTER
"durationSeconds": 6,
```

---

### Fix 7 — Add `job_id` subdirectory to the clip storage path

**File:** `services/backend/app/services/nova_reel.py`, lines 133–147 (`_poll_and_download`)
**File:** `services/backend/app/services/pipeline.py`, lines 458–462 (caller)

**Problem:** The plan specifies `clips/<job_id>/nova_reel_<scene_order>.mp4` to match the existing broll storage pattern (see `pipeline.py:147`). Without a `job_id` subdir, clips from concurrent jobs overwrite each other.

**Fix:** Pass `job_id` into `generate_batch` and down to `_poll_and_download`:

In `nova_reel.py`:
```python
# Update generate_batch signature
async def generate_batch(
    self,
    tasks: List[Tuple[int, int, Any]],
    project_id: str,
    job_id: str,           # ADD THIS
) -> Dict[int, Path]:

# Update _poll_and_download call
clip_map = await self._poll_and_download(pending_tasks, project_id, job_id)

# Update _poll_and_download signature and path
async def _poll_and_download(self, pending_tasks, project_id: str, job_id: str):
    clips_dir = storage_root / 'projects' / project_id / 'clips' / job_id  # was missing / job_id
```

In `pipeline.py`, pass `job_id` to the call (the function already has `clips_dir` which encodes the job path — alternatively just pass `clips_dir` directly to `generate_batch` instead of reconstructing it):

```python
# BEFORE (line ~462)
clip_map = await nova_reel_service.generate_batch(nova_reel_tasks, project_id)

# AFTER
clip_map = await nova_reel_service.generate_batch(nova_reel_tasks, project_id, job_id)
```

> Check what `job_id` variable is available at the call site in `_fetch_stock_footage_with_director`. If it is not currently a parameter, the simplest fix is to pass `clips_dir` directly instead.

---

### Fix 8 — Use the actual image prompt in `broll_query`

**File:** `services/backend/app/services/pipeline.py`, line 469

```python
# BEFORE
f'[nova_reel] AI-generated video',

# AFTER — use the prompt that was passed to Nova Reel, truncated to 50 chars
f'[nova_reel] {image_prompt[:50]}',
```

`image_prompt` is already available in the scope where `nova_reel_tasks` is collected (from `plan_entry.get('image_prompt', '')`). Store it alongside the task and use it when building `downloaded_clips`.

---

### Fix 9 — Add Nova Reel vars to `.env.production.example`

**File:** `services/backend/.env.production.example` (create if it does not exist)

Add the two new variables with placeholder values and a comment:

```bash
# Amazon Nova Reel AI video generation
# Set to true to replace ai_generated zoompan scenes with Nova Reel clips.
# Requires a dedicated S3 bucket — must NOT be the same as NOVAREEL_S3_BUCKET_NAME.
NOVAREEL_USE_NOVA_REEL=false
NOVAREEL_NOVA_REEL_OUTPUT_BUCKET=<your-nova-reel-output-bucket-name>
```

---

## Minor Cleanup

These do not affect correctness but should be cleaned up.

### Cleanup 1 — Remove unused `task_map` variable

**File:** `services/backend/app/services/nova_reel.py`, line 137

```python
# DELETE this line — task_map is never read
task_map = {scene_order: inv_id for scene_order, inv_id in pending_tasks}
```

---

## Verification Checklist

After all fixes are applied, run through these checks before merging:

### Step 1 — Standalone smoke test
```bash
cd services/backend && source .venv/bin/activate
# Ensure NOVAREEL_USE_NOVA_REEL=true and NOVAREEL_NOVA_REEL_OUTPUT_BUCKET is set
python validate_novareel.py
```
Expected: polls to `Completed`, saves a valid `.mp4` locally, no errors.

### Step 2 — End-to-end test with `nova_reel` enabled
1. Set `NOVAREEL_USE_NOVA_REEL=true` in `.env`.
2. Trigger a full project generation.
3. Confirm in worker logs:
   - Multiple concurrent `StartAsyncInvoke` calls logged.
   - Unified polling loop running, logging progress every 10 s.
   - "Nova Reel clip ready for scene N" messages.
   - Final video contains fluid Nova Reel clips for scenes where the director chose `nova_reel`.

### Step 3 — Fallback test
1. Set `NOVAREEL_USE_NOVA_REEL=false`.
2. Run a full generation — must behave identically to before the integration (zoompan for image scenes, no errors).

---

## Fix Summary

| # | File | Lines | Type | Description |
|---|---|---|---|---|
| 1 | `nova_reel.py` | 23 | Critical | Change `'bedrock'` → `'bedrock-runtime'` |
| 2 | `nova_reel.py` | 113–116, 164 | Critical | Store full ARN; pass directly to `get_async_invoke` |
| 3 | `nova_reel.py` | 100–104, 164–173, 211 | Critical | Fix S3 key mismatch; read output URI from response |
| 4 | `broll_director.py` | ~43, ~235 | Critical | Add `nova_reel` to tool enum and director prompt |
| 5 | `nova_reel.py` | 94–106 | Deviation | Implement image-to-video; pass product image bytes |
| 6 | `nova_reel.py` | 97 | Deviation | Change duration `5` → `6` seconds |
| 7 | `nova_reel.py` + `pipeline.py` | 146, 462 | Deviation | Add `job_id` to clip storage path |
| 8 | `pipeline.py` | 469 | Deviation | Use actual `image_prompt` in `broll_query` |
| 9 | `.env.production.example` | — | Deviation | Add Nova Reel env vars |
| C1 | `nova_reel.py` | 137 | Cleanup | Remove unused `task_map` variable |
