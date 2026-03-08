from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

from fastapi.testclient import TestClient


def _setup_env(tmp_path: Path) -> None:
  os.environ['NOVAREEL_AUTH_DISABLED'] = 'true'
  os.environ['NOVAREEL_STORAGE_BACKEND'] = 'local'
  os.environ['NOVAREEL_QUEUE_BACKEND'] = 'poll'
  os.environ['NOVAREEL_USE_MOCK_AI'] = 'true'
  os.environ['NOVAREEL_PUBLIC_API_BASE_URL'] = 'http://testserver'
  os.environ['NOVAREEL_LOCAL_DATA_DIR'] = str(tmp_path / 'data')


def test_project_generation_lifecycle(tmp_path: Path) -> None:
  _setup_env(tmp_path)

  from app.config import get_settings
  from app.dependencies import reset_dependency_caches
  from app.main import create_app

  get_settings.cache_clear()
  reset_dependency_caches()

  app = create_app()
  client = TestClient(app)

  create_response = client.post(
    '/v1/projects',
    json={
      'title': 'Magnetic Phone Mount',
      'product_description': 'Secure mount for dashboard and desk use with fast magnetic lock.',
      'brand_prefs': {'colors': ['#f97316', '#0f172a']},
    },
  )
  assert create_response.status_code == 201
  project = create_response.json()

  upload_url_response = client.post(
    f"/v1/projects/{project['id']}/assets:upload-url",
    json={'filename': 'photo-1.jpg', 'content_type': 'image/jpeg', 'file_size': 1024},
  )
  assert upload_url_response.status_code == 201
  upload_payload = upload_url_response.json()

  invalid_upload_response = client.post(
    f"/v1/projects/{project['id']}/assets:upload-url",
    json={'filename': 'photo-2.gif', 'content_type': 'image/gif', 'file_size': 1024},
  )
  assert invalid_upload_response.status_code == 415

  upload_path = urlparse(upload_payload['upload_url']).path
  put_response = client.put(upload_path, content=b'fake-image-bytes', headers={'Content-Type': 'image/jpeg'})
  assert put_response.status_code == 200

  generate_response = client.post(
    f"/v1/projects/{project['id']}/generate",
    json={'aspect_ratio': '16:9', 'voice_style': 'energetic', 'idempotency_key': 'idem-12345678'},
  )
  assert generate_response.status_code == 202
  job = generate_response.json()
  assert job['status'] == 'queued'

  generate_duplicate_response = client.post(
    f"/v1/projects/{project['id']}/generate",
    json={'aspect_ratio': '16:9', 'voice_style': 'energetic', 'idempotency_key': 'idem-12345678'},
  )
  assert generate_duplicate_response.status_code == 202
  assert generate_duplicate_response.json()['id'] == job['id']

  project_list_response = client.get('/v1/projects')
  assert project_list_response.status_code == 200
  assert any(item['id'] == project['id'] for item in project_list_response.json())

  job_list_response = client.get(f"/v1/projects/{project['id']}/jobs")
  assert job_list_response.status_code == 200
  assert any(item['id'] == job['id'] for item in job_list_response.json())

  process_response = client.post(f"/v1/jobs/{job['id']}:process")
  assert process_response.status_code == 200

  job_status_response = client.get(f"/v1/jobs/{job['id']}")
  assert job_status_response.status_code == 200
  assert job_status_response.json()['status'] in {'completed', 'failed'}

  result_response = client.get(f"/v1/projects/{project['id']}/result")
  if job_status_response.json()['status'] == 'completed':
    assert result_response.status_code == 200
    assert result_response.json()['video_s3_key'].endswith('.mp4')
  else:
    assert result_response.status_code in {404, 200}

  usage_response = client.get('/v1/usage')
  assert usage_response.status_code == 200
  assert 'videos_generated' in usage_response.json()

  analytics_create_response = client.post(
    '/v1/analytics/events',
    json={
      'event_name': 'csat_submitted',
      'project_id': project['id'],
      'job_id': job['id'],
      'properties': {'rating': 5, 'comment': 'Great output'},
    },
  )
  assert analytics_create_response.status_code == 201

  analytics_list_response = client.get('/v1/analytics/events')
  assert analytics_list_response.status_code == 200
  assert any(item['event_name'] == 'csat_submitted' for item in analytics_list_response.json())

  admin_response = client.get('/v1/admin/overview')
  assert admin_response.status_code == 200
  admin_payload = admin_response.json()
  assert 'activation_rate_pct' in admin_payload
  assert 'recent_events' in admin_payload

  dead_letter_response = client.get('/v1/admin/dead-letters')
  assert dead_letter_response.status_code == 200
  assert isinstance(dead_letter_response.json(), list)
