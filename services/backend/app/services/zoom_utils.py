"""Product-aware zoompan filter builder for FFmpeg.

Generates a zoompan filter string that targets a specific focal point
(pan_x, pan_y) in normalized [0, 1] coordinates, with clamping to prevent
the viewport from exceeding image bounds.
"""

from __future__ import annotations


def build_zoompan_vf(
    *,
    width: int,
    height: int,
    duration_sec: float,
    fps: int = 24,
    zoom_dir: str = 'zoom_in',
    zoom_speed: float = 0.0015,
    max_zoom: float = 1.3,
    pan_x: float = 0.5,
    pan_y: float = 0.5,
    adaptive: bool = True,
) -> str:
    """Build a complete zoompan video-filter string targeting a focal point.

    The filter scales the source image to 8000px wide, applies a zoompan that
    tracks toward (pan_x, pan_y) in normalized coordinates, and outputs at the
    requested resolution.

    The x/y expressions clamp the viewport so it never exceeds the source
    image boundaries, preventing black bars or out-of-frame artifacts.

    When *adaptive* is True (default), zoom_speed is auto-computed so the zoom
    spans ~90 % of the segment duration, preventing "frozen" endings where
    the zoom maxes out early on long segments.

    Args:
        width: Output video width in pixels.
        height: Output video height in pixels.
        duration_sec: Segment duration in seconds.
        fps: Frames per second.
        zoom_dir: 'zoom_in' or 'zoom_out'.
        zoom_speed: Zoom increment per frame (0–0.01).  Ignored when adaptive=True.
        max_zoom: Maximum zoom factor (1.0–2.0).
        pan_x: Focal point X in [0, 1] (0=left edge, 1=right edge).
        pan_y: Focal point Y in [0, 1] (0=top edge, 1=bottom edge).
        adaptive: Auto-compute zoom_speed from duration so zoom fills the segment.

    Returns:
        A complete VF string: "scale=8000:-1,zoompan=...,setsar=1"
    """
    total_frames = int(fps * duration_sec)

    # Auto-compute zoom_speed so the zoom spans ~90% of the segment.
    # This prevents the "frozen tail" where zoom maxes out early on
    # long (reconciliation-stretched) segments.
    if adaptive and total_frames > 0:
        target_frames = int(total_frames * 0.92)  # reach max_zoom at 92% of segment
        if target_frames > 0:
            zoom_speed = round((max_zoom - 1.0) / target_frames, 6)
            zoom_speed = max(0.0003, min(zoom_speed, 0.01))  # clamp to sane range

    # Build zoom expression
    if zoom_dir == 'zoom_out':
        zoom_expr = f"if(eq(on\\,1)\\,{max_zoom}\\,max(zoom-{zoom_speed}\\,1.0))"
    else:
        zoom_expr = f"min(zoom+{zoom_speed},{max_zoom})"

    # Clamp pan_x/pan_y to safe range
    pan_x = max(0.0, min(1.0, pan_x))
    pan_y = max(0.0, min(1.0, pan_y))

    # Build x/y expressions that pan toward the focal point.
    #
    # In zoompan, the source image has been scaled to 8000px wide.
    # The viewport size at any frame is (iw/zoom, ih/zoom).
    # We want the viewport center to be at (pan_x * iw, pan_y * ih),
    # so the top-left corner should be at:
    #   x = pan_x * iw - (iw/zoom)/2 = iw * (pan_x - 0.5/zoom)
    #   y = pan_y * ih - (ih/zoom)/2 = ih * (pan_y - 0.5/zoom)
    #
    # Clamped to [0, iw - iw/zoom] and [0, ih - ih/zoom] respectively.
    x_expr = f"max(0\\,min(iw-iw/zoom\\,iw*{pan_x}-iw/zoom/2))"
    y_expr = f"max(0\\,min(ih-ih/zoom\\,ih*{pan_y}-ih/zoom/2))"

    vf = (
        f"scale=8000:-1,"
        f"zoompan=z='{zoom_expr}':x='{x_expr}':y='{y_expr}'"
        f":d={total_frames}:s={width}x{height}:fps={fps},"
        f"setsar=1"
    )
    return vf
