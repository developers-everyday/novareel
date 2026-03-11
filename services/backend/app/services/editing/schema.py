"""Editing plan schema — Pydantic models that describe a video editing plan as JSON.

An EditingPlan is a declarative description of how to assemble a video.  It is
independent of the rendering engine (FFmpeg, MoviePy, …) and can be generated
either deterministically from a storyboard or by an LLM.

Step types
----------
- ``image_segment``  — Ken-Burns zoom on a still image
- ``video_segment``  — Trim / scale a video clip (B-roll)
- ``color_segment``  — Solid-color placeholder
- ``transition``     — Transition effect between the two surrounding segments
- ``intro_clip``     — Pre-roll brand clip
- ``outro_clip``     — Post-roll brand clip
- ``text_overlay``   — drawtext overlay (title card, CTA, …)
- ``logo_overlay``   — Brand logo watermark
- ``subtitle_burn``  — Burn ASS / SRT subtitles into video
- ``audio_mux``      — Mux narration audio onto the video track
- ``music_mix``      — Mix background music with ducking
- ``thumbnail``      — Extract a thumbnail frame
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


# ── Enums ──────────────────────────────────────────────────────────────────

class StepType(str, Enum):
    IMAGE_SEGMENT = 'image_segment'
    VIDEO_SEGMENT = 'video_segment'
    COLOR_SEGMENT = 'color_segment'
    TRANSITION = 'transition'
    INTRO_CLIP = 'intro_clip'
    OUTRO_CLIP = 'outro_clip'
    TEXT_OVERLAY = 'text_overlay'
    LOGO_OVERLAY = 'logo_overlay'
    SUBTITLE_BURN = 'subtitle_burn'
    AUDIO_MUX = 'audio_mux'
    MUSIC_MIX = 'music_mix'
    THUMBNAIL = 'thumbnail'


class ZoomDirection(str, Enum):
    ZOOM_IN = 'zoom_in'
    ZOOM_OUT = 'zoom_out'


# ── Step parameter models ──────────────────────────────────────────────────

class ImageSegmentParams(BaseModel):
    """Render a still image with Ken-Burns zoom effect."""
    type: Literal['image_segment'] = 'image_segment'
    order: int = Field(..., description='Segment order in the final video (0-indexed)')
    image_path: str = Field(..., description='Path to the source image')
    duration_sec: float = Field(..., gt=0, description='Segment duration in seconds')
    zoom: ZoomDirection = ZoomDirection.ZOOM_IN
    zoom_speed: float = Field(0.0015, ge=0, le=0.01, description='Zoom speed per frame')
    max_zoom: float = Field(1.3, ge=1.0, le=2.0, description='Maximum zoom factor')
    pan_x: float = Field(0.5, ge=0.0, le=1.0, description='Focal point X (0=left, 1=right) — zoom target')
    pan_y: float = Field(0.5, ge=0.0, le=1.0, description='Focal point Y (0=top, 1=bottom) — zoom target')
    fps: int = Field(24, ge=12, le=60)
    caption_text: str | None = Field(None, description='Optional burned-in caption text')


class VideoSegmentParams(BaseModel):
    """Trim and scale a video clip (B-roll)."""
    type: Literal['video_segment'] = 'video_segment'
    order: int = Field(..., description='Segment order in the final video (0-indexed)')
    video_path: str = Field(..., description='Path to the source video clip')
    duration_sec: float = Field(..., gt=0)
    fps: int = Field(24, ge=12, le=60)
    caption_text: str | None = None


class ColorSegmentParams(BaseModel):
    """Solid-color placeholder segment."""
    type: Literal['color_segment'] = 'color_segment'
    order: int
    color_hex: str = Field('#0f172a', description='Hex color code')
    duration_sec: float = Field(..., gt=0)
    fps: int = 24


class TransitionParams(BaseModel):
    """Transition effect between segments."""
    type: Literal['transition'] = 'transition'
    effect: str = Field('fade', description='FFmpeg xfade transition name (fade, slideleft, etc.)')
    duration_sec: float = Field(0.5, gt=0, le=3.0)


class IntroClipParams(BaseModel):
    """Pre-roll brand intro clip."""
    type: Literal['intro_clip'] = 'intro_clip'
    clip_path: str


class OutroClipParams(BaseModel):
    """Post-roll brand outro clip."""
    type: Literal['outro_clip'] = 'outro_clip'
    clip_path: str


class TextOverlayParams(BaseModel):
    """Text overlay on the video (title card, CTA, etc.)."""
    type: Literal['text_overlay'] = 'text_overlay'
    text: str
    font_size: int = 48
    font_color: str = 'white'
    border_width: int = 3
    border_color: str = 'black'
    x: str = '(w-text_w)/2'
    y: str = '(h-text_h)/2'
    start_sec: float = 0.0
    duration_sec: float = 3.0
    font_path: str | None = None


class LogoOverlayParams(BaseModel):
    """Brand logo watermark overlay."""
    type: Literal['logo_overlay'] = 'logo_overlay'
    logo_path: str
    position: str = Field('top-right', description='Placement: top-right, top-left, bottom-right, bottom-left')
    size_pct: float = Field(0.08, gt=0, le=0.5, description='Logo width as fraction of video width')
    opacity: float = Field(0.7, ge=0, le=1.0)
    padding_px: int = Field(20, ge=0)


class SubtitleBurnParams(BaseModel):
    """Burn ASS/SRT subtitles into the video."""
    type: Literal['subtitle_burn'] = 'subtitle_burn'
    subtitle_path: str
    subtitle_format: Literal['ass', 'srt'] = 'ass'


class AudioMuxParams(BaseModel):
    """Mux narration audio onto the video track."""
    type: Literal['audio_mux'] = 'audio_mux'
    audio_path: str
    codec: str = 'aac'


class MusicMixParams(BaseModel):
    """Mix background music with volume ducking."""
    type: Literal['music_mix'] = 'music_mix'
    music_path: str
    volume: float = Field(0.12, ge=0, le=1.0, description='Music volume (0–1)')
    loop: bool = Field(True, description='Loop music to match video duration')


class ThumbnailParams(BaseModel):
    """Extract a thumbnail frame from the rendered video."""
    type: Literal['thumbnail'] = 'thumbnail'
    time_sec: float = Field(0.0, ge=0, description='Timestamp to extract (0 = first frame)')
    quality: int = Field(2, ge=1, le=31, description='JPEG quality (1=best, 31=worst)')


# ── Union of all step types ────────────────────────────────────────────────

EditingStep = (
    ImageSegmentParams
    | VideoSegmentParams
    | ColorSegmentParams
    | TransitionParams
    | IntroClipParams
    | OutroClipParams
    | TextOverlayParams
    | LogoOverlayParams
    | SubtitleBurnParams
    | AudioMuxParams
    | MusicMixParams
    | ThumbnailParams
)


# ── Top-level plan ─────────────────────────────────────────────────────────

class EditingPlan(BaseModel):
    """Complete declarative description of how to assemble a video.

    The ``steps`` list is ordered: segment steps define clip order, post-processing
    steps (overlays, audio, subtitles) are applied in list order after segment
    assembly.
    """

    version: str = Field('1.0', description='Schema version')
    resolution: str = Field('1920x1080', description='Output resolution WxH')
    fps: int = Field(24, ge=12, le=60)
    ffmpeg_preset: str = Field('medium', description='libx264 speed preset')

    # Ordered list of editing steps
    steps: list[EditingStep] = Field(default_factory=list)

    # ── Convenience helpers ────────────────────────────────────────────────

    @property
    def segment_steps(self) -> list[ImageSegmentParams | VideoSegmentParams | ColorSegmentParams]:
        """Return only the segment-producing steps, ordered by their ``order`` field."""
        segs = [s for s in self.steps if isinstance(s, (ImageSegmentParams, VideoSegmentParams, ColorSegmentParams))]
        return sorted(segs, key=lambda s: s.order)

    @property
    def transition_step(self) -> TransitionParams | None:
        """Return the (first) transition step, if any."""
        for s in self.steps:
            if isinstance(s, TransitionParams):
                return s
        return None

    @property
    def post_steps(self) -> list[EditingStep]:
        """Return non-segment, non-transition steps in list order."""
        segment_types = (ImageSegmentParams, VideoSegmentParams, ColorSegmentParams, TransitionParams)
        return [s for s in self.steps if not isinstance(s, segment_types)]

    def to_json(self, **kwargs) -> str:
        """Serialize to JSON string."""
        return self.model_dump_json(indent=2, **kwargs)

    @classmethod
    def from_json(cls, raw: str) -> EditingPlan:
        """Deserialize from JSON string."""
        return cls.model_validate_json(raw)
