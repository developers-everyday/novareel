# Bug Fix Review — B-Roll & Caption Sync

> **Reviewer**: Lead Architect
> **Date**: 2026-03-11
> **Scope**: Fixes for B-roll not working + caption desync (5 files changed, +217/-40)
> **Verdict**: All critical fixes are correct. 2 minor issues to address, 3 observations for awareness.

---

## Files Changed

| File | Purpose |
|------|---------|
| `services/backend/app/services/pipeline.py` | B-roll off-by-one fix, start_sec recalc, mock audio duration, audio/video reconciliation |
| `services/backend/app/services/transcription.py` | Mock transcription probes actual audio duration |
| `services/backend/app/services/stock_media.py` | Duration filter logging |
| `services/backend/app/services/video.py` | Subtitle burn-in fallback chain, music mux audio-probe |
| `services/backend/app/config/__init__.py` | env_file path resolution |

---

## Fix-by-Fix Review

### 1. B-Roll Off-by-One (B1-FIX) — `pipeline.py` line 88

```python
scene_order = i + 1  # 1-based to match storyboard segment.order
```

**Verdict**: CORRECT. The `downloaded_clips` tuple and `clip_map` now use 1-based keys matching `segment.order`. The `product_lifestyle` / `lifestyle_focus` skip logic still operates on the 0-based `i` which is correct (the skip decision is about scene index, the storage key is about matching storyboard order).

### 2. B-Roll Start-Sec Recalculation (B1-c) — `pipeline.py` lines 136-139

```python
running_start = 0.0
for seg in updated_storyboard:
    seg.start_sec = round(running_start, 3)
    running_start += seg.duration_sec
```

**Verdict**: CORRECT. After B-roll truncation (`min(segment.duration_sec, clip_duration)`) changes some segment durations, `start_sec` values are recalculated to form a contiguous timeline. Without this, there would be gaps or overlaps.

### 3. Download Failure Logging (B1-d) — `pipeline.py` line 109

**Verdict**: CORRECT. Good addition — failed downloads now produce a warning with scene number and query.

### 4. Mock Audio Duration Match — `pipeline.py` lines 284-296

```python
mock_duration = sum(s.duration_sec for s in storyboard) or 36.0
```

**Verdict**: CORRECT. Mock mode now generates silence that matches the storyboard total duration. This means:
- The audio/video reconciliation step will find durations already matching (skip rescaling) — correct for mock
- The mock transcription (Fix 6) probes this audio and distributes word timings across the real duration — correct

### 5. Audio/Video Duration Reconciliation (B2-FIX-a) — `pipeline.py` lines 313-355

**Verdict**: CORRECT with caveats.

Positives:
- Pipeline ordering is right: NARRATION → RECONCILE → TRANSCRIPTION → RENDERING
- Uses ffprobe (preferred) with ffmpeg stderr fallback
- 0.5-second threshold avoids unnecessary rescaling for trivial differences
- Proportional scaling preserves relative segment weights
- Recalculates both `duration_sec` and `start_sec`

**Minor issue (see below)**: The duration regex and import style could be cleaner.

### 6. Mock Transcription Audio Probe (B2-FIX-b) — `transcription.py` lines 57-71

**Verdict**: CORRECT. MockTranscriptionBackend now probes actual audio duration via ffprobe instead of hardcoding 30 seconds. Falls back to 30s when ffprobe is unavailable. This means mock captions will be spread across the real audio duration.

### 7. Pexels Duration Filter Logging — `stock_media.py` lines 120-157

**Verdict**: CORRECT. Logs a warning when all results are filtered out by duration, making it easy to diagnose "no B-roll" issues caused by the 3-15s filter.

### 8. Subtitle Burn-in Fallback Chain — `video.py` lines 301-374

**Verdict**: CORRECT. Three-tier fallback (ASS → subtitles filter → drawtext) is a significant robustness improvement. The `has_subtitles` detection and `subtitles_burned` flag prevent redundant attempts.

### 9. Music Mux Audio Probe — `video.py` lines 393-434

**Verdict**: CORRECT. This also fixes the Phase 1 CR-6 bug (music skipped when narration failed). The code now probes for an existing audio stream and uses the appropriate ffmpeg command:
- With audio: `amix` to blend music under narration at 12% volume
- Without audio: add music as sole track at 25% volume with `-shortest`

### 10. Config env_file Path — `config/__init__.py`

