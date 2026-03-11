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
  # Phase 2 — Feature A (Translation)
  LOADING = 'loading'
  TRANSLATING = 'translating'
  # Phase 3 — Feature D (Storyboard Editor)
  AWAITING_APPROVAL = 'awaiting_approval'


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
  # Phase 1 (existing)
  aspect_ratio: Literal['16:9', '1:1', '9:16'] = '16:9'
  voice_style: Literal['energetic', 'professional', 'friendly'] = 'energetic'
  voice_provider: Literal['polly', 'edge_tts', 'elevenlabs'] = 'polly'
  voice_gender: Literal['male', 'female'] = 'female'
  language: str = 'en'
  background_music: Literal['none', 'auto', 'upbeat', 'calm', 'corporate', 'luxury'] = 'auto'
  idempotency_key: str | None = Field(default=None, min_length=8, max_length=128)
  # Phase 2
  script_template: str = 'product_showcase'
  video_style: Literal['product_only', 'product_lifestyle', 'lifestyle_focus'] = 'product_only'
  transition_style: Literal[
    'none', 'crossfade', 'slide_left', 'slide_right',
    'slide_up', 'slide_down', 'wipe_left', 'wipe_right',
    'fade_black', 'fade_white', 'circle_open', 'circle_close', 'dissolve',
  ] = 'none'
  caption_style: Literal['none', 'simple', 'word_highlight', 'karaoke'] = 'none'
  show_title_card: bool = False
  cta_text: str | None = None


class TranslateRequest(BaseModel):
  """Request body for POST /v1/projects/{project_id}/jobs/{job_id}/translate."""
  target_languages: list[str]
  voice_provider: Literal['polly', 'edge_tts', 'elevenlabs'] = 'edge_tts'
  voice_gender: Literal['male', 'female'] = 'female'


class JobCreateParams(BaseModel):
  """All parameters for creating a generation or translation job."""
  aspect_ratio: str = '16:9'
  voice_style: str = 'energetic'
  voice_provider: str = 'polly'
  voice_gender: str = 'female'
  language: str = 'en'
  background_music: str = 'auto'
  idempotency_key: str | None = None
  max_attempts: int = 3
  # Phase 2
  script_template: str = 'product_showcase'
  video_style: str = 'product_only'
  transition_style: str = 'none'
  caption_style: str = 'none'
  show_title_card: bool = False
  cta_text: str | None = None
  job_type: str = 'generation'
  source_job_id: str | None = None
  # Phase 3
  auto_approve: bool = True
  variant_group_id: str | None = None


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
  idempotency_key: str | None = None
  attempt_count: int = 0
  max_attempts: int = 3
  next_attempt_at: datetime | None = None
  dead_lettered: bool = False
  dead_letter_reason: str | None = None
  # Phase 2
  job_type: str = 'generation'
  source_job_id: str | None = None
  script_template: str = 'product_showcase'
  video_style: str = 'product_only'
  transition_style: str = 'none'
  caption_style: str = 'none'
  show_title_card: bool = False
  cta_text: str | None = None
  # Phase 3
  auto_approve: bool = True
  variant_group_id: str | None = None


class FocalRegion(BaseModel):
  """Normalized bounding-box center and size for the primary product in an image.

  All values are in [0, 1] relative to the image dimensions.
  """
  cx: float = Field(0.5, ge=0.0, le=1.0, description='Center X (0=left, 1=right)')
  cy: float = Field(0.5, ge=0.0, le=1.0, description='Center Y (0=top, 1=bottom)')
  w: float = Field(0.4, ge=0.0, le=1.0, description='Bounding box width fraction')
  h: float = Field(0.6, ge=0.0, le=1.0, description='Bounding box height fraction')


class StoryboardSegment(BaseModel):
  order: int
  script_line: str
  image_asset_id: str
  start_sec: float
  duration_sec: float
  # Phase 2 — Feature C (Stock Footage)
  media_type: Literal['image', 'video'] = 'image'
  video_path: str | None = None
  # Phase 4 — Product-aware zoom: focal region detected by vision model
  focal_region: FocalRegion | None = None


