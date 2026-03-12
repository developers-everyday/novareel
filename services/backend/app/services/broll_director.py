"""Vision Director for intelligent B-roll planning and validation.

Uses Amazon Nova Vision (via Bedrock Converse API) to:
1. Plan per-scene media decisions (product_closeup / broll / product_in_context)
2. Generate targeted Pexels search queries based on visual requirements
3. Validate downloaded B-roll clips by scoring thumbnail relevance
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.config import Settings
    from app.models import ScriptScene

logger = logging.getLogger(__name__)

# ── Structured tool schema for scene planning ────────────────────────────────

_PLAN_TOOL_SPEC = {
    'toolSpec': {
        'name': 'broll_scene_plan',
        'description': (
            'Produces a per-scene media plan for a marketing video. '
            'Each scene gets a media_type decision and optional metadata.'
        ),
        'inputSchema': {
            'json': {
                'type': 'object',
                'properties': {
                    'scenes': {
                        'type': 'array',
                        'items': {
                            'type': 'object',
                            'properties': {
                                'media_type': {
                                    'type': 'string',
                                    'enum': ['product_closeup', 'broll', 'product_in_context', 'ai_generated'],
                                    'description': (
                                        'product_closeup: keep the uploaded product image with tight framing. '
                                        'broll: replace with stock footage — provide a search_query. '
                                        'product_in_context: keep product image but suggest wider/different framing. '
                                        'ai_generated: generate a new contextual image using AI (Nova Omni) — '
                                        'provide an image_prompt describing the desired scene with the product.'
                                    ),
                                },
                                'image_prompt': {
                                    'type': 'string',
                                    'description': (
                                        'Prompt for AI image generation (required when media_type is "ai_generated"). '
                                        'Describe the scene showing the product in a lifestyle/campaign context. '
                                        'Be specific about lighting, setting, and composition.'
                                    ),
                                },
                                'search_query': {
                                    'type': 'string',
                                    'description': (
                                        'Pexels search query (3-6 words) for stock footage. '
                                        'Required when media_type is "broll". '
                                        'Use specific, visual terms — avoid brand names.'
                                    ),
                                },
                                'acceptance_criteria': {
                                    'type': 'string',
                                    'description': (
                                        'Brief description of what makes a good clip for this scene. '
                                        'Used to validate downloaded footage.'
                                    ),
                                },
                                'focal_override': {
                                    'type': 'object',
                                    'description': 'Optional focal point override for product_closeup/product_in_context.',
                                    'properties': {
                                        'cx': {'type': 'number', 'description': 'Center X (0-1)'},
                                        'cy': {'type': 'number', 'description': 'Center Y (0-1)'},
                                        'w': {'type': 'number', 'description': 'Width fraction (0-1)'},
                                        'h': {'type': 'number', 'description': 'Height fraction (0-1)'},
                                    },
                                },
                                'reasoning': {
                                    'type': 'string',
                                    'description': 'Brief explanation of why this media type was chosen.',
                                },
                            },
                            'required': ['media_type'],
                        },
                    },
                },
                'required': ['scenes'],
            },
        },
    },
}

_VALIDATE_TOOL_SPEC = {
    'toolSpec': {
        'name': 'broll_relevance_score',
        'description': 'Scores a B-roll clip thumbnail for relevance to the scene requirements.',
        'inputSchema': {
            'json': {
                'type': 'object',
                'properties': {
                    'score': {
                        'type': 'number',
                        'description': 'Relevance score from 0 (completely irrelevant) to 10 (perfect match).',
                    },
                    'reasoning': {
                        'type': 'string',
                        'description': 'Brief explanation of the score.',
                    },
                },
                'required': ['score', 'reasoning'],
            },
        },
    },
}


class BRollDirector:
    """Nova Vision-powered B-roll director.

    Analyzes product images and script scenes to make intelligent decisions
    about which scenes should use stock footage vs. product images, generates
    targeted search queries, and validates clip relevance.
    """

    def __init__(self, settings: 'Settings'):
        self._settings = settings
        self._bedrock_client = None

    def _get_bedrock_client(self):
        """Lazy-init Bedrock client."""
        if self._bedrock_client is None and not self._settings.use_mock_ai:
            import boto3
            self._bedrock_client = boto3.client(
                'bedrock-runtime', region_name=self._settings.aws_region,
            )
        return self._bedrock_client

    # ── Step 1: Plan scenes ──────────────────────────────────────────────────

    def plan_scenes(
        self,
        *,
        script_scenes: list[ScriptScene],
        image_analysis: list[dict],
        product_description: str,
        video_style: str,
    ) -> list[dict]:
        """Use Nova Vision to decide per-scene media type and generate search queries.

        Args:
            script_scenes: Script scenes with narration + visual_requirements.
            image_analysis: Image analysis results (asset_id, description, focal_region).
            product_description: Product description for context.
            video_style: 'product_lifestyle' or 'lifestyle_focus'.

        Returns:
            List of dicts, one per scene, with keys:
            - media_type: 'product_closeup' | 'broll' | 'product_in_context'
            - search_query: Pexels query (only for broll)
            - acceptance_criteria: What makes a good clip
            - focal_override: Optional focal region override
            - reasoning: Why this decision was made
        """
        if self._settings.use_mock_ai:
            return self._mock_plan_scenes(script_scenes, video_style)

        client = self._get_bedrock_client()
        if client is None:
            return self._mock_plan_scenes(script_scenes, video_style)

        try:
            return self._invoke_plan(
                client, script_scenes, image_analysis, product_description, video_style,
            )
        except Exception as exc:
            logger.warning('Vision Director plan_scenes failed, using mock fallback: %s', exc)
            return self._mock_plan_scenes(script_scenes, video_style)

    def _invoke_plan(
        self,
        client,
        script_scenes: list[ScriptScene],
        image_analysis: list[dict],
        product_description: str,
        video_style: str,
    ) -> list[dict]:
        """Call Nova Vision to plan scenes."""
        # Build scene descriptions for the prompt
        scene_descriptions = []
        for i, scene in enumerate(script_scenes):
            scene_descriptions.append(
                f'Scene {i + 1}:\n'
                f'  Narration: "{scene.narration}"\n'
                f'  Visual requirement: "{scene.visual_requirements}"'
            )

        # Build image analysis context
        image_context = []
        for info in image_analysis:
            image_context.append(
                f'- Image {info["asset_id"][:8]}: {info["description"]}'
            )

        style_guidance = {
            'product_lifestyle': (
                'Prioritize the uploaded product images. At least 4 out of 6 scenes '
                'MUST use the uploaded product images (product_closeup or product_in_context). '
                'The first and last scenes MUST always be product_closeup. '
                'Use B-roll only for 1-2 middle scenes to add variety.'
            ),
            'lifestyle_focus': (
                'The first scene MUST be product_closeup (hero shot). '
                'At least 3 out of 6 scenes should use the uploaded product images '
                '(product_closeup or product_in_context). '
                'Use B-roll for atmosphere and lifestyle context in remaining scenes.'
            ),
        }

        prompt = (
            f'You are a creative video director planning B-roll for a product marketing video.\n\n'
            f'Product: {product_description[:500]}\n\n'
            f'Available product images:\n'
            f'{chr(10).join(image_context) if image_context else "No image analysis available."}\n\n'
            f'Video style: {video_style}\n'
            f'Style guidance: {style_guidance.get(video_style, "Use your best judgment.")}\n\n'
            f'Scenes:\n{chr(10).join(scene_descriptions)}\n\n'
            f'For each scene, decide the best media approach:\n'
            f'- "product_closeup": Use the uploaded product image with tight framing on a key feature. THIS IS THE DEFAULT — use it unless there is a strong reason not to.\n'
            f'- "product_in_context": Use the product image but with wider framing to show context.\n'
            f'- "broll": Use stock footage — provide a specific, visual Pexels search query (3-6 words). Only use this for mood/atmosphere shots where the product does NOT need to appear.\n'
            f'- "ai_generated": Generate a new image using AI — ONLY as a last resort when no uploaded image fits AND the scene specifically needs the product in a context that cannot be achieved with the existing images.\n\n'
            f'Rules:\n'
            f'- ALWAYS prioritize the uploaded product images first. The viewer should see the REAL product, not AI-generated versions.\n'
            f'- The first and last scenes MUST use product_closeup or product_in_context.\n'
            f'- At least half of all scenes must use the uploaded product images (product_closeup or product_in_context).\n'
            f'- B-roll queries must be specific and visual (e.g. "woman applying skincare morning routine" not "happy person").\n'
            f'- Avoid generic queries — they produce irrelevant results.\n'
            f'- Only use "ai_generated" if absolutely no other option works. In most videos, 0 ai_generated scenes is ideal.\n'
            f'- Include acceptance_criteria describing what the ideal clip/image looks like.\n'
            f'- Use the render tool to output your plan.'
        )

        response = client.converse(
            modelId=self._settings.bedrock_model_script,
            messages=[{'role': 'user', 'content': [{'text': prompt}]}],
            inferenceConfig={'maxTokens': 1500, 'temperature': 0.3},
            toolConfig={
                'tools': [_PLAN_TOOL_SPEC],
                'toolChoice': {'tool': {'name': 'broll_scene_plan'}},
            },
        )

        # Extract tool use output
        for block in response['output']['message']['content']:
            if 'toolUse' in block:
                tool_use = block['toolUse']
                if tool_use['name'] == 'broll_scene_plan':
                    scenes = tool_use['input'].get('scenes', [])
                    # Ensure we have one entry per script scene
                    while len(scenes) < len(script_scenes):
                        scenes.append({'media_type': 'product_closeup'})
                    return scenes[:len(script_scenes)]

        logger.warning('Vision Director: no tool use in response, using mock fallback')
        return self._mock_plan_scenes(script_scenes, video_style)

    # ── Step 2: Validate clips ───────────────────────────────────────────────

    def validate_clip(
        self,
        *,
        clip_path: Path,
        scene_narration: str,
        visual_requirements: str,
        acceptance_criteria: str,
    ) -> float:
        """Score a downloaded B-roll clip for relevance to the scene.

        Extracts a thumbnail frame from the clip and sends it to Nova Vision
        along with the scene context for scoring.

        Args:
            clip_path: Path to the downloaded video clip.
            scene_narration: The narration text for this scene.
            visual_requirements: What should be shown on screen.
            acceptance_criteria: Director's criteria for a good clip.

        Returns:
            Relevance score from 0 to 10.
        """
        if self._settings.use_mock_ai:
            return 8.0  # Mock: always accept

        client = self._get_bedrock_client()
        if client is None:
            return 8.0

        # Extract thumbnail frame
        thumb_bytes = self._extract_thumbnail(clip_path)
        if thumb_bytes is None:
            logger.warning('Failed to extract thumbnail from %s, accepting by default', clip_path)
            return 7.0  # Can't validate, give benefit of doubt

        try:
            return self._invoke_validate(
                client, thumb_bytes, scene_narration, visual_requirements, acceptance_criteria,
            )
        except Exception as exc:
            logger.warning('Vision Director validate_clip failed: %s — accepting by default', exc)
            return 7.0

    def _invoke_validate(
        self,
        client,
        thumb_bytes: bytes,
        scene_narration: str,
        visual_requirements: str,
        acceptance_criteria: str,
    ) -> float:
        """Call Nova Vision to score a clip thumbnail."""
        prompt = (
            f'You are evaluating a B-roll video clip for a marketing video scene.\n\n'
            f'Scene narration: "{scene_narration}"\n'
            f'Visual requirement: "{visual_requirements}"\n'
            f'Acceptance criteria: "{acceptance_criteria}"\n\n'
            f'The image below is a frame from a candidate B-roll clip.\n'
            f'Score how well this clip matches the scene requirements on a scale of 0-10:\n'
            f'- 0-3: Completely irrelevant (wrong subject, wrong mood)\n'
            f'- 4-5: Loosely related but poor fit\n'
            f'- 6-7: Decent match, acceptable\n'
            f'- 8-10: Excellent match\n\n'
            f'Use the scoring tool to provide your score.'
        )

        response = client.converse(
            modelId=self._settings.bedrock_model_script,
            messages=[{
                'role': 'user',
                'content': [
                    {
                        'image': {
                            'format': 'jpeg',
                            'source': {'bytes': thumb_bytes},
                        },
                    },
                    {'text': prompt},
                ],
            }],
            inferenceConfig={'maxTokens': 200, 'temperature': 0.1},
            toolConfig={
                'tools': [_VALIDATE_TOOL_SPEC],
                'toolChoice': {'tool': {'name': 'broll_relevance_score'}},
            },
        )

        for block in response['output']['message']['content']:
            if 'toolUse' in block:
                tool_use = block['toolUse']
                if tool_use['name'] == 'broll_relevance_score':
                    score = float(tool_use['input'].get('score', 5.0))
                    reasoning = tool_use['input'].get('reasoning', '')
                    logger.info('B-roll validation: score=%.1f, reason=%s', score, reasoning[:100])
                    return max(0.0, min(10.0, score))

        logger.warning('Vision Director: no score in validation response')
        return 5.0

    # ── Thumbnail extraction ─────────────────────────────────────────────────

    @staticmethod
    def _extract_thumbnail(clip_path: Path) -> bytes | None:
        """Extract the first frame from a video clip as JPEG bytes."""
        ffmpeg_path = shutil.which('ffmpeg')
        if not ffmpeg_path or not clip_path.exists():
            return None

        import tempfile
        thumb_path = Path(tempfile.mktemp(suffix='.jpg', prefix='broll-thumb-'))
        try:
            result = subprocess.run(
                [
                    ffmpeg_path, '-y',
                    '-i', str(clip_path),
                    '-frames:v', '1',
                    '-q:v', '5',
                    str(thumb_path),
                ],
                capture_output=True, check=False,
            )
            if result.returncode == 0 and thumb_path.exists() and thumb_path.stat().st_size > 100:
                return thumb_path.read_bytes()
            return None
        finally:
            thumb_path.unlink(missing_ok=True)

    # ── Mock implementations ─────────────────────────────────────────────────

    @staticmethod
    def _mock_plan_scenes(
        script_scenes: list[ScriptScene],
        video_style: str,
    ) -> list[dict]:
        """Deterministic mock plan based on video_style.

        product_lifestyle: scenes 0,2,4,5 = product images; 1,3 = broll
        lifestyle_focus: scenes 0,2,4 = product images; 1,3,5 = broll
        No ai_generated scenes by default — product images are prioritized.
        """
        plan: list[dict] = []
        mock_broll_queries = [
            'person using product happy lifestyle',
            'modern workspace productivity',
            'hands unboxing premium package',
            'satisfied customer daily routine',
            'professional creative environment',
            'people enjoying quality lifestyle',
        ]

        for i, scene in enumerate(script_scenes):
            if video_style == 'product_lifestyle':
                # Scenes 0, 2, 4, 5 → product images; 1, 3 → broll
                if i in (1, 3):
                    plan.append({
                        'media_type': 'broll',
                        'search_query': mock_broll_queries[i % len(mock_broll_queries)],
                        'acceptance_criteria': f'Lifestyle scene matching: {scene.visual_requirements}',
                        'reasoning': f'Mock: scene {i} gets B-roll for variety',
                    })
                elif i % 2 == 0:
                    plan.append({
                        'media_type': 'product_closeup',
                        'reasoning': f'Mock: scene {i} gets product close-up',
                    })
                else:
                    plan.append({
                        'media_type': 'product_in_context',
                        'reasoning': f'Mock: scene {i} gets product in context',
                    })
            elif video_style == 'lifestyle_focus':
                # Scenes 0, 2, 4 → product images; 1, 3, 5 → broll
                if i == 0:
                    plan.append({
                        'media_type': 'product_closeup',
                        'reasoning': 'Mock: first scene is always product hero shot',
                    })
                elif i % 2 == 0:
                    plan.append({
                        'media_type': 'product_in_context',
                        'reasoning': f'Mock: scene {i} gets product in context',
                    })
                else:
                    plan.append({
                        'media_type': 'broll',
                        'search_query': mock_broll_queries[i % len(mock_broll_queries)],
                        'acceptance_criteria': f'Lifestyle scene matching: {scene.visual_requirements}',
                        'reasoning': f'Mock: scene {i} gets lifestyle B-roll',
                    })
            else:
                plan.append({
                    'media_type': 'product_closeup',
                    'reasoning': 'Mock: default to product image',
                })

        return plan
