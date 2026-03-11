"""Tests for the LLM-oriented editing framework — schema, planner, compiler."""

from __future__ import annotations

import json
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
from app.services.editing.planner import generate_plan
from app.services.effects import TextOverlay, TransitionConfig, VideoEffectsConfig


# ── Schema tests ───────────────────────────────────────────────────────────

def test_editing_plan_empty():
    """Empty plan is valid."""
    plan = EditingPlan()
    assert plan.version == '1.0'
    assert plan.resolution == '1920x1080'
    assert len(plan.steps) == 0
    assert len(plan.segment_steps) == 0


def test_editing_plan_segment_helpers():
    """segment_steps returns only segment types, sorted by order."""
    plan = EditingPlan(steps=[
        ColorSegmentParams(order=2, duration_sec=3.0),
        ImageSegmentParams(order=0, image_path='/tmp/img.png', duration_sec=5.0),
        TransitionParams(effect='fade', duration_sec=0.5),
        VideoSegmentParams(order=1, video_path='/tmp/clip.mp4', duration_sec=4.0),
        TextOverlayParams(text='Hello'),
    ])
    segs = plan.segment_steps
    assert len(segs) == 3
    assert [s.order for s in segs] == [0, 1, 2]


def test_editing_plan_transition_helper():
    """transition_step returns the first TransitionParams."""
    plan = EditingPlan(steps=[
        TransitionParams(effect='slideleft', duration_sec=0.4),
    ])
    assert plan.transition_step is not None
    assert plan.transition_step.effect == 'slideleft'


def test_editing_plan_transition_helper_none():
    """transition_step returns None if no transition."""
    plan = EditingPlan(steps=[
        ColorSegmentParams(order=0, duration_sec=3.0),
    ])
    assert plan.transition_step is None


def test_editing_plan_post_steps():
    """post_steps excludes segments and transitions."""
    plan = EditingPlan(steps=[
        ImageSegmentParams(order=0, image_path='/tmp/a.png', duration_sec=5.0),
        TransitionParams(effect='fade', duration_sec=0.5),
        TextOverlayParams(text='Title'),
        AudioMuxParams(audio_path='/tmp/audio.mp3'),
        ThumbnailParams(),
    ])
    post = plan.post_steps
    assert len(post) == 3
    types = [type(s).__name__ for s in post]
    assert 'TextOverlayParams' in types
    assert 'AudioMuxParams' in types
    assert 'ThumbnailParams' in types


def test_editing_plan_json_roundtrip():
    """Plan can be serialized to JSON and back."""
    plan = EditingPlan(
        resolution='1080x1920',
        fps=30,
        ffmpeg_preset='ultrafast',
        steps=[
            ImageSegmentParams(order=0, image_path='/tmp/img.png', duration_sec=5.0),
            ColorSegmentParams(order=1, duration_sec=3.0, color_hex='#FF0000'),
            TransitionParams(effect='fade', duration_sec=0.5),
            TextOverlayParams(text='Hello World', font_size=56, start_sec=1.0, duration_sec=2.0),
            LogoOverlayParams(logo_path='/tmp/logo.png', position='bottom-left'),
            AudioMuxParams(audio_path='/tmp/narration.mp3'),
            MusicMixParams(music_path='/tmp/music.mp3', volume=0.15),
            ThumbnailParams(time_sec=2.5),
        ],
    )
    json_str = plan.to_json()
    parsed = json.loads(json_str)
    assert parsed['version'] == '1.0'
    assert parsed['resolution'] == '1080x1920'
    assert len(parsed['steps']) == 8

    restored = EditingPlan.from_json(json_str)
    assert restored.resolution == '1080x1920'
    assert len(restored.steps) == 8
    assert len(restored.segment_steps) == 2


def test_image_segment_zoom_directions():
    """Both zoom directions produce valid params."""
    zoom_in = ImageSegmentParams(order=0, image_path='/tmp/a.png', duration_sec=5.0, zoom=ZoomDirection.ZOOM_IN)
    zoom_out = ImageSegmentParams(order=1, image_path='/tmp/b.png', duration_sec=5.0, zoom=ZoomDirection.ZOOM_OUT)
    assert zoom_in.zoom == ZoomDirection.ZOOM_IN
    assert zoom_out.zoom == ZoomDirection.ZOOM_OUT


def test_logo_overlay_positions():
    """All position values are accepted."""
    for pos in ['top-right', 'top-left', 'bottom-right', 'bottom-left']:
        p = LogoOverlayParams(logo_path='/tmp/logo.png', position=pos)
        assert p.position == pos


def test_video_segment_params():
    """VideoSegmentParams stores all fields correctly."""
    seg = VideoSegmentParams(order=0, video_path='/tmp/clip.mp4', duration_sec=4.0, caption_text='Hello')
    assert seg.video_path == '/tmp/clip.mp4'
    assert seg.caption_text == 'Hello'
    assert seg.fps == 24


# ── Planner tests ──────────────────────────────────────────────────────────

