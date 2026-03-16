"""Celery task definitions — wraps existing pipeline functions as distributed tasks."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _get_celery_app():
  """Lazy-initialize the Celery app to avoid import-time errors when Celery isn't installed."""
  try:
    from celery import Celery
  except ImportError as exc:
    raise RuntimeError(
      'celery is required for task-based workers. '
      'Install with: pip install "celery[redis]>=5.3"'
    ) from exc

  from app.config import get_settings
  settings = get_settings()

  app = Celery(
    'novareel',
    broker=settings.celery_broker_url,
    backend=settings.celery_broker_url,
  )

  app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_reject_on_worker_lost=True,
    task_track_started=True,
  )

  return app


# Lazy singleton
_celery_app = None


def get_celery_app():
  global _celery_app
  if _celery_app is None:
    _celery_app = _get_celery_app()
  return _celery_app


def _resolve_services():
  """Build the service dependencies needed by pipeline functions."""
  from app.config import get_settings
  from app.dependencies import get_repository, get_storage, get_nova_service, get_video_service

  settings = get_settings()
  repo = get_repository()
  storage = get_storage()
  nova = get_nova_service()
  video_service = get_video_service()
  return repo, storage, nova, video_service


async def process_generation_task(job_id: str) -> dict[str, Any]:
  """Process a generation job — wraps process_generation_job() for Celery.

  Args:
    job_id: The job ID to process.

  Returns:
    Dict with job_id and final status.
  """
  from app.services.pipeline import process_generation_job

  repo, storage, nova, video_service = _resolve_services()

  job = repo.get_job(job_id)
  if not job:
    logger.error('Job %s not found', job_id)
    return {'job_id': job_id, 'status': 'not_found'}

  try:
    await process_generation_job(
      repo=repo,
      storage=storage,
      nova=nova,
      video_service=video_service,
      job=job,
    )
    final_job = repo.get_job(job_id)
    return {
      'job_id': job_id,
      'status': final_job.status.value if final_job else 'unknown',
    }
  except Exception as exc:
    logger.exception('Generation task failed for job %s', job_id)
    return {'job_id': job_id, 'status': 'failed', 'error': str(exc)}


def process_translation_task(job_id: str) -> dict[str, Any]:
  """Process a translation job — wraps process_translation_job() for Celery.

  Args:
    job_id: The job ID to process.

  Returns:
    Dict with job_id and final status.
  """
  from app.services.pipeline_translate import process_translation_job
  from app.dependencies import get_translation_service

  repo, storage, _, video_service = _resolve_services()
  translation_service = get_translation_service()

  job = repo.get_job(job_id)
  if not job:
    logger.error('Translation job %s not found', job_id)
    return {'job_id': job_id, 'status': 'not_found'}

  try:
    process_translation_job(
      repo=repo,
      storage=storage,
      translation_service=translation_service,
      video_service=video_service,
      job=job,
    )
    final_job = repo.get_job(job_id)
    return {
      'job_id': job_id,
      'status': final_job.status.value if final_job else 'unknown',
    }
  except Exception as exc:
    logger.exception('Translation task failed for job %s', job_id)
    return {'job_id': job_id, 'status': 'failed', 'error': str(exc)}


def register_celery_tasks():
  """Register pipeline functions as Celery tasks.

  Call this once during app startup when worker_mode == 'celery'.
  Returns the Celery app with registered tasks.
  """
  app = get_celery_app()

  @app.task(bind=True, name='novareel.process_generation', max_retries=3)
  def celery_process_generation(self, job_id: str):
    try:
      return process_generation_task(job_id)
    except Exception as exc:
      logger.exception('Celery generation task failed, retrying')
      raise self.retry(exc=exc, countdown=30)

  @app.task(bind=True, name='novareel.process_translation', max_retries=3)
  def celery_process_translation(self, job_id: str):
    try:
      return process_translation_task(job_id)
    except Exception as exc:
      logger.exception('Celery translation task failed, retrying')
      raise self.retry(exc=exc, countdown=30)

  return app
