from app.queue.base import JobQueue


class NoopQueue(JobQueue):
  def enqueue(self, job_id: str, delay_seconds: int = 0) -> None:
    return None

  def receive(self, max_messages: int = 5, wait_seconds: int = 10) -> list[tuple[str, str | None]]:
    return []

  def ack(self, receipt_handle: str) -> None:
    return None