def test_planner_basic_storyboard():
    """Planner generates correct steps from a simple storyboard."""
    storyboard = [
        StoryboardSegment(order=0, script_line='Line one', image_asset_id='img-1', start_sec=0.0, duration_sec=5.0),
        StoryboardSegment(order=1, script_line='Line two', image_asset_id='img-2', start_sec=5.0, duration_sec=4.0),
    ]
    effects = VideoEffectsConfig(
        transition=TransitionConfig(xfade_name='fade', duration=0.5),
    )

    plan = generate_plan(
        storyboard=storyboard,
        effects_config=effects,
        aspect_ratio='16:9',
    )

    assert plan.resolution == '1920x1080'
    # Should have 2 color segments (no resolve_asset_fn) + transition + thumbnail
    segs = plan.segment_steps
    assert len(segs) == 2
    assert plan.transition_step is not None
    assert plan.transition_step.effect == 'fade'


def test_planner_with_asset_resolver(tmp_path: Path):
    """Planner uses resolve_asset_fn to set image paths."""
    storyboard = [
        StoryboardSegment(order=0, script_line='Scene 1', image_asset_id='img-1', start_sec=0.0, duration_sec=5.0),
    ]
    effects = VideoEffectsConfig()

    # Create a real temp file so Path.exists() passes in the planner
    img_file = tmp_path / 'resolved_img-1.png'
    img_file.write_bytes(b'\x89PNG\r\n')

    def mock_resolver(asset_id: str, project_id: str) -> Path | None:
        return tmp_path / f'resolved_{asset_id}.png'

    plan = generate_plan(
        storyboard=storyboard,
        effects_config=effects,
        resolve_asset_fn=mock_resolver,
        project_id='proj-1',
    )

    segs = plan.segment_steps
    assert len(segs) == 1
    assert isinstance(segs[0], ImageSegmentParams)
    assert segs[0].image_path == str(img_file)


def test_planner_broll_segments():
    """Planner creates VideoSegmentParams for B-roll segments."""
    storyboard = [
        StoryboardSegment(
            order=0, script_line='B-roll scene', image_asset_id='img-1',
            start_sec=0.0, duration_sec=4.0, media_type='video', video_path='/tmp/broll.mp4',
        ),
    ]
    effects = VideoEffectsConfig()

    plan = generate_plan(storyboard=storyboard, effects_config=effects)
    segs = plan.segment_steps
    assert len(segs) == 1
    assert isinstance(segs[0], VideoSegmentParams)
    assert segs[0].video_path == '/tmp/broll.mp4'


def test_planner_includes_overlays():
    """Planner adds text overlays when effects_config has them."""
    storyboard = [
        StoryboardSegment(order=0, script_line='Scene 1', image_asset_id='img-1', start_sec=0.0, duration_sec=5.0),
    ]
    effects = VideoEffectsConfig(
        title_overlay=TextOverlay(text='My Product', font_size=56, duration_sec=3.0),
        cta_overlay=TextOverlay(text='Buy Now', font_size=44, y='h-100', duration_sec=4.0),
    )

    plan = generate_plan(storyboard=storyboard, effects_config=effects)
    text_steps = [s for s in plan.steps if isinstance(s, TextOverlayParams)]
    assert len(text_steps) == 2
    assert text_steps[0].text == 'My Product'
    assert text_steps[1].text == 'Buy Now'


def test_planner_includes_audio_and_music():
    """Planner adds audio mux and music mix when paths provided."""
    storyboard = [
        StoryboardSegment(order=0, script_line='Scene', image_asset_id='img-1', start_sec=0.0, duration_sec=5.0),
    ]
    effects = VideoEffectsConfig()

    # Create temp files so existence checks pass
    import tempfile
    with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as af:
        af.write(b'x' * 200)
        audio = Path(af.name)
    with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as mf:
        mf.write(b'x' * 200)
        music = Path(mf.name)

    try:
        plan = generate_plan(
            storyboard=storyboard,
            effects_config=effects,
            audio_path=audio,
            music_path=music,
        )
        audio_steps = [s for s in plan.steps if isinstance(s, AudioMuxParams)]
        music_steps = [s for s in plan.steps if isinstance(s, MusicMixParams)]
        assert len(audio_steps) == 1
        assert len(music_steps) == 1
    finally:
        audio.unlink(missing_ok=True)
        music.unlink(missing_ok=True)


def test_planner_always_adds_thumbnail():
    """Planner always includes a thumbnail step."""
    storyboard = [
        StoryboardSegment(order=0, script_line='Scene', image_asset_id='img-1', start_sec=0.0, duration_sec=5.0),
    ]
    effects = VideoEffectsConfig()
    plan = generate_plan(storyboard=storyboard, effects_config=effects)
    thumb_steps = [s for s in plan.steps if isinstance(s, ThumbnailParams)]
    assert len(thumb_steps) == 1


def test_planner_aspect_ratios():
    """Planner resolves correct resolution for each aspect ratio."""
    storyboard = [
        StoryboardSegment(order=0, script_line='Scene', image_asset_id='img-1', start_sec=0.0, duration_sec=5.0),
    ]
    effects = VideoEffectsConfig()

    for ar, expected_res in [('16:9', '1920x1080'), ('9:16', '1080x1920'), ('1:1', '1080x1080')]:
        plan = generate_plan(storyboard=storyboard, effects_config=effects, aspect_ratio=ar)
        assert plan.resolution == expected_res, f'Failed for {ar}'


