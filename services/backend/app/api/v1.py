from __future__ import annotations

import logging
from datetime import UTC, datetime

logger = logging.getLogger('novareel.api')

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.auth import AuthUser, get_current_user
from app.config import Settings, get_settings
from app.dependencies import get_nova_service, get_queue, get_repository, get_storage, get_translation_service, get_video_service
from app.models import (
  AdminOverview,
  AnalyticsEventRecord,
  AnalyticsEventRequest,
  AssetUploadRequest,
  GenerateRequest,
  GenerationJobRecord,
  JobCreateParams,
  JobStatus,
  ProjectCreateRequest,
  ProjectRecord,
  TranslateRequest,
  UsageSummary,
  VideoResultRecord,
)
from app.queue.base import JobQueue
from app.repositories.base import Repository
from app.services.nova import NovaService
from app.services.storage import StorageService
from app.services.video import VideoService

router = APIRouter(prefix='/v1', tags=['v1'])


def _require_owner(record_owner: str, current_user: AuthUser) -> None:
  if record_owner != current_user.user_id:
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Forbidden')


@router.post('/projects', response_model=ProjectRecord, status_code=status.HTTP_201_CREATED)
def create_project(
  payload: ProjectCreateRequest,
  current_user: AuthUser = Depends(get_current_user),
  repo: Repository = Depends(get_repository),
) -> ProjectRecord:
  project = repo.create_project(current_user.user_id, payload)
  repo.record_analytics_event(
    owner_id=current_user.user_id,
    event_name='project_created',
    project_id=project.id,
    properties={'title': payload.title},
  )
  return project


@router.get('/projects', response_model=list[ProjectRecord])
def list_projects(
  current_user: AuthUser = Depends(get_current_user),
  repo: Repository = Depends(get_repository),
) -> list[ProjectRecord]:
  return repo.list_projects(owner_id=current_user.user_id, limit=50)


@router.post('/projects/{project_id}/assets:upload-url', status_code=status.HTTP_201_CREATED)
def create_asset_upload_url(
  project_id: str,
  payload: AssetUploadRequest,
  current_user: AuthUser = Depends(get_current_user),
  repo: Repository = Depends(get_repository),
  storage: StorageService = Depends(get_storage),
  settings: Settings = Depends(get_settings),
):
  project = repo.get_project(project_id)
  if not project:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Project not found')

  _require_owner(project.owner_id, current_user)
  existing_assets = repo.list_project_assets(project_id)
  if len(existing_assets) >= settings.max_assets_per_project:
    raise HTTPException(
      status_code=status.HTTP_409_CONFLICT,
      detail=f'Max assets per project reached ({settings.max_assets_per_project})',
    )

  if payload.file_size > settings.max_asset_file_size_bytes:
    raise HTTPException(
      status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
      detail=f'File exceeds max size of {settings.max_asset_file_size_bytes} bytes',
    )

  if payload.content_type not in settings.allowed_asset_content_types:
    raise HTTPException(
      status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
      detail=f'Unsupported content type: {payload.content_type}',
    )

  asset = repo.create_asset(
    project_id=project_id,
    owner_id=current_user.user_id,
    filename=payload.filename,
    content_type=payload.content_type,
    file_size=payload.file_size,
  )
  return storage.create_upload_url(asset)


@router.put('/projects/{project_id}/assets/{asset_id}:upload')
async def upload_asset_bytes(
  project_id: str,
  asset_id: str,
  request: Request,
  current_user: AuthUser = Depends(get_current_user),
  repo: Repository = Depends(get_repository),
  storage: StorageService = Depends(get_storage),
  settings: Settings = Depends(get_settings),
):
  project = repo.get_project(project_id)
  if not project:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Project not found')

  _require_owner(project.owner_id, current_user)

  asset = repo.get_asset(asset_id)
  if not asset or asset.project_id != project_id:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Asset not found')

  payload = await request.body()
  if not payload:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Empty upload payload')
  if len(payload) > settings.max_asset_file_size_bytes:
    raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail='Upload payload too large')
  if not asset.content_type.startswith('image/'):
    raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail='Only image uploads are supported')

  storage.save_local_upload(asset, payload)
  updated = repo.mark_asset_uploaded(asset_id)
  repo.record_analytics_event(
    owner_id=current_user.user_id,
    event_name='asset_uploaded',
    project_id=project_id,
    properties={'asset_id': updated.id, 'file_size': asset.file_size},
  )
  return {'asset_id': updated.id, 'uploaded': updated.uploaded}


