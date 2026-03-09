"""Background music selection logic."""

from __future__ import annotations

import random
from pathlib import Path

MUSIC_DIR = Path(__file__).resolve().parents[2] / 'assets' / 'music'

# Auto-select mapping based on voice_style
AUTO_MAPPING = {
    'energetic': 'upbeat',
    'professional': 'corporate',
    'friendly': 'calm',
}


def select_music_path(background_music: str, voice_style: str) -> Path | None:
    """Return the path to a music file, or None if 'none'."""
    if background_music == 'none':
        return None

    if background_music == 'auto':
        mood = AUTO_MAPPING.get(voice_style, 'calm')
    else:
        mood = background_music

    music_file = MUSIC_DIR / f'{mood}.mp3'
    if music_file.exists():
        return music_file

    # Fallback: pick any available track
    available = list(MUSIC_DIR.glob('*.mp3'))
    return available[0] if available else None
