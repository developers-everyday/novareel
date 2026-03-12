from __future__ import annotations

import json
from typing import Sequence

from app.config import Settings
from app.models import AssetRecord, FocalRegion, ProjectRecord, ScriptScene, StoryboardSegment

import re


# _clean_script_lines has been removed since we now rely on Converse API Tool Use for structured output.


class NovaService:

  def __init__(self, settings: Settings):
    self._settings = settings

  # ------------------------------------------------------------------
  # Phase 1: Vision-Based Image Analysis
  # ------------------------------------------------------------------

  def analyze_images(
    self,
    assets: Sequence[AssetRecord],
  ) -> list[dict]:
    """Use Nova Lite's multimodal vision to extract product features from each image.

    Returns a list of dicts: [{"asset_id": "...", "description": "..."}]
    """
    if self._settings.use_mock_ai or not assets:
      return [{
        'asset_id': a.id,
        'description': f'Product image: {a.filename}',
        'focal_region': {'cx': 0.5, 'cy': 0.5, 'w': 0.4, 'h': 0.6},
      } for a in assets]

    import base64
    import logging

    log = logging.getLogger(__name__)

    try:
      import boto3
    except ImportError:
      return [{
        'asset_id': a.id,
        'description': f'Product image: {a.filename}',
        'focal_region': {'cx': 0.5, 'cy': 0.5, 'w': 0.4, 'h': 0.6},
      } for a in assets]

    runtime = boto3.client('bedrock-runtime', region_name=self._settings.aws_region)
    storage_root = self._settings.local_data_dir / self._settings.local_storage_dir

    results: list[dict] = []
    for asset in assets:
      image_path = storage_root / asset.object_key
      if not image_path.exists():
        results.append({
          'asset_id': asset.id,
          'description': f'Product image: {asset.filename}',
          'focal_region': {'cx': 0.5, 'cy': 0.5, 'w': 0.4, 'h': 0.6},
        })
        continue

      try:
        img_bytes = image_path.read_bytes()
        img_fmt = (asset.content_type.split('/')[-1] if asset.content_type else 'png')
        if img_fmt == 'jpg':
          img_fmt = 'jpeg'

        response = runtime.converse(
          modelId=self._settings.bedrock_model_script,
          messages=[{
            'role': 'user',
            'content': [
              {
                'image': {
                  'format': img_fmt,
                  'source': {'bytes': img_bytes},
                },
              },
              {
                'text': (
                  'You are a product photography expert. '
                  'Describe the product in this image in 2-3 sentences. '
                  'Focus on: what the product is, key visible features, '
                  'the angle/perspective of the shot, and any branding or text visible. '
                  'Be specific and concise.\n\n'
                  'Also estimate the bounding box of the PRIMARY product in the image. '
                  'Return your answer as exactly two lines:\n'
                  'Line 1: your text description\n'
                  'Line 2: BBOX: x_min,y_min,x_max,y_max\n'
                  'where each value is a fraction between 0 and 1 '
                  '(0,0 = top-left corner, 1,1 = bottom-right corner). '
                  'Example: BBOX: 0.20,0.10,0.80,0.90'
                ),
              },
            ],
          }],
          inferenceConfig={'maxTokens': 300, 'temperature': 0.2},
        )

        raw_text = ''
        for block in response['output']['message']['content']:
          if 'text' in block:
            raw_text = block['text'].strip()
            break

        description, focal = self._parse_analysis_response(raw_text, asset.filename)
        results.append({
          'asset_id': asset.id,
          'description': description,
          'focal_region': focal,
        })
        log.info('Analyzed image %s: %s (focal cx=%.2f cy=%.2f)', asset.id, description[:60], focal['cx'], focal['cy'])
      except Exception as exc:
        log.warning('Failed to analyze image %s: %s', asset.id, exc)
        results.append({
          'asset_id': asset.id,
          'description': f'Product image: {asset.filename}',
          'focal_region': {'cx': 0.5, 'cy': 0.5, 'w': 0.4, 'h': 0.6},
        })

    return results

  # ------------------------------------------------------------------
  # Phase 2: Image-Aware Script Generation
  # ------------------------------------------------------------------

  def generate_script(
    self,
    project: ProjectRecord,
    image_analysis: list[dict] | None = None,
    language: str = 'en',
    script_template: str = 'product_showcase',
  ) -> list[ScriptScene]:
    if self._settings.use_mock_ai:
      return self._mock_script(project)

    try:
      import boto3
    except ImportError:
      return self._mock_script(project)

    try:
      runtime = boto3.client('bedrock-runtime', region_name=self._settings.aws_region)

      # Load template system prompt
      template_prompt = self._load_template_prompt(script_template)

      # Build image context from analysis results
      image_context = ''
      if image_analysis:
        lines_desc = []
        for i, info in enumerate(image_analysis, 1):
          lines_desc.append(f'Image {i}: {info["description"]}')
        image_context = (
          f'\n\nYou have {len(image_analysis)} product images available:\n'
          + '\n'.join(lines_desc)
          + '\n\nWrite your script so each scene highlights a feature visible '
          'in one of these images. Prioritize the most compelling visual features first. '
          'Make sure every image is referenced by at least one scene.'
        )

      # Feature C: Multi-language support
      from app.config.languages import get_language_name

      lang_instruction = ''
      if language != 'en':
        lang_name = get_language_name(language)
        lang_instruction = (
          f' Write ALL spoken narration text in {lang_name}. '
          f'The narration must be entirely in {lang_name} — do not use English. '
        )

      if template_prompt:
        prompt = (
          f'{template_prompt}\n\n'
          'You must use the render_video_plan tool to structure your output. '
          f'{lang_instruction}'
          f'Product: {project.title}. Description: {project.product_description}'
          f'{image_context}'
        )
      else:
        prompt = (
          'You are an expert video director and copywriter. '
          'Create a 6-scene marketing video script for this product. '
          'You must use the render_video_plan tool to structure your output. '
          f'{lang_instruction}'
          f'Product: {project.title}. Description: {project.product_description}'
          f'{image_context}'
        )
      
      tool_config = {
        'tools': [
          {
            'toolSpec': {
              'name': 'render_video_plan',
              'description': 'Renders the final video plan consisting of scenes with spoken narration.',
              'inputSchema': {
                'json': {
                  'type': 'object',
                  'properties': {
                    'scenes': {
                      'type': 'array',
                      'items': {
                        'type': 'object',
                        'properties': {
                          'spoken_narration': {
                            'type': 'string',
                            'description': 'The exact words the voiceover narrator will speak. No shot directions, no narrator labels, just the spoken text.'
                          },
                          'visual_requirements': {
                            'type': 'string',
                            'description': 'A description of what should be shown on screen during this narration.'
                          }
                        },
                        'required': ['spoken_narration', 'visual_requirements']
                      },
                      'minItems': 6,
                      'maxItems': 6
                    }
                  },
                  'required': ['scenes']
                }
              }
            }
          }
        ],
        'toolChoice': {
          'tool': { 'name': 'render_video_plan' }
        }
      }

      response = runtime.converse(
        modelId=self._settings.bedrock_model_script,
        messages=[{'role': 'user', 'content': [{'text': prompt}]}],
        inferenceConfig={'maxTokens': 800, 'temperature': 0.4},
        toolConfig=tool_config
      )
      
      # Extract the tool use from the response
      output_message = response['output']['message']
      for content_block in output_message['content']:
        if 'toolUse' in content_block:
          tool_use = content_block['toolUse']
          if tool_use['name'] == 'render_video_plan':
            scenes = tool_use['input']['scenes']
            result = [
              ScriptScene(
                narration=scene['spoken_narration'].strip(),
                visual_requirements=scene.get('visual_requirements', ''),
              )
              for scene in scenes
            ]
            if result:
              return result

    except Exception as exc:
      import logging
      logging.getLogger(__name__).error('Failed to generate script with Converse API: %s', exc)
      return self._mock_script(project)

    return self._mock_script(project)

  def _load_template_prompt(self, template_name: str) -> str | None:
    """Load a YAML template's system_prompt by name. Returns None if not found."""
    from pathlib import Path
    templates_dir = Path(self._settings.prompt_templates_dir)
    template_path = templates_dir / f'{template_name}.yaml'
    if not template_path.exists():
      import logging
      logging.getLogger(__name__).warning('Template %s not found at %s, using default', template_name, template_path)
      return None
    try:
      import yaml
      with open(template_path) as f:
        data = yaml.safe_load(f)
      return data.get('system_prompt', '').strip() or None
    except Exception:
      import logging
      logging.getLogger(__name__).warning('Failed to load template %s', template_name, exc_info=True)
      return None

  def match_images(
    self,
    script_lines: Sequence[str],
    assets: Sequence[AssetRecord],
    image_analysis: list[dict] | None = None,
  ) -> list[StoryboardSegment]:
    if not assets:
      raise ValueError('No uploaded assets available for matching')

    # Build a map of asset_id -> FocalRegion from analysis results
    focal_map: dict[str, FocalRegion] = {}
    if image_analysis:
      for info in image_analysis:
        fr_data = info.get('focal_region')
        if fr_data:
          focal_map[info['asset_id']] = FocalRegion(**fr_data)

    total = max(len(script_lines), 1)
    segment_length = max(4.0, 36.0 / total)

    if not self._settings.use_mock_ai:
      try:
        result = self._embedding_match(script_lines, assets, segment_length, focal_map)
        if result is not None:
          return result
      except Exception as exc:
        import logging
        logging.getLogger(__name__).warning('Embedding match failed, falling back to round-robin: %s', exc)

    return self._round_robin_match(script_lines, assets, segment_length, focal_map)

  @staticmethod
  def _parse_analysis_response(raw_text: str, filename: str) -> tuple[str, dict]:
    """Parse description and bounding box from the vision model response.

    Expected format:
      <description text>
      BBOX: x_min,y_min,x_max,y_max

    Returns:
      (description, focal_region_dict) where focal_region_dict has keys cx, cy, w, h.
    """
    default_focal = {'cx': 0.5, 'cy': 0.5, 'w': 0.4, 'h': 0.6}
    if not raw_text:
      return f'Product image: {filename}', default_focal

    # Try to find BBOX line
    bbox_match = re.search(
      r'BBOX:\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)',
      raw_text,
      re.IGNORECASE,
    )

    if bbox_match:
      try:
        x_min = float(bbox_match.group(1))
        y_min = float(bbox_match.group(2))
        x_max = float(bbox_match.group(3))
        y_max = float(bbox_match.group(4))
        # Clamp to [0, 1]
        x_min = max(0.0, min(1.0, x_min))
        y_min = max(0.0, min(1.0, y_min))
        x_max = max(0.0, min(1.0, x_max))
        y_max = max(0.0, min(1.0, y_max))
        # Ensure min < max
        if x_max <= x_min or y_max <= y_min:
          focal = default_focal
        else:
          focal = {
            'cx': round((x_min + x_max) / 2, 4),
            'cy': round((y_min + y_max) / 2, 4),
            'w': round(x_max - x_min, 4),
            'h': round(y_max - y_min, 4),
          }
      except (ValueError, TypeError):
        focal = default_focal
    else:
      focal = default_focal

    # Extract description (everything before the BBOX line)
    description = re.sub(r'\n*BBOX:.*', '', raw_text, flags=re.IGNORECASE).strip()
    if not description:
      description = f'Product image: {filename}'

    return description, focal

  # ------------------------------------------------------------------
  # Internal helpers
  # ------------------------------------------------------------------

  def _embedding_match(
    self,
    script_lines: Sequence[str],
    assets: Sequence[AssetRecord],
    segment_length: float,
    focal_map: dict[str, FocalRegion] | None = None,
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
        # Extract format without the 'image/' prefix (e.g. 'image/jpeg' -> 'jpeg')
        # Defaults to png if for some reason content_type isn't set
        img_fmt = (asset.content_type.split('/')[-1] if asset.content_type else 'png')
        if img_fmt == 'jpg':
            img_fmt = 'jpeg'
            
        payload = {
            "taskType": "SINGLE_EMBEDDING",
            "singleEmbeddingParams": {
                "embeddingPurpose": "DOCUMENT_RETRIEVAL",
                "image": {
                    "format": img_fmt,
                    "source": { "bytes": b64 }
                }
            }
        }
        resp = runtime.invoke_model(
          modelId=model_id,
          body=json.dumps(payload),
        )
        body = json.loads(resp['body'].read())
        image_embeddings[asset.id] = body.get('embeddings', [{}])[0].get('embedding', [])
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
    # Use a frequency penalty to ensure all images are used before repeating any.
    asset_usages: dict[str, int] = {a.id: 0 for a in embeddable_assets}
    storyboard: list[StoryboardSegment] = []
    for index, line in enumerate(script_lines):
      chosen_asset: AssetRecord | None = None
      try:
        payload = {
            "taskType": "SINGLE_EMBEDDING",
            "singleEmbeddingParams": {
                "embeddingPurpose": "DOCUMENT_RETRIEVAL",
                "text": {
                    "value": line,
                    "truncationMode": "END"
                }
            }
        }
        resp = runtime.invoke_model(
          modelId=model_id,
          body=json.dumps(payload),
        )
        body = json.loads(resp['body'].read())
        line_emb: list[float] = body.get('embeddings', [{}])[0].get('embedding', [])
        chosen_asset = max(
          embeddable_assets,
          key=lambda a: cosine_similarity(line_emb, image_embeddings[a.id])
                        - (10.0 * asset_usages[a.id]),
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
          focal_region=focal_map.get(chosen_asset.id) if focal_map else None,
        )
      )
      asset_usages[chosen_asset.id] = asset_usages.get(chosen_asset.id, 0) + 1

    return storyboard

  @staticmethod
  def _round_robin_match(
    script_lines: Sequence[str],
    assets: Sequence[AssetRecord],
    segment_length: float,
    focal_map: dict[str, FocalRegion] | None = None,
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
          focal_region=focal_map.get(asset.id) if focal_map else None,
        )
      )
    return storyboard

  # synthesize_voice() has been removed — TTS is now handled by
  # app.services.voice.factory.build_voice_provider()

  @staticmethod
  def _mock_script(project: ProjectRecord) -> list[ScriptScene]:
    scenes = [
      (f'Introducing {project.title}, designed for modern sellers.', 'Product hero shot, clean background'),
      ('Capture buyer attention in the first three seconds.', 'Eye-catching lifestyle scene with the product'),
      ('Highlight the top value proposition with visual proof.', 'Close-up of product key feature'),
      ('Show quality details and practical everyday usage.', 'Person using the product in daily life'),
      ('Reinforce trust with concise product benefits and social proof.', 'Customer testimonial or social proof overlay'),
      ('Close with a clear call to action for immediate purchase.', 'Product with CTA text overlay'),
    ]
    return [ScriptScene(narration=n, visual_requirements=v) for n, v in scenes]