def test_planner_no_transition_when_none():
    """Planner omits transition step when transition is 'none'."""
    storyboard = [
        StoryboardSegment(order=0, script_line='A', image_asset_id='i1', start_sec=0.0, duration_sec=5.0),
        StoryboardSegment(order=1, script_line='B', image_asset_id='i2', start_sec=5.0, duration_sec=5.0),
    ]
    effects = VideoEffectsConfig(
        transition=TransitionConfig(xfade_name=None, duration=0.0),
    )
    plan = generate_plan(storyboard=storyboard, effects_config=effects)
    assert plan.transition_step is None


# ── Compiler unit tests (no FFmpeg needed) ─────────────────────────────────

def test_compiler_empty_plan():
    """Compiler returns error for empty plan."""
    from app.services.editing.compiler import PlanCompiler
    compiler = PlanCompiler(ffmpeg_path='/nonexistent/ffmpeg')
    plan = EditingPlan()

    result = compiler.compile(plan, Path('/tmp'))
    assert not result.success
    assert any('No segment steps' in e for e in result.errors)


def test_compilation_result_defaults():
    """CompilationResult has sensible defaults."""
    from app.services.editing.compiler import CompilationResult
    r = CompilationResult()
    assert r.video_path is None
    assert r.thumbnail_path is None
    assert r.duration_sec == 0.0
    assert not r.success
    assert r.errors == []
    assert r.warnings == []


# ── LLM Planner tests ─────────────────────────────────────────────────────

def test_llm_planner_mock_returns_deterministic():
    """LLM planner in mock mode returns the deterministic plan."""
    from app.services.editing.llm_planner import generate_plan_with_llm

    storyboard = [
        StoryboardSegment(order=0, script_line='Scene 1', image_asset_id='img-1', start_sec=0.0, duration_sec=5.0),
        StoryboardSegment(order=1, script_line='Scene 2', image_asset_id='img-2', start_sec=5.0, duration_sec=4.0),
    ]
    effects = VideoEffectsConfig()

    plan = generate_plan_with_llm(
        product_description='A great product',
        storyboard=storyboard,
        effects_config=effects,
        use_mock=True,
    )

    assert isinstance(plan, EditingPlan)
    assert len(plan.segment_steps) == 2
    # Should always have thumbnail
    thumb_steps = [s for s in plan.steps if isinstance(s, ThumbnailParams)]
    assert len(thumb_steps) == 1


def test_llm_planner_no_client_returns_deterministic():
    """LLM planner without bedrock_client falls back to deterministic."""
    from app.services.editing.llm_planner import generate_plan_with_llm

    storyboard = [
        StoryboardSegment(order=0, script_line='Scene', image_asset_id='img-1', start_sec=0.0, duration_sec=5.0),
    ]
    effects = VideoEffectsConfig()

    plan = generate_plan_with_llm(
        product_description='Product',
        storyboard=storyboard,
        effects_config=effects,
        use_mock=False,
        bedrock_client=None,
    )

    assert isinstance(plan, EditingPlan)
    assert len(plan.segment_steps) == 1


def test_llm_planner_exception_returns_fallback():
    """LLM planner gracefully falls back when bedrock raises an exception."""
    from app.services.editing.llm_planner import generate_plan_with_llm

    class FakeBedrock:
        def invoke_model(self, **kwargs):
            raise RuntimeError('Simulated Bedrock failure')

    storyboard = [
        StoryboardSegment(order=0, script_line='Scene', image_asset_id='img-1', start_sec=0.0, duration_sec=5.0),
    ]
    effects = VideoEffectsConfig()

    plan = generate_plan_with_llm(
        product_description='Product',
        storyboard=storyboard,
        effects_config=effects,
        use_mock=False,
        bedrock_client=FakeBedrock(),
    )

    # Should still return a valid plan (deterministic fallback)
    assert isinstance(plan, EditingPlan)
    assert len(plan.segment_steps) == 1


def test_llm_planner_with_brand_kit_assets():
    """LLM planner passes brand kit assets to the prompt."""
    from app.services.editing.llm_planner import generate_plan_with_llm

    storyboard = [
        StoryboardSegment(order=0, script_line='Scene', image_asset_id='img-1', start_sec=0.0, duration_sec=5.0),
    ]
    effects = VideoEffectsConfig(
        logo_path=Path('/tmp/logo.png'),
        brand_font_path=Path('/tmp/font.ttf'),
        intro_clip_path=Path('/tmp/intro.mp4'),
        outro_clip_path=Path('/tmp/outro.mp4'),
    )

    # Mock mode — just ensure it doesn't crash with brand kit fields
    plan = generate_plan_with_llm(
        product_description='Product with brand kit',
        storyboard=storyboard,
        effects_config=effects,
        use_mock=True,
    )
    assert isinstance(plan, EditingPlan)
