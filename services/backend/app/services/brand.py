"""Brand Kit resolution — resolve brand assets and merge into video pipeline."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from app.config import Settings
from app.models import BrandKitRecord, JobCreateParams
from app.repositories.base import Repository
from app.services.storage import StorageService

logger = logging.getLogger(__name__)


@dataclass
class BrandKitConfig:
  """Resolved brand kit with local file paths for all assets."""
  brand_name: str = ''
  primary_color: str = '#1E40AF'
  secondary_color: str = '#F59E0B'
  accent_color: str = '#10B981'
  logo_path: Path | None = None
  font_path: Path | None = None
  intro_clip_path: Path | None = None
  outro_clip_path: Path | None = None
  custom_music_paths: list[Path] = field(default_factory=list)


class BrandService:
  """Resolve brand kit assets for a given user and merge into video pipeline."""

  def __init__(self, settings: Settings, storage: StorageService):
    self._settings = settings
    self._storage = storage
    self._storage_root = settings.local_data_dir / settings.local_storage_dir

  def resolve_brand_kit(self, owner_id: str, repo: Repository) -> BrandKitConfig | None:
    """Load the user's brand kit and resolve all asset paths.

    Returns a BrandKitConfig with local paths to logo, font, intro/outro clips.
    Returns None if the user has no brand kit configured.
    """
    kit = repo.get_brand_kit(owner_id)
    if not kit:
      return None

    config = BrandKitConfig(
      brand_name=kit.brand_name,
      primary_color=kit.primary_color,
      secondary_color=kit.secondary_color,
      accent_color=kit.accent_color,
    )

    # Resolve each referenced library asset to a local file path
    if kit.logo_asset_id:
      config.logo_path = self._resolve_library_asset(kit.logo_asset_id, repo)

    if kit.font_asset_id:
      config.font_path = self._resolve_library_asset(kit.font_asset_id, repo)

    if kit.intro_clip_asset_id:
      config.intro_clip_path = self._resolve_library_asset(kit.intro_clip_asset_id, repo)

    if kit.outro_clip_asset_id:
      config.outro_clip_path = self._resolve_library_asset(kit.outro_clip_asset_id, repo)

    for music_id in kit.custom_music_asset_ids:
      path = self._resolve_library_asset(music_id, repo)
      if path:
        config.custom_music_paths.append(path)

    return config

  def _resolve_library_asset(self, asset_id: str, repo: Repository) -> Path | None:
    """Look up a library asset record and return its local storage path, or None."""
    asset = repo.get_library_asset(asset_id)
    if not asset:
      logger.warning('Library asset %s not found in repo', asset_id)
      return None

    path = self._storage_root / asset.object_key
    if not path.exists():
      logger.warning('Library asset file not found on disk: %s', path)
      return None

    return path

  def build_effects_config(
    self,
    brand_kit: BrandKitConfig | None,
    job,
  ):
    """Merge brand kit assets with per-job settings to build final VideoEffectsConfig.

    Priority: per-job settings > brand kit defaults > system defaults.
    Returns a VideoEffectsConfig with brand assets applied.
    """
    from app.services.effects import VideoEffectsConfig, TextOverlay

    effects = VideoEffectsConfig.from_job(job)

    if not brand_kit:
      return effects

    # Apply brand colors to title overlay if present
    if effects.title_overlay and brand_kit.primary_color:
      effects.title_overlay.font_color = brand_kit.primary_color

    # Apply brand colors to CTA overlay if present
    if effects.cta_overlay and brand_kit.accent_color:
      effects.cta_overlay.font_color = brand_kit.accent_color

    # Store brand asset paths on the effects config for the video renderer
    effects.logo_path = brand_kit.logo_path
    effects.intro_clip_path = brand_kit.intro_clip_path
    effects.outro_clip_path = brand_kit.outro_clip_path
    effects.brand_font_path = brand_kit.font_path
    effects.brand_colors = {
      'primary': brand_kit.primary_color,
      'secondary': brand_kit.secondary_color,
      'accent': brand_kit.accent_color,
    }

    return effects
