from app.config import Settings
from app.queue.base import JobQueue
from app.queue.noop import NoopQueue
from app.queue.sqs import SqsQueue


def build_queue(settings: Settings) -> JobQueue:
  if settings.queue_backend == 'sqs':
    return SqsQueue(settings)
  return NoopQueue()
