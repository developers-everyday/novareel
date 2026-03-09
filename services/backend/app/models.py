from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
  QUEUED = 'queued'
  ANALYZING = 'analyzing'
  SCRIPTING = 'scripting'
  MATCHING = 'matching'
  NARRATION = 'narration'
  RENDERING = 'rendering'
  COMPLETED = 'completed'
  FAILED = 'failed'


class ProjectCreateRequest(BaseModel):
  title: str = Field(min_length=2, max_length=200)
  product_description: str = Field(min_length=10, max_length=4000)
  brand_prefs: dict[str, Any] | list[str] = Field(default_factory=list)


class ProjectRecord(BaseModel):
  id: str
  owner_id: str
  title: str
  product_description: str
  brand_prefs: dict[str, Any] = Field(default_factory=dict)
  created_at: datetime
  asset_ids: list[str] = Field(default_factory=list)


class AssetUploadRequest(BaseModel):
  filename: str = Field(min_length=1, max_length=255)
  content_type: str = 'image/jpeg'
  file_size: int = Field(ge=1)


class AssetRecord(BaseModel):
  id: str
  project_id: str
  owner_id: str
  filename: str
  content_type: str
  file_size: int
  object_key: str
  uploaded: bool = False
  created_at: datetime


class AssetUploadUrlResponse(BaseModel):
  asset_id: str
  object_key: str
  upload_url: str
  method: str = 'PUT'
  headers: dict[str, str]


class GenerateRequest(BaseModel):
  aspect_ratio: Literal['16:9', '1:1', '9:16'] = '16:9'
  voice_style: Literal['energetic', 'professional', 'friendly'] = 'energetic'
  voice_provider: Literal['polly', 'edge_tts', 'elevenlabs'] = 'polly'
  voice_gender: Literal['male', 'female'] = 'female'
  language: str = 'en'
  background_music: Literal['none', 'auto', 'upbeat', 'calm', 'corporate', 'luxury'] = 'auto'
  idempotency_key: str | None = Field(default=None, min_length=8, max_length=128)


class GenerationJobRecord(BaseModel):
  id: str
  project_id: str
  owner_id: str
  status: JobStatus
  stage: JobStatus
  progress_pct: int = Field(ge=0, le=100)
  error_code: str | None = None
  timings: dict[str, float] = Field(default_factory=dict)
  created_at: datetime
  updated_at: datetime
  aspect_ratio: str = '16:9'
  voice_style: str = 'energetic'
  voice_provider: str = 'polly'
  voice_gender: str = 'female'
  language: str = 'en'
  background_music: str = 'auto'
  last_completed_stage: str | None = None
  idempotency_key: str | None = None
  attempt_count: int = 0
  max_attempts: int = 3
  next_attempt_at: datetime | None = None
  dead_lettered: bool = False
  dead_letter_reason: str | None = None


class StoryboardSegment(BaseModel):
  order: int
  script_line: str
  image_asset_id: str
  start_sec: float
  duration_sec: float


class VideoResultRecord(BaseModel):
  project_id: str
  video_s3_key: str
  video_url: str
  duration_sec: float
  resolution: str
  thumbnail_key: str | None = None
  transcript_key: str | None = None
  transcript_url: str | None = None
  subtitle_key: str | None = None
  subtitle_url: str | None = None
  storyboard: list[StoryboardSegment] = Field(default_factory=list)
  completed_at: datetime


class UsageSummary(BaseModel):
  owner_id: str
  month: str
  videos_generated: int
  quota_limit: int
  remaining: int


class AnalyticsEventRequest(BaseModel):
  event_name: str = Field(min_length=2, max_length=64)
  project_id: str | None = None
  job_id: str | None = None
  properties: dict[str, Any] = Field(default_factory=dict)


class AnalyticsEventRecord(BaseModel):
  id: str
  owner_id: str
  event_name: str
  project_id: str | None = None
  job_id: str | None = None
  properties: dict[str, Any] = Field(default_factory=dict)
  created_at: datetime


class AdminOverview(BaseModel):
  month: str
  active_creators: int
  activated_creators: int
  activation_rate_pct: float
  total_projects: int
  total_jobs: int
  successful_jobs: int
  failed_jobs: int
  dead_letter_jobs: int
  videos_generated: int
  recent_jobs: list[GenerationJobRecord] = Field(default_factory=list)
  recent_events: list[AnalyticsEventRecord] = Field(default_factory=list)
