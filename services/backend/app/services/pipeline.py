from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

from app.models import GenerationJobRecord, JobStatus, StoryboardSegment, VideoResultRecord
from app.repositories.base import Repository
from app.services.effects import VideoEffectsConfig
from app.services.nova import NovaService
from app.services.storage import StorageService
from app.services.subtitle_utils import build_srt
from app.services.video import VideoService

logger = logging.getLogger(__name__)


def _probe_audio_duration(audio_path: Path) -> float | None:
  """Probe the duration of an audio file using ffprobe (preferred) or ffmpeg.

  Returns the duration in seconds, or None if probing fails.
  """
  if not audio_path.exists() or audio_path.stat().st_size <= 100:
    return None

  ffprobe = shutil.which('ffprobe')
  if ffprobe:
    result = subprocess.run(
      [ffprobe, '-v', 'quiet',
       '-show_entries', 'format=duration',
       '-of', 'default=noprint_wrappers=1:nokey=1',
       str(audio_path)],
      capture_output=True, check=False,
    )
    try:
      duration = float(result.stdout.decode().strip())
      if duration > 0.5:
        return duration
    except (ValueError, TypeError):
      pass
    return None

  # Fallback: parse "Duration: HH:MM:SS.xx" from ffmpeg stderr
  ffmpeg_path = shutil.which('ffmpeg')
  if not ffmpeg_path:
    return None
  result = subprocess.run(
    [ffmpeg_path, '-i', str(audio_path), '-hide_banner'],
    capture_output=True, check=False,
  )
  m = re.search(r'Duration:\s*(\d+):(\d+):(\d[\d.]+)', result.stderr.decode(errors='replace'))
  if m:
    duration = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    if duration > 0.5:
      return duration
  return None