@router.post('/projects/{project_id}/generate', response_model=GenerationJobRecord, status_code=status.HTTP_202_ACCEPTED)
def enqueue_generation(
  project_id: str,
  payload: GenerateRequest,
  current_user: AuthUser = Depends(get_current_user),
  repo: Repository = Depends(get_repository),
  queue: JobQueue = Depends(get_queue),
  settings: Settings = Depends(get_settings),
) -> GenerationJobRecord:
  project = repo.get_project(project_id)
  if not project:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Project not found')

  _require_owner(project.owner_id, current_user)
  uploaded_assets = [asset for asset in repo.list_project_assets(project_id) if asset.uploaded]
  if not uploaded_assets:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Upload at least one asset before generation')

  month = datetime.now(UTC).strftime('%Y-%m')
  usage = repo.get_usage(current_user.user_id, month, quota_limit=settings.monthly_video_quota)
  exempt_set = {e.lower() for e in settings.quota_exempt_emails}
  is_exempt = (
    current_user.email.lower() in exempt_set
    or current_user.user_id in settings.quota_exempt_emails
  )
  logger.warning('quota check user_id=%s email=%r is_exempt=%s used=%s limit=%s',
               current_user.user_id, current_user.email, is_exempt,
               usage.videos_generated, settings.monthly_video_quota)
  if not is_exempt and usage.videos_generated >= settings.monthly_video_quota:
    raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail='Monthly quota exceeded')

  # Validate Pexels API key for stock footage styles
  if payload.video_style and payload.video_style != 'product_only':
    if not settings.pexels_api_key:
      raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=f"Stock footage style '{payload.video_style}' requires Pexels API key. Configure NOVAREEL_PEXELS_API_KEY or use 'product_only' style.",
      )

  from app.config.languages import SUPPORTED_LANGUAGES
  if payload.language not in SUPPORTED_LANGUAGES:
    raise HTTPException(
      status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
      detail=f'Unsupported language: {payload.language}. Supported: {", ".join(sorted(SUPPORTED_LANGUAGES.keys()))}',
    )

  if payload.idempotency_key:
    existing_job = repo.find_job_by_idempotency(
      owner_id=current_user.user_id,
      project_id=project_id,
      idempotency_key=payload.idempotency_key,
    )
    if existing_job:
      repo.record_analytics_event(
        owner_id=current_user.user_id,
        event_name='generation_deduplicated',
        project_id=project_id,
        job_id=existing_job.id,
        properties={'idempotency_key': payload.idempotency_key},
      )
      return existing_job

  params = JobCreateParams(
    aspect_ratio=payload.aspect_ratio,
    voice_style=payload.voice_style,
    voice_provider=payload.voice_provider,
    voice_gender=payload.voice_gender,
    language=payload.language,
    background_music=payload.background_music,
    idempotency_key=payload.idempotency_key,
    max_attempts=settings.worker_max_attempts,
    script_template=payload.script_template,
    video_style=payload.video_style,
    transition_style=payload.transition_style,
    caption_style=payload.caption_style,
    show_title_card=payload.show_title_card,
    cta_text=payload.cta_text,
  )
  queued_job = repo.create_job(
    project_id=project_id,
    owner_id=current_user.user_id,
    params=params,
  )
  queue.enqueue(queued_job.id)
  repo.record_analytics_event(
    owner_id=current_user.user_id,
    event_name='generation_requested',
    project_id=project_id,
    job_id=queued_job.id,
    properties={
      'aspect_ratio': payload.aspect_ratio,
      'voice_style': payload.voice_style,
      'voice_provider': payload.voice_provider,
      'language': payload.language,
    },
  )
  return queued_job


@router.get('/projects/{project_id}/jobs', response_model=list[GenerationJobRecord])
def list_project_jobs(
  project_id: str,
  current_user: AuthUser = Depends(get_current_user),
  repo: Repository = Depends(get_repository),
) -> list[GenerationJobRecord]:
  project = repo.get_project(project_id)
  if not project:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Project not found')
  _require_owner(project.owner_id, current_user)
  jobs = repo.list_jobs_for_project(project_id)
  return [job for job in jobs if job.owner_id == current_user.user_id]


