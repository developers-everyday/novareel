from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
  model_config = SettingsConfigDict(
    env_prefix='NOVAREEL_',
    env_file=[
      str(Path(__file__).resolve().parents[4] / '.env'),  # project root
      '.env',                                              # CWD fallback
    ],
    extra='ignore',
  )

  app_name: str = 'NovaReel API'
  env: str = 'development'
  auth_disabled: bool = True
  clerk_jwks_url: str = 'https://clerk.dev/.well-known/jwks.json'
  clerk_issuer: str | None = None
  clerk_audience: str | None = None

  storage_backend: Literal['local', 'dynamodb'] = 'local'
  queue_backend: Literal['poll', 'sqs'] = 'poll'

  local_data_dir: Path = Field(default_factory=lambda: Path(__file__).resolve().parents[1] / 'data')
  local_store_file: str = 'local_store.json'
  local_storage_dir: str = 'storage'
  public_api_base_url: str = 'http://localhost:8000'

  aws_region: str = 'us-east-1'
  s3_bucket_name: str = 'novareel-phase1'
  s3_assets_prefix: str = 'projects/'
  dynamodb_projects_table: str = 'novareel-projects'
  dynamodb_jobs_table: str = 'novareel-jobs'
  dynamodb_results_table: str = 'novareel-results'
  dynamodb_usage_table: str = 'novareel-usage'
  dynamodb_analytics_table: str = 'novareel-analytics'
  sqs_queue_url: str | None = None

  bedrock_model_script: str = 'amazon.nova-lite-v1:0'
  bedrock_model_embeddings: str = 'amazon.nova-2-multimodal-embeddings-v1:0'
  bedrock_model_voice: str = 'amazon.nova-sonic-v1:0'
  bedrock_model_image: str = 'amazon.nova-canvas-v1:0'  # Nova Canvas — image generation
  polly_voice_id: str = 'Joanna'
  elevenlabs_api_key: str | None = None
  use_mock_ai: bool = True

  cors_origins: list[str] = ['http://localhost:3000']
  admin_user_ids: list[str] = ['beta-user']
  monthly_video_quota: int = 10
  quota_exempt_emails: list[str] = []
  max_assets_per_project: int = 12
  max_asset_file_size_bytes: int = 10_000_000
  allowed_asset_content_types: list[str] = ['image/jpeg', 'image/png', 'image/webp']
  worker_max_attempts: int = 3
  worker_poll_seconds: int = 4
  worker_retry_backoff_seconds: int = 20
  prompt_templates_dir: str = Field(default_factory=lambda: str(Path(__file__).resolve().parents[2] / 'prompt_templates'))
  default_voice_provider: str = 'polly'  # 'nova_sonic', 'polly', 'edge_tts', or 'elevenlabs'
  transcription_backend: str = 'mock'  # 'aws_transcribe', 'whisper', or 'mock'
  whisper_model: str = 'base'
  pexels_api_key: str | None = None
  # Phase 3 — Feature A: Brand Kit & Asset Library
  max_library_assets: int = 50
  max_library_file_size_bytes: int = 52_428_800  # 50 MB
  allowed_library_content_types: list[str] = [
    'image/jpeg', 'image/png', 'image/webp', 'image/svg+xml',
    'font/ttf', 'font/otf', 'application/x-font-ttf', 'application/x-font-opentype',
    'video/mp4',
    'audio/mpeg', 'audio/mp3',
  ]
  # Phase 3 — Feature C: Social Media Distribution
  google_client_id: str | None = None
  google_client_secret: str | None = None
  social_redirect_base_url: str = 'http://localhost:8000'
  encryption_key: str | None = None  # Fernet key for token encryption
  # Phase 3 — Feature F: Performance & Scalability
  worker_mode: str = 'polling'  # 'polling' (default) or 'celery'
  celery_broker_url: str = 'redis://localhost:6379/0'
  ffmpeg_preset: str = 'medium'  # ultrafast, veryfast, medium
  cdn_base_url: str | None = None  # CloudFront URL (empty = direct S3/local)
  # Phase 4 — Gap C: LLM-Oriented Editing Framework
  use_editing_framework: bool = False  # When True, render via EditingPlan instead of legacy path
  # Vision Director — smart B-roll planning
  use_vision_director: bool = True  # When True, use Nova Vision to plan/validate B-roll
  broll_validation_threshold: float = 6.0  # Minimum relevance score (0-10) for B-roll clips
  broll_max_candidates: int = 3  # Max Pexels results to validate before fallback
  # Agentic Orchestrator — Nova Pro drives the pipeline
  bedrock_model_orchestrator: str = 'amazon.nova-pro-v1:0'  # reasoning / orchestration
  use_agentic_orchestrator: bool = True  # When True, Nova Pro orchestrates the pipeline
  orchestrator_max_turns: int = 10  # safety cap on agentic loop iterations


@lru_cache
def get_settings() -> Settings:
  settings = Settings()
  settings.local_data_dir.mkdir(parents=True, exist_ok=True)
  (settings.local_data_dir / settings.local_storage_dir).mkdir(parents=True, exist_ok=True)
  return settings
