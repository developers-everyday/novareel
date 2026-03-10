from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

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


class Repository(ABC):
  @abstractmethod
  def create_project(self, owner_id: str, payload: ProjectCreateRequest) -> ProjectRecord:
    raise NotImplementedError

  @abstractmethod
  def get_project(self, project_id: str) -> ProjectRecord | None:
    raise NotImplementedError

  @abstractmethod
  def list_projects(self, owner_id: str | None = None, limit: int = 50) -> list[ProjectRecord]:
    raise NotImplementedError

  @abstractmethod
  def create_asset(
    self,
    project_id: str,
    owner_id: str,
    filename: str,
    content_type: str,
    file_size: int,
  ) -> AssetRecord:
    raise NotImplementedError

  @abstractmethod
  def get_asset(self, asset_id: str) -> AssetRecord | None:
    raise NotImplementedError

  @abstractmethod
  def list_project_assets(self, project_id: str) -> list[AssetRecord]:
    raise NotImplementedError

  @abstractmethod
  def mark_asset_uploaded(self, asset_id: str) -> AssetRecord:
    raise NotImplementedError

  @abstractmethod
  def create_job(
    self,
    project_id: str,
    owner_id: str,
    params: JobCreateParams,
  ) -> GenerationJobRecord:
    raise NotImplementedError

  @abstractmethod
  def claim_job(self, job_id: str) -> GenerationJobRecord | None:
    raise NotImplementedError

  @abstractmethod
  def find_job_by_idempotency(
    self, *, owner_id: str, project_id: str, idempotency_key: str
  ) -> GenerationJobRecord | None:
    raise NotImplementedError

  @abstractmethod
  def get_job(self, job_id: str) -> GenerationJobRecord | None:
    raise NotImplementedError

  @abstractmethod
  def list_queued_jobs(self, limit: int = 10) -> list[GenerationJobRecord]:
    raise NotImplementedError

  @abstractmethod
  def list_jobs_for_project(self, project_id: str) -> list[GenerationJobRecord]:
    raise NotImplementedError

  @abstractmethod
  def list_jobs_by_owner(self, owner_id: str | None = None, limit: int = 100) -> list[GenerationJobRecord]:
    raise NotImplementedError

  @abstractmethod
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
    raise NotImplementedError

  @abstractmethod
  def set_result(self, project_id: str, job_id: str, result: VideoResultRecord) -> VideoResultRecord:
    raise NotImplementedError

  @abstractmethod
  def get_result(self, project_id: str, job_id: str | None = None) -> VideoResultRecord | None:
    raise NotImplementedError

  @abstractmethod
  def list_results(self, project_id: str) -> list[VideoResultRecord]:
    raise NotImplementedError

  @abstractmethod
  def increment_usage(self, owner_id: str, month: str, increment_by: int = 1) -> UsageSummary:
    raise NotImplementedError

  @abstractmethod
  def get_usage(self, owner_id: str, month: str, quota_limit: int) -> UsageSummary:
    raise NotImplementedError

  @abstractmethod
  def list_usage_for_month(self, month: str, quota_limit: int) -> list[UsageSummary]:
    raise NotImplementedError

  @abstractmethod
  def record_analytics_event(
    self,
    *,
    owner_id: str,
    event_name: str,
    project_id: str | None = None,
    job_id: str | None = None,
    properties: dict[str, Any] | None = None,
  ) -> AnalyticsEventRecord:
    raise NotImplementedError

  @abstractmethod
  def list_analytics_events(self, owner_id: str | None = None, limit: int = 100) -> list[AnalyticsEventRecord]:
    raise NotImplementedError

  @abstractmethod
  def list_dead_letter_jobs(self, owner_id: str | None = None, limit: int = 100) -> list[GenerationJobRecord]:
    raise NotImplementedError

  # ── Phase 3 — Brand Kit & Asset Library ──────────────────────────────────

  @abstractmethod
  def set_brand_kit(self, owner_id: str, brand_kit: BrandKitRecord) -> BrandKitRecord:
    raise NotImplementedError

  @abstractmethod
  def get_brand_kit(self, owner_id: str) -> BrandKitRecord | None:
    raise NotImplementedError

  @abstractmethod
  def delete_brand_kit(self, owner_id: str) -> None:
    raise NotImplementedError

  @abstractmethod
  def create_library_asset(self, asset: LibraryAssetRecord) -> LibraryAssetRecord:
    raise NotImplementedError

  @abstractmethod
  def list_library_assets(self, owner_id: str, asset_type: str | None = None) -> list[LibraryAssetRecord]:
    raise NotImplementedError

  @abstractmethod
  def get_library_asset(self, asset_id: str) -> LibraryAssetRecord | None:
    raise NotImplementedError

  @abstractmethod
  def delete_library_asset(self, asset_id: str) -> None:
    raise NotImplementedError

  # ── Phase 3 — Social Connections & Publishing ────────────────────────────

  @abstractmethod
  def set_social_connection(self, connection: SocialConnectionRecord) -> SocialConnectionRecord:
    raise NotImplementedError

  @abstractmethod
  def get_social_connection(self, owner_id: str, platform: str) -> SocialConnectionRecord | None:
    raise NotImplementedError

  @abstractmethod
  def list_social_connections(self, owner_id: str) -> list[SocialConnectionRecord]:
    raise NotImplementedError

  @abstractmethod
  def delete_social_connection(self, owner_id: str, platform: str) -> None:
    raise NotImplementedError

  @abstractmethod
  def create_publish_record(self, record: PublishRecord) -> PublishRecord:
    raise NotImplementedError

  @abstractmethod
  def list_publish_records(self, owner_id: str, job_id: str | None = None) -> list[PublishRecord]:
    raise NotImplementedError
