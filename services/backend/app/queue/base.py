from __future__ import annotations

from abc import ABC, abstractmethod


class JobQueue(ABC):
  @abstractmethod
  def enqueue(self, job_id: str, delay_seconds: int = 0) -> None:
    raise NotImplementedError

  @abstractmethod
  def receive(self, max_messages: int = 5, wait_seconds: int = 10) -> list[tuple[str, str | None]]:
    """Return (job_id, receipt_handle) tuples."""
    raise NotImplementedError

  @abstractmethod
  def ack(self, receipt_handle: str) -> None:
    raise NotImplementedError
