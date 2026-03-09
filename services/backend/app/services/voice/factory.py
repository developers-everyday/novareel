from __future__ import annotations

import logging

from app.config import Settings
from app.services.voice.base import VoiceProvider
from app.services.voice.polly import PollyVoiceProvider
from app.services.voice.edge_tts import EdgeTTSVoiceProvider

log = logging.getLogger(__name__)


def build_voice_provider(provider_name: str, settings: Settings) -> VoiceProvider:
  """Factory function that returns the appropriate VoiceProvider instance."""

  if provider_name == 'polly':
    return PollyVoiceProvider(settings)
  elif provider_name == 'edge_tts':
    return EdgeTTSVoiceProvider(settings)
  elif provider_name == 'elevenlabs':
    try:
      from app.services.voice.elevenlabs import ElevenLabsVoiceProvider
      return ElevenLabsVoiceProvider(settings)
    except ValueError:
      log.warning('ElevenLabs API key not configured, falling back to EdgeTTS')
      return EdgeTTSVoiceProvider(settings)
  else:
    log.warning('Unknown voice provider %r, falling back to Polly', provider_name)
    return PollyVoiceProvider(settings)