@router.get('/jobs/{job_id}', response_model=GenerationJobRecord)
def get_job_status(
  job_id: str,
  current_user: AuthUser = Depends(get_current_user),
  repo: Repository = Depends(get_repository),
) -> GenerationJobRecord:
  job = repo.get_job(job_id)
  if not job:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Job not found')

  _require_owner(job.owner_id, current_user)
  return job


@router.get('/projects/{project_id}/result', response_model=VideoResultRecord)
def get_result(
  project_id: str,
  job_id: str | None = None,
  current_user: AuthUser = Depends(get_current_user),
  repo: Repository = Depends(get_repository),
) -> VideoResultRecord:
  project = repo.get_project(project_id)
  if not project:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Project not found')

  _require_owner(project.owner_id, current_user)

  result = repo.get_result(project_id, job_id=job_id)
  if not result:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Result not available yet')

  return result


@router.get('/projects/{project_id}/results', response_model=list[VideoResultRecord])
def list_results(
  project_id: str,
  current_user: AuthUser = Depends(get_current_user),
  repo: Repository = Depends(get_repository),
) -> list[VideoResultRecord]:
  project = repo.get_project(project_id)
  if not project:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Project not found')

  _require_owner(project.owner_id, current_user)
  return repo.list_results(project_id)


@router.post(
  '/projects/{project_id}/jobs/{job_id}/translate',
  response_model=list[GenerationJobRecord],
  status_code=status.HTTP_202_ACCEPTED,
)
def translate_video(
  project_id: str,
  job_id: str,
  payload: TranslateRequest,
  current_user: AuthUser = Depends(get_current_user),
  repo: Repository = Depends(get_repository),
  queue: JobQueue = Depends(get_queue),
  settings: Settings = Depends(get_settings),
) -> list[GenerationJobRecord]:
  """Create translation jobs for a completed video."""
  project = repo.get_project(project_id)
  if not project:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Project not found')

  _require_owner(project.owner_id, current_user)

  source_job = repo.get_job(job_id)
  if not source_job:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Source job not found')
  if source_job.status != JobStatus.COMPLETED:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Source job must be completed before translating')

  # Verify source result exists with script_lines
  source_result = repo.get_result(project_id, job_id=job_id)
  if not source_result or not source_result.script_lines:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Source video result not found or missing script data')

  if not payload.target_languages:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='At least one target language is required')

  from app.config.languages import SUPPORTED_LANGUAGES
  for lang in payload.target_languages:
    if lang not in SUPPORTED_LANGUAGES:
      raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=f'Unsupported language: {lang}. Supported: {", ".join(sorted(SUPPORTED_LANGUAGES.keys()))}',
      )

  translation_jobs: list[GenerationJobRecord] = []
  for lang in payload.target_languages:
    params = JobCreateParams(
      aspect_ratio=source_job.aspect_ratio,
      voice_style=source_job.voice_style,
      voice_provider=payload.voice_provider,
      voice_gender=payload.voice_gender,
      language=lang,
      background_music=source_job.background_music,
      max_attempts=settings.worker_max_attempts,
      script_template=source_job.script_template,
      video_style=source_job.video_style,
      transition_style=source_job.transition_style,
      caption_style=source_job.caption_style,
      show_title_card=source_job.show_title_card,
      cta_text=source_job.cta_text,
      job_type='translation',
      source_job_id=job_id,
    )
    new_job = repo.create_job(
      project_id=project_id,
      owner_id=current_user.user_id,
      params=params,
    )
    queue.enqueue(new_job.id)
    translation_jobs.append(new_job)

  repo.record_analytics_event(
    owner_id=current_user.user_id,
    event_name='translation_requested',
    project_id=project_id,
    job_id=job_id,
    properties={
      'target_languages': payload.target_languages,
      'voice_provider': payload.voice_provider,
      'jobs_created': len(translation_jobs),
    },
  )
  return translation_jobs


@router.get('/usage', response_model=UsageSummary)
def get_usage(
  current_user: AuthUser = Depends(get_current_user),
  repo: Repository = Depends(get_repository),
  settings: Settings = Depends(get_settings),
) -> UsageSummary:
  month = datetime.now(UTC).strftime('%Y-%m')
  return repo.get_usage(current_user.user_id, month, quota_limit=settings.monthly_video_quota)


