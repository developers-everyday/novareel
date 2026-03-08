from __future__ import annotations

import logging
import time
from datetime import UTC, datetime

from app.models import GenerationJobRecord, JobStatus, VideoResultRecord
from app.repositories.base import Repository
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

    repo.update_job(job.id, status=JobStatus.SCRIPTING, stage=JobStatus.SCRIPTING, progress_pct=20)
    phase_start = time.perf_counter()
    script_lines = nova.generate_script(project)
    timings['scripting_sec'] = round(time.perf_counter() - phase_start, 3)

    repo.update_job(
      job.id,
      status=JobStatus.MATCHING,
      stage=JobStatus.MATCHING,
      progress_pct=45,
      timings=timings,
    )
    phase_start = time.perf_counter()
    storyboard = nova.match_images(script_lines, assets)
    timings['matching_sec'] = round(time.perf_counter() - phase_start, 3)

    repo.update_job(
      job.id,
      status=JobStatus.NARRATION,
      stage=JobStatus.NARRATION,
      progress_pct=70,
      timings=timings,
    )
    phase_start = time.perf_counter()
    transcript = '\n'.join(script_lines)
    transcript_key = f'projects/{project.id}/outputs/{job.id}.txt'
    storage.store_text(transcript_key, transcript)
    transcript_url = storage.get_public_url(transcript_key)

    audio_key = f'projects/{project.id}/outputs/{job.id}.mp3'
    audio_payload = nova.synthesize_voice(script_lines, job.voice_style)
    storage.store_bytes(audio_key, audio_payload, content_type='audio/mpeg')
    timings['narration_sec'] = round(time.perf_counter() - phase_start, 3)

    repo.update_job(
      job.id,
      status=JobStatus.RENDERING,
      stage=JobStatus.RENDERING,
      progress_pct=90,
      timings=timings,
    )
    phase_start = time.perf_counter()

    video_key, duration_sec, resolution, thumbnail_key = video_service.render_video(
      project=project,
      job_id=job.id,
      aspect_ratio=job.aspect_ratio,
      storyboard=storyboard,
      storage=storage,
    )
    subtitle_key = f'projects/{project.id}/outputs/{job.id}.srt'
    storage.store_text(subtitle_key, _build_srt(storyboard))

    timings['rendering_sec'] = round(time.perf_counter() - phase_start, 3)

    result = VideoResultRecord(
      project_id=project.id,
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
      completed_at=datetime.now(UTC),
    )

    repo.set_result(project.id, result)
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
