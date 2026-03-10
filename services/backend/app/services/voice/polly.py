from __future__ import annotations

import logging

from app.config import Settings
from app.services.voice.base import MOCK_SILENT_MP3, VoiceProvider

log = logging.getLogger(__name__)


class PollyVoiceProvider(VoiceProvider):
  """AWS Polly TTS provider."""

  def __init__(self, settings: Settings):
    self._settings = settings

  def synthesize(self, text: str, voice_gender: str = 'female', language: str = 'en') -> bytes:
    try:
      import boto3
    except ImportError:
      log.warning('boto3 not installed, returning silent mock MP3')
      return MOCK_SILENT_MP3

    from app.config.languages import get_voice_name

    voice_id = get_voice_name(language, 'polly', voice_gender)
    if not voice_id:
      # Fallback to defaults
      voice_id = 'Joanna' if voice_gender == 'female' else 'Matthew'
    log.info('Polly selected voice_id=%s for language=%s gender=%s', voice_id, language, voice_gender)

    try:
      polly = boto3.client('polly', region_name=self._settings.aws_region)
      response = polly.synthesize_speech(
        Text=text[:3000],
        OutputFormat='mp3',
        VoiceId=voice_id,
      )
      stream = response.get('AudioStream')
      if stream:
        return stream.read()
    except Exception as exc:
      log.warning('Polly synthesis failed: %s', exc)

    return MOCK_SILENT_MP3
