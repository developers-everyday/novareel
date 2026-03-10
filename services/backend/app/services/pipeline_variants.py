"""A/B Video Variants — shared analysis + per-variant generation orchestrator."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from app.models import GenerationJobRecord, JobCreateParams
from app.queue.base import JobQueue
from app.repositories.base import Repository

logger = logging.getLogger(__name__)


def create_variant_jobs(
  *,
  project_id: str,
  owner_id: str,
  variant_count: int,
  shared: dict[str, Any],
  overrides: list[dict[str, Any]],
  repo: Repository,
  queue: JobQueue,
) -> list[GenerationJobRecord]:
  """Create multiple variant generation jobs for a project.

  All variants share the same `variant_group_id`. The first variant will
  perform image analysis and cache it; subsequent variants will reuse the
  cached analysis (handled in pipeline.py via the intermediate artifact
  prefix pattern).

  Args:
    project_id: The project to generate variants for.
    owner_id: The owner of the project.
    variant_count: Number of variants to generate (2-5).
    shared: Shared parameters applied to all variants.
    overrides: Per-variant parameter overrides (len may be < variant_count).
    repo: Repository for job creation.
    queue: Job queue for enqueuing jobs.

  Returns:
    List of created GenerationJobRecord instances.
  """
  variant_group_id = str(uuid.uuid4())
  jobs: list[GenerationJobRecord] = []

  for i in range(variant_count):
    override = overrides[i] if i < len(overrides) else {}
    merged = {**shared, **override}

    # Build JobCreateParams from merged dict, only including valid fields
    valid_fields = {k: v for k, v in merged.items() if k in JobCreateParams.model_fields}
    params = JobCreateParams(**valid_fields)
    params.variant_group_id = variant_group_id

    job = repo.create_job(project_id=project_id, owner_id=owner_id, params=params)
    queue.enqueue(job.id)
    jobs.append(job)

    logger.info(
      'Created variant job %d/%d: %s (group=%s)',
      i + 1, variant_count, job.id, variant_group_id,
    )

  return jobs
