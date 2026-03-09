from __future__ import annotations

import logging

from app.config import Settings
from app.services.voice.base import VoiceProvider

log = logging.getLogger(__name__)

# Default ElevenLabs voice IDs
_VOICE_MAP = {
  'female': 'EXAVITQu4vr4xnSDxMaL',  # Rachel
  'male': 'pNInz6obpgDQGcFmaJgB',     # Adam
}


class ElevenLabsVoiceProvider(VoiceProvider):
  """ElevenLabs premium TTS provider."""

  def __init__(self, settings: Settings):
    self._settings = settings
    self._api_key = settings.elevenlabs_api_key
    if not self._api_key:
      raise ValueError(
        'ElevenLabs API key is required. Set NOVAREEL_ELEVENLABS_API_KEY in .env '
        'or choose a different voice provider.'
      )

  def synthesize(self, text: str, voice_gender: str = 'female', language: str = 'en') -> bytes:
    try:
      import httpx
    except ImportError:
      log.warning('httpx not installed, returning mock audio')
      return f'MOCK-VOICE::elevenlabs::{voice_gender}::{text}'.encode('utf-8')

    voice_id = _VOICE_MAP.get(voice_gender, _VOICE_MAP['female'])

    try:
      response = httpx.post(
        f'https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream',
        headers={
          'xi-api-key': self._api_key,
          'Content-Type': 'application/json',
        },
        json={
          'text': text[:5000],
          'model_id': 'eleven_multilingual_v2',
          'voice_settings': {
            'stability': 0.5,
            'similarity_boost': 0.75,
          },
        },
        timeout=60.0,
      )
      response.raise_for_status()
      return response.content
    except Exception as exc:
      log.warning('ElevenLabs synthesis failed: %s', exc)
      return f'MOCK-VOICE::elevenlabs::{voice_gender}::{text}'.encode('utf-8')
