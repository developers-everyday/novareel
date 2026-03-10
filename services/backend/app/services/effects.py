"""Video effects configuration — transitions between segments and text overlays."""

from __future__ import annotations

from dataclasses import dataclass, field


# ── Transition Styles ────────────────────────────────────────────────────────

TRANSITION_STYLES = {
    'none': {'xfade_name': None, 'duration': 0.0},
    'crossfade': {'xfade_name': 'fade', 'duration': 0.5},
    'slide_left': {'xfade_name': 'slideleft', 'duration': 0.4},
    'slide_right': {'xfade_name': 'slideright', 'duration': 0.4},
    'slide_up': {'xfade_name': 'slideup', 'duration': 0.4},
    'slide_down': {'xfade_name': 'slidedown', 'duration': 0.4},
    'wipe_left': {'xfade_name': 'wipeleft', 'duration': 0.5},
    'wipe_right': {'xfade_name': 'wiperight', 'duration': 0.5},
    'fade_black': {'xfade_name': 'fadeblack', 'duration': 0.6},
    'fade_white': {'xfade_name': 'fadewhite', 'duration': 0.6},
    'circle_open': {'xfade_name': 'circleopen', 'duration': 0.5},
    'circle_close': {'xfade_name': 'circleclose', 'duration': 0.5},
    'dissolve': {'xfade_name': 'dissolve', 'duration': 0.5},
}


@dataclass
class TransitionConfig:
    """Configuration for a single transition between two segments."""
    xfade_name: str | None = 'fade'
    duration: float = 0.5

    @classmethod
    def from_style(cls, style: str) -> TransitionConfig:
        """Create a config from a named style. Falls back to 'none' for unknown styles."""
        config = TRANSITION_STYLES.get(style, TRANSITION_STYLES['none'])
        return cls(xfade_name=config['xfade_name'], duration=config['duration'])


@dataclass
class TextOverlay:
    """Configuration for a text overlay on the video."""
    text: str
    font_size: int = 48
    font_color: str = 'white'
    border_width: int = 3
    border_color: str = 'black'
    x: str = '(w-text_w)/2'  # centered
    y: str = '(h-text_h)/2'  # centered
    start_sec: float = 0.0
    duration_sec: float = 3.0

    @property
    def escaped_text(self) -> str:
        """Escape text for ffmpeg drawtext filter."""
        return self.text.replace("'", "\u2019").replace(":", "\\:")


@dataclass
class VideoEffectsConfig:
    """Full rendering effects configuration, built from job params."""
    transition: TransitionConfig = field(default_factory=lambda: TransitionConfig(xfade_name=None, duration=0.0))
    title_overlay: TextOverlay | None = None
    cta_overlay: TextOverlay | None = None
    caption_style: str = 'none'

    @classmethod
    def from_job(cls, job) -> VideoEffectsConfig:
        """Build effects config from a GenerationJobRecord."""
        transition = TransitionConfig.from_style(job.transition_style or 'none')

        title_overlay = None
        if job.show_title_card:
            project_title = getattr(job, '_project_title', None) or ''
            if project_title:
                title_overlay = TextOverlay(
                    text=project_title,
                    font_size=56,
                    font_color='white',
                    border_width=4,
                    border_color='black',
                    x='(w-text_w)/2',
                    y='(h-text_h)/2',
                    start_sec=0.0,
                    duration_sec=3.0,
                )

        cta_overlay = None
        if job.cta_text:
            cta_overlay = TextOverlay(
                text=job.cta_text,
                font_size=44,
                font_color='white',
                border_width=3,
                border_color='black',
                x='(w-text_w)/2',
                y='h-100',
                start_sec=0.0,  # Will be set relative to the last segment
                duration_sec=4.0,
            )

        return cls(
            transition=transition,
            title_overlay=title_overlay,
            cta_overlay=cta_overlay,
            caption_style=job.caption_style or 'none',
        )
