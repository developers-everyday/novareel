from __future__ import annotations

import io
import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch
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


def test_match_images_embedding(tmp_path: Path) -> None:
  """
  Verify that match_images uses cosine-similarity embedding results when
  use_mock_ai=False and boto3 is available.

  Setup
  -----
  Two assets: asset_A and asset_B.
  Two script lines: line_0 and line_1.

  Embeddings are crafted so that:
    - line_0 text embedding is closest to image_B  (would be asset_A in round-robin)
    - line_1 text embedding is closest to image_A  (would be asset_B in round-robin)

  This proves the new code is using semantics, not position.
  """
  from datetime import datetime

  from app.config import Settings
  from app.models import AssetRecord
  from app.services.nova import NovaService

  # --- Build a minimal Settings pointing at tmp_path ---
  data_dir = tmp_path / 'data'
  storage_root = data_dir / 'storage'
  storage_root.mkdir(parents=True)

  settings = Settings(
    use_mock_ai=False,
    local_data_dir=data_dir,
    local_storage_dir='storage',
    aws_region='us-east-1',
    bedrock_model_embeddings='amazon.nova-multimodal-embeddings-v1',
  )

  # --- Write fake image files to disk at the expected object_key paths ---
  asset_A_key = 'projects/proj-1/assets/asset-A-front.jpg'
  asset_B_key = 'projects/proj-1/assets/asset-B-side.jpg'

  path_A = storage_root / asset_A_key
  path_B = storage_root / asset_B_key
  path_A.parent.mkdir(parents=True, exist_ok=True)
  path_A.write_bytes(b'fake-image-A')
  path_B.write_bytes(b'fake-image-B')

  now = datetime.utcnow()
  assets = [
    AssetRecord(
      id='asset-A',
      project_id='proj-1',
      owner_id='user-1',
      filename='front.jpg',
      content_type='image/jpeg',
      file_size=12,
      object_key=asset_A_key,
      uploaded=True,
      created_at=now,
    ),
    AssetRecord(
      id='asset-B',
      project_id='proj-1',
      owner_id='user-1',
      filename='side.jpg',
      content_type='image/jpeg',
      file_size=12,
      object_key=asset_B_key,
      uploaded=True,
      created_at=now,
    ),
  ]

  script_lines = ['front view of the product', 'side angle showing the mount']

  # --- Craft embeddings so semantic match is opposite of round-robin ---
  # image_A embedding: high in dimension 0
  # image_B embedding: high in dimension 1
  # line_0 text embedding: high in dimension 1  → closest to image_B (asset-B)
  # line_1 text embedding: high in dimension 0  → closest to image_A (asset-A)
  emb_image_A = [1.0, 0.0]
  emb_image_B = [0.0, 1.0]
  emb_line_0  = [0.0, 1.0]  # closest to image_B
  emb_line_1  = [1.0, 0.0]  # closest to image_A

  call_count = {'n': 0}

  def fake_invoke_model(modelId: str, body: str) -> dict:  # noqa: N803
    payload = json.loads(body)
    call_count['n'] += 1
    if 'inputImage' in payload:
      # Determine which asset by inspecting the base64 content
      import base64
      raw = base64.b64decode(payload['inputImage'])
      emb = emb_image_A if raw == b'fake-image-A' else emb_image_B
    else:
      # Text embedding — match by line content
      emb = emb_line_0 if payload['inputText'] == script_lines[0] else emb_line_1

    response_body = json.dumps({'embedding': emb}).encode('utf-8')
    return {'body': io.BytesIO(response_body)}

  mock_runtime = MagicMock()
  mock_runtime.invoke_model.side_effect = fake_invoke_model

  mock_boto3 = MagicMock()
  mock_boto3.client.return_value = mock_runtime

  with patch.dict('sys.modules', {'boto3': mock_boto3}):
    service = NovaService(settings)
    storyboard = service.match_images(script_lines, assets)

  # Verify the boto3 client was called with the correct service and region
  mock_boto3.client.assert_called_once_with('bedrock-runtime', region_name='us-east-1')

  # Verify embed calls: 2 images + 2 lines = 4
  assert call_count['n'] == 4, f"Expected 4 invoke_model calls, got {call_count['n']}"

  # Verify semantic assignment (opposite of round-robin)
  assert len(storyboard) == 2
  assert storyboard[0].image_asset_id == 'asset-B', (
    f"line_0 should match asset-B by embedding similarity, got {storyboard[0].image_asset_id}"
  )
  assert storyboard[1].image_asset_id == 'asset-A', (
    f"line_1 should match asset-A by embedding similarity, got {storyboard[1].image_asset_id}"
  )

  # Verify ordering and timing are correct
  assert storyboard[0].order == 1
  assert storyboard[1].order == 2
  assert storyboard[0].start_sec == 0.0
  assert storyboard[1].start_sec == storyboard[0].duration_sec


