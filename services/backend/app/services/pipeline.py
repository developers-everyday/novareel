from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path

from app.models import GenerationJobRecord, JobStatus, StoryboardSegment, VideoResultRecord
from app.repositories.base import Repository
from app.services.effects import VideoEffectsConfig
from app.services.nova import NovaService
from app.services.storage import StorageService
from app.services.video import VideoService

logger = logging.getLogger(__name__)


def _to_srt_timestamp(value: float) -> str:
  millis = int(round(value * 1000))
  hours = millis // 3_600_000
  millis %= 3_600_000
  minutes = millis // 60_000
  millis %= 60_000
  seconds = millis // 1_000
  millis %= 1_000
  return f'{hours:02}:{minutes:02}:{seconds:02},{millis:03}'


def _build_srt(storyboard) -> str:
  rows: list[str] = []
  for segment in storyboard:
    start = _to_srt_timestamp(segment.start_sec)
    end = _to_srt_timestamp(segment.start_sec + segment.duration_sec)
    rows.append(f'{segment.order}\n{start} --> {end}\n{segment.script_line}\n')
  return '\n'.join(rows)


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
      storyboard = nova.match_images(script_lines, assets)
      storage.store_text(f'{prefix}/storyboard.json', json.dumps([s.model_dump() for s in storyboard]))
      timings['matching_sec'] = round(time.perf_counter() - phase_start, 3)

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
        audio_payload = f'MOCK-VOICE::{job.voice_provider}::{job.voice_gender}::{transcript}'.encode()
      else:
        provider = build_voice_provider(job.voice_provider, settings)
        audio_payload = provider.synthesize(transcript[:3000], voice_gender=job.voice_gender, language=job.language)

      storage.store_bytes(audio_key, audio_payload, content_type='audio/mpeg')
      timings['narration_sec'] = round(time.perf_counter() - phase_start, 3)

    transcript_url = storage.get_public_url(transcript_key)

    # Compute resolution for ASS subtitle generation and render
    ass_resolution, _ = video_service._resolution_for(job.aspect_ratio)

    # ── TRANSCRIPTION (word-level captions) ────────────────────────
    ass_subtitle_file = None
    caption_style = job.caption_style or 'none'
    if caption_style != 'none':
      from app.services.transcription import build_transcription_backend, generate_ass_subtitles

      settings = get_settings()
      backend = build_transcription_backend(
        settings.transcription_backend, settings, script_lines=script_lines,
      )
      word_timings = backend.transcribe(audio_path, language=job.language)

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

    # Build effects config for transitions and overlays
    job._project_title = project.title  # Inject for title card overlay
    effects_config = VideoEffectsConfig.from_job(job)

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
    storage.store_text(subtitle_key, _build_srt(storyboard))

    timings['rendering_sec'] = round(time.perf_counter() - phase_start, 3)

    result = VideoResultRecord(
      project_id=project.id,
      job_id=job.id,
      video_s3_key=video_key,
      video_url=storage.get_public_url(video_key),
      duration_sec=duration_sec,
      resolution=resolution,
      thumbnail_key=thumbnail_key,
      transcript_key=transcript_key,
      transcript_url=transcript_url,
      subtitle_key=subtitle_key,
      subtitle_url=storage.get_public_url(subtitle_key),
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