@router.post('/analytics/events', response_model=AnalyticsEventRecord, status_code=status.HTTP_201_CREATED)
def create_analytics_event(
  payload: AnalyticsEventRequest,
  current_user: AuthUser = Depends(get_current_user),
  repo: Repository = Depends(get_repository),
) -> AnalyticsEventRecord:
  if payload.project_id:
    project = repo.get_project(payload.project_id)
    if not project:
      raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Project not found')
    _require_owner(project.owner_id, current_user)

  if payload.job_id:
    job = repo.get_job(payload.job_id)
    if not job:
      raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Job not found')
    _require_owner(job.owner_id, current_user)

  return repo.record_analytics_event(
    owner_id=current_user.user_id,
    event_name=payload.event_name,
    project_id=payload.project_id,
    job_id=payload.job_id,
    properties=payload.properties,
  )


@router.get('/analytics/events', response_model=list[AnalyticsEventRecord])
def list_analytics_events(
  current_user: AuthUser = Depends(get_current_user),
  repo: Repository = Depends(get_repository),
) -> list[AnalyticsEventRecord]:
  return repo.list_analytics_events(owner_id=current_user.user_id, limit=100)


@router.get('/admin/overview', response_model=AdminOverview)
def get_admin_overview(
  current_user: AuthUser = Depends(get_current_user),
  repo: Repository = Depends(get_repository),
  settings: Settings = Depends(get_settings),
) -> AdminOverview:
  if current_user.user_id not in settings.admin_user_ids:
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Admin access required')

  month = datetime.now(UTC).strftime('%Y-%m')
  projects = repo.list_projects(owner_id=None, limit=500)
  jobs = repo.list_jobs_by_owner(owner_id=None, limit=500)
  usage_rows = repo.list_usage_for_month(month, settings.monthly_video_quota)
  recent_events = repo.list_analytics_events(owner_id=None, limit=25)

  active_creators = len({project.owner_id for project in projects})
  activated_creators = len({job.owner_id for job in jobs if job.status == JobStatus.COMPLETED})
  activation_rate_pct = round((activated_creators / active_creators) * 100, 2) if active_creators else 0.0

  successful_jobs = sum(1 for job in jobs if job.status == JobStatus.COMPLETED)
  failed_jobs = sum(1 for job in jobs if job.status == JobStatus.FAILED)
  dead_letter_jobs = sum(1 for job in jobs if job.dead_lettered)
  videos_generated = sum(item.videos_generated for item in usage_rows)

  return AdminOverview(
    month=month,
    active_creators=active_creators,
    activated_creators=activated_creators,
    activation_rate_pct=activation_rate_pct,
    total_projects=len(projects),
    total_jobs=len(jobs),
    successful_jobs=successful_jobs,
    failed_jobs=failed_jobs,
    dead_letter_jobs=dead_letter_jobs,
    videos_generated=videos_generated,
    recent_jobs=jobs[:20],
    recent_events=recent_events,
  )


@router.get('/admin/dead-letters', response_model=list[GenerationJobRecord])
def get_dead_letter_jobs(
  current_user: AuthUser = Depends(get_current_user),
  repo: Repository = Depends(get_repository),
  settings: Settings = Depends(get_settings),
) -> list[GenerationJobRecord]:
  if current_user.user_id not in settings.admin_user_ids:
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Admin access required')
  return repo.list_dead_letter_jobs(owner_id=None, limit=100)


@router.post('/jobs/{job_id}:process', response_model=GenerationJobRecord)
def process_single_job(
  job_id: str,
  current_user: AuthUser = Depends(get_current_user),
  repo: Repository = Depends(get_repository),
  storage: StorageService = Depends(get_storage),
  nova: NovaService = Depends(get_nova_service),
  video_service: VideoService = Depends(get_video_service),
  settings: Settings = Depends(get_settings),
) -> GenerationJobRecord:
  """Admin-only debug endpoint for local testing."""
  if current_user.user_id not in settings.admin_user_ids:
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Only dev user can trigger processing')

  job = repo.get_job(job_id)
  if not job:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Job not found')

  claimed = repo.claim_job(job_id)
  if not claimed and job.status != JobStatus.QUEUED:
    return job

  target_job = claimed or job
  if target_job.job_type == 'translation':
    from app.services.pipeline_translate import process_translation_job
    translation_service = get_translation_service()
    process_translation_job(repo=repo, storage=storage, translation_service=translation_service, video_service=video_service, job=target_job)
  else:
    from app.services.pipeline import process_generation_job
    process_generation_job(repo=repo, storage=storage, nova=nova, video_service=video_service, job=target_job)
  final_job = repo.get_job(job_id)
  if not final_job:
    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail='Job state missing')
  return final_job
