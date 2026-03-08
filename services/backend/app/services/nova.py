from __future__ import annotations

import json
from typing import Sequence

from app.config import Settings
from app.models import AssetRecord, ProjectRecord, StoryboardSegment

import re


def _clean_script_lines(raw: str) -> list[str]:
  """Strip shot directions, Narrator: labels, and formatting from LLM script output."""
  lines = []
  for line in raw.split('\n'):
    line = line.strip()
    if not line:
      continue
    # Drop pure shot direction lines like [Opening shot...] or (scene description)
    if re.match(r'^[\[\(]', line):
      continue
    # Strip inline shot directions appended to a line
    line = re.sub(r'\[.*?\]', '', line).strip()
    line = re.sub(r'\(.*?\)', '', line).strip()
    # Strip "Narrator:" / "Narrator :" prefix
    line = re.sub(r'^narrator\s*:\s*', '', line, flags=re.IGNORECASE)
    # Strip surrounding quotes
    line = line.strip('"\'')
    # Strip leading bullet / number markers like "1." "- " "* "
    line = re.sub(r'^[\d]+\.\s*', '', line)
    line = line.strip('-* ').strip()
    if len(line) > 5:
      lines.append(line)
  return lines


class NovaService:

  def __init__(self, settings: Settings):
    self._settings = settings

  def generate_script(self, project: ProjectRecord) -> list[str]:
    if self._settings.use_mock_ai:
      return self._mock_script(project)

    try:
      import boto3
    except ImportError:
      return self._mock_script(project)

    try:
      runtime = boto3.client('bedrock-runtime', region_name=self._settings.aws_region)
      prompt = (
        'Write exactly 6 spoken narration lines for a 30-60 second ecommerce product video. '
        'Output ONLY the words the narrator speaks — no shot directions, no scene descriptions, '
        'no "Narrator:" labels, no brackets, no numbering. One sentence per line. '
        f'Product: {project.title}. Description: {project.product_description}'
      )
      response = runtime.invoke_model(
        modelId=self._settings.bedrock_model_script,
        body=json.dumps(
          {
            'messages': [{'role': 'user', 'content': [{'text': prompt}]}],
            'inferenceConfig': {'maxTokens': 600, 'temperature': 0.4},
          }
        ),
      )
      payload = json.loads(response['body'].read().decode('utf-8'))
      text = payload.get('output', {}).get('message', {}).get('content', [{}])[0].get('text')
      if isinstance(text, str) and text.strip():
        return _clean_script_lines(text)[:6]
    except Exception:
      return self._mock_script(project)

    return self._mock_script(project)

  def match_images(self, script_lines: Sequence[str], assets: Sequence[AssetRecord]) -> list[StoryboardSegment]:
    if not assets:
      raise ValueError('No uploaded assets available for matching')

    total = max(len(script_lines), 1)
    segment_length = max(4.0, 36.0 / total)

    if not self._settings.use_mock_ai:
      try:
        result = self._embedding_match(script_lines, assets, segment_length)
        if result is not None:
          return result
      except Exception as exc:
        import logging
        logging.getLogger(__name__).warning('Embedding match failed, falling back to round-robin: %s', exc)

    return self._round_robin_match(script_lines, assets, segment_length)

  # ------------------------------------------------------------------
  # Internal helpers
  # ------------------------------------------------------------------

  def _embedding_match(
    self,
    script_lines: Sequence[str],
    assets: Sequence[AssetRecord],
    segment_length: float,
  ) -> list[StoryboardSegment] | None:
    """Return a storyboard built with embedding cosine-similarity, or None on failure."""
    import base64
    import math
    import logging

    log = logging.getLogger(__name__)

    try:
      import boto3
    except ImportError:
      return None

    runtime = boto3.client('bedrock-runtime', region_name=self._settings.aws_region)
    model_id = self._settings.bedrock_model_embeddings
    storage_root = self._settings.local_data_dir / self._settings.local_storage_dir

    # Step 1 — embed each image once (skip if file not found on disk)
    image_embeddings: dict[str, list[float]] = {}
    for asset in assets:
      image_path = storage_root / asset.object_key
      if not image_path.exists():
        log.warning('Asset file not found on disk, skipping from embedding candidates: %s', image_path)
        continue
      try:
        b64 = base64.b64encode(image_path.read_bytes()).decode('utf-8')
        resp = runtime.invoke_model(
          modelId=model_id,
          body=json.dumps({'inputImage': b64}),
        )
        image_embeddings[asset.id] = json.loads(resp['body'].read())['embedding']
      except Exception as exc:
        log.warning('Failed to embed image %s: %s', asset.id, exc)

    # If no images could be embedded, fall through to round-robin
    embeddable_assets = [a for a in assets if a.id in image_embeddings]
    if not embeddable_assets:
      return None

    def cosine_similarity(a: list[float], b: list[float]) -> float:
      dot = sum(x * y for x, y in zip(a, b))
      mag = math.sqrt(sum(x ** 2 for x in a)) * math.sqrt(sum(x ** 2 for x in b))
      return dot / mag if mag else 0.0

    # Step 2 — for each script line, embed the text and pick the best-matching image
    storyboard: list[StoryboardSegment] = []
    for index, line in enumerate(script_lines):
      chosen_asset: AssetRecord | None = None
      try:
        resp = runtime.invoke_model(
          modelId=model_id,
          body=json.dumps({'inputText': line}),
        )
        line_emb: list[float] = json.loads(resp['body'].read())['embedding']
        chosen_asset = max(
          embeddable_assets,
          key=lambda a: cosine_similarity(line_emb, image_embeddings[a.id]),
        )
      except Exception as exc:
        log.warning('Failed to embed script line %d, using round-robin for this line: %s', index, exc)

      # Fall back to round-robin for this individual line if embedding failed
      if chosen_asset is None:
        chosen_asset = assets[index % len(assets)]

      storyboard.append(
        StoryboardSegment(
          order=index + 1,
          script_line=line,
          image_asset_id=chosen_asset.id,
          start_sec=index * segment_length,
          duration_sec=segment_length,
        )
      )

    return storyboard

  @staticmethod
  def _round_robin_match(
    script_lines: Sequence[str],
    assets: Sequence[AssetRecord],
    segment_length: float,
  ) -> list[StoryboardSegment]:
    storyboard: list[StoryboardSegment] = []
    for index, line in enumerate(script_lines):
      asset = assets[index % len(assets)]
      storyboard.append(
        StoryboardSegment(
          order=index + 1,
          script_line=line,
          image_asset_id=asset.id,
          start_sec=index * segment_length,
          duration_sec=segment_length,
        )
      )
    return storyboard

  def synthesize_voice(self, script_lines: Sequence[str], voice_style: str) -> bytes:
    transcript = ' '.join(script_lines)
    if self._settings.use_mock_ai:
      return f'MOCK-VOICE::{voice_style}::{transcript}'.encode('utf-8')

    try:
      import boto3
    except ImportError:
      return f'MOCK-VOICE::{voice_style}::{transcript}'.encode('utf-8')

    text = transcript[:3000]

    try:
      polly = boto3.client('polly', region_name=self._settings.aws_region)
      response = polly.synthesize_speech(
        Text=text,
        OutputFormat='mp3',
        VoiceId=self._settings.polly_voice_id,
      )
      stream = response.get('AudioStream')
      if stream:
        return stream.read()
    except Exception:
      return f'MOCK-VOICE::{voice_style}::{transcript}'.encode('utf-8')

    return f'MOCK-VOICE::{voice_style}::{transcript}'.encode('utf-8')

  @staticmethod
  def _mock_script(project: ProjectRecord) -> list[str]:
    return [
      f'Introducing {project.title}, designed for modern sellers.',
      'Capture buyer attention in the first three seconds.',
      'Highlight the top value proposition with visual proof.',
      'Show quality details and practical everyday usage.',
      'Reinforce trust with concise product benefits and social proof.',
      'Close with a clear call to action for immediate purchase.',
    ]
