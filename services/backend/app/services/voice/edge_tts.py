from __future__ import annotations

import asyncio
import concurrent.futures
import io
import logging

from app.config import Settings
from app.services.voice.base import MOCK_SILENT_MP3, VoiceProvider

log = logging.getLogger(__name__)


class EdgeTTSVoiceProvider(VoiceProvider):
  """Microsoft EdgeTTS provider — free, supports 50+ languages."""

  def __init__(self, settings: Settings):
    self._settings = settings

  def synthesize(self, text: str, voice_gender: str = 'female', language: str = 'en') -> bytes:
    try:
      import edge_tts
    except ImportError:
      log.warning('edge-tts package not installed, returning silent mock MP3')
      return MOCK_SILENT_MP3

    from app.config.languages import get_voice_name

    voice_name = get_voice_name(language, 'edge_tts', voice_gender)
    if not voice_name:
      # Fallback to English
      voice_name = 'en-AU-NatashaNeural' if voice_gender == 'female' else 'en-AU-WilliamNeural'
    log.info('EdgeTTS selected voice=%s for language=%s gender=%s', voice_name, language, voice_gender)

    try:
      # Run in a dedicated thread so asyncio.run() works even when called
      # from within a running event loop (e.g. the async pipeline worker).
      with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(
          asyncio.run, self._async_synthesize(edge_tts, text[:3000], voice_name)
        ).result()
    except Exception as exc:
      log.warning('EdgeTTS synthesis failed: %s', exc)
      return MOCK_SILENT_MP3

  @staticmethod
  async def _async_synthesize(edge_tts, text: str, voice: str) -> bytes:
    communicate = edge_tts.Communicate(text, voice)
    buffer = io.BytesIO()
    async for chunk in communicate.stream():
      if chunk['type'] == 'audio':
        buffer.write(chunk['data'])
    return buffer.getvalue()
