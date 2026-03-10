from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

from app.config import Settings
from app.models import ProjectRecord, StoryboardSegment
from app.services.effects import VideoEffectsConfig
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

  @staticmethod
  def _detect_ffmpeg_features(ffmpeg_path: str) -> dict[str, bool]:
    """Detect available ffmpeg filters (drawtext, ass, xfade)."""
    features = {'drawtext': False, 'ass': False, 'xfade': False}
    try:
      result = subprocess.run(
        [ffmpeg_path, '-filters'], capture_output=True, check=False,
      )
      stdout = result.stdout
      features['drawtext'] = b'drawtext' in stdout
      features['ass'] = b' ass ' in stdout or b'libass' in stdout
      features['xfade'] = b'xfade' in stdout
    except Exception:
      pass
    return features

  def render_video(
    self,
    *,
    project: ProjectRecord,
    job_id: str,
    aspect_ratio: str,
    storyboard: list[StoryboardSegment],
    storage: StorageService,
    music_path: 'Path | None' = None,
    effects_config: VideoEffectsConfig | None = None,
    ass_subtitle_path: Path | None = None,
  ) -> tuple[str, float, str, str | None]:
    resolution, duration_sec = self._resolution_for(aspect_ratio)
    width, height = resolution.split('x')

    if effects_config is None:
      effects_config = VideoEffectsConfig()

    output_key = f'projects/{project.id}/outputs/{job_id}.mp4'
    thumbnail_key = f'projects/{project.id}/outputs/{job_id}.jpg'

    ffmpeg_path = shutil.which('ffmpeg')
    if not ffmpeg_path:
      logger.warning('ffmpeg not found, storing placeholder bytes')
      storage.store_bytes(output_key, b'Placeholder MP4 bytes. Install ffmpeg for real rendering.', content_type='video/mp4')
      return output_key, duration_sec, resolution, None

    storage_root = self._settings.local_data_dir / self._settings.local_storage_dir
    audio_path = storage_root / 'projects' / project.id / 'outputs' / f'{job_id}.mp3'

    features = self._detect_ffmpeg_features(ffmpeg_path)
    has_drawtext = features['drawtext']
    has_xfade = features['xfade']
    has_ass = features['ass']

    use_transitions = (
      has_xfade
      and effects_config.transition.xfade_name is not None
      and effects_config.transition.duration > 0
    )

    with tempfile.TemporaryDirectory(prefix='novareel-render-') as temp_dir:
      temp_root = Path(temp_dir)
      video_path = temp_root / 'render.mp4'
      image_path = temp_root / 'thumb.jpg'
      concat_list = temp_root / 'concat.txt'

      seg_paths: list[Path] = []
      seg_durations: list[float] = []

      # Classify segments into B-roll (sequential) and image (parallel-eligible)
      image_segments: list[tuple[int, StoryboardSegment]] = []
      broll_segments: list[tuple[int, StoryboardSegment]] = []
      for idx, segment in enumerate(storyboard):
        if segment.media_type == 'video' and segment.video_path:
          broll_segments.append((idx, segment))
        else:
          image_segments.append((idx, segment))

      # Dict to collect rendered paths keyed by segment index
      rendered: dict[int, tuple[Path, float]] = {}

      # ── Phase 1: Render B-roll segments sequentially ──────────────────
      for idx, segment in broll_segments:
        seg_video = temp_root / f'seg_{idx:03d}.mp4'
        seg_duration = segment.duration_sec
        fps = 24
        broll_path = Path(segment.video_path)
        if broll_path.exists() and broll_path.stat().st_size > 100:
          vf = f'scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1'

          if has_drawtext and segment.script_line and not ass_subtitle_path:
            escaped_text = segment.script_line.replace("'", "\u2019").replace(":", "\\:")
            vf += (
              f",drawtext=text='{escaped_text}'"
              f":fontsize=36:fontcolor=white:borderw=3:bordercolor=black"
              f":x=(w-text_w)/2:y=h-80"
            )

          cmd = [
            ffmpeg_path, '-y',
            '-i', str(broll_path),
            '-vf', vf,
            '-t', str(seg_duration),
            '-c:v', 'libx264',
            '-preset', self._settings.ffmpeg_preset,
            '-pix_fmt', 'yuv420p',
            '-an',
            '-r', str(fps),
            str(seg_video),
          ]

          result = subprocess.run(cmd, check=False, capture_output=True)
          if result.returncode != 0:
            err = result.stderr.decode('utf-8', errors='replace')
            logger.warning('ffmpeg video segment %d failed: %s', idx, err[-300:])
            # Fall back to image rendering for this segment
            image_segments.append((idx, segment.model_copy(update={'media_type': 'image', 'video_path': None})))
            image_segments.sort(key=lambda x: x[0])
          else:
            rendered[idx] = (seg_video, seg_duration)

      # ── Phase 2: Render image segments (parallel when ≥ 3) ───────────
      use_parallel = len(image_segments) >= 3
      if use_parallel:
        from app.services.parallel import SegmentRenderTask, render_segments_parallel
        parallel_tasks: list[SegmentRenderTask] = []
        for idx, segment in image_segments:
          seg_video = temp_root / f'seg_{idx:03d}.mp4'
          asset_path = self._resolve_asset_path(segment.image_asset_id, project.id)
          if asset_path and asset_path.exists():
            parallel_tasks.append(SegmentRenderTask(
              segment_index=idx,
              image_path=str(asset_path),
              duration=segment.duration_sec,
              aspect_ratio=aspect_ratio,
              output_path=str(seg_video),
              ken_burns=True,
              ffmpeg_preset=self._settings.ffmpeg_preset,
            ))
          else:
            # Render color placeholder sequentially
            self._render_color_segment(ffmpeg_path, seg_video, resolution, segment.duration_sec, self._settings.ffmpeg_preset)
            if seg_video.exists():
              rendered[idx] = (seg_video, segment.duration_sec)

        if parallel_tasks:
          results = render_segments_parallel(parallel_tasks)
          for r in results:
            if r.success and Path(r.output_path).exists():
              seg = next(s for i, s in image_segments if i == r.segment_index)
              rendered[r.segment_index] = (Path(r.output_path), seg.duration_sec)
            else:
              logger.warning('Parallel segment %d failed: %s', r.segment_index, r.error[:200])
      else:
        # Sequential rendering for image segments (< 3 segments or fallback)
        for idx, segment in image_segments:
          seg_video = temp_root / f'seg_{idx:03d}.mp4'
          seg_duration = segment.duration_sec
          fps = 24
          total_frames = int(fps * seg_duration)

          asset_path = self._resolve_asset_path(segment.image_asset_id, project.id)
          if asset_path and asset_path.exists():
            if idx % 2 == 0:
              zoom_expr = f"min(zoom+0.0015,1.3)"
            else:
              zoom_expr = f"if(eq(on\\,1)\\,1.3\\,max(zoom-0.0015\\,1.0))"

            vf = (
              f'scale=8000:-1,'
              f"zoompan=z='{zoom_expr}':d={total_frames}:s={width}x{height}:fps={fps},"
              f'setsar=1'
            )

            if has_drawtext and segment.script_line and not ass_subtitle_path:
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
            '-preset', self._settings.ffmpeg_preset,
            '-pix_fmt', 'yuv420p',
            '-r', str(fps),
            str(seg_video),
          ]

          result = subprocess.run(cmd, check=False, capture_output=True)
          if result.returncode != 0:
            err = result.stderr.decode('utf-8', errors='replace')
            err_lines = [l for l in err.splitlines() if not l.startswith('  ') and l.strip()]
            logger.warning('ffmpeg segment %d failed: %s', idx, '\n'.join(err_lines[-6:]))
          else:
            rendered[idx] = (seg_video, seg_duration)

      # Reassemble in original order
      for idx in sorted(rendered.keys()):
        path, dur = rendered[idx]
        seg_paths.append(path)
        seg_durations.append(dur)

      if not seg_paths:
        logger.error('No segment videos rendered; storing placeholder')
        storage.store_bytes(output_key, b'Fallback render output', content_type='video/mp4')
        return output_key, duration_sec, resolution, None

      # ── Join segments: xfade transitions OR simple concat ──────────────
      if use_transitions and len(seg_paths) > 1:
        joined_video = self._join_with_xfade(
          ffmpeg_path, temp_root, seg_paths, seg_durations,
          effects_config.transition.xfade_name,
          effects_config.transition.duration,
          ffmpeg_preset=self._settings.ffmpeg_preset,
        )
        # Fallback to concat if xfade fails
        if joined_video is None:
          joined_video = self._join_with_concat(ffmpeg_path, temp_root, seg_paths, concat_list)
      else:
        joined_video = self._join_with_concat(ffmpeg_path, temp_root, seg_paths, concat_list)

      if joined_video is None or not joined_video.exists():
        logger.error('Join step failed; storing placeholder')
        storage.store_bytes(output_key, b'Fallback render output', content_type='video/mp4')
        return output_key, duration_sec, resolution, None

      # ── Stitch intro/outro clips (Phase 3 — Brand Kit) ─────────────────
      joined_video = self._stitch_intro_outro(
        ffmpeg_path, temp_root, joined_video, effects_config,
      )

      # ── Apply text overlays (title card + CTA) ─────────────────────────
      total_video_duration = sum(seg_durations)
      overlaid = self._apply_text_overlays(
        ffmpeg_path, temp_root, joined_video, effects_config,
        has_drawtext, total_video_duration,
        ffmpeg_preset=self._settings.ffmpeg_preset,
      )
      if overlaid:
        joined_video = overlaid

      # ── Logo watermark overlay (Phase 3 — Brand Kit) ───────────────────
      if effects_config.logo_path and Path(effects_config.logo_path).exists():
        logo_overlaid = self._apply_logo_watermark(
          ffmpeg_path, temp_root, joined_video, Path(effects_config.logo_path),
          int(width), int(height), ffmpeg_preset=self._settings.ffmpeg_preset,
        )
        if logo_overlaid:
          joined_video = logo_overlaid

      # ── Burn ASS subtitles if provided ──────────────────────────────────
      if ass_subtitle_path and ass_subtitle_path.exists() and has_ass:
        subtitled = temp_root / 'subtitled.mp4'
        sub_cmd = [
          ffmpeg_path, '-y',
          '-i', str(joined_video),
          '-vf', f"ass='{ass_subtitle_path}'",
          '-c:v', 'libx264', '-preset', self._settings.ffmpeg_preset, '-c:a', 'copy',
          str(subtitled),
        ]
        sub_result = subprocess.run(sub_cmd, check=False, capture_output=True)
        if sub_result.returncode == 0 and subtitled.exists():
          joined_video = subtitled
          logger.info('ASS subtitles burned in successfully')
        else:
          logger.warning('ASS subtitle burn-in failed, continuing without')

      # ── Mux audio ────────────────────────────────────────────────────────
      final_video = joined_video
      if audio_path.exists() and audio_path.stat().st_size > 100:
        muxed = temp_root / 'muxed.mp4'
        mux_cmd = [
          ffmpeg_path, '-y',
          '-i', str(joined_video),
          '-i', str(audio_path),
          '-c:v', 'copy', '-c:a', 'aac', '-shortest',
          str(muxed),
        ]
        result = subprocess.run(mux_cmd, check=False, capture_output=True)
        if result.returncode == 0 and muxed.exists():
          final_video = muxed
        else:
          logger.warning('Audio mux failed, using video-only output')

      # ── Mix background music ──────────────────────────────────────────
      if music_path and music_path.exists():
        music_muxed = temp_root / 'music_muxed.mp4'
        music_cmd = [
          ffmpeg_path, '-y',
          '-i', str(final_video),
          '-i', str(music_path),
          '-filter_complex',
          '[1:a]aloop=loop=-1:size=2e+09,volume=0.12[bg];[0:a][bg]amix=inputs=2:duration=first',
          '-c:v', 'copy', '-c:a', 'aac',
          str(music_muxed),
        ]
        music_result = subprocess.run(music_cmd, check=False, capture_output=True)
        if music_result.returncode == 0 and music_muxed.exists():
          final_video = music_muxed
          logger.info('Background music mixed successfully')
        else:
          logger.warning('Music mux failed, using narration-only audio')

      # ── Thumbnail ────────────────────────────────────────────────────────
      thumb_cmd = [
        ffmpeg_path, '-y', '-i', str(final_video),
        '-frames:v', '1', '-q:v', '2', str(image_path),
      ]
      subprocess.run(thumb_cmd, check=False, capture_output=True)

      # ── Store ─────────────────────────────────────────────────────────────
      actual_duration = sum(s.duration_sec for s in storyboard) or duration_sec
      storage.store_bytes(output_key, final_video.read_bytes(), content_type='video/mp4')

      if image_path.exists():
        storage.store_bytes(thumbnail_key, image_path.read_bytes(), content_type='image/jpeg')
        return output_key, actual_duration, resolution, thumbnail_key

    return output_key, actual_duration, resolution, None

  def render_from_plan(
    self,
    *,
    plan: 'EditingPlan',
    storage: StorageService,
    output_key: str,
    thumbnail_key: str,
  ) -> tuple[str, float, str, str | None]:
    """Render a video from an EditingPlan using the editing framework compiler.

    This is the new rendering path, gated behind the ``use_editing_framework``
    feature flag.  It delegates all FFmpeg work to ``PlanCompiler``.

    Returns:
        (output_key, duration_sec, resolution, thumbnail_key | None)
    """
    from app.services.editing.compiler import PlanCompiler

    compiler = PlanCompiler()

    with tempfile.TemporaryDirectory(prefix='novareel-plan-') as temp_dir:
      work_dir = Path(temp_dir)
      result = compiler.compile(plan, work_dir)

      if not result.success:
        for err in result.errors:
          logger.error('EditingPlan compile error: %s', err)
        for warn in result.warnings:
          logger.warning('EditingPlan compile warning: %s', warn)
        storage.store_bytes(output_key, b'Fallback render output', content_type='video/mp4')
        return output_key, 0.0, plan.resolution, None

      for warn in result.warnings:
        logger.warning('EditingPlan compile warning: %s', warn)

      storage.store_bytes(output_key, result.video_path.read_bytes(), content_type='video/mp4')

      if result.thumbnail_path and result.thumbnail_path.exists():
        storage.store_bytes(thumbnail_key, result.thumbnail_path.read_bytes(), content_type='image/jpeg')
        return output_key, result.duration_sec, result.resolution, thumbnail_key

    return output_key, result.duration_sec, result.resolution, None

  # ── Private helpers ──────────────────────────────────────────────────────

  @staticmethod
  def _join_with_concat(
    ffmpeg_path: str, temp_root: Path, seg_paths: list[Path], concat_list: Path,
  ) -> Path | None:
    """Join segments with simple concat demuxer (no transitions)."""
    concat_lines = [f"file '{p}'\n" for p in seg_paths]
    concat_list.write_text(''.join(concat_lines))
    concat_video = temp_root / 'concat.mp4'
    cmd = [
      ffmpeg_path, '-y',
      '-f', 'concat', '-safe', '0', '-i', str(concat_list),
      '-c', 'copy',
      str(concat_video),
    ]
    subprocess.run(cmd, check=False, capture_output=True)
    return concat_video if concat_video.exists() else None

  @staticmethod
  def _join_with_xfade(
    ffmpeg_path: str, temp_root: Path,
    seg_paths: list[Path], seg_durations: list[float],
    xfade_name: str, transition_duration: float,
    ffmpeg_preset: str = 'medium',
  ) -> Path | None:
    """Join segments using xfade filter for smooth transitions.

    Builds a chained xfade filtergraph:
      [0:v][1:v]xfade=transition=fade:duration=0.5:offset=6.5[v01];
      [v01][2:v]xfade=transition=fade:duration=0.5:offset=12.5[v012];
    """
    if len(seg_paths) < 2:
      return seg_paths[0] if seg_paths else None

    input_args: list[str] = []
    for p in seg_paths:
      input_args.extend(['-i', str(p)])

    filter_parts: list[str] = []
    cumulative_offset = 0.0

    for i in range(len(seg_paths) - 1):
      if i == 0:
        src = '[0:v]'
      else:
        src = f'[v{i}]'

      cumulative_offset += seg_durations[i] - transition_duration
      offset = max(0, cumulative_offset)

      if i == len(seg_paths) - 2:
        output_label = '[vout]'
      else:
        output_label = f'[v{i+1}]'

      filter_parts.append(
        f"{src}[{i+1}:v]xfade=transition={xfade_name}:duration={transition_duration}:offset={offset:.3f}{output_label}"
      )

    filter_graph = ';'.join(filter_parts)
    xfade_video = temp_root / 'xfade.mp4'

    cmd = [
      ffmpeg_path, '-y',
      *input_args,
      '-filter_complex', filter_graph,
      '-map', '[vout]',
      '-c:v', 'libx264', '-preset', ffmpeg_preset, '-pix_fmt', 'yuv420p',
      str(xfade_video),
    ]

    result = subprocess.run(cmd, check=False, capture_output=True)
    if result.returncode != 0:
      err = result.stderr.decode('utf-8', errors='replace')
      logger.warning('xfade failed, falling back to concat: %s', err[-300:])
      return None
    return xfade_video if xfade_video.exists() else None

  @staticmethod
  def _apply_text_overlays(
    ffmpeg_path: str, temp_root: Path, input_video: Path,
    effects_config: VideoEffectsConfig, has_drawtext: bool,
    total_duration: float,
    ffmpeg_preset: str = 'medium',
  ) -> Path | None:
    """Apply title card and CTA drawtext overlays if configured."""
    if not has_drawtext:
      return None

    filters: list[str] = []

    # Phase 3 — use brand font if available
    font_file_arg = ''
    if effects_config.brand_font_path and Path(effects_config.brand_font_path).exists():
      font_file_arg = f":fontfile='{effects_config.brand_font_path}'"

    if effects_config.title_overlay:
      t = effects_config.title_overlay
      filters.append(
        f"drawtext=text='{t.escaped_text}'"
        f":fontsize={t.font_size}:fontcolor={t.font_color}"
        f":borderw={t.border_width}:bordercolor={t.border_color}"
        f":x={t.x}:y={t.y}"
        f"{font_file_arg}"
        f":enable='between(t,{t.start_sec},{t.start_sec + t.duration_sec})'"
      )

    if effects_config.cta_overlay:
      c = effects_config.cta_overlay
      cta_start = max(0, total_duration - c.duration_sec - 0.5)
      filters.append(
        f"drawtext=text='{c.escaped_text}'"
        f":fontsize={c.font_size}:fontcolor={c.font_color}"
        f":borderw={c.border_width}:bordercolor={c.border_color}"
        f":x={c.x}:y={c.y}"
        f"{font_file_arg}"
        f":enable='between(t,{cta_start},{cta_start + c.duration_sec})'"
      )

    if not filters:
      return None

    overlaid = temp_root / 'overlaid.mp4'
    cmd = [
      ffmpeg_path, '-y',
      '-i', str(input_video),
      '-vf', ','.join(filters),
      '-c:v', 'libx264', '-preset', ffmpeg_preset, '-c:a', 'copy',
      str(overlaid),
    ]

    result = subprocess.run(cmd, check=False, capture_output=True)
    if result.returncode != 0:
      logger.warning('Text overlay failed, continuing without overlays')
      return None
    return overlaid if overlaid.exists() else None

  @staticmethod
  def _render_color_segment(
    ffmpeg_path: str, output: Path, resolution: str, duration: float,
    ffmpeg_preset: str = 'medium',
  ) -> None:
    """Render a solid-color placeholder segment."""
    cmd = [
      ffmpeg_path, '-y',
      '-f', 'lavfi', '-i', f'color=c=#0f172a:s={resolution}:d={duration}',
      '-vf', 'setsar=1',
      '-t', str(duration),
      '-c:v', 'libx264', '-preset', ffmpeg_preset, '-pix_fmt', 'yuv420p',
      '-r', '24',
      str(output),
    ]
    subprocess.run(cmd, check=False, capture_output=True)

  @staticmethod
  def _apply_logo_watermark(
    ffmpeg_path: str, temp_root: Path, input_video: Path,
    logo_path: Path, video_width: int, video_height: int,
    ffmpeg_preset: str = 'medium',
  ) -> Path | None:
    """Overlay brand logo as a watermark in the top-right corner."""
    output = temp_root / 'logo_watermark.mp4'
    # Scale logo to ~8% of video width, place in top-right with 20px padding
    logo_w = max(int(video_width * 0.08), 40)
    filter_graph = (
      f"[1:v]scale={logo_w}:-1,format=rgba,colorchannelmixer=aa=0.7[logo];"
      f"[0:v][logo]overlay=W-w-20:20"
    )
    cmd = [
      ffmpeg_path, '-y',
      '-i', str(input_video),
      '-i', str(logo_path),
      '-filter_complex', filter_graph,
      '-c:v', 'libx264', '-preset', ffmpeg_preset, '-c:a', 'copy',
      str(output),
    ]
    result = subprocess.run(cmd, check=False, capture_output=True)
    if result.returncode != 0:
      logger.warning('Logo watermark failed, continuing without: %s',
                      result.stderr.decode('utf-8', errors='replace')[-200:])
      return None
    return output if output.exists() else None

  @staticmethod
  def _stitch_intro_outro(
    ffmpeg_path: str, temp_root: Path, main_video: Path,
    effects_config: VideoEffectsConfig,
  ) -> Path:
    """Prepend intro clip and/or append outro clip to the main video."""
    parts: list[Path] = []

    if effects_config.intro_clip_path and Path(effects_config.intro_clip_path).exists():
      parts.append(Path(effects_config.intro_clip_path))

    parts.append(main_video)

    if effects_config.outro_clip_path and Path(effects_config.outro_clip_path).exists():
      parts.append(Path(effects_config.outro_clip_path))

    # Nothing to stitch if it's just the main video
    if len(parts) == 1:
      return main_video

    concat_file = temp_root / 'stitch_concat.txt'
    concat_file.write_text(''.join(f"file '{p}'\n" for p in parts))
    stitched = temp_root / 'stitched.mp4'

    cmd = [
      ffmpeg_path, '-y',
      '-f', 'concat', '-safe', '0', '-i', str(concat_file),
      '-c', 'copy',
      str(stitched),
    ]
    result = subprocess.run(cmd, check=False, capture_output=True)
    if result.returncode != 0:
      logger.warning('Intro/outro stitch failed, using main video only: %s',
                      result.stderr.decode('utf-8', errors='replace')[-200:])
      return main_video
    return stitched if stitched.exists() else main_video
