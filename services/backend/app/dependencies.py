from functools import lru_cache

from app.config import Settings, get_settings
from app.queue import JobQueue, build_queue
from app.repositories import Repository, build_repository
from app.services.nova import NovaService
from app.services.storage import StorageService, build_storage
from app.services.video import VideoService


@lru_cache
def get_repository() -> Repository:
  return build_repository(get_settings())


@lru_cache
def get_queue() -> JobQueue:
  return build_queue(get_settings())


@lru_cache
def get_storage() -> StorageService:
  return build_storage(get_settings())


@lru_cache
def get_nova_service() -> NovaService:
  settings = get_settings()
  return NovaService(settings)


@lru_cache
def get_video_service() -> VideoService:
  settings = get_settings()
  return VideoService(settings)


def reset_dependency_caches() -> None:
  get_repository.cache_clear()
  get_queue.cache_clear()
  get_storage.cache_clear()
  get_nova_service.cache_clear()
  get_video_service.cache_clear()
