# Bug Analysis — B-Roll Not Working & Captions Out of Sync

> **Analyst**: Lead Architect
> **Date**: 2026-03-11
> **Reported by**: QA testing of ShortGPT integration flow
> **Severity**: Both bugs are HIGH — core feature broken

---

## Bug 1: B-Roll Stock Footage Not Working

### Symptom

When `video_style` is set to `product_lifestyle` or `lifestyle_focus`, the rendered video still shows only product images — no stock footage clips from Pexels appear.

### Root Cause: Off-by-One Between Clip Index and Storyboard Order

**Primary bug location**: `services/backend/app/services/pipeline.py` — `_fetch_stock_footage()` lines 87-131

The storyboard uses **1-based** `order` values, but the B-roll clip map uses **0-based** loop indices.

**How storyboard orders are assigned** (`services/backend/app/services/nova.py`):

```python
# _embedding_match() — line 379:
order=index + 1    # 1-based

# _round_robin_match() — line 401:
order=index + 1    # 1-based
```

So for 6 script lines, storyboard orders are: **[1, 2, 3, 4, 5, 6]**

**How clip_map keys are assigned** (`pipeline.py`):

```python
# Line 87:
for i, query in enumerate(search_queries):    # i is 0-based
    ...
    # Line 106:
    downloaded_clips.append((i, clip_path, ...))   # key is 0-based

# Line 114:
clip_map = {idx: (path, dur) for idx, path, dur in downloaded_clips}
# Keys are: {0, 1, 2, 3, 4, 5} (0-based)
```

**The mismatch** — clip lookup on line 117:

```python
for segment in storyboard:
    if segment.order in clip_map:     # 1-based order vs 0-based keys
```

For `product_lifestyle` (skip even indices: i=0,2,4 → keep clips for i=1,3,5):

| Storyboard Segment | `segment.order` | `clip_map` has key? | Result |
|---|---|---|---|
| Scene 0 (should be product image) | 1 | `clip_map[1]` = YES | **Gets B-roll (WRONG)** |
| Scene 1 (should be B-roll) | 2 | `clip_map[2]` = NO | **Keeps image (WRONG)** |
| Scene 2 (should be product image) | 3 | `clip_map[3]` = YES | **Gets B-roll (WRONG)** |
| Scene 3 (should be B-roll) | 4 | `clip_map[4]` = NO | **Keeps image (WRONG)** |
| Scene 4 (should be product image) | 5 | `clip_map[5]` = YES | **Gets B-roll (WRONG)** |
| Scene 5 (should be B-roll) | 6 | `clip_map[6]` = NO | **Keeps image (WRONG)** |

**Every single assignment is inverted** — product scenes get B-roll and B-roll scenes keep product images.

For `lifestyle_focus` (skip only i=0 → clips for i=1,2,3,4,5):

| Storyboard Segment | `segment.order` | `clip_map` has key? | Result |
|---|---|---|---|
| Scene 0 (should be product) | 1 | `clip_map[1]` = YES | **Gets B-roll (WRONG)** |
| Scene 1 (should be B-roll) | 2 | `clip_map[2]` = YES | Correct |
| ... | ... | ... | ... |
| Scene 5 (should be B-roll) | 6 | `clip_map[6]` = NO | **Keeps image (WRONG)** |

First scene gets B-roll when it shouldn't, last scene misses B-roll.

### Fix

Change the clip_map lookup from `segment.order` to use the 0-based index, OR change the clip_map keys to 1-based. The cleanest fix:

```python
# pipeline.py line 114-131 — change clip_map to use 1-based order
# Option A: Adjust the download loop to use 1-based keys
for i, query in enumerate(search_queries):
    scene_order = i + 1   # Convert to 1-based to match storyboard
    if video_style == 'product_lifestyle' and i % 2 == 0:
        continue
    elif video_style == 'lifestyle_focus' and i == 0:
        continue
    ...
    downloaded_clips.append((scene_order, clip_path, ...))
```

```python
# Option B (minimal): Adjust the lookup
for segment in storyboard:
    clip_key = segment.order - 1   # Convert 1-based order to 0-based index
    if clip_key in clip_map:
        ...
```

**Recommend Option A** — it makes the intent clear.

### Secondary Failure Modes (May Also Contribute)

These won't cause a complete failure on their own, but compound the issue:

#### 1a. Silent fallback when Pexels API key is missing

**Where**: `pipeline.py` line 56-58

```python
if not settings.pexels_api_key:
    logger.warning('Pexels API key not configured, falling back to product_only style')
    return storyboard
```

If `NOVAREEL_PEXELS_API_KEY` env var is not set, the entire B-roll feature silently degrades to product-only. The API endpoint validates this (v1.py line 180-185) for new jobs, but if the key was set during enqueue but removed before the worker runs, the pipeline silently falls back.

