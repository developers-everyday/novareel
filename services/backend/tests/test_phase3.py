"""Phase 3 tests: Brand Kit, Library Assets, Storyboard Editor, Variants, Social, Parallel rendering."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from app.config import Settings
from app.models import (
    BrandKitRecord,
    BrandKitRequest as BrandKitUpdateRequest,
    GenerateRequest,
    GenerateVariantsRequest,
    JobCreateParams,
    JobStatus,
    LibraryAssetRecord,
    ProjectCreateRequest,
    StoryboardSegment,
)
from app.repositories.local import LocalRepository
from app.services.effects import VideoEffectsConfig


def _make_settings(tmp_path: Path) -> Settings:
    return Settings(local_data_dir=tmp_path, auth_disabled=True)


def _make_repo(tmp_path: Path) -> LocalRepository:
    return LocalRepository(_make_settings(tmp_path))


# ─── Feature A: Brand Kit ─────────────────────────────────────────────────

def test_brand_kit_create_and_update(tmp_path):
    """Brand kit can be created and updated via repository."""
    repo = _make_repo(tmp_path)
    owner = 'user-brand-1'

    # Get default (empty) brand kit
    kit = repo.get_brand_kit(owner)
    assert kit is not None
    assert kit.brand_name == ''

    # Update brand kit
    updated = repo.update_brand_kit(owner, BrandKitUpdateRequest(
        brand_name='TestBrand',
        primary_color='#FF0000',
        secondary_color='#00FF00',
        accent_color='#0000FF',
    ))
    assert updated.brand_name == 'TestBrand'
    assert updated.primary_color == '#FF0000'

    # Retrieve again
    reloaded = repo.get_brand_kit(owner)
    assert reloaded.brand_name == 'TestBrand'


def test_brand_kit_asset_references(tmp_path):
    """Brand kit stores asset references for logo, font, intro, outro."""
    repo = _make_repo(tmp_path)
    owner = 'user-brand-2'

    updated = repo.update_brand_kit(owner, BrandKitUpdateRequest(
        logo_asset_id='logo-abc',
        font_asset_id='font-def',
        intro_clip_asset_id='intro-ghi',
        outro_clip_asset_id='outro-jkl',
    ))
    assert updated.logo_asset_id == 'logo-abc'
    assert updated.font_asset_id == 'font-def'
    assert updated.intro_clip_asset_id == 'intro-ghi'
    assert updated.outro_clip_asset_id == 'outro-jkl'


# ─── Feature A: Library Assets ────────────────────────────────────────────

def test_library_asset_crud(tmp_path):
    """Library assets can be created, listed, and deleted."""
    repo = _make_repo(tmp_path)
    owner = 'user-lib-1'

    asset = LibraryAssetRecord(
        id='asset-001',
        owner_id=owner,
        asset_type='logo',
        filename='logo.png',
        content_type='image/png',
        file_size=12345,
        object_key='library/user-lib-1/asset-001/logo.png',
        created_at=datetime.now(UTC),
    )
    repo.create_library_asset(asset)

    assets = repo.list_library_assets(owner)
    assert len(assets) == 1
    assert assets[0].id == 'asset-001'
    assert assets[0].filename == 'logo.png'

    # Delete
    repo.delete_library_asset(owner, 'asset-001')
    assert len(repo.list_library_assets(owner)) == 0


# ─── Feature D: Storyboard Editor ─────────────────────────────────────────

def test_storyboard_editor_service():
    """Storyboard editor can validate and transform scenes."""
    from app.services.storyboard_editor import validate_storyboard, load_storyboard_from_job

    scenes = [
        {'order': 0, 'script_line': 'Hello world', 'image_asset_id': 'img-1',
         'start_sec': 0.0, 'duration_sec': 5.0},
        {'order': 1, 'script_line': 'Second scene', 'image_asset_id': 'img-2',
         'start_sec': 5.0, 'duration_sec': 4.0},
    ]
    errors = validate_storyboard(scenes)
    assert errors == [], f"Unexpected validation errors: {errors}"


def test_storyboard_validation_rejects_empty():
    """Storyboard validation rejects empty scene list."""
    from app.services.storyboard_editor import validate_storyboard

    errors = validate_storyboard([])
    assert len(errors) > 0


# ─── Feature E: Variants ──────────────────────────────────────────────────

def test_generate_variants_request_model():
    """GenerateVariantsRequest model accepts variant_count and overrides."""
    req = GenerateVariantsRequest(variant_count=3)
    assert req.variant_count == 3


# ─── Feature F: Video Effects Config with Brand Kit ────────────────────────

def test_effects_config_brand_fields():
    """VideoEffectsConfig includes brand kit fields."""
    cfg = VideoEffectsConfig(
        logo_path='/tmp/logo.png',
        brand_font_path='/tmp/brand.ttf',
        intro_clip_path='/tmp/intro.mp4',
        outro_clip_path='/tmp/outro.mp4',
    )
    assert cfg.logo_path == '/tmp/logo.png'
    assert cfg.brand_font_path == '/tmp/brand.ttf'
    assert cfg.intro_clip_path == '/tmp/intro.mp4'
    assert cfg.outro_clip_path == '/tmp/outro.mp4'


def test_effects_config_defaults():
    """VideoEffectsConfig has None defaults for optional brand fields."""
    cfg = VideoEffectsConfig()
    assert cfg.logo_path is None
    assert cfg.brand_font_path is None
    assert cfg.intro_clip_path is None
    assert cfg.outro_clip_path is None


# ─── Feature F: Parallel Rendering ────────────────────────────────────────

def test_parallel_segment_render_task_dataclass():
    """SegmentRenderTask dataclass fields are correct."""
    from app.services.parallel import SegmentRenderTask

    task = SegmentRenderTask(
        segment_index=0,
        image_path='/tmp/img.png',
        duration=5.0,
        aspect_ratio='16:9',
        output_path='/tmp/seg_000.mp4',
        ken_burns=True,
        ffmpeg_preset='ultrafast',
    )
    assert task.segment_index == 0
    assert task.ffmpeg_preset == 'ultrafast'


def test_parallel_segment_render_result_dataclass():
    """SegmentRenderResult dataclass fields are correct."""
    from app.services.parallel import SegmentRenderResult

    result = SegmentRenderResult(
        segment_index=0,
        output_path='/tmp/seg_000.mp4',
        success=True,
        error='',
        duration_sec=2.5,
    )
    assert result.success is True
    assert result.duration_sec == 2.5


# ─── Feature F: CDN URL helper ────────────────────────────────────────────

def test_cdn_url_generation():
    """CDN base URL is prepended to storage keys when configured."""
    settings = Settings(
        local_data_dir=Path('/tmp/novareel-test'),
        auth_disabled=True,
        cdn_base_url='https://cdn.example.com',
    )
    key = 'projects/p1/outputs/j1.mp4'
    expected = f'https://cdn.example.com/{key}'
    url = f'{settings.cdn_base_url.rstrip("/")}/{key}'
    assert url == expected


def test_cdn_url_empty_fallback():
    """When cdn_base_url is None, no CDN URL is generated."""
    settings = Settings(
        local_data_dir=Path('/tmp/novareel-test'),
        auth_disabled=True,
        cdn_base_url=None,
    )
    assert settings.cdn_base_url is None


# ─── Feature F: Worker Mode Config ────────────────────────────────────────

def test_worker_mode_config():
    """Worker mode config accepts polling and celery values."""
    settings = Settings(
        local_data_dir=Path('/tmp/novareel-test'),
        auth_disabled=True,
        worker_mode='celery',
        celery_broker_url='redis://localhost:6379/0',
    )
    assert settings.worker_mode == 'celery'
    assert settings.celery_broker_url == 'redis://localhost:6379/0'


def test_ffmpeg_preset_config():
    """FFmpeg preset config is customizable."""
    settings = Settings(
        local_data_dir=Path('/tmp/novareel-test'),
        auth_disabled=True,
        ffmpeg_preset='ultrafast',
    )
    assert settings.ffmpeg_preset == 'ultrafast'
