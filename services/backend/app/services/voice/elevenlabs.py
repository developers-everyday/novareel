from __future__ import annotations

import logging

from app.config import Settings
from app.config.languages import get_voice_name, SUPPORTED_LANGUAGES
from app.services.voice.base import MOCK_SILENT_MP3, VoiceProvider

log = logging.getLogger(__name__)

# Default ElevenLabs voice IDs (fallback for unsupported languages)
_DEFAULT_VOICE_MAP = {
  'female': 'EXAVITQu4vr4xnSDxMaL',  # Rachel
  'male': 'pNInz6obpgDQGcFmaJgB',     # Adam
}


class ElevenLabsVoiceProvider(VoiceProvider):
  """ElevenLabs premium TTS provider."""

  def __init__(self, settings: Settings):
    self._settings = settings
    self._api_key = settings.elevenlabs_api_key
    log.info('ElevenLabs key loaded (prefix: %s...)', (self._api_key or '')[:12])
    if not self._api_key:
      raise ValueError(
        'ElevenLabs API key is required. Set NOVAREEL_ELEVENLABS_API_KEY in .env '
        'or choose a different voice provider.'
      )

  def synthesize(self, text: str, voice_gender: str = 'female', language: str = 'en') -> bytes:
    try:
      import httpx
    except ImportError:
      log.warning('httpx not installed, returning silent mock MP3')
      return MOCK_SILENT_MP3

    # Use language-aware voice if available
    lang_config = SUPPORTED_LANGUAGES.get(language, {})
    voice_id = None
    if lang_config.get('elevenlabs_supported'):
      voice_name = get_voice_name(language, 'elevenlabs', voice_gender)
      if voice_name:
        voice_id = voice_name
    if not voice_id:
      voice_id = _DEFAULT_VOICE_MAP.get(voice_gender, _DEFAULT_VOICE_MAP['female'])
    log.info('ElevenLabs selected voice_id=%s for language=%s gender=%s', voice_id, language, voice_gender)

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
      log.warning('ElevenLabs synthesis failed: %s — falling back to EdgeTTS', exc)
      from app.services.voice.edge_tts import EdgeTTSVoiceProvider
      return EdgeTTSVoiceProvider(self._settings).synthesize(text, voice_gender=voice_gender, language=language)