def _fetch_stock_footage(
  *,
  storyboard: list[StoryboardSegment],
  script_lines: list[str],
  product_description: str,
  aspect_ratio: str,
  video_style: str,
  storage: StorageService,
  project_id: str,
  job_id: str,
) -> list[StoryboardSegment]:
  """Fetch stock footage clips and interleave with product images.

  Args:
    storyboard: Original storyboard with product images
    script_lines: Script lines for search query generation
    product_description: Product description for context
    aspect_ratio: Video aspect ratio (16:9, 1:1, 9:16)
    video_style: 'product_lifestyle' or 'lifestyle_focus'
    storage: Storage service for downloading clips
    project_id: Project ID for storage paths
    job_id: Job ID for storage paths

  Returns:
    Updated storyboard with B-roll segments interleaved
  """
  from app.config import get_settings
  from app.services.stock_media import (
    StockMediaService,
    generate_search_queries,
    get_orientation_for_aspect_ratio,
  )

  settings = get_settings()

  # Check if Pexels API key is configured
  if not settings.pexels_api_key:
    logger.warning('Pexels API key not configured, falling back to product_only style')
    return storyboard

  # Initialize stock media service with cache
  cache_dir = settings.local_data_dir / 'cache' / 'pexels'
  stock_service = StockMediaService(settings.pexels_api_key, cache_dir=cache_dir)

  # Generate search queries using LLM
  if settings.use_mock_ai:
    search_queries = generate_search_queries(
      script_lines, product_description, None, '', use_mock=True,
    )
  else:
    import boto3
    bedrock_client = boto3.client('bedrock-runtime', region_name=settings.aws_region)
    search_queries = generate_search_queries(
      script_lines, product_description, bedrock_client,
      settings.bedrock_model_script, use_mock=False,
    )

  # Determine orientation from aspect ratio
  orientation = get_orientation_for_aspect_ratio(aspect_ratio)

  # Fetch and download clips
  storage_root = settings.local_data_dir / settings.local_storage_dir
  clips_dir = storage_root / 'projects' / project_id / 'clips' / job_id
  clips_dir.mkdir(parents=True, exist_ok=True)

  downloaded_clips: list[tuple[int, Path, float]] = []  # (scene_index, path, duration)

  for i, query in enumerate(search_queries):
    scene_order = i + 1  # 1-based to match storyboard segment.order
    # For product_lifestyle: alternate (every other scene gets B-roll)
    # For lifestyle_focus: most scenes get B-roll
    if video_style == 'product_lifestyle' and i % 2 == 0:
      continue  # Keep product image for even scenes
    elif video_style == 'lifestyle_focus' and i == 0:
      continue  # Keep first scene as product image

    clip_path = clips_dir / f'broll_{scene_order:03d}.mp4'
    seg_duration = storyboard[i].duration_sec if i < len(storyboard) else 5.0

    if settings.use_mock_ai:
      # Mock mode: generate a solid-color placeholder clip via ffmpeg
      # instead of making real HTTP calls to Pexels.
      _ffmpeg = shutil.which('ffmpeg')
      if _ffmpeg:
        _width, _height = ('1920', '1080') if aspect_ratio == '16:9' else (
          ('1080', '1080') if aspect_ratio == '1:1' else ('1080', '1920')
        )
        subprocess.run([
          _ffmpeg, '-y', '-f', 'lavfi',
          '-i', f'color=c=#334155:s={_width}x{_height}:d={seg_duration}',
          '-vf', 'setsar=1', '-t', str(seg_duration),
          '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p',
          '-r', '24', str(clip_path),
        ], check=False, capture_output=True)
      if clip_path.exists() and clip_path.stat().st_size > 100:
        downloaded_clips.append((scene_order, clip_path, seg_duration))
        logger.info('Mock mode: generated placeholder B-roll for scene %d', scene_order)
      else:
        logger.warning('Mock mode: failed to generate placeholder B-roll for scene %d', scene_order)
      continue

    results = stock_service.search_videos(query, orientation=orientation)
    if not results:
      logger.warning('No stock footage found for query: %s', query)
      continue

    # Pick the first result
    clip_info = results[0]

    downloaded = stock_service.download_clip(clip_info['url'], clip_path)
    if downloaded:
      downloaded_clips.append((scene_order, clip_path, min(clip_info['duration'], 5)))
    else:
      logger.warning('B-roll download failed for scene %d (query: %s)', scene_order, query)

  # Update storyboard with B-roll segments
  if not downloaded_clips:
    logger.info('No B-roll clips downloaded, keeping original storyboard')
    return storyboard

  updated_storyboard: list[StoryboardSegment] = []
  clip_map = {idx: (path, dur) for idx, path, dur in downloaded_clips}

  for segment in storyboard:
    if segment.order in clip_map:
      clip_path, clip_duration = clip_map[segment.order]
      # Replace with video segment
      updated_storyboard.append(StoryboardSegment(
        order=segment.order,
        script_line=segment.script_line,
        image_asset_id=segment.image_asset_id,  # Keep reference for fallback
        start_sec=segment.start_sec,
        duration_sec=min(segment.duration_sec, clip_duration),
        media_type='video',
        video_path=str(clip_path),
      ))
    else:
      # Keep original image segment
      updated_storyboard.append(segment)

  # B1-c: Recalculate start_sec after B-roll duration truncation may have changed durations
  running_start = 0.0
  for seg in updated_storyboard:
    seg.start_sec = round(running_start, 3)
    running_start += seg.duration_sec

  logger.info('Updated storyboard with %d B-roll clips', len(downloaded_clips))
  return updated_storyboard