**Action**: Check that `NOVAREEL_PEXELS_API_KEY` is set in the environment where the worker runs, not just the API server.

#### 1b. Pexels duration filter may eliminate all results

**Where**: `stock_media.py` line 122-123

```python
if duration < min_duration or duration > max_duration:
    continue
```

Default: `min_duration=3, max_duration=15`. If Pexels only returns clips shorter than 3 seconds or longer than 15 seconds for a query, they're all filtered out. The search returns an empty list, and no clips download.

**Action**: Consider widening the filter or logging when all results are filtered.

#### 1c. B-roll duration truncation breaks timing cascade

**Where**: `pipeline.py` line 125

```python
duration_sec=min(segment.duration_sec, clip_duration),
```

If a Pexels clip is 4 seconds but the storyboard segment is 6 seconds, the B-roll segment becomes 4 seconds. But `start_sec` of subsequent segments is NOT recalculated. This creates a gap or overlap in the rendered video.

**Action**: After modifying durations, recalculate `start_sec` for all subsequent segments.

#### 1d. No download error logging at the clip level

When `download_clip()` fails (stock_media.py line 175-176), it logs and returns None. But in the pipeline (line 104-106), a failed download simply doesn't append to `downloaded_clips` — there's no log at the pipeline level showing which scenes lost their B-roll.

**Action**: Add a log warning when a clip fails to download:
```python
downloaded = stock_service.download_clip(clip_info['url'], clip_path)
if downloaded:
    downloaded_clips.append((i, clip_path, min(clip_info['duration'], 5)))
else:
    logger.warning('B-roll download failed for scene %d (query: %s)', i, query)
```

---

## Bug 2: Captions Not Synced With Narration

### Symptom

Captions (word_highlight, karaoke, or simple) appear at the wrong times — they drift ahead of or behind the spoken narration, and don't align with the visual scene transitions.

### Root Cause: Three Independent Unsynchronized Timing Systems

The pipeline has three timing domains that are never reconciled:

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  STORYBOARD     │    │  AUDIO / TTS    │    │  CAPTIONS       │
│  TIMING         │    │  TIMING         │    │  (WORD TIMINGS) │
│                 │    │                 │    │                 │
│  Set by         │    │  Set by TTS     │    │  Set by         │
│  match_images() │    │  provider       │    │  transcription  │
│  in nova.py     │    │  speech rate    │    │  of audio       │
│                 │    │                 │    │                 │
│  6 sec/segment  │    │  Variable       │    │  Variable       │
│  = 36 sec total │    │  (25-50 sec)    │    │  (or 30s mock)  │
└────────┬────────┘    └────────┬────────┘    └────────┬────────┘
         │                      │                      │
         ▼                      ▼                      ▼
    Video visuals          Narration audio         ASS subtitles
    (per-segment           (single continuous      (timed to audio,
     durations)             audio track)            NOT to segments)
```

#### Problem A: Audio vs Video duration mismatch

**Where**: `nova.py` line 259 and `pipeline.py` line 271

```python
# nova.py — storyboard timing:
segment_length = max(4.0, 36.0 / total)
# For 6 scenes: 6.0 sec each = 36 sec total video

# pipeline.py — narration:
transcript = '\n'.join(script_lines)
audio_payload = provider.synthesize(transcript[:3000], ...)
# Audio duration = whatever the TTS produces (maybe 28 sec, maybe 45 sec)
```

The video renders with segment durations from the storyboard (36 sec total), but the audio plays at its own pace. The `mux` step uses `-shortest` (video.py line 384):
- If audio (28 sec) < video (36 sec): video cuts off at 28 sec, last segment's visuals never shown
- If audio (45 sec) > video (36 sec): audio cuts off at 36 sec, narration never finishes

**Neither outcome is correct.**

#### Problem B: Caption timings are based on audio, not on video segments

**Where**: `pipeline.py` lines 318-321 and `transcription.py`

```python
word_timings = backend.transcribe(audio_path, language=job.language)
```

Whisper/Transcribe produce word timings based on the actual audio's internal timeline (e.g., word at 12.5 seconds in the audio). These get baked into the ASS subtitle file. But the video's visual timeline is determined by storyboard segment durations — a completely independent timeline.

If the audio is 28 seconds but the video is 36 seconds:
- Caption for a word at audio position 25 seconds appears at video position 25 seconds
- But the video at 25 seconds is showing segment 5's visuals (which starts at 24 sec in video-time)
- The narration at audio 25 sec might be for segment 4's text
- Result: **captions show segment 4's words over segment 5's visuals**

#### Problem C: Mock transcription hardcodes 30-second duration

**Where**: `transcription.py` line 57-58

```python
duration = 30.0
word_duration = duration / len(all_words)
```

Mock mode spreads word timings evenly across a fixed 30-second window, regardless of:
- Actual video duration (36 seconds for 16:9 with 6 segments)
- Actual mock audio duration (2 seconds from ffmpeg silence generator, pipeline.py line 283)

So in mock mode: captions are timed for 0-30 sec, video is 36 sec, audio is 2 sec. Everything is wrong.

#### Problem D: SRT subtitles use storyboard timing, ASS uses audio timing

**Where**: `subtitle_utils.py` line 20-27 and `transcription.py` line 196

Two separate subtitle systems produce conflicting timing:
- `build_srt()` generates SRT based on storyboard segment `start_sec` / `duration_sec`
- `generate_ass_subtitles()` generates ASS based on transcription word timings

The pipeline generates BOTH (ASS for burn-in, SRT for download). They will show different timing if the user downloads the SRT vs what's burned into the video.

### Fix Strategy

This requires a multi-part fix. Here's the recommended approach in priority order:

#### Fix 2a: Reconcile audio and video durations (REQUIRED)

After TTS synthesis, probe the actual audio duration and recompute storyboard segment durations to match:

```python
# After audio generation, probe real duration:
import subprocess
probe = subprocess.run(
    [ffmpeg_path, '-i', str(audio_path), '-hide_banner'],
    capture_output=True, check=False
)
# Parse "Duration: 00:00:28.50" from stderr
audio_duration = _parse_duration(probe.stderr)

