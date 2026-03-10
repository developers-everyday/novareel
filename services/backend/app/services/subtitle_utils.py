"""Shared SRT subtitle utilities used by both generation and translation pipelines."""

from __future__ import annotations

from app.models import StoryboardSegment


def to_srt_timestamp(value: float) -> str:
    """Convert seconds to SRT timestamp format (HH:MM:SS,mmm)."""
    millis = int(round(value * 1000))
    hours = millis // 3_600_000
    millis %= 3_600_000
    minutes = millis // 60_000
    millis %= 60_000
    seconds = millis // 1_000
    millis %= 1_000
    return f'{hours:02}:{minutes:02}:{seconds:02},{millis:03}'


def build_srt(storyboard: list[StoryboardSegment]) -> str:
    """Build an SRT subtitle string from a storyboard."""
    rows: list[str] = []
    for segment in storyboard:
        start = to_srt_timestamp(segment.start_sec)
        end = to_srt_timestamp(segment.start_sec + segment.duration_sec)
        rows.append(f'{segment.order}\n{start} --> {end}\n{segment.script_line}\n')
    return '\n'.join(rows)
