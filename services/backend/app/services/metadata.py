"""LLM-based metadata generation for social media platforms."""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

SUPPORTED_PLATFORMS = ('youtube', 'tiktok', 'instagram')

# ── Prompt template ─────────────────────────────────────────────────────────

_METADATA_PROMPT = """\
You are a social media marketing expert. Given a product description and the script used in a marketing video, generate platform-optimized metadata for the requested social media platforms.

Product description:
{product_description}

Video script:
{script_text}

Product keywords: {keywords}

Generate metadata for these platforms: {platforms}

Respond in JSON with this exact structure (include only requested platforms):
{{
  "youtube": {{
    "title": "...",
    "description": "...",
    "tags": ["...", "..."],
    "category": "..."
  }},
  "tiktok": {{
    "caption": "...",
    "hashtags": ["#...", "#..."]
  }},
  "instagram": {{
    "caption": "...",
    "hashtags": ["#...", "#..."]
  }}
}}

Rules:
- YouTube title: max 100 chars, include key product feature, use | separator for branding
- YouTube description: 2-3 paragraphs, include features list with bullet points, CTA
- YouTube tags: 8-15 relevant tags
- TikTok caption: max 150 chars, include 1-2 emojis, conversational tone
- TikTok hashtags: 5-8 trending-style hashtags
- Instagram caption: 2-3 short paragraphs, include emojis, CTA
- Instagram hashtags: 10-15 relevant hashtags
- All content must be specific to the product, never generic

Respond with ONLY valid JSON, no markdown fences.
"""


# ── Mock responses ──────────────────────────────────────────────────────────

def _mock_metadata(platforms: list[str], product_description: str) -> dict[str, Any]:
  """Return mock metadata for testing without LLM calls."""
  short_desc = product_description[:60]
  result: dict[str, Any] = {}

  if 'youtube' in platforms:
    result['youtube'] = {
      'title': f'Amazing Product Review | {short_desc}',
      'description': f'Check out this incredible product!\n\n{product_description}\n\n👉 Shop now!',
      'tags': ['product review', 'marketing', 'novareel', 'ecommerce'],
      'category': 'Science & Technology',
    }

  if 'tiktok' in platforms:
    result['tiktok'] = {
      'caption': f'This product just changed everything ✨ #productreview',
      'hashtags': ['#productreview', '#marketing', '#novareel', '#musthave', '#trending'],
    }

  if 'instagram' in platforms:
    result['instagram'] = {
      'caption': f'Say hello to your new favorite product ✨\n\n{short_desc}\n\n👉 Link in bio!',
      'hashtags': ['#productreview', '#ecommerce', '#marketing', '#novareel', '#shopnow'],
    }

  return result


# ── LLM metadata generation ────────────────────────────────────────────────

def generate_metadata(
  *,
  product_description: str,
  script_lines: list[str],
  platforms: list[str],
  keywords: list[str] | None = None,
  bedrock_client: Any = None,
  bedrock_model: str = '',
  use_mock: bool = False,
) -> dict[str, Any]:
  """Generate platform-specific metadata for a completed video.

  Args:
    product_description: The product description from the project.
    script_lines: The video script lines.
    platforms: List of target platforms ('youtube', 'tiktok', 'instagram').
    keywords: Optional product keywords to include.
    bedrock_client: boto3 bedrock-runtime client (required if not mock).
    bedrock_model: Bedrock model ID for script generation.
    use_mock: If True, return mock metadata.

  Returns:
    Dict keyed by platform with metadata dicts.
  """
  valid_platforms = [p for p in platforms if p in SUPPORTED_PLATFORMS]
  if not valid_platforms:
    return {}

  if use_mock:
    return _mock_metadata(valid_platforms, product_description)

  if not bedrock_client or not bedrock_model:
    logger.warning('No Bedrock client/model provided, falling back to mock metadata')
    return _mock_metadata(valid_platforms, product_description)

  script_text = '\n'.join(script_lines)
  keyword_str = ', '.join(keywords) if keywords else 'none provided'
  platform_str = ', '.join(valid_platforms)

  prompt = _METADATA_PROMPT.format(
    product_description=product_description,
    script_text=script_text,
    keywords=keyword_str,
    platforms=platform_str,
  )

  try:
    body = json.dumps({
      'messages': [{'role': 'user', 'content': [{'text': prompt}]}],
      'inferenceConfig': {'maxTokens': 2048, 'temperature': 0.7},
    })

    response = bedrock_client.invoke_model(
      modelId=bedrock_model,
      contentType='application/json',
      accept='application/json',
      body=body,
    )

    response_body = json.loads(response['body'].read())
    raw_text = response_body['output']['message']['content'][0]['text'].strip()

    # Strip markdown fences if present
    if raw_text.startswith('```'):
      lines = raw_text.split('\n')
      lines = [l for l in lines if not l.startswith('```')]
      raw_text = '\n'.join(lines)

    result = json.loads(raw_text)

    # Only return requested platforms
    return {k: v for k, v in result.items() if k in valid_platforms}

  except Exception:
    logger.exception('Metadata generation failed, falling back to mock')
    return _mock_metadata(valid_platforms, product_description)
