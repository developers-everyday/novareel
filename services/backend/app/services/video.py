from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

from app.config import Settings
from app.models import ProjectRecord, StoryboardSegment
from app.services.storage import StorageService

logger = logging.getLogger(__name__)



class VideoService:
  def __init__(self, settings: Settings):
    self._settings = settings

  @staticmethod
  def _resolution_for(aspect_ratio: str) -> tuple[str, float]:
    mapping = {
      '16:9': ('1920x1080', 42.0),
      '1:1': ('1080x1080', 36.0),
      '9:16': ('1080x1920', 36.0),
    }
    return mapping.get(aspect_ratio, ('1920x1080', 42.0))

  def _resolve_asset_path(self, asset_id: str, project_id: str) -> Path | None:
    """Find the uploaded asset file in local storage."""
    storage_root = self._settings.local_data_dir / self._settings.local_storage_dir
    asset_dir = storage_root / 'projects' / project_id / 'assets'
    if not asset_dir.exists():
      return None
    matches = list(asset_dir.glob(f'{asset_id}*'))
    return matches[0] if matches else None

  def render_video(
    self,
    *,
    project: ProjectRecord,
    job_id: str,
    aspect_ratio: str,
    storyboard: list[StoryboardSegment],
    storage: StorageService,
  ) -> tuple[str, float, str, str | None]:
    resolution, duration_sec = self._resolution_for(aspect_ratio)
    width, height = resolution.split('x')

    output_key = f'projects/{project.id}/outputs/{job_id}.mp4'
    thumbnail_key = f'projects/{project.id}/outputs/{job_id}.jpg'

    ffmpeg_path = shutil.which('ffmpeg')
    if not ffmpeg_path:
      logger.warning('ffmpeg not found, storing placeholder bytes')
      storage.store_bytes(output_key, b'Placeholder MP4 bytes. Install ffmpeg for real rendering.', content_type='video/mp4')
      return output_key, duration_sec, resolution, None

    storage_root = self._settings.local_data_dir / self._settings.local_storage_dir
    audio_path = storage_root / 'projects' / project.id / 'outputs' / f'{job_id}.mp3'

    with tempfile.TemporaryDirectory(prefix='novareel-render-') as temp_dir:
      temp_root = Path(temp_dir)
      video_path = temp_root / 'render.mp4'
      image_path = temp_root / 'thumb.jpg'
      concat_list = temp_root / 'concat.txt'

      # Check once if drawtext is available (requires libfreetype)
      has_drawtext = False
      try:
        filter_check = subprocess.run(
          [ffmpeg_path, '-filters'], capture_output=True, check=False,
        )
        has_drawtext = b'drawtext' in filter_check.stdout
      except Exception:
        pass

      concat_lines: list[str] = []

      for idx, segment in enumerate(storyboard):
        seg_video = temp_root / f'seg_{idx:03d}.mp4'
        seg_duration = segment.duration_sec
        asset_path = self._resolve_asset_path(segment.image_asset_id, project.id)
        fps = 24
        total_frames = int(fps * seg_duration)

        if asset_path and asset_path.exists():
          # --- Ken Burns effect: alternate zoom-in / zoom-out ---
          if idx % 2 == 0:
            # Zoom in: start at 1.0x, end at 1.3x
            zoom_expr = f"min(zoom+0.0015,1.3)"
          else:
            # Zoom out: start at 1.3x, end at 1.0x
            zoom_expr = f"if(eq(on\\,1)\\,1.3\\,max(zoom-0.0015\\,1.0))"

          vf = (
            f'scale=8000:-1,'
            f"zoompan=z='{zoom_expr}':d={total_frames}:s={width}x{height}:fps={fps},"
            f'setsar=1'
          )

          # --- Burned-in subtitles ---
          if has_drawtext and segment.script_line:
            escaped_text = segment.script_line.replace("'", "\u2019").replace(":", "\\:")
            vf += (
              f",drawtext=text='{escaped_text}'"
              f":fontsize=36:fontcolor=white:borderw=3:bordercolor=black"
              f":x=(w-text_w)/2:y=h-80"
            )

          input_args = ['-i', str(asset_path)]
        else:
          logger.info('Segment %d: no image found, using color background', idx)
          vf = 'setsar=1'
          input_args = ['-f', 'lavfi', '-i', f'color=c=#0f172a:s={resolution}:d={seg_duration}']

        cmd = [
          ffmpeg_path, '-y',
          *input_args,
          '-vf', vf,
          '-t', str(seg_duration),
          '-c:v', 'libx264',
          '-preset', 'fast',
          '-pix_fmt', 'yuv420p',
          '-r', str(fps),
          str(seg_video),
        ]

        result = subprocess.run(cmd, check=False, capture_output=True)
        if result.returncode != 0:
          err = result.stderr.decode('utf-8', errors='replace')
          # Skip the version banner — log only the last meaningful lines
          err_lines = [l for l in err.splitlines() if not l.startswith('  ') and l.strip()]
          logger.warning('ffmpeg segment %d failed: %s', idx, '\n'.join(err_lines[-6:]))
        else:
          concat_lines.append(f"file '{seg_video}'\n")

      if not concat_lines:
        logger.error('No segment videos rendered; storing placeholder')
        storage.store_bytes(output_key, b'Fallback render output', content_type='video/mp4')
        return output_key, duration_sec, resolution, None

      concat_list.write_text(''.join(concat_lines))

      # ── Concatenate ──────────────────────────────────────────────────────────
      concat_video = temp_root / 'concat.mp4'
      concat_cmd = [
        ffmpeg_path, '-y',
        '-f', 'concat', '-safe', '0', '-i', str(concat_list),
        '-c', 'copy',
        str(concat_video),
      ]
      subprocess.run(concat_cmd, check=False, capture_output=True)

      if not concat_video.exists():
        logger.error('Concat step failed; storing placeholder')
        storage.store_bytes(output_key, b'Fallback render output', content_type='video/mp4')
        return output_key, duration_sec, resolution, None

      # ── Mux audio ────────────────────────────────────────────────────────────
      final_video = concat_video
      if audio_path.exists() and audio_path.stat().st_size > 100:
        muxed = temp_root / 'muxed.mp4'
        mux_cmd = [
          ffmpeg_path, '-y',
          '-i', str(concat_video),
          '-i', str(audio_path),
          '-c:v', 'copy', '-c:a', 'aac', '-shortest',
          str(muxed),
        ]
        result = subprocess.run(mux_cmd, check=False, capture_output=True)
        if result.returncode == 0 and muxed.exists():
          final_video = muxed
        else:
          logger.warning('Audio mux failed, using video-only output')

      # ── Thumbnail ────────────────────────────────────────────────────────────
      thumb_cmd = [
        ffmpeg_path, '-y', '-i', str(final_video),
        '-frames:v', '1', '-q:v', '2', str(image_path),
      ]
      subprocess.run(thumb_cmd, check=False, capture_output=True)

      # ── Store ─────────────────────────────────────────────────────────────────
      actual_duration = sum(s.duration_sec for s in storyboard) or duration_sec
      storage.store_bytes(output_key, final_video.read_bytes(), content_type='video/mp4')

      if image_path.exists():
        storage.store_bytes(thumbnail_key, image_path.read_bytes(), content_type='image/jpeg')
        return output_key, actual_duration, resolution, thumbnail_key

    return output_key, actual_duration, resolution, None