**Verdict**: CORRECT but unrelated to the B-roll/caption bugs. Having both project root and CWD `.env` as sources prevents missing config when the worker runs from a different directory than the API.

---

## Issues to Address

### Issue 1: Mock B-Roll Skip Was Removed — Now Hits Real Pexels API in Mock Mode

**Where**: `pipeline.py` lines 104-109 (the old `if settings.use_mock_ai: continue` was removed)

**Problem**: The old code explicitly skipped B-roll downloads in mock mode. The new code removes this check, meaning mock mode will make real HTTP requests to the Pexels API (search + download) as long as `pexels_api_key` is set.

**Impact**: This may be intentional (mock only skips expensive Bedrock LLM calls, not Pexels). But it means:
- Running tests with `use_mock_ai=True` and a Pexels key will make real network calls
- CI environments without network access will see download failures (but gracefully — they just get no B-roll)

**Recommendation**: If this is intentional, add a comment explaining why mock mode still uses real Pexels. If not, gate the download behind a separate `use_mock_stock_media` flag, or at minimum check `settings.use_mock_ai` and generate a valid placeholder video via ffmpeg instead of downloading.

### Issue 2: Reconciliation Inline Imports and Aliased Names

**Where**: `pipeline.py` lines 317-338

```python
import shutil as _shutil2
import subprocess as _sp2
...
import re as _re
```

**Problem**: The underscore-prefixed aliased imports (`_shutil2`, `_sp2`, `_re`) are used to avoid shadowing earlier imports with the same name in the narration block. This works but is fragile — it suggests the function is too long and has conflicting scopes.

**Recommendation**: Extract the audio duration probing into a helper function:
```python
def _probe_audio_duration(audio_path: Path) -> float | None:
    """Return audio duration in seconds, or None if probing fails."""
    import shutil, subprocess, re
    ffprobe = shutil.which('ffprobe') or shutil.which('ffmpeg')
    ...
```

This eliminates the aliased imports and makes the reconciliation block testable independently.

---

## Observations (No Action Required)

### Observation A: SRT vs ASS Timing Sources Differ After Fallback

The ASS subtitles use word-level transcription timing (from audio). The SRT fallback in `video.py` Attempt 2 uses `build_srt(storyboard)` which uses storyboard segment timing. After reconciliation these should be close, but if the ASS path fails and the SRT path succeeds, subtitles switch from word-level to segment-level granularity. This is an acceptable degradation — just be aware the subtitle experience differs across the fallback tiers.

### Observation B: Reconciliation Operates on Mutable Storyboard

The reconciliation modifies `storyboard` segments in-place (line 349-350). This is fine because the same storyboard list is used downstream for rendering and SRT generation. But if any future code caches or re-reads the storyboard after this point, it would get the reconciled (not original) durations. The intermediate cache at `storyboard_with_broll.json` is written BEFORE reconciliation, so a pipeline resume would re-reconcile — which is correct since audio may differ on retry.

### Observation C: Scale Factor Could Be Extreme

If TTS produces 15 seconds of audio but the storyboard is 36 seconds, the scale factor is 0.42 — each 6-second segment becomes 2.5 seconds. Visually this could feel too fast. There's no clamp on the scale factor. Consider logging a warning when `scale_factor < 0.5` or `scale_factor > 2.0` to flag potential quality issues, but don't block the render.

---

## Summary

| Fix ID | Status | Notes |
|--------|--------|-------|
| B1-FIX (off-by-one) | PASS | Clean, correct |
| B1-c (start_sec recalc) | PASS | |
| B1-d (download logging) | PASS | |
| B2-FIX-a (reconciliation) | PASS | Extract helper (Issue 2) |
| B2-FIX-b (mock transcription) | PASS | |
| Pexels filter logging | PASS | |
| Subtitle fallback chain | PASS | Good robustness improvement |
| Music mux probe | PASS | Also fixes Phase 1 CR-6 |
| Config env_file | PASS | Unrelated but fine |
| Mock B-roll behavior | **REVIEW** | Issue 1 — clarify intent |
| Inline import aliases | **MINOR** | Issue 2 — extract helper |

**Overall**: The critical bugs are fixed correctly. The pipeline ordering (narrate → reconcile → transcribe → render) is sound. Two minor items to clean up before merging. Ready to ship after addressing Issue 1 (mock B-roll intent).
