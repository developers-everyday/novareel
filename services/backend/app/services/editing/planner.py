"""Deterministic plan generator — converts a storyboard + effects config into an EditingPlan.

This is the bridge between the existing pipeline output and the new editing
framework.  The pipeline produces a storyboard (list of segments), effects
config, and audio paths; this module converts those into a declarative
EditingPlan that the compiler can render.
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.models import StoryboardSegment
from app.services.editing.schema import (
    AudioMuxParams,
    ColorSegmentParams,
    EditingPlan,
    ImageSegmentParams,
    IntroClipParams,
    LogoOverlayParams,
    MusicMixParams,
    OutroClipParams,
    SubtitleBurnParams,
    TextOverlayParams,
    ThumbnailParams,
    TransitionParams,
    VideoSegmentParams,
    ZoomDirection,
)
from app.services.effects import VideoEffectsConfig

logger = logging.getLogger(__name__)


def generate_plan(
    *,
    storyboard: list[StoryboardSegment],
    effects_config: VideoEffectsConfig,
    aspect_ratio: str = '16:9',
    audio_path: Path | None = None,
    music_path: Path | None = None,
    ass_subtitle_path: Path | None = None,
    ffmpeg_preset: str = 'medium',
    project_id: str = '',
    resolve_asset_fn: 'callable | None' = None,
) -> EditingPlan:
    """Build an EditingPlan from pipeline artifacts.

    Args:
        storyboard: Ordered list of storyboard segments from the pipeline.
        effects_config: Video effects configuration (transitions, overlays, brand kit).
        aspect_ratio: Target aspect ratio (16:9, 9:16, 1:1).
        audio_path: Path to the narration audio file.
        music_path: Path to background music file.
        ass_subtitle_path: Path to ASS subtitle file.
        ffmpeg_preset: FFmpeg encoding preset.
        project_id: Project ID (for asset path resolution).
        resolve_asset_fn: Callable(asset_id, project_id) -> Path | None.

    Returns:
        An EditingPlan ready for the compiler.
    """
    resolution = _resolution_for(aspect_ratio)
    steps: list = []

    # ── 1. Segment steps ───────────────────────────────────────────────────
    for idx, seg in enumerate(storyboard):
        if seg.media_type == 'video' and seg.video_path:
            steps.append(VideoSegmentParams(
                order=idx,
                video_path=seg.video_path,
                duration_sec=seg.duration_sec,
                caption_text=seg.script_line if not ass_subtitle_path else None,
            ))
        else:
            # Resolve image asset path
            image_path: str | None = None
            if resolve_asset_fn and seg.image_asset_id:
                resolved = resolve_asset_fn(seg.image_asset_id, project_id)
                if resolved and Path(resolved).exists():
                    image_path = str(resolved)

            if image_path:
                steps.append(ImageSegmentParams(
                    order=idx,
                    image_path=image_path,
                    duration_sec=seg.duration_sec,
                    zoom=ZoomDirection.ZOOM_IN if idx % 2 == 0 else ZoomDirection.ZOOM_OUT,
                    caption_text=seg.script_line if not ass_subtitle_path else None,
                ))
            else:
                steps.append(ColorSegmentParams(
                    order=idx,
                    duration_sec=seg.duration_sec,
                ))

    # ── 2. Transition step ─────────────────────────────────────────────────
    if effects_config.transition.xfade_name and effects_config.transition.duration > 0:
        steps.append(TransitionParams(
            effect=effects_config.transition.xfade_name,
            duration_sec=effects_config.transition.duration,
        ))

    # ── 3. Intro / outro clips ─────────────────────────────────────────────
    if effects_config.intro_clip_path and Path(effects_config.intro_clip_path).exists():
        steps.append(IntroClipParams(clip_path=str(effects_config.intro_clip_path)))

    if effects_config.outro_clip_path and Path(effects_config.outro_clip_path).exists():
        steps.append(OutroClipParams(clip_path=str(effects_config.outro_clip_path)))

    # ── 4. Text overlays ───────────────────────────────────────────────────
    total_duration = sum(s.duration_sec for s in storyboard)

    if effects_config.title_overlay:
        t = effects_config.title_overlay
        steps.append(TextOverlayParams(
            text=t.text,
            font_size=t.font_size,
            font_color=t.font_color,
            border_width=t.border_width,
            border_color=t.border_color,
            x=t.x,
            y=t.y,
            start_sec=t.start_sec,
            duration_sec=t.duration_sec,
            font_path=str(effects_config.brand_font_path) if effects_config.brand_font_path else None,
        ))

    if effects_config.cta_overlay:
        c = effects_config.cta_overlay
        cta_start = max(0, total_duration - c.duration_sec - 0.5)
        steps.append(TextOverlayParams(
            text=c.text,
            font_size=c.font_size,
            font_color=c.font_color,
            border_width=c.border_width,
            border_color=c.border_color,
            x=c.x,
            y=c.y,
            start_sec=cta_start,
            duration_sec=c.duration_sec,
            font_path=str(effects_config.brand_font_path) if effects_config.brand_font_path else None,
        ))

    # ── 5. Logo watermark ──────────────────────────────────────────────────
    if effects_config.logo_path and Path(effects_config.logo_path).exists():
        steps.append(LogoOverlayParams(
            logo_path=str(effects_config.logo_path),
        ))

    # ── 6. Subtitles ──────────────────────────────────────────────────────
    if ass_subtitle_path and ass_subtitle_path.exists():
        steps.append(SubtitleBurnParams(
            subtitle_path=str(ass_subtitle_path),
            subtitle_format='ass',
        ))

    # ── 7. Audio ───────────────────────────────────────────────────────────
    if audio_path and audio_path.exists() and audio_path.stat().st_size > 100:
        steps.append(AudioMuxParams(audio_path=str(audio_path)))

    # ── 8. Music ───────────────────────────────────────────────────────────
    if music_path and music_path.exists():
        steps.append(MusicMixParams(music_path=str(music_path)))

    # ── 9. Thumbnail ───────────────────────────────────────────────────────
    steps.append(ThumbnailParams())

    return EditingPlan(
        resolution=resolution,
        ffmpeg_preset=ffmpeg_preset,
        steps=steps,
    )


def _resolution_for(aspect_ratio: str) -> str:
    mapping = {
        '16:9': '1920x1080',
        '1:1': '1080x1080',
        '9:16': '1080x1920',
    }
    return mapping.get(aspect_ratio, '1920x1080')
