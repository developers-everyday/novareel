from __future__ import annotations

from abc import ABC, abstractmethod


class VoiceProvider(ABC):
  """Abstract base class for TTS providers."""

  @abstractmethod
  def synthesize(self, text: str, voice_gender: str = 'female', language: str = 'en') -> bytes:
    """Synthesize speech from text, return MP3 bytes."""
    raise NotImplementedError