def process_generation_job(
  *,
  repo: Repository,
  storage: StorageService,
  nova: NovaService,
  video_service: VideoService,
  job: GenerationJobRecord,
) -> None:
  started = time.perf_counter()
  timings: dict[str, float] = {}

  try:
    project = repo.get_project(job.project_id)
    if not project:
      raise ValueError('project_not_found')

    assets = [asset for asset in repo.list_project_assets(job.project_id) if asset.uploaded]
    if not assets:
      raise ValueError('no_uploaded_assets')

    # Intermediate artifact prefix for resumable pipeline (Feature D)
    prefix = f'projects/{project.id}/intermediate/{job.id}'

    # ── ANALYZING ──────────────────────────────────────────────────
    existing_analysis = storage.load_text(f'{prefix}/image_analysis.json')
    if existing_analysis:
      image_analysis = json.loads(existing_analysis)
      logger.info('Resuming: skipped ANALYZING (cached)')
    else:
      repo.update_job(job.id, status=JobStatus.ANALYZING, stage=JobStatus.ANALYZING, progress_pct=10)
      phase_start = time.perf_counter()
      image_analysis = nova.analyze_images(assets)
      storage.store_text(f'{prefix}/image_analysis.json', json.dumps(image_analysis))
      timings['analyzing_sec'] = round(time.perf_counter() - phase_start, 3)

    # ── SCRIPTING ──────────────────────────────────────────────────
    existing_script = storage.load_text(f'{prefix}/script_lines.json')
    if existing_script:
      script_lines = json.loads(existing_script)
      logger.info('Resuming: skipped SCRIPTING (cached)')
    else:
      repo.update_job(job.id, status=JobStatus.SCRIPTING, stage=JobStatus.SCRIPTING, progress_pct=25)
      phase_start = time.perf_counter()
      script_lines = nova.generate_script(project, image_analysis=image_analysis, language=job.language, script_template=job.script_template)
      storage.store_text(f'{prefix}/script_lines.json', json.dumps(script_lines))
      timings['scripting_sec'] = round(time.perf_counter() - phase_start, 3)

    # ── MATCHING ───────────────────────────────────────────────────
    existing_storyboard = storage.load_text(f'{prefix}/storyboard.json')
    if existing_storyboard:
      storyboard = [StoryboardSegment(**s) for s in json.loads(existing_storyboard)]
      logger.info('Resuming: skipped MATCHING (cached)')
    else:
      repo.update_job(job.id, status=JobStatus.MATCHING, stage=JobStatus.MATCHING, progress_pct=45, timings=timings)
      phase_start = time.perf_counter()
      storyboard = nova.match_images(script_lines, assets, image_analysis=image_analysis)
      storage.store_text(f'{prefix}/storyboard.json', json.dumps([s.model_dump() for s in storyboard]))
      timings['matching_sec'] = round(time.perf_counter() - phase_start, 3)

    # ── STOCK FOOTAGE (Feature C) ─────────────────────────────────
    if job.video_style and job.video_style != 'product_only':
      existing_broll = storage.load_text(f'{prefix}/storyboard_with_broll.json')
      if existing_broll:
        storyboard = [StoryboardSegment(**s) for s in json.loads(existing_broll)]
        logger.info('Resuming: skipped STOCK FOOTAGE (cached)')
      else:
        storyboard = _fetch_stock_footage(
          storyboard=storyboard,
          script_lines=script_lines,
          product_description=project.product_description,
          aspect_ratio=job.aspect_ratio,
          video_style=job.video_style,
          storage=storage,
          project_id=project.id,
          job_id=job.id,
        )
        storage.store_text(f'{prefix}/storyboard_with_broll.json', json.dumps([s.model_dump() for s in storyboard]))

    # ── Phase 3 Feature D: AWAITING_APPROVAL gate ─────────────────
    if not job.auto_approve:
      from app.services.storyboard_editor import StoryboardEditorService
      editor = StoryboardEditorService(storage)
      existing_sb = editor.load_storyboard(project.id, job.id)
      if not existing_sb:
        # First time reaching this point — save storyboard and pause
        matched_images = [{'image_key': seg.image_key} for seg in storyboard]
        sb = editor.build_storyboard_from_pipeline(job, script_lines, matched_images, storage)
        editor.save_storyboard(sb)
        repo.update_job(
          job.id,
          status=JobStatus.AWAITING_APPROVAL,
          stage=JobStatus.AWAITING_APPROVAL,
          progress_pct=50,
          timings=timings,
        )
        logger.info('Job %s paused at AWAITING_APPROVAL (auto_approve=False)', job.id)
        return
      else:
        # Resuming after approval — apply edited storyboard
        edited_lines, edited_keys = editor.apply_storyboard_to_pipeline(existing_sb)
        script_lines = edited_lines
        # Invalidate cached narration so it uses the edited script
        storage.store_text(f'{prefix}/script_lines.json', json.dumps(script_lines))
        logger.info('Resuming job %s from AWAITING_APPROVAL with edited storyboard', job.id)

    # ── NARRATION ──────────────────────────────────────────────────
    transcript = '\n'.join(script_lines)
    transcript_key = f'projects/{project.id}/outputs/{job.id}.txt'
    audio_key = f'projects/{project.id}/outputs/{job.id}.mp3'

    # Compute the local file path for the audio (used by transcription step too)
    from app.config import get_settings
    settings = get_settings()
    storage_root = settings.local_data_dir / settings.local_storage_dir
    audio_path = storage_root / audio_key

    if storage.exists(audio_key):
      logger.info('Resuming: skipped NARRATION (cached)')
    else:
      repo.update_job(job.id, status=JobStatus.NARRATION, stage=JobStatus.NARRATION, progress_pct=70, timings=timings)
      phase_start = time.perf_counter()

      storage.store_text(transcript_key, transcript)

      # Feature A: Multi-provider TTS
      from app.config import get_settings
      from app.services.voice.factory import build_voice_provider

      settings = get_settings()
      if settings.use_mock_ai:
        from app.services.voice.base import MOCK_SILENT_MP3
        audio_payload = MOCK_SILENT_MP3
      else:
        provider = build_voice_provider(job.voice_provider, settings)
        audio_payload = provider.synthesize(transcript[:3000], voice_gender=job.voice_gender, language=job.language)

      storage.store_bytes(audio_key, audio_payload, content_type='audio/mpeg')

      # If mock AI, regenerate audio as valid silence via ffmpeg so mux/music work
      # Duration matches storyboard total so audio/video stay in sync
      if settings.use_mock_ai and audio_path.exists():
        _ffmpeg = shutil.which('ffmpeg')
        if _ffmpeg:
          mock_duration = sum(s.duration_sec for s in storyboard) or 36.0
          subprocess.run([
            _ffmpeg, '-y', '-f', 'lavfi', '-i', 'anullsrc=r=44100:cl=mono',
            '-t', str(mock_duration), '-c:a', 'libmp3lame', '-q:a', '9', str(audio_path),
          ], check=False, capture_output=True)
          logger.info('Replaced mock audio with valid ffmpeg-generated silence (%.1fs)', mock_duration)

      # Phase 3 — Audio post-processing (silence trim + normalize)
      if not settings.use_mock_ai and audio_path.exists() and audio_path.stat().st_size > 100:
        from app.services.audio import AudioProcessor
        audio_proc = AudioProcessor()
        audio_proc.process(
          audio_path, audio_path,
          trim_silence=True,
          normalize=True,
          speed=1.0,
        )

      timings['narration_sec'] = round(time.perf_counter() - phase_start, 3)

    transcript_url = storage.get_public_url(transcript_key)

    # ── RECONCILE AUDIO / VIDEO DURATIONS ─────────────────────────
    # Probe real audio duration and rescale storyboard segments so
    # the video timeline matches the narration exactly.
    audio_duration = _probe_audio_duration(audio_path)
    if audio_duration:
      total_sb_duration = sum(s.duration_sec for s in storyboard)
      if total_sb_duration > 0 and abs(audio_duration - total_sb_duration) > 0.5:
        # Only stretch image segments — B-roll clips have a hard duration
        # ceiling (the source file length) and can't be extended, which would
        # cause xfade offset miscalculations if we inflated their duration.
        broll_total = sum(s.duration_sec for s in storyboard if s.media_type == 'video')
        image_total = total_sb_duration - broll_total
        stretch_budget = audio_duration - broll_total
        image_scale = stretch_budget / image_total if image_total > 0 else 1.0

        running_start = 0.0
        for seg in storyboard:
          if seg.media_type != 'video':
            seg.duration_sec = round(seg.duration_sec * image_scale, 3)
          seg.start_sec = round(running_start, 3)
          running_start += seg.duration_sec
        logger.info(
          'Reconciled storyboard duration: %.1fs → %.1fs (image_scale=%.3f, broll_fixed=%.1fs)',
          total_sb_duration, audio_duration, image_scale, broll_total,
        )

    # Compute resolution for ASS subtitle generation and render
    ass_resolution, _ = video_service._resolution_for(job.aspect_ratio)

    # ── TRANSCRIPTION (word-level captions) ────────────────────────
    ass_subtitle_file = None
    caption_style = job.caption_style or 'none'
    if caption_style != 'none':
      from app.services.transcription import build_transcription_backend, generate_ass_subtitles, WordTiming

      settings = get_settings()

      existing_timings = storage.load_text(f'{prefix}/word_timings.json')
      if existing_timings:
        word_timings = [WordTiming(**w) for w in json.loads(existing_timings)]
        logger.info('Resuming: skipped TRANSCRIPTION (cached)')
      else:
        backend = build_transcription_backend(
          settings.transcription_backend, settings, script_lines=script_lines,
        )
        word_timings = backend.transcribe(audio_path, language=job.language)
        if word_timings:
          from dataclasses import asdict
          storage.store_text(f'{prefix}/word_timings.json', json.dumps([asdict(w) for w in word_timings]))

      if word_timings:
        ass_content = generate_ass_subtitles(
          word_timings, caption_style=caption_style, resolution=ass_resolution,
        )
        ass_key = f'projects/{project.id}/outputs/{job.id}.ass'
        storage.store_text(ass_key, ass_content)

        # Write ASS to a temp file for ffmpeg
        import tempfile
        ass_subtitle_file = Path(tempfile.mktemp(suffix='.ass', prefix='novareel-'))
        ass_subtitle_file.write_text(ass_content)

    # ── RENDERING (always re-run) ─────────────────────────────────
    repo.update_job(job.id, status=JobStatus.RENDERING, stage=JobStatus.RENDERING, progress_pct=90, timings=timings)
    phase_start = time.perf_counter()

    # Feature B: Background music
    from app.services.music import select_music_path
    music_path = select_music_path(job.background_music, job.voice_style)

    # Phase 3 — Resolve brand kit and build effects config
    from app.services.brand import BrandService
    brand_service = BrandService(settings, storage)
    brand_kit = brand_service.resolve_brand_kit(project.owner_id, repo)

    # If brand kit has custom music and job uses 'auto', prefer brand music
    if brand_kit and brand_kit.custom_music_paths and job.background_music == 'auto':
      music_path = brand_kit.custom_music_paths[0]

    job._project_title = project.title  # Inject for title card overlay
    effects_config = brand_service.build_effects_config(brand_kit, job)

    output_key = f'projects/{project.id}/outputs/{job.id}.mp4'
    thumbnail_key_path = f'projects/{project.id}/outputs/{job.id}.jpg'

    if settings.use_editing_framework:
      # Phase 4 — render via EditingPlan (deterministic or LLM-generated)
      from app.services.editing.llm_planner import generate_plan_with_llm
      import boto3
      bedrock_client = None if settings.use_mock_ai else boto3.client('bedrock-runtime', region_name=settings.aws_region)
      editing_plan = generate_plan_with_llm(
        product_description=project.product_description,
        storyboard=storyboard,
        effects_config=effects_config,
        aspect_ratio=job.aspect_ratio,
        audio_path=audio_path,
        music_path=music_path,
        ass_subtitle_path=ass_subtitle_file,
        ffmpeg_preset=settings.ffmpeg_preset,
        project_id=project.id,
        resolve_asset_fn=video_service._resolve_asset_path,
        bedrock_client=bedrock_client,
        bedrock_model=settings.bedrock_model_script,
        use_mock=settings.use_mock_ai,
      )
      # Persist the plan JSON for debugging / API inspection
      storage.store_text(f'{prefix}/editing_plan.json', editing_plan.to_json())
      video_key, duration_sec, resolution, thumbnail_key = video_service.render_from_plan(
        plan=editing_plan,
        storage=storage,
        output_key=output_key,
        thumbnail_key=thumbnail_key_path,
      )
    else:
      video_key, duration_sec, resolution, thumbnail_key = video_service.render_video(
        project=project,
        job_id=job.id,
        aspect_ratio=job.aspect_ratio,
        storyboard=storyboard,
        storage=storage,
        music_path=music_path,
        effects_config=effects_config,
        ass_subtitle_path=ass_subtitle_file,
      )

    # Cleanup temp ASS file
    if ass_subtitle_file and ass_subtitle_file.exists():
      ass_subtitle_file.unlink(missing_ok=True)
    subtitle_key = f'projects/{project.id}/outputs/{job.id}.srt'
    storage.store_text(subtitle_key, build_srt(storyboard))

    timings['rendering_sec'] = round(time.perf_counter() - phase_start, 3)

    # Phase 3 Feature F — CDN URL support
    def _public_url(key: str) -> str:
      if settings.cdn_base_url:
        return f'{settings.cdn_base_url.rstrip("/")}/{key}'
      return storage.get_public_url(key)

    result = VideoResultRecord(
      project_id=project.id,
      job_id=job.id,
      video_s3_key=video_key,
      video_url=_public_url(video_key),
      duration_sec=duration_sec,
      resolution=resolution,
      thumbnail_key=thumbnail_key,
      transcript_key=transcript_key,
      transcript_url=_public_url(transcript_key),
      subtitle_key=subtitle_key,
      subtitle_url=_public_url(subtitle_key),
      storyboard=storyboard,
      script_lines=script_lines,
      language=job.language,
      completed_at=datetime.now(UTC),
    )

    repo.set_result(project.id, job.id, result)
    month = datetime.now(UTC).strftime('%Y-%m')
    repo.increment_usage(project.owner_id, month)
    repo.record_analytics_event(
      owner_id=project.owner_id,
      event_name='generation_completed',
      project_id=project.id,
      job_id=job.id,
      properties={
        'duration_sec': duration_sec,
        'resolution': resolution,
      },
    )

    # Feature D: Cleanup intermediate artifacts on success
    storage.delete_prefix(f'{prefix}/')

    timings['total_sec'] = round(time.perf_counter() - started, 3)
    repo.update_job(
      job.id,
      status=JobStatus.COMPLETED,
      stage=JobStatus.COMPLETED,
      progress_pct=100,
      timings=timings,
      error_code=None,
    )
  except Exception as exc:  # pragma: no cover - exercised in error flows
    logger.exception('Job %s failed', job.id)
    # Clean up intermediate artifacts from failed attempt
    try:
      storage.delete_prefix(f'{prefix}/')
    except Exception:
      pass  # Don't mask the original error
    project = repo.get_project(job.project_id)
    if project:
      repo.record_analytics_event(
        owner_id=project.owner_id,
        event_name='generation_failed',
        project_id=project.id,
        job_id=job.id,
        properties={'error_code': str(exc)[:160]},
      )
    repo.update_job(
      job.id,
      status=JobStatus.FAILED,
      stage=JobStatus.FAILED,
      progress_pct=100,
      error_code=str(exc)[:160],
      timings={'total_sec': round(time.perf_counter() - started, 3)},
    )
