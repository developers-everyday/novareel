from __future__ import annotations

from app.config import Settings
from app.queue.base import JobQueue


class SqsQueue(JobQueue):
  def __init__(self, settings: Settings):
    if not settings.sqs_queue_url:
      raise ValueError('NOVAREEL_SQS_QUEUE_URL is required for sqs queue backend')

    try:
      import boto3
    except ImportError as exc:
      raise RuntimeError('boto3 is required for SqsQueue') from exc

    self._settings = settings
    self._queue_url = settings.sqs_queue_url
    self._client = boto3.client('sqs', region_name=settings.aws_region)

  def enqueue(self, job_id: str, delay_seconds: int = 0) -> None:
    self._client.send_message(QueueUrl=self._queue_url, MessageBody=job_id, DelaySeconds=max(0, min(delay_seconds, 900)))

  def receive(self, max_messages: int = 5, wait_seconds: int = 10) -> list[tuple[str, str | None]]:
    response = self._client.receive_message(
      QueueUrl=self._queue_url,
      MaxNumberOfMessages=max_messages,
      WaitTimeSeconds=wait_seconds,
      VisibilityTimeout=120,
    )

    messages: list[tuple[str, str | None]] = []
    for item in response.get('Messages', []):
      messages.append((item['Body'], item.get('ReceiptHandle')))
    return messages

  def ack(self, receipt_handle: str) -> None:
    self._client.delete_message(QueueUrl=self._queue_url, ReceiptHandle=receipt_handle)
