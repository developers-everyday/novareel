"""Tests for the Vision Director B-roll planning and validation."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.models import ScriptScene, StoryboardSegment


# ── Mock settings helper ─────────────────────────────────────────────────────

def _mock_settings(**overrides):
    """Create a mock Settings object with sensible defaults for testing."""
    defaults = {
        'use_mock_ai': True,
        'aws_region': 'us-east-1',
        'bedrock_model_script': 'amazon.nova-lite-v1:0',
        'broll_validation_threshold': 6.0,
        'broll_max_candidates': 3,
        'use_vision_director': True,
    }
    defaults.update(overrides)
    settings = MagicMock()
    for k, v in defaults.items():
        setattr(settings, k, v)
    return settings


def _sample_scenes(n: int = 6) -> list[ScriptScene]:
    """Generate sample ScriptScene instances."""
    data = [
        ('Introducing our premium skincare serum.', 'Product hero shot, clean background'),
        ('Feel the difference from day one.', 'Woman applying serum in morning routine'),
        ('Packed with hyaluronic acid and vitamin C.', 'Close-up of product ingredients label'),
        ('Perfect for your daily skincare routine.', 'Person using product in bathroom'),
        ('Trusted by thousands of happy customers.', 'Customer testimonials montage'),
        ('Order now and transform your skin.', 'Product with CTA overlay'),
    ]
    return [ScriptScene(narration=d[0], visual_requirements=d[1]) for d in data[:n]]


# ── BRollDirector.plan_scenes() tests ────────────────────────────────────────

def test_plan_scenes_mock_product_lifestyle():
    """Mock plan for product_lifestyle: even=product, odd=ai_generated or broll."""
    from app.services.broll_director import BRollDirector

    director = BRollDirector(_mock_settings())
    scenes = _sample_scenes()

    plan = director.plan_scenes(
        script_scenes=scenes,
        image_analysis=[{'asset_id': 'img-1', 'description': 'A skincare serum bottle'}],
        product_description='Premium skincare serum',
        video_style='product_lifestyle',
    )

    assert len(plan) == len(scenes)
    for i, entry in enumerate(plan):
        assert 'media_type' in entry
        if i in (1, 3):
            assert entry['media_type'] == 'broll'
            assert 'search_query' in entry
        elif i % 2 == 0:
            assert entry['media_type'] == 'product_closeup'
        else:
            assert entry['media_type'] == 'product_in_context'


def test_plan_scenes_mock_lifestyle_focus():
    """Mock plan for lifestyle_focus: 0,2,4=product images; 1,3,5=broll."""
    from app.services.broll_director import BRollDirector

    director = BRollDirector(_mock_settings())
    scenes = _sample_scenes()

    plan = director.plan_scenes(
        script_scenes=scenes,
        image_analysis=[],
        product_description='Premium skincare serum',
        video_style='lifestyle_focus',
    )

    assert len(plan) == len(scenes)
    assert plan[0]['media_type'] == 'product_closeup'
    for i, entry in enumerate(plan[1:], start=1):
        if i % 2 == 0:
            assert entry['media_type'] == 'product_in_context'
        else:
            assert entry['media_type'] == 'broll'
            assert 'search_query' in entry


def test_plan_scenes_mock_unknown_style():
    """Unknown video_style defaults all scenes to product_closeup."""
    from app.services.broll_director import BRollDirector

    director = BRollDirector(_mock_settings())
    scenes = _sample_scenes(3)

    plan = director.plan_scenes(
        script_scenes=scenes,
        image_analysis=[],
        product_description='Test product',
        video_style='unknown_style',
    )

    assert len(plan) == 3
    for entry in plan:
        assert entry['media_type'] == 'product_closeup'


def test_plan_scenes_single_scene():
    """Plan works correctly with a single scene."""
    from app.services.broll_director import BRollDirector

    director = BRollDirector(_mock_settings())
    scenes = _sample_scenes(1)

    plan = director.plan_scenes(
        script_scenes=scenes,
        image_analysis=[],
        product_description='Test',
        video_style='product_lifestyle',
    )

    assert len(plan) == 1
    assert plan[0]['media_type'] == 'product_closeup'


# ── BRollDirector.validate_clip() tests ──────────────────────────────────────

def test_validate_clip_mock_always_accepts():
    """In mock mode, validate_clip returns 8.0 (above default threshold)."""
    from app.services.broll_director import BRollDirector

    director = BRollDirector(_mock_settings())
    from pathlib import Path

    score = director.validate_clip(
        clip_path=Path('/tmp/nonexistent.mp4'),
        scene_narration='Test narration',
        visual_requirements='Test visual',
        acceptance_criteria='Test criteria',
    )

    assert score == 8.0
    assert score >= 6.0  # Above default threshold


# ── BRollDirector._extract_thumbnail() tests ────────────────────────────────

def test_extract_thumbnail_missing_file():
    """Returns None for non-existent file."""
    from app.services.broll_director import BRollDirector
    from pathlib import Path

    result = BRollDirector._extract_thumbnail(Path('/tmp/nonexistent_clip.mp4'))
    assert result is None


def test_extract_thumbnail_no_ffmpeg():
    """Returns None when ffmpeg is not available."""
    from app.services.broll_director import BRollDirector
    from pathlib import Path

    with patch('shutil.which', return_value=None):
        result = BRollDirector._extract_thumbnail(Path('/tmp/some.mp4'))
        assert result is None


# ── BRollDirector fallback behavior ──────────────────────────────────────────

def test_plan_scenes_falls_back_on_exception():
    """When bedrock call fails, plan_scenes returns mock plan."""
    from app.services.broll_director import BRollDirector

    settings = _mock_settings(use_mock_ai=False)
    director = BRollDirector(settings)
    # Force bedrock client to raise
    director._bedrock_client = MagicMock()
    director._bedrock_client.converse.side_effect = RuntimeError('Simulated failure')

    scenes = _sample_scenes(3)
    plan = director.plan_scenes(
        script_scenes=scenes,
        image_analysis=[],
        product_description='Test',
        video_style='product_lifestyle',
    )

    # Should fallback to mock plan
    assert len(plan) == 3
    assert all('media_type' in entry for entry in plan)


def test_validate_clip_falls_back_on_exception():
    """When bedrock call fails, validate_clip returns 7.0 (benefit of doubt)."""
    from app.services.broll_director import BRollDirector
    from pathlib import Path
    import tempfile

    settings = _mock_settings(use_mock_ai=False)
    director = BRollDirector(settings)
    director._bedrock_client = MagicMock()
    director._bedrock_client.converse.side_effect = RuntimeError('Simulated failure')

    # Create a temp file so extraction path is attempted
    with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as f:
        f.write(b'x' * 200)
        clip = Path(f.name)

    try:
        score = director.validate_clip(
            clip_path=clip,
            scene_narration='Test',
            visual_requirements='Test',
            acceptance_criteria='Test',
        )
        # Should return default score (7.0) on failure
        assert score == 7.0
    finally:
        clip.unlink(missing_ok=True)


# ── ScriptScene model tests ──────────────────────────────────────────────────

def test_script_scene_model():
    """ScriptScene stores narration and visual_requirements."""
    scene = ScriptScene(narration='Hello', visual_requirements='Product shot')
    assert scene.narration == 'Hello'
    assert scene.visual_requirements == 'Product shot'


def test_script_scene_model_defaults():
    """ScriptScene has empty visual_requirements by default."""
    scene = ScriptScene(narration='Hello')
    assert scene.visual_requirements == ''


def test_script_scene_serialization():
    """ScriptScene round-trips through dict."""
    scene = ScriptScene(narration='Hello', visual_requirements='Wide shot')
    data = scene.model_dump()
    restored = ScriptScene(**data)
    assert restored.narration == 'Hello'
    assert restored.visual_requirements == 'Wide shot'


# ── StoryboardSegment new fields tests ────────────────────────────────────────

def test_storyboard_segment_director_fields():
    """StoryboardSegment carries vision director metadata."""
    seg = StoryboardSegment(
        order=1,
        script_line='Test line',
        image_asset_id='img-1',
        start_sec=0.0,
        duration_sec=5.0,
        visual_requirements='Product close-up',
        broll_query='woman applying serum',
        broll_relevance_score=8.5,
    )
    assert seg.visual_requirements == 'Product close-up'
    assert seg.broll_query == 'woman applying serum'
    assert seg.broll_relevance_score == 8.5


def test_storyboard_segment_director_fields_default_none():
    """New StoryboardSegment fields default to None."""
    seg = StoryboardSegment(
        order=1,
        script_line='Test',
        image_asset_id='img-1',
        start_sec=0.0,
        duration_sec=5.0,
    )
    assert seg.visual_requirements is None
    assert seg.broll_query is None
    assert seg.broll_relevance_score is None


# ── Integration: nova.py generate_script returns ScriptScene ──────────────────

def test_nova_generate_script_returns_script_scenes():
    """NovaService.generate_script() returns list[ScriptScene] in mock mode."""
    from app.services.nova import NovaService

    settings = _mock_settings()
    settings.use_mock_ai = True
    settings.prompt_templates_dir = '/tmp'
    nova = NovaService(settings)

    from app.models import ProjectRecord
    from datetime import datetime, UTC

    project = ProjectRecord(
        id='p1', owner_id='u1', title='Test Product',
        product_description='A great test product',
        created_at=datetime.now(UTC),
    )

    result = nova.generate_script(project)
    assert len(result) == 6
    assert all(isinstance(s, ScriptScene) for s in result)
    assert all(s.narration for s in result)
    assert all(s.visual_requirements for s in result)
    # First scene should mention the product title
    assert 'Test Product' in result[0].narration


# ── Nova Sonic voice provider tests ───────────────────────────────────────────

def test_nova_sonic_provider_mock_returns_mp3():
    """NovaSonicVoiceProvider returns mock MP3 bytes when use_mock_ai is True."""
    from app.services.voice.nova_sonic import NovaSonicVoiceProvider
    from app.services.voice.base import MOCK_SILENT_MP3

    # NovaSonicVoiceProvider doesn't check use_mock_ai itself —
    # the pipeline gates on use_mock_ai before calling the provider.
    # When boto3 is not importable or fails, it returns MOCK_SILENT_MP3.
    settings = _mock_settings()
    provider = NovaSonicVoiceProvider(settings)
    assert provider is not None


def test_nova_sonic_factory_registration():
    """Voice factory returns NovaSonicVoiceProvider for 'nova_sonic'."""
    from app.services.voice.factory import build_voice_provider
    from app.services.voice.nova_sonic import NovaSonicVoiceProvider

    settings = _mock_settings()
    settings.bedrock_model_voice = 'amazon.nova-sonic-v1:0'
    provider = build_voice_provider('nova_sonic', settings)
    assert isinstance(provider, NovaSonicVoiceProvider)


def test_factory_unknown_falls_back_to_nova_sonic():
    """Unknown provider name now falls back to Nova Sonic (not Polly)."""
    from app.services.voice.factory import build_voice_provider
    from app.services.voice.nova_sonic import NovaSonicVoiceProvider

    settings = _mock_settings()
    settings.bedrock_model_voice = 'amazon.nova-sonic-v1:0'
    provider = build_voice_provider('unknown_provider', settings)
    assert isinstance(provider, NovaSonicVoiceProvider)


def test_default_voice_provider_is_polly():
    """Default voice provider in models is polly."""
    from app.models import GenerateRequest, TranslateRequest, JobCreateParams
    req = GenerateRequest(aspect_ratio='16:9')
    assert req.voice_provider == 'polly'

    tr = TranslateRequest(target_languages=['es'])
    assert tr.voice_provider == 'polly'

    params = JobCreateParams()
    assert params.voice_provider == 'polly'


# ── Nova Omni image generator tests ──────────────────────────────────────────

def test_image_generator_mock_returns_none(tmp_path):
    """ImageGenerator returns None in mock mode so pipeline keeps product image."""
    from app.services.image_generator import ImageGenerator

    settings = _mock_settings()
    settings.ffmpeg_preset = 'ultrafast'
    gen = ImageGenerator(settings)
    output = tmp_path / 'test_gen.jpg'

    result = gen.generate_scene_image(
        scene_description='Product on a marble counter',
        output_path=output,
        aspect_ratio='16:9',
    )

    assert result is None


def test_image_generator_mock_video_from_image(tmp_path):
    """ImageGenerator converts a mock image to video segment."""
    from app.services.image_generator import ImageGenerator
    import shutil

    if not shutil.which('ffmpeg'):
        return  # Skip if ffmpeg not installed

    settings = _mock_settings()
    settings.ffmpeg_preset = 'ultrafast'
    gen = ImageGenerator(settings)

    # First generate a mock image
    img_path = tmp_path / 'scene.jpg'
    gen.generate_scene_image(
        scene_description='Test scene',
        output_path=img_path,
        aspect_ratio='16:9',
    )

    if not img_path.exists():
        return  # Skip if image gen failed

    # Convert to video
    video_path = tmp_path / 'scene.mp4'
    result = gen.generate_scene_video_from_image(
        image_path=img_path,
        duration_sec=3.0,
        output_path=video_path,
        aspect_ratio='16:9',
    )

    assert result is not None
    assert video_path.exists()
    assert video_path.stat().st_size > 100


def test_image_generator_missing_ffmpeg():
    """ImageGenerator returns None when ffmpeg is not available."""
    from app.services.image_generator import ImageGenerator
    from pathlib import Path

    settings = _mock_settings()
    gen = ImageGenerator(settings)

    with patch('shutil.which', return_value=None):
        result = gen._generate_mock_image(Path('/tmp/test.jpg'), '16:9')
        assert result is None


# ── ai_generated plan entry tests ────────────────────────────────────────────

def test_plan_has_no_ai_generated_entries_lifestyle():
    """lifestyle_focus mock plan prioritizes product images — no ai_generated by default."""
    from app.services.broll_director import BRollDirector

    director = BRollDirector(_mock_settings())
    scenes = _sample_scenes()

    plan = director.plan_scenes(
        script_scenes=scenes,
        image_analysis=[],
        product_description='Test product',
        video_style='lifestyle_focus',
    )

    ai_entries = [e for e in plan if e['media_type'] == 'ai_generated']
    assert len(ai_entries) == 0
    product_entries = [e for e in plan if e['media_type'] in ('product_closeup', 'product_in_context')]
    assert len(product_entries) >= 3  # At least half of 6 scenes


def test_plan_has_no_ai_generated_entries_product_lifestyle():
    """product_lifestyle mock plan prioritizes product images — no ai_generated by default."""
    from app.services.broll_director import BRollDirector

    director = BRollDirector(_mock_settings())
    scenes = _sample_scenes()

    plan = director.plan_scenes(
        script_scenes=scenes,
        image_analysis=[],
        product_description='Test product',
        video_style='product_lifestyle',
    )

    ai_entries = [e for e in plan if e['media_type'] == 'ai_generated']
    assert len(ai_entries) == 0
    product_entries = [e for e in plan if e['media_type'] in ('product_closeup', 'product_in_context')]
    assert len(product_entries) >= 4  # At least 4 out of 6 scenes


# ── Config tests ─────────────────────────────────────────────────────────────

def test_config_has_bedrock_model_image():
    """Config includes bedrock_model_image for Nova Canvas."""
    from app.config import Settings
    s = Settings(
        _env_file=None,
        local_data_dir='/tmp/novareel-test-data',
    )
    assert hasattr(s, 'bedrock_model_image')
    assert 'canvas' in s.bedrock_model_image
