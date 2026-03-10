from __future__ import annotations

import base64
from abc import ABC, abstractmethod

# Minimal valid MP3 frame (MPEG1 Layer 3, 128kbps, 44100Hz, ~0.026s of silence).
# Used for mock/fallback audio so ffmpeg can still process the file.
# This is a single valid MPEG audio frame header + padding.
_SILENT_MP3_FRAME = base64.b64decode(
    '//uQxAAAAAANIAAAAAExBTUUzLjEwMFVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV'
    'VVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV'
    'VVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV'
    'VVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVQ=='
)

# Repeat the frame to create ~1 second of silence for a usable mock audio file.
MOCK_SILENT_MP3 = _SILENT_MP3_FRAME * 40


class VoiceProvider(ABC):
  """Abstract base class for TTS providers."""

  @abstractmethod
  def synthesize(self, text: str, voice_gender: str = 'female', language: str = 'en') -> bytes:
    """Synthesize speech from text, return MP3 bytes."""
    raise NotImplementedError
