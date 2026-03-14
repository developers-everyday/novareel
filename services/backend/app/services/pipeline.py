from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

from app.models import GenerationJobRecord, JobStatus, ScriptScene, StoryboardSegment, VideoResultRecord
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


def _select_cleanest_image(image_analysis: list[dict]) -> str | None:
  """Pick the product image with the least text/branding from analysis.

  Scans image_analysis descriptions for keywords that indicate overlaid text,
  logos, or branding.  Returns the asset_id of the image whose description
  contains the fewest such indicators — i.e. the "cleanest" product shot
  best suited as a reference for Nova Canvas.
  """
  if not image_analysis:
    return None

  text_indicators = [
    'text', 'logo', 'label', 'branding', 'watermark', 'lettering',
    'typography', 'caption', 'tagline', 'slogan', 'brand name',
  ]

  scored: list[tuple[int, str]] = []
  for info in image_analysis:
    desc = (info.get('description') or '').lower()
    penalty = sum(1 for kw in text_indicators if kw in desc)
    scored.append((penalty, info['asset_id']))

  scored.sort(key=lambda x: x[0])
  return scored[0][1] if scored else None


def _fetch_stock_footage(
  *,
  storyboard: list[StoryboardSegment],
  script_lines: list[str],
  script_scenes: list[ScriptScene] | None = None,
  product_description: str,
  image_analysis: list[dict] | None = None,
  aspect_ratio: str,
  video_style: str,
  storage: StorageService,
  project_id: str,
  job_id: str,
) -> list[StoryboardSegment]:
  """Fetch stock footage clips and interleave with product images.

  When the Vision Director is enabled, it plans per-scene media decisions
  (product_closeup / broll / product_in_context), generates targeted search
  queries, and validates downloaded clips for relevance.

  Args:
    storyboard: Original storyboard with product images
    script_lines: Script lines for search query generation
    script_scenes: ScriptScene list with visual_requirements (used by Vision Director)
    product_description: Product description for context
    image_analysis: Image analysis results from the ANALYZING stage
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

  # Determine orientation from aspect ratio
  orientation = get_orientation_for_aspect_ratio(aspect_ratio)

  # Fetch and download clips
  storage_root = settings.local_data_dir / settings.local_storage_dir
  clips_dir = storage_root / 'projects' / project_id / 'clips' / job_id
  clips_dir.mkdir(parents=True, exist_ok=True)

  # ── Vision Director path ─────────────────────────────────────────
  if settings.use_vision_director and script_scenes:
    return _fetch_stock_footage_with_director(
      storyboard=storyboard,
      script_scenes=script_scenes,
      product_description=product_description,
      image_analysis=image_analysis,
      aspect_ratio=aspect_ratio,
      video_style=video_style,
      stock_service=stock_service,
      orientation=orientation,
      clips_dir=clips_dir,
      settings=settings,
      project_id=project_id,
    )

  # ── Legacy path (fallback) ──────────────────────────────────────
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


def _fetch_stock_footage_with_director(
  *,
  storyboard: list[StoryboardSegment],
  script_scenes: list[ScriptScene],
  product_description: str,
  image_analysis: list[dict] | None,
  aspect_ratio: str,
  video_style: str,
  stock_service: 'StockMediaService',
  orientation: str,
  clips_dir: Path,
  settings: 'Settings',
  project_id: str = '',
) -> list[StoryboardSegment]:
  """Vision Director path: plan, fetch, and validate B-roll clips."""
  from app.services.broll_director import BRollDirector

  director = BRollDirector(settings)

  # Step 1: Plan — let Nova Vision decide per-scene media type + queries
  scene_plan = director.plan_scenes(
    script_scenes=script_scenes,
    image_analysis=image_analysis or [],
    product_description=product_description,
    video_style=video_style,
  )

  downloaded_clips: dict[int, tuple[Path, float, str, float | None, bool]] = {}
  # Maps scene_order -> (clip_path, duration, query, relevance_score, is_ai_generated)

  for i, plan_entry in enumerate(scene_plan):
    if i >= len(storyboard):
      break

    scene_order = i + 1
    media_decision = plan_entry.get('media_type', 'product_closeup')

    if media_decision == 'product_closeup':
      # Keep the product image — optionally update focal_region from director
      if plan_entry.get('focal_override'):
        fo = plan_entry['focal_override']
        from app.models import FocalRegion
        storyboard[i].focal_region = FocalRegion(
          cx=fo.get('cx', 0.5), cy=fo.get('cy', 0.5),
          w=fo.get('w', 0.4), h=fo.get('h', 0.6),
        )
      continue

    if media_decision == 'product_in_context':
      # Keep product image but with different framing suggested by director
      if plan_entry.get('focal_override'):
        fo = plan_entry['focal_override']
        from app.models import FocalRegion
        storyboard[i].focal_region = FocalRegion(
          cx=fo.get('cx', 0.5), cy=fo.get('cy', 0.5),
          w=fo.get('w', 0.6), h=fo.get('h', 0.8),
        )
      continue

    if media_decision == 'ai_generated':
      # Generate a contextual image using Nova Canvas
      from app.services.image_generator import ImageGenerator
      from app.services.video import VideoService

      image_prompt = plan_entry.get('image_prompt', 'Product in a lifestyle setting')
      visual_req = script_scenes[i].visual_requirements if i < len(script_scenes) else ''
      gen_image_path = clips_dir / f'ai_gen_{scene_order:03d}.jpg'
      clip_path = clips_dir / f'ai_gen_{scene_order:03d}.mp4'
      seg_duration = storyboard[i].duration_sec

      # Pick the cleanest product image (least text/branding) as reference
      # for Nova Canvas, rather than defaulting to the segment's assigned image.
      product_img_path = None
      video_svc = VideoService(settings)
      if image_analysis and project_id:
        best_asset_id = _select_cleanest_image(image_analysis)
        if best_asset_id:
          product_img_path = video_svc._resolve_asset_path(best_asset_id, project_id)

      # Fallback to the segment's assigned image
      if product_img_path is None and storyboard[i].image_asset_id and project_id:
        product_img_path = video_svc._resolve_asset_path(
          storyboard[i].image_asset_id, project_id,
        )

      img_gen = ImageGenerator(settings)
      generated = img_gen.generate_scene_image(
        product_image_path=product_img_path,
        scene_description=image_prompt,
        visual_requirements=visual_req,
        product_description=product_description,
        output_path=gen_image_path,
        aspect_ratio=aspect_ratio,
      )

      if generated:
        # Convert the generated image into a video segment
        video_seg = img_gen.generate_scene_video_from_image(
          image_path=gen_image_path,
          duration_sec=seg_duration,
          output_path=clip_path,
          aspect_ratio=aspect_ratio,
        )
        if video_seg:
          downloaded_clips[scene_order] = (clip_path, seg_duration, f'[ai] {image_prompt[:50]}', 10.0, True)
          logger.info('Scene %d: AI-generated image → video (prompt: %s)', scene_order, image_prompt[:60])
          continue

      logger.warning('Scene %d: AI image generation failed, keeping product image', scene_order)
      continue

    # media_decision == 'broll'
    query = plan_entry.get('search_query', 'lifestyle product usage')
    clip_path = clips_dir / f'broll_{scene_order:03d}.mp4'
    seg_duration = storyboard[i].duration_sec

    if settings.use_mock_ai:
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
        downloaded_clips[scene_order] = (clip_path, seg_duration, query, 10.0, False)
        logger.info('Mock mode: generated placeholder B-roll for scene %d (query: %s)', scene_order, query)
      continue

    # Fetch candidates from Pexels and validate with Vision
    results = stock_service.search_videos(query, orientation=orientation)
    if not results:
      logger.warning('No stock footage found for query: %s (scene %d)', query, scene_order)
      continue

    acceptance_criteria = plan_entry.get('acceptance_criteria', '')
    max_candidates = settings.broll_max_candidates
    best_clip = None
    best_score = 0.0

    for candidate in results[:max_candidates]:
      temp_clip = clips_dir / f'broll_{scene_order:03d}_candidate.mp4'
      downloaded = stock_service.download_clip(candidate['url'], temp_clip)
      if not downloaded:
        continue

      # Validate with Vision Director
      score = director.validate_clip(
        clip_path=temp_clip,
        scene_narration=script_scenes[i].narration if i < len(script_scenes) else '',
        visual_requirements=script_scenes[i].visual_requirements if i < len(script_scenes) else '',
        acceptance_criteria=acceptance_criteria,
      )

      if score >= settings.broll_validation_threshold:
        # Move candidate to final path
        if temp_clip != clip_path:
          shutil.move(str(temp_clip), str(clip_path))
        best_clip = clip_path
        best_score = score
        logger.info('Scene %d: accepted B-roll (query=%s, score=%.1f)', scene_order, query, score)
        break
      elif score > best_score:
        best_score = score
        best_clip = temp_clip

      # Cleanup rejected candidate
      if temp_clip.exists() and temp_clip != clip_path:
        temp_clip.unlink(missing_ok=True)

    if best_clip and best_score >= settings.broll_validation_threshold:
      if best_clip != clip_path and best_clip.exists():
        shutil.move(str(best_clip), str(clip_path))
      downloaded_clips[scene_order] = (
        clip_path, min(results[0]['duration'], seg_duration), query, best_score, False,
      )
    else:
      logger.warning('Scene %d: all candidates rejected (best_score=%.1f, threshold=%.1f), keeping product image',
                      scene_order, best_score, settings.broll_validation_threshold)

  # Build updated storyboard
  if not downloaded_clips:
    logger.info('Vision Director: no B-roll clips passed validation, keeping original storyboard')
    return storyboard

  updated_storyboard: list[StoryboardSegment] = []
  for segment in storyboard:
    if segment.order in downloaded_clips:
      clip_path, clip_duration, query, score, ai_gen = downloaded_clips[segment.order]
      updated_storyboard.append(StoryboardSegment(
        order=segment.order,
        script_line=segment.script_line,
        image_asset_id=segment.image_asset_id,
        start_sec=segment.start_sec,
        duration_sec=min(segment.duration_sec, clip_duration),
        media_type='video',
        video_path=str(clip_path),
        focal_region=segment.focal_region,
        visual_requirements=segment.visual_requirements,
        broll_query=query,
        broll_relevance_score=score,
        is_ai_generated=ai_gen,
      ))
    else:
      updated_storyboard.append(segment)

  # Recalculate start_sec
  running_start = 0.0
  for seg in updated_storyboard:
    seg.start_sec = round(running_start, 3)
    running_start += seg.duration_sec

  accepted = len(downloaded_clips)
  logger.info('Vision Director: updated storyboard with %d validated B-roll clips', accepted)
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

    # Ensure all uploaded assets are available on local disk before pipeline starts.
    # In production (S3 backend) assets are stored in S3 and must be downloaded first.
    from app.config import get_settings as _get_settings
    _settings = _get_settings()
    _storage_root = _settings.local_data_dir / _settings.local_storage_dir
    for _asset in assets:
      _local_path = _storage_root / _asset.object_key
      if not _local_path.exists():
        ok = storage.download_to_path(_asset.object_key, _local_path)
        if ok:
          logger.info('Downloaded asset from storage: %s', _asset.object_key)
        else:
          logger.warning('Failed to download asset from storage: %s', _asset.object_key)

    # Intermediate artifact prefix for resumable pipeline (Feature D)
    prefix = f'projects/{project.id}/intermediate/{job.id}'

    # ── AGENTIC ORCHESTRATOR (Nova Pro) ────────────────────────────
    # When enabled, Nova Pro orchestrates ANALYZING → SCRIPTING → MATCHING → MEDIA
    # as a single intelligent loop, replacing the linear sequence below.
    from app.config import get_settings
    settings = get_settings()

    if settings.use_agentic_orchestrator:
      existing_orchestrator = storage.load_text(f'{prefix}/orchestrator_result.json')
      if existing_orchestrator:
        orch_data = json.loads(existing_orchestrator)
        image_analysis = orch_data.get('image_analysis', [])
        script_scenes = [ScriptScene(**s) for s in orch_data.get('script_scenes', [])]
        script_lines = orch_data.get('script_lines', [])
        storyboard = [StoryboardSegment(**s) for s in orch_data.get('storyboard', [])]
        if orch_data.get('review_notes'):
          repo.update_job(job.id, review_notes=orch_data['review_notes'])
        logger.info('Resuming: skipped ORCHESTRATOR (cached)')
      else:
        repo.update_job(job.id, status=JobStatus.ANALYZING, stage=JobStatus.ANALYZING, progress_pct=10)

        from app.services.orchestrator import PipelineOrchestrator
        storage_root = settings.local_data_dir / settings.local_storage_dir
        clips_dir = storage_root / 'projects' / project.id / 'clips' / job.id
        clips_dir.mkdir(parents=True, exist_ok=True)

        phase_start = time.perf_counter()
        orchestrator = PipelineOrchestrator(
          settings=settings, nova=nova, storage=storage, repo=repo,
        )
        orch_result = orchestrator.run(
          project=project, job=job, assets=assets, clips_dir=clips_dir,
        )
        timings['orchestrator_sec'] = round(time.perf_counter() - phase_start, 3)

        image_analysis = orch_result.image_analysis
        script_scenes = orch_result.script_scenes
        script_lines = orch_result.script_lines
        storyboard = orch_result.storyboard

        if orch_result.review_notes:
          repo.update_job(job.id, review_notes=orch_result.review_notes)

        # Persist all orchestrator artifacts for resume
        storage.store_text(f'{prefix}/image_analysis.json', json.dumps(image_analysis))
        storage.store_text(f'{prefix}/script_lines.json', json.dumps(script_lines))
        storage.store_text(f'{prefix}/script_scenes.json', json.dumps([s.model_dump() for s in script_scenes]))
        storage.store_text(f'{prefix}/storyboard.json', json.dumps([s.model_dump() for s in storyboard]))
        storage.store_text(f'{prefix}/orchestrator_result.json', json.dumps({
          'image_analysis': image_analysis,
          'script_scenes': [s.model_dump() for s in script_scenes],
          'script_lines': script_lines,
          'storyboard': [s.model_dump() for s in storyboard],
          'review_notes': orch_result.review_notes,
          'summary': orch_result.summary,
          'audio_duration': orch_result.audio_duration,
          'audio_key': orch_result.audio_key,
          'per_scene_duration': orch_result.per_scene_duration,
        }))
        logger.info('Orchestrator complete: %d scenes, %d storyboard segments (%.1fs)',
                     len(script_scenes), len(storyboard), timings.get('orchestrator_sec', 0))

    else:
      # ── LINEAR PIPELINE (legacy fallback) ──────────────────────────

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
      existing_scenes = storage.load_text(f'{prefix}/script_scenes.json')
      if existing_script:
        script_lines = json.loads(existing_script)
        if existing_scenes:
          script_scenes = [ScriptScene(**s) for s in json.loads(existing_scenes)]
        else:
          script_scenes = [ScriptScene(narration=line) for line in script_lines]
        logger.info('Resuming: skipped SCRIPTING (cached)')
      else:
        repo.update_job(job.id, status=JobStatus.SCRIPTING, stage=JobStatus.SCRIPTING, progress_pct=25)
        phase_start = time.perf_counter()
        script_scenes = nova.generate_script(project, image_analysis=image_analysis, language=job.language, script_template=job.script_template)
        script_lines = [s.narration for s in script_scenes]
        storage.store_text(f'{prefix}/script_lines.json', json.dumps(script_lines))
        storage.store_text(f'{prefix}/script_scenes.json', json.dumps([s.model_dump() for s in script_scenes]))
        timings['scripting_sec'] = round(time.perf_counter() - phase_start, 3)

      # ── EARLY NARRATION (audio-first) ──────────────────────────────
      # Generate TTS before matching so we know the real audio duration.
      # The later NARRATION section will skip via storage.exists() check.
      from app.config import get_settings as _get_settings
      _settings = _get_settings()
      _audio_key = f'projects/{project.id}/outputs/{job.id}.mp3'
      _storage_root = _settings.local_data_dir / _settings.local_storage_dir
      _audio_path = _storage_root / _audio_key
      _per_scene_duration: float | None = None

      if not storage.exists(_audio_key):
        repo.update_job(job.id, status=JobStatus.NARRATION, stage=JobStatus.NARRATION, progress_pct=40, timings=timings)
        phase_start = time.perf_counter()
        _transcript = '\n'.join(script_lines)
        storage.store_text(f'projects/{project.id}/outputs/{job.id}.txt', _transcript)

        if _settings.use_mock_ai:
          from app.services.voice.base import MOCK_SILENT_MP3
          storage.store_bytes(_audio_key, MOCK_SILENT_MP3, content_type='audio/mpeg')
          _ffmpeg = shutil.which('ffmpeg')
          if _ffmpeg and _audio_path.exists():
            _mock_dur = max(6.0 * len(script_lines), 36.0)
            subprocess.run([
              _ffmpeg, '-y', '-f', 'lavfi', '-i', 'anullsrc=r=44100:cl=mono',
              '-t', str(_mock_dur), '-c:a', 'libmp3lame', '-q:a', '9', str(_audio_path),
            ], check=False, capture_output=True)
        else:
          from app.services.voice.factory import build_voice_provider
          _provider = build_voice_provider(job.voice_provider, _settings)
          _audio_payload = _provider.synthesize(_transcript[:3000], voice_gender=job.voice_gender, language=job.language)
          storage.store_bytes(_audio_key, _audio_payload, content_type='audio/mpeg')
          if _audio_path.exists() and _audio_path.stat().st_size > 100:
            from app.services.audio import AudioProcessor
            AudioProcessor().process(_audio_path, _audio_path, trim_silence=True, normalize=True, speed=1.0)

        timings['narration_sec'] = round(time.perf_counter() - phase_start, 3)

      _audio_dur = _probe_audio_duration(_audio_path)
      if _audio_dur and _audio_dur > 0:
        _num = max(len(script_lines), 1)
        _per_scene_duration = round(_audio_dur / _num, 3)
        logger.info('Audio-first: %.1fs total, %.2fs per scene (%d scenes)', _audio_dur, _per_scene_duration, _num)

      # ── MATCHING ───────────────────────────────────────────────────
      existing_storyboard = storage.load_text(f'{prefix}/storyboard.json')
      if existing_storyboard:
        storyboard = [StoryboardSegment(**s) for s in json.loads(existing_storyboard)]
        logger.info('Resuming: skipped MATCHING (cached)')
      else:
        repo.update_job(job.id, status=JobStatus.MATCHING, stage=JobStatus.MATCHING, progress_pct=50, timings=timings)
        phase_start = time.perf_counter()
        storyboard = nova.match_images(script_lines, assets, image_analysis=image_analysis, segment_length=_per_scene_duration)
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
            script_scenes=script_scenes,
            product_description=project.product_description,
            image_analysis=image_analysis,
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
        # Only stretch image segments and AI-generated segments — real B-roll
        # clips (from Pexels) have a hard duration ceiling (the source file
        # length) and can't be extended.  AI-generated segments are rendered
        # from still images and CAN be stretched.
        def _is_fixed_duration(s: StoryboardSegment) -> bool:
          return s.media_type == 'video' and not s.is_ai_generated

        fixed_total = sum(s.duration_sec for s in storyboard if _is_fixed_duration(s))
        stretchable_total = total_sb_duration - fixed_total
        stretch_budget = audio_duration - fixed_total
        stretch_scale = stretch_budget / stretchable_total if stretchable_total > 0 else 1.0

        running_start = 0.0
        for seg in storyboard:
          if not _is_fixed_duration(seg):
            seg.duration_sec = round(seg.duration_sec * stretch_scale, 3)
          seg.start_sec = round(running_start, 3)
          running_start += seg.duration_sec
        logger.info(
          'Reconciled storyboard duration: %.1fs → %.1fs (stretch_scale=%.3f, fixed=%.1fs)',
          total_sb_duration, audio_duration, stretch_scale, fixed_total,
        )

      # Safety net: if total is still shorter than audio (e.g. rounding or
      # all segments are fixed-duration B-roll), extend the last segment.
      final_sb_duration = sum(s.duration_sec for s in storyboard)
      if audio_duration and final_sb_duration < audio_duration - 0.1 and storyboard:
        gap = round(audio_duration - final_sb_duration + 0.05, 3)
        storyboard[-1].duration_sec = round(storyboard[-1].duration_sec + gap, 3)
        # Recalculate start_sec for the last segment
        if len(storyboard) > 1:
          storyboard[-1].start_sec = round(
            sum(s.duration_sec for s in storyboard[:-1]), 3,
          )
        logger.info(
          'Safety-net: extended last segment by %.1fs to cover audio (%.1fs → %.1fs)',
          gap, final_sb_duration, sum(s.duration_sec for s in storyboard),
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

    # In S3 mode, audio was stored in S3 — download for local ffmpeg rendering.
    if not audio_path.exists():
      ok = storage.download_to_path(audio_key, audio_path)
      if ok:
        logger.info('Downloaded audio from storage: %s', audio_key)
      else:
        logger.warning('Failed to download audio from storage: %s', audio_key)

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
