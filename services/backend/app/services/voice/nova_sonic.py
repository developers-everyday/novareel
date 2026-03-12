"""Amazon Nova Sonic TTS voice provider.

Nova 2 Sonic is a speech-to-speech model on Bedrock that requires a
bidirectional WebSocket streaming API (invoke_model_with_response_stream).
The standard Converse API does NOT support Nova Sonic.

Currently this provider falls back to EdgeTTS until the WebSocket
streaming integration is implemented.
"""

from __future__ import annotations

import json
import logging

from app.config import Settings
from app.services.voice.base import MOCK_SILENT_MP3, VoiceProvider

log = logging.getLogger(__name__)

# Nova Sonic voice presets — maps (language, gender) to a system prompt persona.
# Nova Sonic doesn't use named voice IDs like Polly; instead voice characteristics
# are controlled via the system prompt and inferenceConfig.
_VOICE_PERSONAS = {
    ('en', 'female'): 'You are a professional female voice-over artist with a clear, warm tone.',
    ('en', 'male'): 'You are a professional male voice-over artist with a clear, confident tone.',
}

_DEFAULT_PERSONA = {
    'female': 'You are a professional female narrator with a clear, engaging voice.',
    'male': 'You are a professional male narrator with a clear, engaging voice.',
}


class NovaSonicVoiceProvider(VoiceProvider):
    """Amazon Nova 2 Sonic TTS provider via Bedrock Converse API."""

    def __init__(self, settings: Settings):
        self._settings = settings

    def synthesize(self, text: str, voice_gender: str = 'female', language: str = 'en') -> bytes:
        # Nova Sonic requires WebSocket streaming (invoke_model_with_response_stream)
        # which is not yet implemented. Fall back to EdgeTTS for now.
        log.info('Nova Sonic: WebSocket streaming not yet implemented, delegating to EdgeTTS')
        return self._fallback_edge_tts(text, voice_gender, language)

    def _fallback_edge_tts(self, text: str, voice_gender: str, language: str) -> bytes:
        """Delegate to EdgeTTS as a reliable fallback."""
        from app.services.voice.edge_tts import EdgeTTSVoiceProvider
        fallback = EdgeTTSVoiceProvider(self._settings)
        return fallback.synthesize(text, voice_gender=voice_gender, language=language)