class VideoResultRecord(BaseModel):
  project_id: str
  job_id: str = ''  # Phase 2 — per-job results
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
  script_lines: list[str] = Field(default_factory=list)  # Phase 2 — for translation
  language: str = 'en'  # Phase 2 — for translation
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


# ── Phase 3 — Feature A: Brand Kit & Asset Library ──────────────────────────

class BrandKitRequest(BaseModel):
  """Request body for POST /v1/brand-kit."""
  brand_name: str = ''
  primary_color: str = '#1E40AF'
  secondary_color: str = '#F59E0B'
  accent_color: str = '#10B981'
  logo_asset_id: str | None = None
  font_asset_id: str | None = None
  intro_clip_asset_id: str | None = None
  outro_clip_asset_id: str | None = None
  custom_music_asset_ids: list[str] = Field(default_factory=list)


class BrandKitRecord(BaseModel):
  owner_id: str
  brand_name: str = ''
  primary_color: str = '#1E40AF'
  secondary_color: str = '#F59E0B'
  accent_color: str = '#10B981'
  logo_asset_id: str | None = None
  font_asset_id: str | None = None
  intro_clip_asset_id: str | None = None
  outro_clip_asset_id: str | None = None
  custom_music_asset_ids: list[str] = Field(default_factory=list)
  updated_at: datetime


class LibraryAssetUploadRequest(BaseModel):
  """Request body for POST /v1/library/assets."""
  filename: str = Field(min_length=1, max_length=255)
  asset_type: Literal['logo', 'font', 'intro_clip', 'outro_clip', 'music', 'image']
  content_type: str = 'image/png'
  file_size: int = Field(ge=1)


class LibraryAssetRecord(BaseModel):
  id: str
  owner_id: str
  asset_type: Literal['logo', 'font', 'intro_clip', 'outro_clip', 'music', 'image']
  filename: str
  content_type: str
  file_size: int
  object_key: str
  created_at: datetime


# ── Phase 3 — Feature C: Social Media Distribution ──────────────────────────

class MetadataRequest(BaseModel):
  """Request body for POST /v1/projects/{project_id}/jobs/{job_id}/metadata."""
  platforms: list[Literal['youtube', 'tiktok', 'instagram']] = Field(default_factory=lambda: ['youtube'])
  product_keywords: list[str] = Field(default_factory=list)


class MetadataResponse(BaseModel):
  """Response for metadata generation endpoint."""
  youtube: dict[str, Any] | None = None
  tiktok: dict[str, Any] | None = None
  instagram: dict[str, Any] | None = None


class SocialConnectionRecord(BaseModel):
  id: str
  owner_id: str
  platform: Literal['youtube', 'tiktok', 'instagram']
  platform_user_id: str
  platform_username: str
  encrypted_access_token: str
  encrypted_refresh_token: str
  token_expires_at: datetime
  connected_at: datetime


class PublishRequest(BaseModel):
  """Request body for POST /v1/projects/{project_id}/jobs/{job_id}/publish/youtube."""
  title: str = Field(min_length=1, max_length=100)
  description: str = ''
  tags: list[str] = Field(default_factory=list)
  category: str = 'Science & Technology'
  privacy: Literal['public', 'unlisted', 'private'] = 'private'


class PublishRecord(BaseModel):
  id: str
  owner_id: str
  job_id: str
  platform: str
  platform_video_id: str
  platform_url: str
  metadata_used: dict[str, Any] = Field(default_factory=dict)
  published_at: datetime


# ── Phase 3 — Feature E: A/B Video Variants ─────────────────────────────────

class GenerateVariantsRequest(BaseModel):
  """Request body for POST /v1/projects/{project_id}/generate-variants."""
  variant_count: int = Field(default=3, ge=2, le=5)
  shared: dict[str, Any] = Field(default_factory=dict)
  overrides: list[dict[str, Any]] = Field(default_factory=list)
