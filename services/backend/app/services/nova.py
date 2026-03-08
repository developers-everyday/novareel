from __future__ import annotations

import json
from typing import Sequence

from app.config import Settings
from app.models import AssetRecord, ProjectRecord, StoryboardSegment


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
        'Write a 30-60 second ecommerce product video script with 6 lines. '
        f"Product: {project.title}. Description: {project.product_description}"
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
        return [line.strip('- ').strip() for line in text.split('\n') if line.strip()][:6]
    except Exception:
      return self._mock_script(project)

    return self._mock_script(project)

  def match_images(self, script_lines: Sequence[str], assets: Sequence[AssetRecord]) -> list[StoryboardSegment]:
    if not assets:
      raise ValueError('No uploaded assets available for matching')

    total = max(len(script_lines), 1)
    segment_length = max(4.0, 36.0 / total)

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
