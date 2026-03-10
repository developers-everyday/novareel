from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
  model_config = SettingsConfigDict(env_prefix='NOVAREEL_', env_file='.env', extra='ignore')

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


@lru_cache
def get_settings() -> Settings:
  settings = Settings()
  settings.local_data_dir.mkdir(parents=True, exist_ok=True)
  (settings.local_data_dir / settings.local_storage_dir).mkdir(parents=True, exist_ok=True)
  return settings
