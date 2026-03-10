"""Storyboard editor — edit/validate storyboard, approve & resume pipeline."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from app.models import GenerationJobRecord, JobStatus
from app.repositories.base import Repository
from app.services.storage import StorageService

logger = logging.getLogger(__name__)


@dataclass
class StoryboardScene:
  """A single scene in the storyboard."""
  order: int
  script_line: str
  image_key: str
  image_url: str = ''
  duration_hint: float = 5.0


@dataclass
class Storyboard:
  """Editable storyboard — intermediate artifact between MATCHING and NARRATION."""
  job_id: str
  project_id: str
  scenes: list[StoryboardScene] = field(default_factory=list)

  def to_dict(self) -> dict[str, Any]:
    return {
      'job_id': self.job_id,
      'project_id': self.project_id,
      'scenes': [
        {
          'order': s.order,
          'script_line': s.script_line,
          'image_key': s.image_key,
          'image_url': s.image_url,
          'duration_hint': s.duration_hint,
        }
        for s in self.scenes
      ],
    }

  @classmethod
  def from_dict(cls, data: dict[str, Any]) -> Storyboard:
    scenes = [
      StoryboardScene(
        order=s['order'],
        script_line=s['script_line'],
        image_key=s['image_key'],
        image_url=s.get('image_url', ''),
        duration_hint=s.get('duration_hint', 5.0),
      )
      for s in data.get('scenes', [])
    ]
    return cls(
      job_id=data['job_id'],
      project_id=data['project_id'],
      scenes=scenes,
    )


class StoryboardEditorService:
  """Manage storyboard lifecycle: save, load, validate, and resume pipeline."""

  def __init__(self, storage: StorageService):
    self._storage = storage

  def storyboard_key(self, project_id: str, job_id: str) -> str:
    """Storage key for a storyboard artifact."""
    return f'projects/{project_id}/jobs/{job_id}/storyboard.json'

  def save_storyboard(self, storyboard: Storyboard) -> None:
    """Persist storyboard to storage."""
    key = self.storyboard_key(storyboard.project_id, storyboard.job_id)
    self._storage.store_text(key, json.dumps(storyboard.to_dict(), indent=2))
    logger.info('Saved storyboard for job %s (%d scenes)', storyboard.job_id, len(storyboard.scenes))

  def load_storyboard(self, project_id: str, job_id: str) -> Storyboard | None:
    """Load storyboard from storage. Returns None if not found."""
    key = self.storyboard_key(project_id, job_id)
    text = self._storage.load_text(key)
    if not text:
      return None
    try:
      data = json.loads(text)
      return Storyboard.from_dict(data)
    except (json.JSONDecodeError, KeyError):
      logger.warning('Failed to parse storyboard for job %s', job_id)
      return None

  def build_storyboard_from_pipeline(
    self,
    job: GenerationJobRecord,
    script_lines: list[str],
    matched_images: list[dict[str, Any]],
    storage: StorageService,
  ) -> Storyboard:
    """Build a Storyboard from pipeline artifacts after MATCHING stage.

    Args:
      job: The generation job record.
      script_lines: The generated script lines.
      matched_images: List of dicts with 'image_key' for each scene.
      storage: StorageService to resolve public URLs.

    Returns:
      A Storyboard instance ready for editing.
    """
    scenes: list[StoryboardScene] = []
    for i, line in enumerate(script_lines):
      image_key = ''
      if i < len(matched_images):
        image_key = matched_images[i].get('image_key', '') or matched_images[i].get('object_key', '')

      image_url = ''
      if image_key:
        try:
          image_url = storage.get_public_url(image_key)
        except Exception:
          pass

      scenes.append(StoryboardScene(
        order=i,
        script_line=line,
        image_key=image_key,
        image_url=image_url,
        duration_hint=5.0,
      ))

    return Storyboard(
      job_id=job.id,
      project_id=job.project_id,
      scenes=scenes,
    )

  def validate_storyboard_edit(
    self,
    original: Storyboard,
    edited: Storyboard,
  ) -> list[str]:
    """Validate an edited storyboard against the original.

    Returns a list of validation error strings (empty = valid).
    """
    errors: list[str] = []

    if len(edited.scenes) != len(original.scenes):
      errors.append(
        f'Scene count mismatch: original has {len(original.scenes)}, '
        f'edited has {len(edited.scenes)}'
      )
      return errors

    for i, scene in enumerate(edited.scenes):
      if not scene.script_line.strip():
        errors.append(f'Scene {i} has empty script line')
      if len(scene.script_line) > 1000:
        errors.append(f'Scene {i} script line exceeds 1000 characters')

    return errors

  def apply_storyboard_to_pipeline(
    self,
    storyboard: Storyboard,
  ) -> tuple[list[str], list[str]]:
    """Extract script lines and image keys from a storyboard for pipeline resumption.

    Returns:
      Tuple of (script_lines, image_keys).
    """
    script_lines = [s.script_line for s in storyboard.scenes]
    image_keys = [s.image_key for s in storyboard.scenes]
    return script_lines, image_keys