# Recompute segment durations proportionally
total_storyboard_duration = sum(s.duration_sec for s in storyboard)
scale_factor = audio_duration / total_storyboard_duration

running_start = 0.0
for seg in storyboard:
    seg.duration_sec = round(seg.duration_sec * scale_factor, 3)
    seg.start_sec = round(running_start, 3)
    running_start += seg.duration_sec
```

This ensures the video duration matches the audio duration, so `-shortest` doesn't cut anything.

#### Fix 2b: Fix mock transcription to use actual duration (REQUIRED for dev/test)

**Where**: `transcription.py` — `MockTranscriptionBackend.transcribe()`

```python
def transcribe(self, audio_path: Path, language: str = 'en') -> list[WordTiming]:
    # Probe actual audio duration instead of hardcoding 30s
    duration = 30.0  # default fallback
    if audio_path.exists():
        import subprocess, shutil
        ffprobe = shutil.which('ffprobe')
        if ffprobe:
            result = subprocess.run(
                [ffprobe, '-v', 'quiet', '-show_entries', 'format=duration',
                 '-of', 'default=noprint_wrappers=1:nokey=1', str(audio_path)],
                capture_output=True, check=False
            )
            try:
                duration = float(result.stdout.strip())
            except (ValueError, TypeError):
                pass
    ...
```

#### Fix 2c: Per-segment TTS synthesis for precise timing (IDEAL but larger effort)

Instead of synthesizing the entire transcript as one audio blob, synthesize each script line separately and concatenate:

```python
audio_segments = []
for line in script_lines:
    segment_audio = provider.synthesize(line, ...)
    audio_segments.append(segment_audio)
    # Measure duration of each segment
    # Update storyboard timing to match
```

This gives precise per-segment timing control and eliminates the drift problem entirely. However, it increases TTS API calls (6x for 6 scenes) and requires audio concatenation logic.

**Recommend as Phase 2 improvement**, not an immediate fix.

#### Fix 2d: Update SRT generation to use reconciled timing

After Fix 2a reconciles durations, the `build_srt()` output will match the video. But also ensure the SRT download reflects the same timing as the burned-in ASS captions.

---

## Action Items Summary

| ID | Bug | Severity | Effort | Description |
|----|-----|----------|--------|-------------|
| **B1-FIX** | B-Roll | **HIGH** | 15 min | Fix off-by-one: use `segment.order - 1` or 1-based clip keys |
| B1-a | B-Roll | MEDIUM | 10 min | Verify `NOVAREEL_PEXELS_API_KEY` is set in worker env |
| B1-b | B-Roll | LOW | 15 min | Widen/log Pexels duration filter |
| B1-c | B-Roll | MEDIUM | 30 min | Recalculate `start_sec` after B-roll duration truncation |
| B1-d | B-Roll | LOW | 5 min | Add pipeline-level log for failed clip downloads |
| **B2-FIX-a** | Captions | **HIGH** | 1.5 hrs | Reconcile audio and video durations after TTS |
| **B2-FIX-b** | Captions | **HIGH** | 30 min | Fix mock transcription to probe actual audio duration |
| B2-FIX-c | Captions | MEDIUM | 3-4 hrs | Per-segment TTS synthesis (future improvement) |
| B2-FIX-d | Captions | LOW | 15 min | Ensure SRT uses reconciled timing |

**Recommended fix order**: B1-FIX → B2-FIX-a → B2-FIX-b → B1-c → rest

**Total effort for required fixes**: ~2.5-3 hours