def test_match_images_falls_back_to_round_robin_when_files_missing(tmp_path: Path) -> None:
  """When no asset files exist on disk, embedding is skipped and round-robin is used."""
  from datetime import datetime

  from app.config import Settings
  from app.models import AssetRecord
  from app.services.nova import NovaService

  data_dir = tmp_path / 'data'
  (data_dir / 'storage').mkdir(parents=True)

  settings = Settings(
    use_mock_ai=False,
    local_data_dir=data_dir,
    local_storage_dir='storage',
    aws_region='us-east-1',
    bedrock_model_embeddings='amazon.nova-multimodal-embeddings-v1',
  )

  now = datetime.utcnow()
  assets = [
    AssetRecord(
      id='asset-X',
      project_id='proj-2',
      owner_id='user-1',
      filename='x.jpg',
      content_type='image/jpeg',
      file_size=10,
      object_key='projects/proj-2/assets/asset-X-x.jpg',
      uploaded=True,
      created_at=now,
    ),
    AssetRecord(
      id='asset-Y',
      project_id='proj-2',
      owner_id='user-1',
      filename='y.jpg',
      content_type='image/jpeg',
      file_size=10,
      object_key='projects/proj-2/assets/asset-Y-y.jpg',
      uploaded=True,
      created_at=now,
    ),
  ]

  script_lines = ['line one', 'line two', 'line three']

  mock_boto3 = MagicMock()

  with patch.dict('sys.modules', {'boto3': mock_boto3}):
    service = NovaService(settings)
    storyboard = service.match_images(script_lines, assets)

  # No invoke_model calls should have been made (files not on disk → skip)
  mock_boto3.client.return_value.invoke_model.assert_not_called()

  # Round-robin: line0→X, line1→Y, line2→X
  assert storyboard[0].image_asset_id == 'asset-X'
  assert storyboard[1].image_asset_id == 'asset-Y'
  assert storyboard[2].image_asset_id == 'asset-X'


def test_match_images_uses_round_robin_in_mock_mode(tmp_path: Path) -> None:
  """When use_mock_ai=True, no Bedrock calls are made and round-robin is used."""
  from datetime import datetime

  from app.config import Settings
  from app.models import AssetRecord
  from app.services.nova import NovaService

  data_dir = tmp_path / 'data'
  (data_dir / 'storage').mkdir(parents=True)

  settings = Settings(
    use_mock_ai=True,
    local_data_dir=data_dir,
    local_storage_dir='storage',
    aws_region='us-east-1',
  )

  now = datetime.utcnow()
  assets = [
    AssetRecord(
      id='img-1', project_id='p', owner_id='u', filename='a.jpg',
      content_type='image/jpeg', file_size=1,
      object_key='projects/p/assets/img-1-a.jpg', uploaded=True, created_at=now,
    ),
    AssetRecord(
      id='img-2', project_id='p', owner_id='u', filename='b.jpg',
      content_type='image/jpeg', file_size=1,
      object_key='projects/p/assets/img-2-b.jpg', uploaded=True, created_at=now,
    ),
  ]

  service = NovaService(settings)
  storyboard = service.match_images(['line A', 'line B', 'line C'], assets)

  assert storyboard[0].image_asset_id == 'img-1'
  assert storyboard[1].image_asset_id == 'img-2'
  assert storyboard[2].image_asset_id == 'img-1'
