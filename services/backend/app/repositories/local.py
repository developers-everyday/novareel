from __future__ import annotations

import json
import tempfile
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import Settings
from app.models import (
  AssetRecord,
  AnalyticsEventRecord,
  GenerationJobRecord,
  JobCreateParams,
  JobStatus,
  ProjectCreateRequest,
  ProjectRecord,
  UsageSummary,
  VideoResultRecord,
)
from app.repositories.base import Repository


def _utcnow() -> datetime:
  return datetime.now(UTC)


class LocalRepository(Repository):
  def __init__(self, settings: Settings):
    self._settings = settings
    self._path = settings.local_data_dir / settings.local_store_file
    self._lock = threading.Lock()
    self._initialize()

  def _initialize(self) -> None:
    if self._path.exists():
      return

    self._path.parent.mkdir(parents=True, exist_ok=True)
    initial = {
      'projects': {},
      'assets': {},
      'jobs': {},
      'results': {},
      'usage': {},
      'analytics': {},
    }
    self._path.write_text(json.dumps(initial, indent=2), encoding='utf-8')

  def _load(self) -> dict[str, Any]:
    with self._lock:
      payload = json.loads(self._path.read_text(encoding='utf-8'))
    payload.setdefault('projects', {})
    payload.setdefault('assets', {})
    payload.setdefault('jobs', {})
    payload.setdefault('results', {})
    payload.setdefault('usage', {})
    payload.setdefault('analytics', {})
    return payload

  def _save(self, payload: dict[str, Any]) -> None:
    with self._lock:
      with tempfile.NamedTemporaryFile('w', delete=False, dir=self._path.parent, encoding='utf-8') as tmp:
        json.dump(payload, tmp, indent=2)
        tmp_path = Path(tmp.name)
      tmp_path.replace(self._path)

  @staticmethod
  def _as_month_key(moment: datetime) -> str:
    return moment.strftime('%Y-%m')

  def create_project(self, owner_id: str, payload: ProjectCreateRequest) -> ProjectRecord:
    store = self._load()
    project = ProjectRecord(
      id=str(uuid.uuid4()),
      owner_id=owner_id,
      title=payload.title,
      product_description=payload.product_description,
      brand_prefs=payload.brand_prefs,
      created_at=_utcnow(),
      asset_ids=[],
    )
    store['projects'][project.id] = project.model_dump(mode='json')
    self._save(store)
    return project

  def get_project(self, project_id: str) -> ProjectRecord | None:
    store = self._load()
    raw = store['projects'].get(project_id)
    if not raw:
      return None
    return ProjectRecord.model_validate(raw)

  def list_projects(self, owner_id: str | None = None, limit: int = 50) -> list[ProjectRecord]:
    store = self._load()
    projects = [ProjectRecord.model_validate(item) for item in store['projects'].values()]
    if owner_id is not None:
      projects = [project for project in projects if project.owner_id == owner_id]
    projects.sort(key=lambda item: item.created_at, reverse=True)
    return projects[:limit]

  def create_asset(
    self,
    project_id: str,
    owner_id: str,
    filename: str,
    content_type: str,
    file_size: int,
  ) -> AssetRecord:
    store = self._load()
    project = store['projects'].get(project_id)
    if not project:
      raise ValueError('Project not found')

    asset_id = str(uuid.uuid4())
    safe_filename = Path(filename).name.replace(' ', '_')
    object_key = f'projects/{project_id}/assets/{asset_id}-{safe_filename}'

    asset = AssetRecord(
      id=asset_id,
      project_id=project_id,
      owner_id=owner_id,
      filename=filename,
      content_type=content_type,
      file_size=file_size,
      object_key=object_key,
      uploaded=False,
      created_at=_utcnow(),
    )

    store['assets'][asset.id] = asset.model_dump(mode='json')
    project['asset_ids'] = project.get('asset_ids', []) + [asset.id]
    store['projects'][project_id] = project
    self._save(store)
    return asset

  def get_asset(self, asset_id: str) -> AssetRecord | None:
    store = self._load()
    raw = store['assets'].get(asset_id)
    if not raw:
      return None
    return AssetRecord.model_validate(raw)

  def list_project_assets(self, project_id: str) -> list[AssetRecord]:
    store = self._load()
    project = store['projects'].get(project_id)
    if not project:
      return []

    items: list[AssetRecord] = []
    for asset_id in project.get('asset_ids', []):
      raw = store['assets'].get(asset_id)
      if raw:
        items.append(AssetRecord.model_validate(raw))
    return items

  def mark_asset_uploaded(self, asset_id: str) -> AssetRecord:
    store = self._load()
    raw = store['assets'].get(asset_id)
    if not raw:
      raise ValueError('Asset not found')
    raw['uploaded'] = True
    store['assets'][asset_id] = raw
    self._save(store)
    return AssetRecord.model_validate(raw)

  def create_job(
    self,
    project_id: str,
    owner_id: str,
    params: JobCreateParams,
  ) -> GenerationJobRecord:
    store = self._load()
    now = _utcnow()
    job = GenerationJobRecord(
      id=str(uuid.uuid4()),
      project_id=project_id,
      owner_id=owner_id,
      status=JobStatus.QUEUED,
      stage=JobStatus.QUEUED,
      progress_pct=0,
      error_code=None,
      timings={},
      created_at=now,
      updated_at=now,
      aspect_ratio=params.aspect_ratio,
      voice_style=params.voice_style,
      voice_provider=params.voice_provider,
      voice_gender=params.voice_gender,
      language=params.language,
      background_music=params.background_music,
      idempotency_key=params.idempotency_key,
      attempt_count=0,
      max_attempts=params.max_attempts,
      next_attempt_at=None,
      dead_lettered=False,
      dead_letter_reason=None,
      # Phase 2
      job_type=params.job_type,
      source_job_id=params.source_job_id,
      script_template=params.script_template,
      video_style=params.video_style,
      transition_style=params.transition_style,
      caption_style=params.caption_style,
      show_title_card=params.show_title_card,
      cta_text=params.cta_text,
    )
    store['jobs'][job.id] = job.model_dump(mode='json')
    self._save(store)
    return job

  def claim_job(self, job_id: str) -> GenerationJobRecord | None:
    store = self._load()
    raw = store['jobs'].get(job_id)
    if not raw:
      return None

    current = GenerationJobRecord.model_validate(raw)
    if current.status != JobStatus.QUEUED:
      return None

    now = _utcnow()
    if current.next_attempt_at and current.next_attempt_at > now:
      return None

    initial_status = JobStatus.LOADING if current.job_type == 'translation' else JobStatus.SCRIPTING
    raw['status'] = initial_status.value
    raw['stage'] = initial_status.value
    raw['progress_pct'] = 5
    raw['attempt_count'] = int(raw.get('attempt_count', 0)) + 1
    raw['next_attempt_at'] = None
    raw['updated_at'] = now.isoformat()
    store['jobs'][job_id] = raw
    self._save(store)
    return GenerationJobRecord.model_validate(raw)

  def find_job_by_idempotency(
    self, *, owner_id: str, project_id: str, idempotency_key: str
  ) -> GenerationJobRecord | None:
    store = self._load()
    for raw in store['jobs'].values():
      if (
        raw.get('owner_id') == owner_id
        and raw.get('project_id') == project_id
        and raw.get('idempotency_key') == idempotency_key
      ):
        return GenerationJobRecord.model_validate(raw)
    return None

  def get_job(self, job_id: str) -> GenerationJobRecord | None:
    store = self._load()
    raw = store['jobs'].get(job_id)
    if not raw:
      return None
    return GenerationJobRecord.model_validate(raw)

  def list_queued_jobs(self, limit: int = 10) -> list[GenerationJobRecord]:
    store = self._load()
    now = _utcnow()
    queued = [
      GenerationJobRecord.model_validate(raw)
      for raw in store['jobs'].values()
      if raw.get('status') == JobStatus.QUEUED.value
      and not raw.get('dead_lettered', False)
      and (
        raw.get('next_attempt_at') is None
        or datetime.fromisoformat(str(raw.get('next_attempt_at')).replace('Z', '+00:00')) <= now
      )
    ]
    queued.sort(key=lambda item: item.created_at)
    return queued[:limit]

  def list_jobs_for_project(self, project_id: str) -> list[GenerationJobRecord]:
    store = self._load()
    jobs = [
      GenerationJobRecord.model_validate(raw)
      for raw in store['jobs'].values()
      if raw.get('project_id') == project_id
    ]
    jobs.sort(key=lambda item: item.created_at, reverse=True)
    return jobs

  def list_jobs_by_owner(self, owner_id: str | None = None, limit: int = 100) -> list[GenerationJobRecord]:
    store = self._load()
    jobs = [GenerationJobRecord.model_validate(raw) for raw in store['jobs'].values()]
    if owner_id is not None:
      jobs = [job for job in jobs if job.owner_id == owner_id]
    jobs.sort(key=lambda item: item.created_at, reverse=True)
    return jobs[:limit]

  def update_job(
    self,
    job_id: str,
    *,
    status: JobStatus | None = None,
    stage: JobStatus | None = None,
    progress_pct: int | None = None,
    error_code: str | None = None,
    timings: dict[str, float] | None = None,
    attempt_count: int | None = None,
    next_attempt_at: datetime | None = None,
    dead_lettered: bool | None = None,
    dead_letter_reason: str | None = None,
  ) -> GenerationJobRecord:
    store = self._load()
    raw = store['jobs'].get(job_id)
    if not raw:
      raise ValueError('Job not found')

    if status is not None:
      raw['status'] = status.value
    if stage is not None:
      raw['stage'] = stage.value
    if progress_pct is not None:
      raw['progress_pct'] = max(0, min(progress_pct, 100))

    if error_code is not None or raw.get('error_code'):
      raw['error_code'] = error_code

    if timings is not None:
      merged = dict(raw.get('timings', {}))
      merged.update(timings)
      raw['timings'] = merged

    if attempt_count is not None:
      raw['attempt_count'] = max(0, attempt_count)

    if next_attempt_at is not None:
      raw['next_attempt_at'] = next_attempt_at.isoformat()
    elif status is not None and status != JobStatus.QUEUED:
      raw['next_attempt_at'] = None

    if dead_lettered is not None:
      raw['dead_lettered'] = dead_lettered

    if dead_letter_reason is not None or raw.get('dead_letter_reason'):
      raw['dead_letter_reason'] = dead_letter_reason

    raw['updated_at'] = _utcnow().isoformat()
    store['jobs'][job_id] = raw
    self._save(store)
    return GenerationJobRecord.model_validate(raw)

  def set_result(self, project_id: str, job_id: str, result: VideoResultRecord) -> VideoResultRecord:
    store = self._load()
    key = f'{project_id}:{job_id}'
    store['results'][key] = result.model_dump(mode='json')
    self._save(store)
    return result

  def get_result(self, project_id: str, job_id: str | None = None) -> VideoResultRecord | None:
    store = self._load()
    if job_id:
      key = f'{project_id}:{job_id}'
      raw = store['results'].get(key)
      if not raw:
        return None
      return VideoResultRecord.model_validate(raw)
    # Return latest result for this project
    results = self.list_results(project_id)
    return results[0] if results else None

  def list_results(self, project_id: str) -> list[VideoResultRecord]:
    store = self._load()
    results: list[VideoResultRecord] = []
    for key, raw in store['results'].items():
      if key.startswith(f'{project_id}:'):
        results.append(VideoResultRecord.model_validate(raw))
    results.sort(key=lambda r: r.completed_at, reverse=True)
    return results

  def increment_usage(self, owner_id: str, month: str, increment_by: int = 1) -> UsageSummary:
    store = self._load()
    key = f'{owner_id}:{month}'
    usage = store['usage'].get(key, {'owner_id': owner_id, 'month': month, 'videos_generated': 0})
    usage['videos_generated'] = int(usage.get('videos_generated', 0)) + increment_by
    store['usage'][key] = usage
    self._save(store)
    return self.get_usage(owner_id, month, self._settings.monthly_video_quota)

  def get_usage(self, owner_id: str, month: str, quota_limit: int) -> UsageSummary:
    store = self._load()
    key = f'{owner_id}:{month}'
    usage = store['usage'].get(key, {'owner_id': owner_id, 'month': month, 'videos_generated': 0})
    videos_generated = int(usage.get('videos_generated', 0))
    return UsageSummary(
      owner_id=owner_id,
      month=month,
      videos_generated=videos_generated,
      quota_limit=quota_limit,
      remaining=max(quota_limit - videos_generated, 0),
    )

  def list_usage_for_month(self, month: str, quota_limit: int) -> list[UsageSummary]:
    store = self._load()
    summaries: list[UsageSummary] = []
    for raw in store['usage'].values():
      if raw.get('month') != month:
        continue
      owner_id = raw.get('owner_id')
      if not owner_id:
        continue
      summaries.append(self.get_usage(owner_id, month, quota_limit))
    return summaries

  def record_analytics_event(
    self,
    *,
    owner_id: str,
    event_name: str,
    project_id: str | None = None,
    job_id: str | None = None,
    properties: dict[str, Any] | None = None,
  ) -> AnalyticsEventRecord:
    store = self._load()
    event = AnalyticsEventRecord(
      id=str(uuid.uuid4()),
      owner_id=owner_id,
      event_name=event_name,
      project_id=project_id,
      job_id=job_id,
      properties=properties or {},
      created_at=_utcnow(),
    )
    store['analytics'][event.id] = event.model_dump(mode='json')
    self._save(store)
    return event

  def list_analytics_events(self, owner_id: str | None = None, limit: int = 100) -> list[AnalyticsEventRecord]:
    store = self._load()
    events = [AnalyticsEventRecord.model_validate(item) for item in store['analytics'].values()]
    if owner_id is not None:
      events = [event for event in events if event.owner_id == owner_id]
    events.sort(key=lambda item: item.created_at, reverse=True)
    return events[:limit]

  def list_dead_letter_jobs(self, owner_id: str | None = None, limit: int = 100) -> list[GenerationJobRecord]:
    store = self._load()
    jobs = [
      GenerationJobRecord.model_validate(raw)
      for raw in store['jobs'].values()
      if raw.get('dead_lettered', False)
    ]
    if owner_id is not None:
      jobs = [job for job in jobs if job.owner_id == owner_id]
    jobs.sort(key=lambda item: item.updated_at, reverse=True)
    return jobs[:limit]
