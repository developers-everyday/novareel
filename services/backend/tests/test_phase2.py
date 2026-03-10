"""Phase 2 – Sprint 3 tests: JobCreateParams, per-job results, translation, and templates."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

from app.config import Settings
from app.models import (
  GenerateRequest,
  JobCreateParams,
  JobStatus,
  ProjectCreateRequest,
  StoryboardSegment,
  VideoResultRecord,
)
from app.repositories.local import LocalRepository


def _make_settings(tmp_path: Path) -> Settings:
  return Settings(local_data_dir=tmp_path, auth_disabled=True)


def _make_repo(tmp_path: Path) -> LocalRepository:
  return LocalRepository(_make_settings(tmp_path))


# ─── JobCreateParams ───────────────────────────────────────────────────────

def test_job_create_params_all_fields_stored(tmp_path):
  """JobCreateParams values propagate to the created job record."""
  repo = _make_repo(tmp_path)
  project = repo.create_project('u-1', ProjectCreateRequest(
    title='ParamsTest', product_description='Testing all JobCreateParams fields end-to-end.', brand_prefs={},
  ))

  params = JobCreateParams(
    aspect_ratio='9:16',
    voice_style='professional',
    voice_provider='edge_tts',
    voice_gender='male',
    language='es',
    background_music='calm',
    script_template='problem_solution',
    video_style='product_lifestyle',
    transition_style='slide_left',
    caption_style='word_highlight',
    show_title_card=False,
    cta_text='Buy now!',
    job_type='generation',
    source_job_id=None,
    max_attempts=5,
    idempotency_key='idem-params-01',
  )
  job = repo.create_job(project.id, 'u-1', params)

  assert job.aspect_ratio == '9:16'
  assert job.voice_style == 'professional'
  assert job.voice_provider == 'edge_tts'
  assert job.language == 'es'
  assert job.script_template == 'problem_solution'
  assert job.video_style == 'product_lifestyle'
  assert job.transition_style == 'slide_left'
  assert job.caption_style == 'word_highlight'
  assert job.show_title_card is False
  assert job.cta_text == 'Buy now!'
  assert job.job_type == 'generation'
  assert job.max_attempts == 5


# ─── Per-Job Result Storage ────────────────────────────────────────────────

def test_per_job_result_storage(tmp_path):
  """set_result writes per-job, get_result retrieves by job_id, list_results returns all."""
  repo = _make_repo(tmp_path)
  now = datetime.now(UTC)

  # Create two results for the same project
  r1 = VideoResultRecord(
    project_id='proj-1', job_id='job-1', video_s3_key='a.mp4', video_url='/a.mp4',
    duration_sec=10.0, resolution='1920x1080', script_lines=['Line one'], language='en', completed_at=now,
  )
  r2 = VideoResultRecord(
    project_id='proj-1', job_id='job-2', video_s3_key='b.mp4', video_url='/b.mp4',
    duration_sec=15.0, resolution='1920x1080', script_lines=['Línea uno'], language='es', completed_at=now,
  )

  repo.set_result('proj-1', 'job-1', r1)
  repo.set_result('proj-1', 'job-2', r2)

  # get_result by job_id
  fetched = repo.get_result('proj-1', job_id='job-1')
  assert fetched is not None
  assert fetched.job_id == 'job-1'
  assert fetched.language == 'en'

  fetched2 = repo.get_result('proj-1', job_id='job-2')
  assert fetched2 is not None
  assert fetched2.language == 'es'

  # get_result without job_id returns latest
  latest = repo.get_result('proj-1')
  assert latest is not None

  # list_results returns all
  results = repo.list_results('proj-1')
  assert len(results) == 2

  # Different project returns empty
  assert repo.list_results('proj-999') == []
  assert repo.get_result('proj-999') is None


# ─── Translation ───────────────────────────────────────────────────────────

def test_translate_endpoint_creates_jobs(tmp_path):
  """POST /translate creates one job per target language with job_type='translation'."""
  os.environ['NOVAREEL_AUTH_DISABLED'] = 'true'
  os.environ['NOVAREEL_STORAGE_BACKEND'] = 'local'
  os.environ['NOVAREEL_QUEUE_BACKEND'] = 'poll'
  os.environ['NOVAREEL_USE_MOCK_AI'] = 'true'
  os.environ['NOVAREEL_PUBLIC_API_BASE_URL'] = 'http://testserver'
  os.environ['NOVAREEL_LOCAL_DATA_DIR'] = str(tmp_path / 'data')

  from app.config import get_settings
  from app.dependencies import reset_dependency_caches
  from app.main import create_app
  from fastapi.testclient import TestClient

  get_settings.cache_clear()
  reset_dependency_caches()

  app = create_app()
  client = TestClient(app)

  # Create project + upload asset
  project = client.post('/v1/projects', json={
    'title': 'Translate Test',
    'product_description': 'A product for testing translation flow end to end.',
    'brand_prefs': {},
  }).json()

  upload_url = client.post(
    f"/v1/projects/{project['id']}/assets:upload-url",
    json={'filename': 'img.jpg', 'content_type': 'image/jpeg', 'file_size': 100},
  ).json()
  from urllib.parse import urlparse
  upload_path = urlparse(upload_url['upload_url']).path
  client.put(upload_path, content=b'fake-img', headers={'Content-Type': 'image/jpeg'})

  # Generate original video
  gen = client.post(f"/v1/projects/{project['id']}/generate", json={
    'aspect_ratio': '16:9', 'voice_style': 'energetic',
  }).json()
  client.post(f"/v1/jobs/{gen['id']}:process")

  # Verify the source job completed
  job_status = client.get(f"/v1/jobs/{gen['id']}").json()
  assert job_status['status'] == 'completed'

  # Now translate to 2 languages
  translate_response = client.post(
    f"/v1/projects/{project['id']}/jobs/{gen['id']}/translate",
    json={'target_languages': ['es', 'de'], 'voice_provider': 'edge_tts', 'voice_gender': 'female'},
  )
  assert translate_response.status_code == 202
  translation_jobs = translate_response.json()
  assert len(translation_jobs) == 2
  assert translation_jobs[0]['job_type'] == 'translation'
  assert translation_jobs[0]['source_job_id'] == gen['id']
  assert translation_jobs[0]['language'] == 'es'
  assert translation_jobs[1]['language'] == 'de'


def test_translate_rejects_incomplete_source(tmp_path):
  """POST /translate returns 400 if source job is not completed."""
  os.environ['NOVAREEL_AUTH_DISABLED'] = 'true'
  os.environ['NOVAREEL_STORAGE_BACKEND'] = 'local'
  os.environ['NOVAREEL_QUEUE_BACKEND'] = 'poll'
  os.environ['NOVAREEL_USE_MOCK_AI'] = 'true'
  os.environ['NOVAREEL_PUBLIC_API_BASE_URL'] = 'http://testserver'
  os.environ['NOVAREEL_LOCAL_DATA_DIR'] = str(tmp_path / 'data')

  from app.config import get_settings
  from app.dependencies import reset_dependency_caches
  from app.main import create_app
  from fastapi.testclient import TestClient

  get_settings.cache_clear()
  reset_dependency_caches()

  app = create_app()
  client = TestClient(app)

  project = client.post('/v1/projects', json={
    'title': 'Reject Test',
    'product_description': 'A product for testing rejection of incomplete source job.',
    'brand_prefs': {},
  }).json()

  upload_url = client.post(
    f"/v1/projects/{project['id']}/assets:upload-url",
    json={'filename': 'img.jpg', 'content_type': 'image/jpeg', 'file_size': 100},
  ).json()
  from urllib.parse import urlparse
  upload_path = urlparse(upload_url['upload_url']).path
  client.put(upload_path, content=b'fake-img', headers={'Content-Type': 'image/jpeg'})

  gen = client.post(f"/v1/projects/{project['id']}/generate", json={
    'aspect_ratio': '16:9', 'voice_style': 'energetic',
  }).json()

  # Don't process the job — it's still queued
  translate_response = client.post(
    f"/v1/projects/{project['id']}/jobs/{gen['id']}/translate",
    json={'target_languages': ['fr']},
  )
  assert translate_response.status_code == 400


# ─── YAML Template Loading ─────────────────────────────────────────────────

def test_load_yaml_template(tmp_path):
  """YAML template loads with expected fields."""
  import yaml
  template_path = Path(__file__).resolve().parents[1] / 'prompt_templates' / 'problem_solution.yaml'
  assert template_path.exists(), f'Template not found: {template_path}'

  with open(template_path) as f:
    data = yaml.safe_load(f)

  assert data['name'] == 'Problem/Solution'
  assert 'system_prompt' in data
  assert len(data['system_prompt']) > 50
  assert data['scenes'] == 6


def test_all_templates_are_valid(tmp_path):
  """All 8 YAML templates are valid and have required fields."""
  import yaml
  templates_dir = Path(__file__).resolve().parents[1] / 'prompt_templates'

  expected_templates = [
    'product_showcase', 'problem_solution', 'comparison', 'unboxing',
    'testimonial', 'how_to', 'seasonal', 'luxury',
  ]

  for name in expected_templates:
    path = templates_dir / f'{name}.yaml'
    assert path.exists(), f'Missing template: {name}'
    with open(path) as f:
      data = yaml.safe_load(f)
    assert 'name' in data, f'{name} missing "name"'
    assert 'system_prompt' in data, f'{name} missing "system_prompt"'
    assert 'scenes' in data, f'{name} missing "scenes"'
    assert isinstance(data['scenes'], int), f'{name} scenes should be int'


def test_nova_load_template_prompt(tmp_path):
  """NovaService._load_template_prompt returns str for valid template, None for unknown."""
  settings = _make_settings(tmp_path)
  from app.services.nova import NovaService
  service = NovaService(settings)

  result = service._load_template_prompt('product_showcase')
  assert result is not None
  assert 'marketing' in result.lower() or 'product' in result.lower()

  missing = service._load_template_prompt('nonexistent_template_xyz')
  assert missing is None


# ─── Sprint 4: Captions ────────────────────────────────────────────────────

def test_mock_transcription_backend():
  """MockTranscriptionBackend generates evenly-spaced word timings."""
  from app.services.transcription import MockTranscriptionBackend

  backend = MockTranscriptionBackend(script_lines=['Hello world', 'Testing one two three'])
  timings = backend.transcribe(Path('/fake/audio.mp3'), language='en')

  assert len(timings) == 6  # Hello world Testing one two three -> 6 words
  assert timings[0].word == 'Hello'
  assert timings[-1].word == 'three'
  assert timings[0].start_sec < timings[0].end_sec
  assert timings[-1].end_sec > timings[-2].end_sec


def test_ass_subtitle_generation_word_highlight():
  """generate_ass_subtitles produces valid ASS with word_highlight style."""
  from app.services.transcription import WordTiming, generate_ass_subtitles

  timings = [
    WordTiming(word='Hello', start_sec=0.0, end_sec=0.5),
    WordTiming(word='world', start_sec=0.6, end_sec=1.0),
    WordTiming(word='this', start_sec=1.5, end_sec=2.0),
    WordTiming(word='is', start_sec=2.1, end_sec=2.4),
    WordTiming(word='a', start_sec=2.5, end_sec=2.7),
    WordTiming(word='test', start_sec=2.8, end_sec=3.2),
  ]

  ass = generate_ass_subtitles(timings, caption_style='word_highlight', resolution='1920x1080')

  assert '[Script Info]' in ass
  assert 'PlayResX: 1920' in ass
  assert 'PlayResY: 1080' in ass
  assert '[V4+ Styles]' in ass
  assert 'Style: Highlight' in ass
  assert 'Dialogue:' in ass
  assert 'Hello' in ass
  assert 'world' in ass


def test_ass_subtitle_generation_karaoke():
  """generate_ass_subtitles produces valid ASS with karaoke style."""
  from app.services.transcription import WordTiming, generate_ass_subtitles

  timings = [
    WordTiming(word='One', start_sec=0.0, end_sec=0.5),
    WordTiming(word='two', start_sec=0.6, end_sec=1.0),
    WordTiming(word='three', start_sec=1.1, end_sec=1.6),
  ]

  ass = generate_ass_subtitles(timings, caption_style='karaoke')
  assert '\\kf' in ass  # karaoke tag present
  assert 'One' in ass


def test_ass_subtitle_generation_simple():
  """generate_ass_subtitles produces valid ASS with simple style."""
  from app.services.transcription import WordTiming, generate_ass_subtitles

  timings = [
    WordTiming(word='Simple', start_sec=0.0, end_sec=1.0),
    WordTiming(word='test', start_sec=1.1, end_sec=2.0),
  ]

  ass = generate_ass_subtitles(timings, caption_style='simple')
  assert 'Simple test' in ass
  assert '\\kf' not in ass  # no karaoke tags


# ─── Sprint 4: Effects ────────────────────────────────────────────────────

def test_transition_config_from_style():
  """TransitionConfig.from_style returns correct xfade name and duration."""
  from app.services.effects import TransitionConfig

  cfg = TransitionConfig.from_style('crossfade')
  assert cfg.xfade_name == 'fade'
  assert cfg.duration == 0.5

  cfg_slide = TransitionConfig.from_style('slide_left')
  assert cfg_slide.xfade_name == 'slideleft'
  assert cfg_slide.duration == 0.4

  cfg_none = TransitionConfig.from_style('none')
  assert cfg_none.xfade_name is None
  assert cfg_none.duration == 0.0

  cfg_unknown = TransitionConfig.from_style('nonexistent_style')
  assert cfg_unknown.xfade_name is None


def test_video_effects_config_from_job():
  """VideoEffectsConfig.from_job builds config with transition, title, CTA."""
  from app.services.effects import VideoEffectsConfig
  from unittest.mock import MagicMock

  job = MagicMock()
  job.transition_style = 'crossfade'
  job.show_title_card = True
  job._project_title = 'Test Product'
  job.cta_text = 'Buy now!'
  job.caption_style = 'word_highlight'

  config = VideoEffectsConfig.from_job(job)
  assert config.transition.xfade_name == 'fade'
  assert config.transition.duration == 0.5
  assert config.title_overlay is not None
  assert config.title_overlay.text == 'Test Product'
  assert config.cta_overlay is not None
  assert config.cta_overlay.text == 'Buy now!'
  assert config.caption_style == 'word_highlight'


def test_text_overlay_escaped_text():
  """TextOverlay.escaped_text properly escapes special characters."""
  from app.services.effects import TextOverlay

  overlay = TextOverlay(text="It's a test: value")
  # Apostrophes become right single quote, colons are escaped
  assert "'" not in overlay.escaped_text
  assert "\\:" in overlay.escaped_text


def test_xfade_filter_graph_construction():
  """VideoService._join_with_xfade builds correct ffmpeg filter graph (unit test)."""
  from app.services.video import VideoService

  # Test with None return when only 1 segment
  result = VideoService._join_with_xfade(
    '/usr/bin/ffmpeg', Path('/tmp'),
    [Path('/tmp/seg_000.mp4')], [5.0],
    'fade', 0.5,
  )
  # Single segment — returns the segment itself
  assert result == Path('/tmp/seg_000.mp4')


def test_build_transcription_backend():
  """build_transcription_backend returns correct backend type."""
  from app.services.transcription import (
    MockTranscriptionBackend,
    build_transcription_backend,
  )
  from unittest.mock import MagicMock

  settings = MagicMock()
  settings.use_mock_ai = True

  backend = build_transcription_backend('aws_transcribe', settings, script_lines=['Test'])
  assert isinstance(backend, MockTranscriptionBackend)

  settings.use_mock_ai = False
  settings.whisper_model = 'base'

  from app.services.transcription import WhisperTranscriptionBackend
  backend_whisper = build_transcription_backend('whisper', settings)
  assert isinstance(backend_whisper, WhisperTranscriptionBackend)

