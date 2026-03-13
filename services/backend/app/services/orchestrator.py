"""Agentic Pipeline Orchestrator — Nova Pro drives the video generation pipeline.

Nova Pro (orchestrator) inspects available resources, decides what actions to
take, reviews/self-corrects the script, and intelligently falls back to AI image
generation when stock footage fails.  Nova Lite (worker) does the heavy lifting
(script generation, image analysis, B-roll planning).

Architecture:
  Nova Pro (tool-use loop via Converse API)
    ├─ tool: analyze_images      → NovaService.analyze_images()
    ├─ tool: generate_script     → NovaService.generate_script()
    ├─ tool: review_script       → Nova Pro reviews inline (no external call)
    ├─ tool: synthesize_audio    → TTS provider → audio duration (AUDIO-FIRST)
    ├─ tool: plan_media          → Decide per-scene visuals with real durations
    ├─ tool: search_stock_footage→ StockMediaService.search_videos()
    ├─ tool: generate_ai_image   → ImageGenerator.generate_scene_image() (JPG only)
    ├─ tool: match_images        → NovaService.match_images()
    └─ tool: finalize            → Returns artifacts to pipeline
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.config import Settings
    from app.models import (
        AssetRecord,
        GenerationJobRecord,
        ProjectRecord,
        ScriptScene,
        StoryboardSegment,
    )
    from app.repositories.base import Repository
    from app.services.nova import NovaService
    from app.services.storage import StorageService

logger = logging.getLogger(__name__)


# ── Tool Definitions ──────────────────────────────────────────────────────────

ORCHESTRATOR_TOOLS = [
    {
        'toolSpec': {
            'name': 'analyze_images',
            'description': (
                'Analyze uploaded product images using Nova Vision. '
                'Returns per-image descriptions and focal regions. '
                'Call this first to understand what product images are available.'
            ),
            'inputSchema': {
                'json': {
                    'type': 'object',
                    'properties': {
                        'reasoning': {
                            'type': 'string',
                            'description': 'Why you are analyzing images now.',
                        },
                    },
                    'required': ['reasoning'],
                },
            },
        },
    },
    {
        'toolSpec': {
            'name': 'generate_script',
            'description': (
                'Generate a 6-scene marketing video script using Nova Lite. '
                'The script includes spoken narration and visual requirements per scene. '
                'Requires image analysis to be completed first.'
            ),
            'inputSchema': {
                'json': {
                    'type': 'object',
                    'properties': {
                        'reasoning': {
                            'type': 'string',
                            'description': 'Why you are generating a script now.',
                        },
                    },
                    'required': ['reasoning'],
                },
            },
        },
    },
    {
        'toolSpec': {
            'name': 'review_script',
            'description': (
                'Review the current script for quality, accuracy, and tone. '
                'Provide specific issues found and a corrected version of any weak scenes. '
                'Only call this after generate_script has produced a script.'
            ),
            'inputSchema': {
                'json': {
                    'type': 'object',
                    'properties': {
                        'issues': {
                            'type': 'array',
                            'items': {'type': 'string'},
                            'description': 'List of specific issues found in the script.',
                        },
                        'revised_scenes': {
                            'type': 'array',
                            'items': {
                                'type': 'object',
                                'properties': {
                                    'scene_index': {
                                        'type': 'integer',
                                        'description': '0-based index of the scene to revise.',
                                    },
                                    'spoken_narration': {
                                        'type': 'string',
                                        'description': 'Revised narration text.',
                                    },
                                    'visual_requirements': {
                                        'type': 'string',
                                        'description': 'Revised visual requirements.',
                                    },
                                },
                                'required': ['scene_index', 'spoken_narration'],
                            },
                            'description': 'Revised scenes. Only include scenes that need changes.',
                        },
                        'approved': {
                            'type': 'boolean',
                            'description': 'True if the script is good enough to proceed.',
                        },
                        'review_summary': {
                            'type': 'string',
                            'description': 'Brief summary of the review for the user.',
                        },
                    },
                    'required': ['approved', 'review_summary'],
                },
            },
        },
    },
    {
        'toolSpec': {
            'name': 'plan_media',
            'description': (
                'Plan per-scene media decisions: which scenes keep the product image, '
                'which get AI-generated images, and which get stock B-roll footage. '
                'IMPORTANT: When only 1-2 product images are available, you MUST plan '
                'ai_generated images for at least 3 scenes to create visual variety. '
                'Do NOT repeat the same product image for all 6 scenes.'
            ),
            'inputSchema': {
                'json': {
                    'type': 'object',
                    'properties': {
                        'reasoning': {
                            'type': 'string',
                            'description': 'Explain your media strategy based on available resources.',
                        },
                        'scene_decisions': {
                            'type': 'array',
                            'items': {
                                'type': 'object',
                                'properties': {
                                    'scene_index': {
                                        'type': 'integer',
                                        'description': '0-based scene index.',
                                    },
                                    'media_type': {
                                        'type': 'string',
                                        'enum': ['product_closeup', 'product_in_context', 'broll', 'ai_generated'],
                                        'description': (
                                            'product_closeup: keep uploaded product image. '
                                            'product_in_context: product image with wider framing. '
                                            'broll: stock footage from Pexels. '
                                            'ai_generated: generate new image via Nova Canvas.'
                                        ),
                                    },
                                    'search_query': {
                                        'type': 'string',
                                        'description': 'Pexels search query (required for broll).',
                                    },
                                    'image_prompt': {
                                        'type': 'string',
                                        'description': 'AI image generation prompt (required for ai_generated).',
                                    },
                                },
                                'required': ['scene_index', 'media_type'],
                            },
                        },
                    },
                    'required': ['reasoning', 'scene_decisions'],
                },
            },
        },
    },
    {
        'toolSpec': {
            'name': 'search_stock_footage',
            'description': (
                'Search Pexels for stock B-roll video clips. Returns clip metadata '
                'or empty list if nothing suitable found. If empty, consider falling '
                'back to ai_generated for that scene.'
            ),
            'inputSchema': {
                'json': {
                    'type': 'object',
                    'properties': {
                        'scene_index': {
                            'type': 'integer',
                            'description': '0-based scene index this search is for.',
                        },
                        'query': {
                            'type': 'string',
                            'description': 'Pexels search query (3-6 specific visual words).',
                        },
                    },
                    'required': ['scene_index', 'query'],
                },
            },
        },
    },
    {
        'toolSpec': {
            'name': 'generate_ai_image',
            'description': (
                'Generate a contextual image using Nova Canvas. Use this when stock '
                'footage is unavailable or when you need a specific product-in-scene '
                'visual that does not exist in the uploaded images.'
            ),
            'inputSchema': {
                'json': {
                    'type': 'object',
                    'properties': {
                        'scene_index': {
                            'type': 'integer',
                            'description': '0-based scene index.',
                        },
                        'prompt': {
                            'type': 'string',
                            'description': (
                                'Detailed image generation prompt. Describe the product in a '
                                'specific lifestyle/campaign context with lighting, setting, '
                                'and composition details.'
                            ),
                        },
                    },
                    'required': ['scene_index', 'prompt'],
                },
            },
        },
    },
    {
        'toolSpec': {
            'name': 'synthesize_audio',
            'description': (
                'Generate the TTS narration audio from the current script. '
                'Returns the exact audio duration and per-scene duration. '
                'MUST be called after review_script and BEFORE plan_media, so you '
                'know the real timing when planning video elements.'
            ),
            'inputSchema': {
                'json': {
                    'type': 'object',
                    'properties': {
                        'reasoning': {
                            'type': 'string',
                            'description': 'Why you are synthesizing audio now.',
                        },
                    },
                    'required': ['reasoning'],
                },
            },
        },
    },
    {
        'toolSpec': {
            'name': 'finalize',
            'description': (
                'Signal that all planning is complete. Call this when: '
                '(1) images are analyzed, (2) script is generated and reviewed, '
                '(3) audio is synthesized, (4) media plan is decided, and '
                '(5) any needed AI images are generated. '
                'Returns the final artifacts to the pipeline.'
            ),
            'inputSchema': {
                'json': {
                    'type': 'object',
                    'properties': {
                        'summary': {
                            'type': 'string',
                            'description': 'Brief summary of what was decided and why.',
                        },
                    },
                    'required': ['summary'],
                },
            },
        },
    },
]


# ── Result Dataclass ──────────────────────────────────────────────────────────

@dataclass
class OrchestratorResult:
    """Artifacts produced by the orchestrator for the rest of the pipeline."""
    image_analysis: list[dict] = field(default_factory=list)
    script_scenes: list[Any] = field(default_factory=list)
    script_lines: list[str] = field(default_factory=list)
    storyboard: list[Any] = field(default_factory=list)
    media_plan: list[dict] = field(default_factory=list)
    review_notes: str = ''
    summary: str = ''
    success: bool = False
    audio_duration: float = 0.0
    audio_key: str = ''
    per_scene_duration: float = 0.0


# ── Orchestrator Class ────────────────────────────────────────────────────────

class PipelineOrchestrator:
    """Nova Pro-driven agentic orchestrator for the video generation pipeline.

    Runs a Converse API tool-use loop where Nova Pro decides which pipeline
    steps to execute, reviews quality, and handles fallbacks.
    """

    def __init__(
        self,
        settings: 'Settings',
        nova: 'NovaService',
        storage: 'StorageService',
        repo: 'Repository',
    ):
        self._settings = settings
        self._nova = nova
        self._storage = storage
        self._repo = repo
        self._client = None

        # State accumulated during the agentic loop
        self._image_analysis: list[dict] = []
        self._script_scenes: list[Any] = []
        self._script_lines: list[str] = []
        self._storyboard: list[Any] = []
        self._media_plan: list[dict] = []
        self._review_notes: str = ''
        self._generated_images: dict[int, Path] = {}  # scene_index → image path
        self._generated_videos: dict[int, Path] = {}  # scene_index → video path
        self._broll_clips: dict[int, tuple[Path, float]] = {}  # scene_index → (path, duration)
        # Audio-first state
        self._audio_duration: float = 0.0
        self._per_scene_duration: float = 0.0
        self._audio_key: str = ''

    def _get_client(self):
        if self._client is None:
            import boto3
            self._client = boto3.client(
                'bedrock-runtime', region_name=self._settings.aws_region,
            )
        return self._client

    # ── Main entry point ──────────────────────────────────────────────────

    def run(
        self,
        *,
        project: 'ProjectRecord',
        job: 'GenerationJobRecord',
        assets: list['AssetRecord'],
        clips_dir: Path,
    ) -> OrchestratorResult:
        """Run the agentic orchestrator loop.

        Args:
            project: The project record.
            job: The generation job record.
            assets: Uploaded product image assets.
            clips_dir: Directory for generated clips/images.

        Returns:
            OrchestratorResult with all pipeline artifacts.
        """
        result = OrchestratorResult()

        if self._settings.use_mock_ai:
            logger.info('Orchestrator: mock mode — using linear fallback')
            return self._mock_fallback(project, job, assets, clips_dir, result)

        client = self._get_client()
        system_prompt = self._build_system_prompt(project, job, assets)

        messages: list[dict] = [
            {
                'role': 'user',
                'content': [{'text': (
                    f'Please orchestrate the video generation pipeline for this project. '
                    f'You have {len(assets)} uploaded product image(s). '
                    f'Start by analyzing the images, then generate and review a script, '
                    f'plan the media for each scene, and generate any needed AI images. '
                    f'Call finalize when everything is ready.'
                )}],
            },
        ]

        max_turns = self._settings.orchestrator_max_turns
        finalized = False

        for turn in range(max_turns):
            try:
                response = client.converse(
                    modelId=self._settings.bedrock_model_orchestrator,
                    system=[{'text': system_prompt}],
                    messages=messages,
                    inferenceConfig={'maxTokens': 2000, 'temperature': 0.2},
                    toolConfig={'tools': ORCHESTRATOR_TOOLS},
                )
            except Exception as exc:
                logger.error('Orchestrator Converse API call failed (turn %d): %s', turn, exc)
                break

            stop_reason = response.get('stopReason', '')
            assistant_message = response['output']['message']
            messages.append(assistant_message)

            # Log any text the model produced
            for block in assistant_message.get('content', []):
                if 'text' in block:
                    logger.info('Orchestrator (turn %d): %s', turn, block['text'][:200])

            if stop_reason == 'end_turn':
                logger.info('Orchestrator finished without calling finalize (turn %d)', turn)
                finalized = True
                break

            if stop_reason != 'tool_use':
                logger.info('Orchestrator stop_reason=%s at turn %d', stop_reason, turn)
                break

            # Process all tool calls in this turn
            tool_results: list[dict] = []
            for block in assistant_message.get('content', []):
                if 'toolUse' not in block:
                    continue

                tool_use = block['toolUse']
                tool_name = tool_use['name']
                tool_input = tool_use['input']
                tool_use_id = tool_use['toolUseId']

                logger.info('Orchestrator tool call: %s (input keys: %s)',
                            tool_name, list(tool_input.keys()))

                try:
                    tool_output = self._execute_tool(
                        tool_name, tool_input, project, job, assets, clips_dir,
                    )
                except Exception as exc:
                    logger.error('Tool %s failed: %s', tool_name, exc)
                    tool_output = {'error': str(exc)}

                tool_results.append({
                    'toolUseId': tool_use_id,
                    'content': [{'json': tool_output}],
                })

                if tool_name == 'finalize':
                    finalized = True

            # Append tool results as user message
            messages.append({
                'role': 'user',
                'content': [{'toolResult': tr} for tr in tool_results],
            })

            if finalized:
                logger.info('Orchestrator finalized at turn %d', turn)
                break
        else:
            logger.warning('Orchestrator hit max turns (%d) without finalizing', max_turns)

        # Build result from accumulated state
        result.image_analysis = self._image_analysis
        result.script_scenes = self._script_scenes
        result.script_lines = self._script_lines
        result.storyboard = self._storyboard
        result.media_plan = self._media_plan
        result.review_notes = self._review_notes
        result.audio_duration = self._audio_duration
        result.audio_key = self._audio_key
        result.per_scene_duration = self._per_scene_duration
        result.success = finalized and bool(self._script_scenes)

        if not result.success:
            logger.warning('Orchestrator did not produce complete artifacts, using linear fallback')
            return self._mock_fallback(project, job, assets, clips_dir, result)

        # Build storyboard from media plan if not already built
        if not self._storyboard and self._script_scenes:
            seg_len = self._per_scene_duration if self._per_scene_duration > 0 else None
            self._storyboard = self._nova.match_images(
                self._script_lines, assets, image_analysis=self._image_analysis,
                segment_length=seg_len,
            )
            result.storyboard = self._storyboard

        # Apply media plan (AI-generated images, B-roll) to storyboard
        if self._media_plan and self._storyboard:
            self._apply_media_plan_to_storyboard(
                project.id, assets, clips_dir, job.aspect_ratio,
            )
            result.storyboard = self._storyboard

        return result

    # ── Tool execution dispatcher ─────────────────────────────────────────

    def _execute_tool(
        self,
        tool_name: str,
        tool_input: dict,
        project: 'ProjectRecord',
        job: 'GenerationJobRecord',
        assets: list['AssetRecord'],
        clips_dir: Path,
    ) -> dict:
        """Execute a tool and return the result as a dict."""

        if tool_name == 'analyze_images':
            return self._tool_analyze_images(assets)

        if tool_name == 'generate_script':
            return self._tool_generate_script(project, job)

        if tool_name == 'review_script':
            return self._tool_review_script(tool_input)

        if tool_name == 'synthesize_audio':
            return self._tool_synthesize_audio(project, job)

        if tool_name == 'plan_media':
            return self._tool_plan_media(tool_input, assets)

        if tool_name == 'search_stock_footage':
            return self._tool_search_stock_footage(
                tool_input, job.aspect_ratio, clips_dir,
            )

        if tool_name == 'generate_ai_image':
            return self._tool_generate_ai_image(
                tool_input, project, assets, clips_dir, job.aspect_ratio,
            )

        if tool_name == 'finalize':
            return self._tool_finalize(tool_input)

        return {'error': f'Unknown tool: {tool_name}'}

    # ── Tool implementations ──────────────────────────────────────────────

    def _tool_analyze_images(self, assets: list['AssetRecord']) -> dict:
        """Analyze uploaded product images."""
        self._image_analysis = self._nova.analyze_images(assets)
        descriptions = [
            f"Image {i+1} ({a['asset_id'][:8]}): {a['description']}"
            for i, a in enumerate(self._image_analysis)
        ]
        return {
            'num_images': len(self._image_analysis),
            'descriptions': descriptions,
        }

    def _tool_generate_script(
        self, project: 'ProjectRecord', job: 'GenerationJobRecord',
    ) -> dict:
        """Generate a 6-scene script using Nova Lite."""
        self._script_scenes = self._nova.generate_script(
            project,
            image_analysis=self._image_analysis,
            language=job.language,
            script_template=job.script_template,
        )
        self._script_lines = [s.narration for s in self._script_scenes]
        scenes_data = [
            {
                'index': i,
                'narration': s.narration,
                'visual_requirements': s.visual_requirements,
            }
            for i, s in enumerate(self._script_scenes)
        ]
        return {'num_scenes': len(self._script_scenes), 'scenes': scenes_data}

    def _tool_review_script(self, tool_input: dict) -> dict:
        """Apply script review decisions from Nova Pro."""
        approved = tool_input.get('approved', True)
        review_summary = tool_input.get('review_summary', '')
        revised_scenes = tool_input.get('revised_scenes', [])
        issues = tool_input.get('issues', [])

        self._review_notes = review_summary
        if issues:
            self._review_notes += '\n\nIssues found:\n' + '\n'.join(f'- {i}' for i in issues)

        # Apply revisions to existing script
        revisions_applied = 0
        from app.models import ScriptScene
        for rev in revised_scenes:
            idx = rev.get('scene_index', -1)
            if 0 <= idx < len(self._script_scenes):
                new_narration = rev.get('spoken_narration', '')
                new_visual = rev.get('visual_requirements', '')
                if new_narration:
                    self._script_scenes[idx] = ScriptScene(
                        narration=new_narration,
                        visual_requirements=new_visual or self._script_scenes[idx].visual_requirements,
                    )
                    self._script_lines[idx] = new_narration
                    revisions_applied += 1

        logger.info('Script review: approved=%s, revisions=%d, issues=%d',
                     approved, revisions_applied, len(issues))

        return {
            'approved': approved,
            'revisions_applied': revisions_applied,
            'review_notes': self._review_notes,
        }

    def _tool_synthesize_audio(
        self, project: 'ProjectRecord', job: 'GenerationJobRecord',
    ) -> dict:
        """Generate TTS narration and return the exact audio duration.

        This is the AUDIO-FIRST step: by knowing the real audio duration
        before planning media, every downstream element gets the correct
        per-scene duration from the start.
        """
        if not self._script_lines:
            return {'error': 'No script available. Call generate_script first.'}

        transcript = '\n'.join(self._script_lines)
        audio_key = f'projects/{project.id}/outputs/{job.id}.mp3'

        storage_root = self._settings.local_data_dir / self._settings.local_storage_dir
        audio_path = storage_root / audio_key

        # Generate TTS
        if self._settings.use_mock_ai:
            from app.services.voice.base import MOCK_SILENT_MP3
            audio_payload = MOCK_SILENT_MP3
        else:
            from app.services.voice.factory import build_voice_provider
            provider = build_voice_provider(job.voice_provider, self._settings)
            audio_payload = provider.synthesize(
                transcript[:3000], voice_gender=job.voice_gender, language=job.language,
            )

        self._storage.store_bytes(audio_key, audio_payload, content_type='audio/mpeg')

        # If mock AI, generate valid silence via ffmpeg matching a reasonable duration
        if self._settings.use_mock_ai and audio_path.exists():
            _ffmpeg = shutil.which('ffmpeg')
            if _ffmpeg:
                mock_dur = max(6.0 * len(self._script_lines), 36.0)
                subprocess.run([
                    _ffmpeg, '-y', '-f', 'lavfi', '-i', 'anullsrc=r=44100:cl=mono',
                    '-t', str(mock_dur), '-c:a', 'libmp3lame', '-q:a', '9',
                    str(audio_path),
                ], check=False, capture_output=True)

        # Audio post-processing (silence trim + normalize)
        if not self._settings.use_mock_ai and audio_path.exists() and audio_path.stat().st_size > 100:
            from app.services.audio import AudioProcessor
            AudioProcessor().process(audio_path, audio_path, trim_silence=True, normalize=True, speed=1.0)

        # Probe the actual audio duration
        from app.services.pipeline import _probe_audio_duration
        duration = _probe_audio_duration(audio_path) or 36.0

        num_scenes = max(len(self._script_lines), 1)
        per_scene = round(duration / num_scenes, 3)

        self._audio_duration = duration
        self._per_scene_duration = per_scene
        self._audio_key = audio_key

        # Also store transcript
        transcript_key = f'projects/{project.id}/outputs/{job.id}.txt'
        self._storage.store_text(transcript_key, transcript)

        logger.info('Audio synthesized: %.1fs total, %.2fs per scene (%d scenes)',
                     duration, per_scene, num_scenes)

        return {
            'audio_duration': round(duration, 2),
            'per_scene_duration': round(per_scene, 2),
            'num_scenes': num_scenes,
        }

    def _tool_plan_media(self, tool_input: dict, assets: list['AssetRecord']) -> dict:
        """Store the media plan decided by Nova Pro."""
        decisions = tool_input.get('scene_decisions', [])
        self._media_plan = decisions

        summary = {}
        for d in decisions:
            mt = d.get('media_type', 'product_closeup')
            summary[mt] = summary.get(mt, 0) + 1

        logger.info('Media plan: %s (from %d uploaded images)', summary, len(assets))
        return {'plan_summary': summary, 'num_scenes_planned': len(decisions)}

    def _tool_search_stock_footage(
        self, tool_input: dict, aspect_ratio: str, clips_dir: Path,
    ) -> dict:
        """Search Pexels for stock footage."""
        scene_index = tool_input.get('scene_index', 0)
        query = tool_input.get('query', 'lifestyle product')

        if not self._settings.pexels_api_key:
            return {'found': False, 'reason': 'Pexels API key not configured'}

        from app.services.stock_media import StockMediaService, get_orientation_for_aspect_ratio

        cache_dir = self._settings.local_data_dir / 'cache' / 'pexels'
        stock_service = StockMediaService(self._settings.pexels_api_key, cache_dir=cache_dir)
        orientation = get_orientation_for_aspect_ratio(aspect_ratio)

        results = stock_service.search_videos(
            query, orientation=orientation, min_duration=2, max_duration=30,
        )

        if not results:
            return {
                'found': False,
                'scene_index': scene_index,
                'query': query,
                'reason': 'No clips found. Consider using ai_generated instead.',
            }

        # Download the best clip
        clip_info = results[0]
        clip_path = clips_dir / f'broll_{scene_index:03d}.mp4'
        clips_dir.mkdir(parents=True, exist_ok=True)

        downloaded = stock_service.download_clip(clip_info['url'], clip_path)
        if downloaded and clip_path.exists():
            self._broll_clips[scene_index] = (clip_path, min(clip_info['duration'], 8.0))
            return {
                'found': True,
                'scene_index': scene_index,
                'query': query,
                'duration': clip_info['duration'],
                'clip_path': str(clip_path),
            }

        return {
            'found': False,
            'scene_index': scene_index,
            'query': query,
            'reason': 'Download failed. Consider using ai_generated instead.',
        }

    def _tool_generate_ai_image(
        self,
        tool_input: dict,
        project: 'ProjectRecord',
        assets: list['AssetRecord'],
        clips_dir: Path,
        aspect_ratio: str,
    ) -> dict:
        """Generate an AI image via Nova Canvas (JPG only — no pre-rendered video).

        The video renderer (video.py) handles converting images to video
        segments at the correct duration via zoompan.  Pre-rendering to .mp4
        here caused duration mismatches because the orchestrator didn't know
        the final per-scene duration at generation time.
        """
        from app.services.image_generator import ImageGenerator
        from app.services.video import VideoService

        scene_index = tool_input.get('scene_index', 0)
        prompt = tool_input.get('prompt', 'Product in a lifestyle setting')

        clips_dir.mkdir(parents=True, exist_ok=True)
        gen_image_path = clips_dir / f'ai_gen_{scene_index:03d}.jpg'

        # Resolve best product image as reference
        product_img_path = None
        video_svc = VideoService(self._settings)
        if assets:
            product_img_path = video_svc._resolve_asset_path(
                assets[0].id, project.id,
            )

        img_gen = ImageGenerator(self._settings)
        generated = img_gen.generate_scene_image(
            product_image_path=product_img_path,
            scene_description=prompt,
            visual_requirements='',
            product_description=project.product_description,
            output_path=gen_image_path,
            aspect_ratio=aspect_ratio,
        )

        if not generated:
            return {'success': False, 'scene_index': scene_index, 'reason': 'Image generation failed'}

        # Store the generated image path — video rendering happens later
        # in video.py which will render via zoompan at the correct duration.
        self._generated_images[scene_index] = gen_image_path
        logger.info('Orchestrator: AI image generated for scene %d (prompt: %s)',
                    scene_index, prompt[:60])
        return {
            'success': True,
            'scene_index': scene_index,
            'image_path': str(gen_image_path),
        }

    def _tool_finalize(self, tool_input: dict) -> dict:
        """Signal completion."""
        summary = tool_input.get('summary', 'Pipeline orchestration complete.')
        logger.info('Orchestrator finalize: %s', summary)
        return {'status': 'finalized', 'summary': summary}

    # ── Apply media plan to storyboard ────────────────────────────────────

    def _apply_media_plan_to_storyboard(
        self,
        project_id: str,
        assets: list['AssetRecord'],
        clips_dir: Path,
        aspect_ratio: str,
    ) -> None:
        """Apply generated images and B-roll clips to the storyboard.

        AI-generated images are stored as image paths on the segment
        (media_type stays 'image', ai_image_path holds the JPG).
        The video renderer (video.py) handles converting them to zoompan
        video at the correct duration.

        B-roll clips are stored as video paths with their actual clip
        duration capped to the per-scene duration.
        """
        from app.models import StoryboardSegment

        for decision in self._media_plan:
            idx = decision.get('scene_index', -1)
            media_type = decision.get('media_type', 'product_closeup')

            if idx < 0 or idx >= len(self._storyboard):
                continue

            seg = self._storyboard[idx]

            if media_type == 'ai_generated' and idx in self._generated_images:
                img_path = self._generated_images[idx]
                self._storyboard[idx] = StoryboardSegment(
                    order=seg.order,
                    script_line=seg.script_line,
                    image_asset_id=seg.image_asset_id,
                    start_sec=seg.start_sec,
                    duration_sec=seg.duration_sec,
                    media_type='image',
                    ai_image_path=str(img_path),
                    focal_region=seg.focal_region,
                    is_ai_generated=True,
                )

            elif media_type == 'broll' and idx in self._broll_clips:
                clip_path, clip_dur = self._broll_clips[idx]
                self._storyboard[idx] = StoryboardSegment(
                    order=seg.order,
                    script_line=seg.script_line,
                    image_asset_id=seg.image_asset_id,
                    start_sec=seg.start_sec,
                    duration_sec=min(seg.duration_sec, clip_dur),
                    media_type='video',
                    video_path=str(clip_path),
                    focal_region=seg.focal_region,
                )

        # Recalculate start_sec
        running_start = 0.0
        for seg in self._storyboard:
            seg.start_sec = round(running_start, 3)
            running_start += seg.duration_sec

    # ── System prompt ─────────────────────────────────────────────────────

    def _build_system_prompt(
        self,
        project: 'ProjectRecord',
        job: 'GenerationJobRecord',
        assets: list['AssetRecord'],
    ) -> str:
        return (
            'You are NovaReel\'s Agentic Pipeline Orchestrator — a creative video director AI.\n\n'
            'Your job is to orchestrate the generation of a product marketing video.\n'
            'You make decisions about what actions to take based on the available resources.\n\n'
            f'PROJECT CONTEXT:\n'
            f'- Title: {project.title}\n'
            f'- Product description: {project.product_description[:500]}\n'
            f'- Uploaded images: {len(assets)}\n'
            f'- Script template: {job.script_template}\n'
            f'- Video style: {job.video_style}\n'
            f'- Aspect ratio: {job.aspect_ratio}\n'
            f'- Language: {job.language}\n\n'
            'WORKFLOW:\n'
            '1. Call analyze_images to understand the uploaded product photos.\n'
            '2. Call generate_script to create a 6-scene narration script.\n'
            '3. Call review_script to check quality — fix any weak scenes inline.\n'
            '   If the script needs major changes, call generate_script again (max 1 retry).\n'
            '4. Call synthesize_audio to generate the TTS narration. This returns the\n'
            '   exact audio duration and per-scene duration — use these when planning media.\n'
            '5. Call plan_media to decide per-scene visuals:\n'
            f'   - You have {len(assets)} uploaded image(s).\n'
            + (
                '   - With only 1-2 images, you MUST use ai_generated for at least 3 scenes.\n'
                '     Do NOT show the same product image 6 times — that makes a boring video.\n'
                '     Use product_closeup for the first and last scenes, and ai_generated\n'
                '     for middle scenes to show the product in different lifestyle contexts.\n'
                if len(assets) <= 2 else
                '   - With 3+ images, prioritize product images. Use ai_generated or broll\n'
                '     for 1-2 scenes to add variety.\n'
            ) +
            '6. For scenes marked broll: call search_stock_footage.\n'
            '   If Pexels returns nothing, call generate_ai_image as fallback.\n'
            '7. For scenes marked ai_generated: call generate_ai_image with a detailed prompt\n'
            '   describing the product in a lifestyle context (lighting, setting, composition).\n'
            '8. Call finalize when everything is ready.\n\n'
            'RULES:\n'
            '- Always call analyze_images first.\n'
            '- Always call synthesize_audio BEFORE plan_media — you need the real durations.\n'
            '- Always review the script before synthesizing audio.\n'
            '- Never skip the finalize step.\n'
            '- Keep reasoning concise — focus on decisions, not long explanations.\n'
        )

    # ── Mock / linear fallback ────────────────────────────────────────────

    def _mock_fallback(
        self,
        project: 'ProjectRecord',
        job: 'GenerationJobRecord',
        assets: list['AssetRecord'],
        clips_dir: Path,
        result: OrchestratorResult,
    ) -> OrchestratorResult:
        """Fall back to the existing linear pipeline logic."""
        # Analyze
        result.image_analysis = self._nova.analyze_images(assets)

        # Script
        result.script_scenes = self._nova.generate_script(
            project,
            image_analysis=result.image_analysis,
            language=job.language,
            script_template=job.script_template,
        )
        result.script_lines = [s.narration for s in result.script_scenes]

        # Match
        result.storyboard = self._nova.match_images(
            result.script_lines, assets, image_analysis=result.image_analysis,
        )

        result.review_notes = 'Linear fallback used (mock mode or orchestrator unavailable).'
        result.success = True
        return result
