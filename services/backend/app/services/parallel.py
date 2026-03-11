"""Parallel segment rendering utility for video generation pipeline."""

from __future__ import annotations

import logging
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Cap concurrency to avoid FFmpeg resource exhaustion
MAX_PARALLEL_SEGMENTS = min(os.cpu_count() or 2, 4)


@dataclass
class SegmentRenderTask:
  """Input for a single segment render job."""
  segment_index: int
  image_path: str
  duration: float
  aspect_ratio: str
  output_path: str
  ken_burns: bool = True
  ffmpeg_preset: str = 'medium'
  pan_x: float = 0.5
  pan_y: float = 0.5


@dataclass
class SegmentRenderResult:
  """Output from a single segment render job."""
  segment_index: int
  output_path: str
  success: bool
  error: str = ''
  duration_sec: float = 0.0


def _render_single_segment(task_dict: dict[str, Any]) -> dict[str, Any]:
  """Render a single video segment in a subprocess.

  This function runs in a separate process via ProcessPoolExecutor.
  It must be a module-level function (not a method) for pickling.

  Args:
    task_dict: Serialized SegmentRenderTask fields.

  Returns:
    Serialized SegmentRenderResult fields.
  """
  import subprocess
  import time

  segment_index = task_dict['segment_index']
  image_path = task_dict['image_path']
  duration = task_dict['duration']
  aspect_ratio = task_dict['aspect_ratio']
  output_path = task_dict['output_path']
  ken_burns = task_dict.get('ken_burns', True)
  ffmpeg_preset = task_dict.get('ffmpeg_preset', 'medium')
  pan_x = task_dict.get('pan_x', 0.5)
  pan_y = task_dict.get('pan_y', 0.5)

  start = time.perf_counter()

  # Resolve dimensions from aspect ratio
  dims = {
    '16:9': (1920, 1080),
    '9:16': (1080, 1920),
    '1:1': (1080, 1080),
  }
  width, height = dims.get(aspect_ratio, (1920, 1080))

  try:
    # Build ffmpeg command for single segment
    if ken_burns:
      from app.services.zoom_utils import build_zoompan_vf

      vf = build_zoompan_vf(
        width=width, height=height,
        duration_sec=duration,
        fps=25,
        zoom_dir='zoom_in' if segment_index % 2 == 0 else 'zoom_out',
        zoom_speed=0.001,
        max_zoom=1.2,
        pan_x=pan_x,
        pan_y=pan_y,
      )
    else:
      vf = f'scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2'

    cmd = [
      'ffmpeg', '-y',
      '-loop', '1',
      '-i', image_path,
      '-vf', vf,
      '-t', str(duration),
      '-c:v', 'libx264',
      '-preset', ffmpeg_preset,
      '-tune', 'stillimage',
      '-pix_fmt', 'yuv420p',
      '-r', '25',
      output_path,
    ]

    result = subprocess.run(cmd, capture_output=True, check=False, timeout=120)
    elapsed = time.perf_counter() - start

    if result.returncode != 0:
      return {
        'segment_index': segment_index,
        'output_path': output_path,
        'success': False,
        'error': result.stderr.decode('utf-8', errors='replace')[-300:],
        'duration_sec': elapsed,
      }

    return {
      'segment_index': segment_index,
      'output_path': output_path,
      'success': True,
      'error': '',
      'duration_sec': elapsed,
    }

  except Exception as exc:
    return {
      'segment_index': segment_index,
      'output_path': output_path,
      'success': False,
      'error': str(exc),
      'duration_sec': time.perf_counter() - start,
    }


def render_segments_parallel(
  tasks: list[SegmentRenderTask],
  max_workers: int | None = None,
) -> list[SegmentRenderResult]:
  """Render multiple video segments in parallel using a process pool.

  Args:
    tasks: List of segment render tasks.
    max_workers: Max parallel workers (defaults to MAX_PARALLEL_SEGMENTS).

  Returns:
    List of SegmentRenderResult, ordered by segment_index.
  """
  workers = min(max_workers or MAX_PARALLEL_SEGMENTS, len(tasks))
  logger.info('Rendering %d segments in parallel (max_workers=%d)', len(tasks), workers)

  # Serialize tasks to dicts for pickling across processes
  task_dicts = [
    {
      'segment_index': t.segment_index,
      'image_path': t.image_path,
      'duration': t.duration,
      'aspect_ratio': t.aspect_ratio,
      'output_path': t.output_path,
      'ken_burns': t.ken_burns,
      'ffmpeg_preset': t.ffmpeg_preset,
      'pan_x': t.pan_x,
      'pan_y': t.pan_y,
    }
    for t in tasks
  ]

  results: list[SegmentRenderResult] = []

  with ProcessPoolExecutor(max_workers=workers) as executor:
    future_map = {
      executor.submit(_render_single_segment, td): td['segment_index']
      for td in task_dicts
    }

    for future in as_completed(future_map):
      try:
        result_dict = future.result(timeout=180)
        results.append(SegmentRenderResult(**result_dict))
      except Exception as exc:
        idx = future_map[future]
        logger.error('Segment %d render failed: %s', idx, exc)
        results.append(SegmentRenderResult(
          segment_index=idx,
          output_path='',
          success=False,
          error=str(exc),
        ))

  # Sort by segment index to maintain order
  results.sort(key=lambda r: r.segment_index)

  succeeded = sum(1 for r in results if r.success)
  logger.info('Parallel render complete: %d/%d segments succeeded', succeeded, len(tasks))
  return results
