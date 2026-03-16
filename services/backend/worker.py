from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime, timedelta

from app.config import Settings, get_settings
from app.dependencies import get_nova_service, get_queue, get_repository, get_storage, get_translation_service, get_video_service
from app.models import JobStatus
from app.queue.base import JobQueue
from app.services.pipeline import process_generation_job
from app.services.pipeline_translate import process_translation_job

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger('novareel.worker')


def _retry_delay_seconds(settings: Settings, attempt_count: int) -> int:
  exponent = max(attempt_count - 1, 0)
  return int(settings.worker_retry_backoff_seconds * (2**exponent))


async def process_job_by_id(job_id: str, *, queue: JobQueue, settings: Settings) -> bool:
  repo = get_repository()
  storage = get_storage()
  nova = get_nova_service()
  video_service = get_video_service()

  claimed = repo.claim_job(job_id)
  if not claimed:
    return False

  # Route based on job_type
  if claimed.job_type == 'translation':
    translation_service = get_translation_service()
    process_translation_job(
      repo=repo,
      storage=storage,
      translation_service=translation_service,
      video_service=video_service,
      job=claimed,
    )
  else:
    await process_generation_job(repo=repo, storage=storage, nova=nova, video_service=video_service, job=claimed)

  final = repo.get_job(job_id)
  if not final:
    return True

  if final.status == JobStatus.FAILED and not final.dead_lettered:
    if final.attempt_count < final.max_attempts:
      delay_seconds = _retry_delay_seconds(settings, final.attempt_count)
      next_attempt_at = datetime.now(UTC) + timedelta(seconds=delay_seconds)

      repo.update_job(
        job_id,
        status=JobStatus.QUEUED,
        stage=JobStatus.QUEUED,
        progress_pct=0,
        next_attempt_at=next_attempt_at,
        dead_lettered=False,
        dead_letter_reason=None,
      )
      repo.record_analytics_event(
        owner_id=final.owner_id,
        event_name='generation_requeued',
        project_id=final.project_id,
        job_id=final.id,
        properties={'attempt_count': final.attempt_count, 'max_attempts': final.max_attempts, 'delay_seconds': delay_seconds},
      )

      queue.enqueue(job_id, delay_seconds=delay_seconds if settings.queue_backend == 'sqs' else 0)
      logger.warning(
        'Requeued job %s (attempt %s/%s, retry in %ss)',
        final.id,
        final.attempt_count,
        final.max_attempts,
        delay_seconds,
      )
    else:
      repo.update_job(
        job_id,
        status=JobStatus.FAILED,
        stage=JobStatus.FAILED,
        dead_lettered=True,
        dead_letter_reason=final.error_code or 'unknown_error',
      )
      repo.record_analytics_event(
        owner_id=final.owner_id,
        event_name='generation_dead_lettered',
        project_id=final.project_id,
        job_id=final.id,
        properties={'attempt_count': final.attempt_count, 'max_attempts': final.max_attempts},
      )
      logger.error('Dead-lettered job %s after %s attempts', final.id, final.attempt_count)

  return True


async def run_once() -> int:
  settings = get_settings()
  repo = get_repository()
  queue = get_queue()

  processed = 0

  if settings.queue_backend == 'sqs':
    messages = queue.receive(max_messages=5, wait_seconds=10)
    for job_id, receipt_handle in messages:
      if await process_job_by_id(job_id, queue=queue, settings=settings):
        processed += 1
      if receipt_handle:
        queue.ack(receipt_handle)
    return processed

  queued_jobs = repo.list_queued_jobs(limit=5)
  for job in queued_jobs:
    if await process_job_by_id(job.id, queue=queue, settings=settings):
      processed += 1

  return processed


async def run_forever() -> None:
  settings = get_settings()
  logger.info('Worker started (queue_backend=%s)', settings.queue_backend)

  while True:
    processed = await run_once()
    if processed == 0:
      time.sleep(settings.worker_poll_seconds)
      continue

    logger.info('Processed %s job(s)', processed)


def run_celery_worker() -> None:
  """Start the Celery worker process for distributed task execution."""
  from celery_config import celery_app  # noqa: F401

  settings = get_settings()
  logger.info('Starting Celery worker (broker=%s)', settings.celery_broker_url)

  celery_app.worker_main([
    'worker',
    '--loglevel=info',
    '--concurrency=2',
    '--pool=prefork',
  ])


if __name__ == '__main__':
  import sys
  mode = 'polling'
  for arg in sys.argv[1:]:
    if arg.startswith('--mode='):
      mode = arg.split('=', 1)[1]

  if mode == 'celery':
    run_celery_worker()
  else:
    asyncio.run(run_forever())
