from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import Settings
from app.models import (
  AssetRecord,
  AnalyticsEventRecord,
  BrandKitRecord,
  GenerationJobRecord,
  JobCreateParams,
  JobStatus,
  LibraryAssetRecord,
  ProjectCreateRequest,
  ProjectRecord,
  PublishRecord,
  SocialConnectionRecord,
  UsageSummary,
  VideoResultRecord,
)
from app.repositories.base import Repository


class DynamoRepository(Repository):
  def __init__(self, settings: Settings):
    try:
      import boto3
    except ImportError as exc:
      raise RuntimeError('boto3 is required for DynamoRepository') from exc

    self._settings = settings
    dynamodb = boto3.resource('dynamodb', region_name=settings.aws_region)
    self._projects = dynamodb.Table(settings.dynamodb_projects_table)
    self._assets = dynamodb.Table(f"{settings.dynamodb_projects_table}-assets")
    self._jobs = dynamodb.Table(settings.dynamodb_jobs_table)
    self._results = dynamodb.Table(settings.dynamodb_results_table)
    self._usage = dynamodb.Table(settings.dynamodb_usage_table)
    self._analytics = dynamodb.Table(settings.dynamodb_analytics_table)
    self._brand_kits = dynamodb.Table(f"{settings.dynamodb_projects_table}-brand-kits")
    self._library_assets = dynamodb.Table(f"{settings.dynamodb_projects_table}-library-assets")
    self._social_connections = dynamodb.Table(f"{settings.dynamodb_projects_table}-social-connections")
    self._publish_records = dynamodb.Table(f"{settings.dynamodb_projects_table}-publish-records")

  @staticmethod
  def _utcnow() -> datetime:
    return datetime.now(UTC)

  def create_project(self, owner_id: str, payload: ProjectCreateRequest) -> ProjectRecord:
    project = ProjectRecord(
      id=str(uuid.uuid4()),
      owner_id=owner_id,
      title=payload.title,
      product_description=payload.product_description,
      brand_prefs=payload.brand_prefs,
      created_at=self._utcnow(),
      asset_ids=[],
    )
    self._projects.put_item(Item=project.model_dump(mode='json'))
    return project

  def get_project(self, project_id: str) -> ProjectRecord | None:
    response = self._projects.get_item(Key={'id': project_id})
    item = response.get('Item')
    if not item:
      return None
    return ProjectRecord.model_validate(item)

  def list_projects(self, owner_id: str | None = None, limit: int = 50) -> list[ProjectRecord]:
    response = self._projects.scan()
    projects = [ProjectRecord.model_validate(item) for item in response.get('Items', [])]
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
    asset_id = str(uuid.uuid4())
    safe_filename = Path(filename).name.replace(' ', '_')
    asset = AssetRecord(
      id=asset_id,
      project_id=project_id,
      owner_id=owner_id,
      filename=filename,
      content_type=content_type,
      file_size=file_size,
      object_key=f'projects/{project_id}/assets/{asset_id}-{safe_filename}',
      uploaded=False,
      created_at=self._utcnow(),
    )
    self._assets.put_item(Item=asset.model_dump(mode='json'))

    project = self.get_project(project_id)
    if not project:
      raise ValueError('Project not found')

    project.asset_ids.append(asset.id)
    self._projects.put_item(Item=project.model_dump(mode='json'))
    return asset

  def get_asset(self, asset_id: str) -> AssetRecord | None:
    response = self._assets.get_item(Key={'id': asset_id})
    item = response.get('Item')
    if not item:
      return None
    return AssetRecord.model_validate(item)

  def list_project_assets(self, project_id: str) -> list[AssetRecord]:
    project = self.get_project(project_id)
    if not project:
      return []

    assets: list[AssetRecord] = []
    for asset_id in project.asset_ids:
      asset = self.get_asset(asset_id)
      if asset:
        assets.append(asset)
    return assets

  def mark_asset_uploaded(self, asset_id: str) -> AssetRecord:
    asset = self.get_asset(asset_id)
    if not asset:
      raise ValueError('Asset not found')

    asset.uploaded = True
    self._assets.put_item(Item=asset.model_dump(mode='json'))
    return asset

  def create_job(
    self,
    project_id: str,
    owner_id: str,
    params: JobCreateParams,
  ) -> GenerationJobRecord:
    now = self._utcnow()
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
      # Phase 3
      auto_approve=params.auto_approve,
      variant_group_id=params.variant_group_id,
    )
    self._jobs.put_item(Item=job.model_dump(mode='json'))
    return job

  def claim_job(self, job_id: str) -> GenerationJobRecord | None:
    job = self.get_job(job_id)
    now = self._utcnow()
    if not job or job.status != JobStatus.QUEUED:
      return None
    if job.next_attempt_at and job.next_attempt_at > now:
      return None
    initial_status = JobStatus.LOADING if job.job_type == 'translation' else JobStatus.SCRIPTING
    return self.update_job(
      job_id,
      status=initial_status,
      stage=initial_status,
      progress_pct=5,
      attempt_count=job.attempt_count + 1,
    )

  def find_job_by_idempotency(
    self, *, owner_id: str, project_id: str, idempotency_key: str
  ) -> GenerationJobRecord | None:
    response = self._jobs.scan()
    for item in response.get('Items', []):
      if (
        item.get('owner_id') == owner_id
        and item.get('project_id') == project_id
        and item.get('idempotency_key') == idempotency_key
      ):
        return GenerationJobRecord.model_validate(item)
    return None

  def get_job(self, job_id: str) -> GenerationJobRecord | None:
    response = self._jobs.get_item(Key={'id': job_id})
    item = response.get('Item')
    if not item:
      return None
    return GenerationJobRecord.model_validate(item)

  def list_queued_jobs(self, limit: int = 10) -> list[GenerationJobRecord]:
    now = self._utcnow()
    response = self._jobs.scan()
    jobs = [
      GenerationJobRecord.model_validate(item)
      for item in response.get('Items', [])
      if item.get('status') == JobStatus.QUEUED.value
      and not item.get('dead_lettered', False)
    ]
    jobs = [job for job in jobs if not job.next_attempt_at or job.next_attempt_at <= now]
    jobs.sort(key=lambda item: item.created_at)
    return jobs[:limit]

  def list_jobs_for_project(self, project_id: str) -> list[GenerationJobRecord]:
    response = self._jobs.scan()
    jobs = [
      GenerationJobRecord.model_validate(item)
      for item in response.get('Items', [])
      if item.get('project_id') == project_id
    ]
    jobs.sort(key=lambda item: item.created_at, reverse=True)
    return jobs

  def list_jobs_by_owner(self, owner_id: str | None = None, limit: int = 100) -> list[GenerationJobRecord]:
    response = self._jobs.scan()
    jobs = [GenerationJobRecord.model_validate(item) for item in response.get('Items', [])]
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
    job = self.get_job(job_id)
    if not job:
      raise ValueError('Job not found')

    if status is not None:
      job.status = status
    if stage is not None:
      job.stage = stage
    if progress_pct is not None:
      job.progress_pct = max(0, min(progress_pct, 100))
    if error_code is not None or job.error_code:
      job.error_code = error_code
    if timings is not None:
      merged = dict(job.timings)
      merged.update(timings)
      job.timings = merged
    if attempt_count is not None:
      job.attempt_count = max(0, attempt_count)
    if next_attempt_at is not None:
      job.next_attempt_at = next_attempt_at
    elif status is not None and status != JobStatus.QUEUED:
      job.next_attempt_at = None
    if dead_lettered is not None:
      job.dead_lettered = dead_lettered
    if dead_letter_reason is not None or job.dead_letter_reason:
      job.dead_letter_reason = dead_letter_reason
    job.updated_at = self._utcnow()

    self._jobs.put_item(Item=job.model_dump(mode='json'))
    return job

  def set_result(self, project_id: str, job_id: str, result: VideoResultRecord) -> VideoResultRecord:
    self._results.put_item(Item=result.model_dump(mode='json'))
    return result

  def get_result(self, project_id: str, job_id: str | None = None) -> VideoResultRecord | None:
    if job_id:
      # Query by composite key
      response = self._results.get_item(Key={'project_id': project_id, 'job_id': job_id})
      item = response.get('Item')
      if not item:
        return None
      return VideoResultRecord.model_validate(item)
    # Return latest result for this project
    results = self.list_results(project_id)
    return results[0] if results else None

  def list_results(self, project_id: str) -> list[VideoResultRecord]:
    response = self._results.scan()
    results = [
      VideoResultRecord.model_validate(item)
      for item in response.get('Items', [])
      if item.get('project_id') == project_id
    ]
    results.sort(key=lambda r: r.completed_at, reverse=True)
    return results

  def increment_usage(self, owner_id: str, month: str, increment_by: int = 1) -> UsageSummary:
    key = f'{owner_id}:{month}'
    response = self._usage.get_item(Key={'id': key})
    item = response.get('Item') or {'id': key, 'owner_id': owner_id, 'month': month, 'videos_generated': 0}
    item['videos_generated'] = int(item.get('videos_generated', 0)) + increment_by
    self._usage.put_item(Item=item)
    return self.get_usage(owner_id, month, self._settings.monthly_video_quota)

  def get_usage(self, owner_id: str, month: str, quota_limit: int) -> UsageSummary:
    key = f'{owner_id}:{month}'
    response = self._usage.get_item(Key={'id': key})
    item = response.get('Item') or {'owner_id': owner_id, 'month': month, 'videos_generated': 0}
    videos_generated = int(item.get('videos_generated', 0))
    return UsageSummary(
      owner_id=owner_id,
      month=month,
      videos_generated=videos_generated,
      quota_limit=quota_limit,
      remaining=max(quota_limit - videos_generated, 0),
    )

  def list_usage_for_month(self, month: str, quota_limit: int) -> list[UsageSummary]:
    response = self._usage.scan()
    summaries: list[UsageSummary] = []
    for item in response.get('Items', []):
      if item.get('month') != month:
        continue
      owner_id = item.get('owner_id')
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
    event = AnalyticsEventRecord(
      id=str(uuid.uuid4()),
      owner_id=owner_id,
      event_name=event_name,
      project_id=project_id,
      job_id=job_id,
      properties=properties or {},
      created_at=self._utcnow(),
    )
    self._analytics.put_item(Item=event.model_dump(mode='json'))
    return event

  def list_analytics_events(self, owner_id: str | None = None, limit: int = 100) -> list[AnalyticsEventRecord]:
    response = self._analytics.scan()
    events = [AnalyticsEventRecord.model_validate(item) for item in response.get('Items', [])]
    if owner_id is not None:
      events = [event for event in events if event.owner_id == owner_id]
    events.sort(key=lambda item: item.created_at, reverse=True)
    return events[:limit]

  def list_dead_letter_jobs(self, owner_id: str | None = None, limit: int = 100) -> list[GenerationJobRecord]:
    response = self._jobs.scan()
    jobs = [
      GenerationJobRecord.model_validate(item)
      for item in response.get('Items', [])
      if item.get('dead_lettered', False)
    ]
    if owner_id is not None:
      jobs = [job for job in jobs if job.owner_id == owner_id]
    jobs.sort(key=lambda item: item.updated_at, reverse=True)
    return jobs[:limit]

  # ── Phase 3 — Brand Kit & Asset Library ──────────────────────────────────

  def set_brand_kit(self, owner_id: str, brand_kit: BrandKitRecord) -> BrandKitRecord:
    self._brand_kits.put_item(Item=brand_kit.model_dump(mode='json'))
    return brand_kit

  def get_brand_kit(self, owner_id: str) -> BrandKitRecord | None:
    response = self._brand_kits.get_item(Key={'owner_id': owner_id})
    item = response.get('Item')
    if not item:
      return None
    return BrandKitRecord.model_validate(item)

  def delete_brand_kit(self, owner_id: str) -> None:
    self._brand_kits.delete_item(Key={'owner_id': owner_id})

  def create_library_asset(self, asset: LibraryAssetRecord) -> LibraryAssetRecord:
    self._library_assets.put_item(Item=asset.model_dump(mode='json'))
    return asset

  def list_library_assets(self, owner_id: str, asset_type: str | None = None) -> list[LibraryAssetRecord]:
    response = self._library_assets.scan()
    assets = [
      LibraryAssetRecord.model_validate(item)
      for item in response.get('Items', [])
      if item.get('owner_id') == owner_id
    ]
    if asset_type:
      assets = [a for a in assets if a.asset_type == asset_type]
    assets.sort(key=lambda a: a.created_at, reverse=True)
    return assets

  def get_library_asset(self, asset_id: str) -> LibraryAssetRecord | None:
    response = self._library_assets.get_item(Key={'id': asset_id})
    item = response.get('Item')
    if not item:
      return None
    return LibraryAssetRecord.model_validate(item)

  def delete_library_asset(self, asset_id: str) -> None:
    self._library_assets.delete_item(Key={'id': asset_id})

  # ── Phase 3 — Social Connections & Publishing ──────────────────────────────

  def set_social_connection(self, connection: SocialConnectionRecord) -> SocialConnectionRecord:
    self._social_connections.put_item(Item=connection.model_dump(mode='json'))
    return connection

  def get_social_connection(self, owner_id: str, platform: str) -> SocialConnectionRecord | None:
    response = self._social_connections.scan()
    for item in response.get('Items', []):
      if item.get('owner_id') == owner_id and item.get('platform') == platform:
        return SocialConnectionRecord.model_validate(item)
    return None

  def list_social_connections(self, owner_id: str) -> list[SocialConnectionRecord]:
    response = self._social_connections.scan()
    connections = [
      SocialConnectionRecord.model_validate(item)
      for item in response.get('Items', [])
      if item.get('owner_id') == owner_id
    ]
    connections.sort(key=lambda c: c.connected_at, reverse=True)
    return connections

  def delete_social_connection(self, owner_id: str, platform: str) -> None:
    conn = self.get_social_connection(owner_id, platform)
    if conn:
      self._social_connections.delete_item(Key={'id': conn.id})

  def create_publish_record(self, record: PublishRecord) -> PublishRecord:
    self._publish_records.put_item(Item=record.model_dump(mode='json'))
    return record

  def list_publish_records(self, owner_id: str, job_id: str | None = None) -> list[PublishRecord]:
    response = self._publish_records.scan()
    records = [
      PublishRecord.model_validate(item)
      for item in response.get('Items', [])
      if item.get('owner_id') == owner_id
    ]
    if job_id:
      records = [r for r in records if r.job_id == job_id]
    records.sort(key=lambda r: r.published_at, reverse=True)
    return records
