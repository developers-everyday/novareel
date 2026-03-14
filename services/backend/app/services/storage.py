from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from urllib.parse import quote

from app.config import Settings
from app.models import AssetRecord, AssetUploadUrlResponse


class StorageService(ABC):
  @abstractmethod
  def create_upload_url(self, asset: AssetRecord) -> AssetUploadUrlResponse:
    raise NotImplementedError

  @abstractmethod
  def save_local_upload(self, asset: AssetRecord, payload: bytes) -> None:
    raise NotImplementedError

  @abstractmethod
  def store_bytes(self, object_key: str, payload: bytes, content_type: str = 'application/octet-stream') -> None:
    raise NotImplementedError

  @abstractmethod
  def store_text(self, object_key: str, content: str) -> None:
    raise NotImplementedError

  @abstractmethod
  def get_public_url(self, object_key: str) -> str:
    raise NotImplementedError

  def load_text(self, key: str) -> str | None:
    """Load text content by key, return None if not found."""
    return None

  def exists(self, key: str) -> bool:
    """Check if a key exists in storage."""
    return False

  def delete_prefix(self, prefix: str) -> None:
    """Delete all objects with the given prefix."""
    pass


class LocalStorageService(StorageService):
  def __init__(self, settings: Settings):
    self._settings = settings
    self._root = settings.local_data_dir / settings.local_storage_dir
    self._root.mkdir(parents=True, exist_ok=True)

  @property
  def root(self) -> Path:
    return self._root

  def _resolve_object_path(self, object_key: str) -> Path:
    destination = (self._root / object_key).resolve()
    root = self._root.resolve()
    if root not in destination.parents and destination != root:
      raise ValueError('Invalid object key path')
    destination.parent.mkdir(parents=True, exist_ok=True)
    return destination

  def create_upload_url(self, asset: AssetRecord) -> AssetUploadUrlResponse:
    upload_url = (
      f"{self._settings.public_api_base_url.rstrip('/')}"
      f"/v1/projects/{asset.project_id}/assets/{asset.id}:upload"
    )
    return AssetUploadUrlResponse(
      asset_id=asset.id,
      object_key=asset.object_key,
      upload_url=upload_url,
      method='PUT',
      headers={'Content-Type': asset.content_type},
    )

  def save_local_upload(self, asset: AssetRecord, payload: bytes) -> None:
    destination = self._resolve_object_path(asset.object_key)
    destination.write_bytes(payload)

  def store_bytes(self, object_key: str, payload: bytes, content_type: str = 'application/octet-stream') -> None:
    destination = self._resolve_object_path(object_key)
    destination.write_bytes(payload)

  def store_text(self, object_key: str, content: str) -> None:
    destination = self._resolve_object_path(object_key)
    destination.write_text(content, encoding='utf-8')

  def get_public_url(self, object_key: str) -> str:
    encoded = quote(object_key)
    return f"{self._settings.public_api_base_url.rstrip('/')}/files/{encoded}"

  def load_text(self, key: str) -> str | None:
    try:
      path = self._resolve_object_path(key)
      if path.exists():
        return path.read_text(encoding='utf-8')
    except (ValueError, OSError):
      pass
    return None

  def exists(self, key: str) -> bool:
    try:
      path = self._resolve_object_path(key)
      return path.exists() and path.stat().st_size > 0
    except (ValueError, OSError):
      return False

  def delete_prefix(self, prefix: str) -> None:
    import shutil
    try:
      target_dir = (self._root / prefix).resolve()
      if target_dir.exists() and target_dir.is_dir():
        shutil.rmtree(target_dir)
      elif target_dir.exists():
        target_dir.unlink()
    except (ValueError, OSError):
      pass


class S3StorageService(StorageService):
  def __init__(self, settings: Settings):
    try:
      import boto3
    except ImportError as exc:
      raise RuntimeError('boto3 is required for S3StorageService') from exc

    from botocore.config import Config
    self._settings = settings
    self._bucket = settings.s3_bucket_name
    self._client = boto3.client('s3', region_name=settings.aws_region,
                                config=Config(signature_version='s3v4'))

  def create_upload_url(self, asset: AssetRecord) -> AssetUploadUrlResponse:
    upload_url = (
      f"{self._settings.public_api_base_url.rstrip('/')}"
      f"/v1/projects/{asset.project_id}/assets/{asset.id}:upload"
    )
    return AssetUploadUrlResponse(
      asset_id=asset.id,
      object_key=asset.object_key,
      upload_url=upload_url,
      method='PUT',
      headers={'Content-Type': asset.content_type},
    )

  def save_local_upload(self, asset: AssetRecord, payload: bytes) -> None:
    self.store_bytes(asset.object_key, payload, content_type=asset.content_type)

  def store_bytes(self, object_key: str, payload: bytes, content_type: str = 'application/octet-stream') -> None:
    self._client.put_object(Bucket=self._bucket, Key=object_key, Body=payload, ContentType=content_type)

  def store_text(self, object_key: str, content: str) -> None:
    self.store_bytes(object_key, content.encode('utf-8'), content_type='text/plain')

  def get_public_url(self, object_key: str) -> str:
    return self._client.generate_presigned_url(
      'get_object',
      Params={'Bucket': self._bucket, 'Key': object_key},
      ExpiresIn=3600,
    )

  def load_text(self, key: str) -> str | None:
    try:
      response = self._client.get_object(Bucket=self._bucket, Key=key)
      return response['Body'].read().decode('utf-8')
    except self._client.exceptions.NoSuchKey:
      return None
    except Exception:
      return None

  def exists(self, key: str) -> bool:
    try:
      self._client.head_object(Bucket=self._bucket, Key=key)
      return True
    except Exception:
      return False

  def delete_prefix(self, prefix: str) -> None:
    try:
      paginator = self._client.get_paginator('list_objects_v2')
      for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
        objects = page.get('Contents', [])
        if not objects:
          continue
        delete_keys = [{'Key': obj['Key']} for obj in objects]
        self._client.delete_objects(
          Bucket=self._bucket,
          Delete={'Objects': delete_keys},
        )
    except Exception:
      pass


def build_storage(settings: Settings) -> StorageService:
  if settings.storage_backend == 'dynamodb':
    return S3StorageService(settings)
  return LocalStorageService(settings)
