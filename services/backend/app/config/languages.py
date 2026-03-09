"""Language configuration with TTS voice mappings for all supported languages."""

from __future__ import annotations


SUPPORTED_LANGUAGES: dict[str, dict] = {
    'en': {
        'name': 'English',
        'edge_tts_female': 'en-AU-NatashaNeural',
        'edge_tts_male': 'en-AU-WilliamNeural',
        'polly_female': 'Joanna',
        'polly_male': 'Matthew',
        'elevenlabs_supported': True,
    },
    'es': {
        'name': 'Spanish',
        'edge_tts_female': 'es-AR-ElenaNeural',
        'edge_tts_male': 'es-AR-TomasNeural',
        'polly_female': 'Lucia',
        'polly_male': 'Sergio',
        'elevenlabs_supported': True,
    },
    'fr': {
        'name': 'French',
        'edge_tts_female': 'fr-CA-SylvieNeural',
        'edge_tts_male': 'fr-CA-AntoineNeural',
        'polly_female': 'Lea',
        'polly_male': 'Mathieu',
        'elevenlabs_supported': True,
    },
    'de': {
        'name': 'German',
        'edge_tts_female': 'de-DE-KatjaNeural',
        'edge_tts_male': 'de-DE-ConradNeural',
        'polly_female': 'Vicki',
        'polly_male': 'Daniel',
        'elevenlabs_supported': True,
    },
    'ar': {
        'name': 'Arabic',
        'edge_tts_female': 'ar-AE-FatimaNeural',
        'edge_tts_male': 'ar-AE-HamdanNeural',
        'polly_female': 'Zeina',
        'polly_male': None,
        'elevenlabs_supported': True,
        'rtl': True,
    },
    'hi': {
        'name': 'Hindi',
        'edge_tts_female': 'hi-IN-SwaraNeural',
        'edge_tts_male': 'hi-IN-MadhurNeural',
        'polly_female': 'Aditi',
        'polly_male': None,
        'elevenlabs_supported': False,
    },
    'ja': {
        'name': 'Japanese',
        'edge_tts_female': 'ja-JP-NanamiNeural',
        'edge_tts_male': 'ja-JP-KeitaNeural',
        'polly_female': 'Mizuki',
        'polly_male': 'Takumi',
        'elevenlabs_supported': False,
    },
    'zh': {
        'name': 'Chinese',
        'edge_tts_female': 'zh-CN-XiaoxiaoNeural',
        'edge_tts_male': 'zh-CN-YunxiNeural',
        'polly_female': 'Zhiyu',
        'polly_male': None,
        'elevenlabs_supported': False,
    },
    'ko': {
        'name': 'Korean',
        'edge_tts_female': 'ko-KR-SunHiNeural',
        'edge_tts_male': 'ko-KR-InJoonNeural',
        'polly_female': 'Seoyeon',
        'polly_male': None,
        'elevenlabs_supported': False,
    },
    'pt': {
        'name': 'Portuguese',
        'edge_tts_female': 'pt-BR-FranciscaNeural',
        'edge_tts_male': 'pt-BR-AntonioNeural',
        'polly_female': 'Camila',
        'polly_male': 'Thiago',
        'elevenlabs_supported': True,
    },
    'it': {
        'name': 'Italian',
        'edge_tts_female': 'it-IT-ElsaNeural',
        'edge_tts_male': 'it-IT-DiegoNeural',
        'polly_female': 'Bianca',
        'polly_male': 'Adriano',
        'elevenlabs_supported': True,
    },
    'ru': {
        'name': 'Russian',
        'edge_tts_female': 'ru-RU-SvetlanaNeural',
        'edge_tts_male': 'ru-RU-DmitryNeural',
        'polly_female': 'Tatyana',
        'polly_male': 'Maxim',
        'elevenlabs_supported': False,
    },
    'tr': {
        'name': 'Turkish',
        'edge_tts_female': 'tr-TR-EmelNeural',
        'edge_tts_male': 'tr-TR-AhmetNeural',
        'polly_female': 'Filiz',
        'polly_male': None,
        'elevenlabs_supported': False,
    },
    'nl': {
        'name': 'Dutch',
        'edge_tts_female': 'nl-NL-FennaNeural',
        'edge_tts_male': 'nl-NL-MaartenNeural',
        'polly_female': 'Lotte',
        'polly_male': 'Ruben',
        'elevenlabs_supported': False,
    },
    'pl': {
        'name': 'Polish',
        'edge_tts_female': 'pl-PL-ZofiaNeural',
        'edge_tts_male': 'pl-PL-MarekNeural',
        'polly_female': 'Ewa',
        'polly_male': 'Jacek',
        'elevenlabs_supported': True,
    },
    'sv': {
        'name': 'Swedish',
        'edge_tts_female': 'sv-SE-SofieNeural',
        'edge_tts_male': 'sv-SE-MattiasNeural',
        'polly_female': 'Astrid',
        'polly_male': None,
        'elevenlabs_supported': False,
    },
    'th': {
        'name': 'Thai',
        'edge_tts_female': 'th-TH-PremwadeeNeural',
        'edge_tts_male': 'th-TH-NiwatNeural',
        'polly_female': None,
        'polly_male': None,
        'elevenlabs_supported': False,
    },
    'vi': {
        'name': 'Vietnamese',
        'edge_tts_female': 'vi-VN-HoaiMyNeural',
        'edge_tts_male': 'vi-VN-NamMinhNeural',
        'polly_female': None,
        'polly_male': None,
        'elevenlabs_supported': False,
    },
    'id': {
        'name': 'Indonesian',
        'edge_tts_female': 'id-ID-GadisNeural',
        'edge_tts_male': 'id-ID-ArdiNeural',
        'polly_female': None,
        'polly_male': None,
        'elevenlabs_supported': False,
    },
    'ms': {
        'name': 'Malay',
        'edge_tts_female': 'ms-MY-YasminNeural',
        'edge_tts_male': 'ms-MY-OsmanNeural',
        'polly_female': None,
        'polly_male': None,
        'elevenlabs_supported': False,
    },
}


def get_language_name(code: str) -> str:
    """Return display name for a language code, or the code itself if unknown."""
    lang = SUPPORTED_LANGUAGES.get(code)
    return lang['name'] if lang else code


def get_voice_name(code: str, provider: str, gender: str) -> str | None:
    """Return the TTS voice name for a language/provider/gender combination."""
    lang = SUPPORTED_LANGUAGES.get(code)
    if not lang:
        return None
    key = f'{provider}_{gender}'
    return lang.get(key)


def is_rtl(code: str) -> bool:
    """Return True if the language uses right-to-left script."""
    lang = SUPPORTED_LANGUAGES.get(code)
    return lang.get('rtl', False) if lang else False
