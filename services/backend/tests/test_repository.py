from __future__ import annotations

from app.config import Settings
from app.models import JobCreateParams, JobStatus, ProjectCreateRequest
from app.repositories.local import LocalRepository


def test_local_repository_usage_increment(tmp_path):
  settings = Settings(local_data_dir=tmp_path, auth_disabled=True)
  repo = LocalRepository(settings)

  project = repo.create_project(
    owner_id='u-1',
    payload=ProjectCreateRequest(
      title='Test Product',
      product_description='A detailed product description for test coverage.',
      brand_prefs={},
    ),
  )
  assert project.owner_id == 'u-1'

  usage_before = repo.get_usage('u-1', '2026-03', quota_limit=10)
  assert usage_before.videos_generated == 0

  usage_after = repo.increment_usage('u-1', '2026-03')
  assert usage_after.videos_generated == 1


def test_local_repository_projects_and_analytics(tmp_path):
  settings = Settings(local_data_dir=tmp_path, auth_disabled=True)
  repo = LocalRepository(settings)

  project = repo.create_project(
    owner_id='u-2',
    payload=ProjectCreateRequest(
      title='Another Product',
      product_description='Another product description with enough detail to pass validation.',
      brand_prefs={},
    ),
  )

  projects = repo.list_projects(owner_id='u-2')
  assert len(projects) == 1
  assert projects[0].id == project.id

  event = repo.record_analytics_event(owner_id='u-2', event_name='project_created', project_id=project.id)
  assert event.owner_id == 'u-2'

  events = repo.list_analytics_events(owner_id='u-2')
  assert len(events) == 1
  assert events[0].event_name == 'project_created'


def test_local_repository_job_idempotency_and_dead_letter_listing(tmp_path):
  settings = Settings(local_data_dir=tmp_path, auth_disabled=True)
  repo = LocalRepository(settings)

  project = repo.create_project(
    owner_id='u-3',
    payload=ProjectCreateRequest(
      title='Idempotent Product',
      product_description='Detailed description for idempotency and dead-letter test path.',
      brand_prefs={},
    ),
  )

  params = JobCreateParams(
    aspect_ratio='16:9',
    voice_style='friendly',
    max_attempts=3,
    idempotency_key='idem-abc12345',
  )
  job = repo.create_job(
    project_id=project.id,
    owner_id='u-3',
    params=params,
  )
  found = repo.find_job_by_idempotency(owner_id='u-3', project_id=project.id, idempotency_key='idem-abc12345')
  assert found is not None
  assert found.id == job.id

  repo.update_job(
    job.id,
    status=JobStatus.FAILED,
    stage=JobStatus.FAILED,
    dead_lettered=True,
    dead_letter_reason='synthetic_failure',
  )
  dead_letters = repo.list_dead_letter_jobs(owner_id='u-3')
  assert len(dead_letters) == 1
  assert dead_letters[0].id == job.id

