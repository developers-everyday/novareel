from __future__ import annotations

import logging

from app.config import Settings
from app.services.voice.base import VoiceProvider

log = logging.getLogger(__name__)


class PollyVoiceProvider(VoiceProvider):
  """AWS Polly TTS provider."""

  def __init__(self, settings: Settings):
    self._settings = settings

  def synthesize(self, text: str, voice_gender: str = 'female', language: str = 'en') -> bytes:
    try:
      import boto3
    except ImportError:
      return f'MOCK-VOICE::polly::{voice_gender}::{text}'.encode('utf-8')

    from app.config.languages import get_voice_name

    voice_id = get_voice_name(language, 'polly', voice_gender)
    if not voice_id:
      # Fallback to defaults
      voice_id = 'Joanna' if voice_gender == 'female' else 'Matthew'

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

    return f'MOCK-VOICE::polly::{voice_gender}::{text}'.encode('utf-8')
