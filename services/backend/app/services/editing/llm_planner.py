"""LLM-driven editing plan generation.

Prompts Amazon Bedrock (Nova) with the product description, storyboard, and
available assets, then asks it to produce an EditingPlan JSON.  Falls back to
the deterministic planner if the LLM output is invalid.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from app.models import StoryboardSegment
from app.services.editing.schema import EditingPlan
from app.services.editing.planner import generate_plan as deterministic_plan
from app.services.effects import VideoEffectsConfig

logger = logging.getLogger(__name__)

# ── Prompt ─────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are an expert video editor AI. You will receive a product description, a storyboard \
(list of scenes with script lines, image asset paths, and durations), and a set of \
available post-processing options. Your job is to produce a JSON editing plan that \
describes how to assemble the final video.

The editing plan schema has these step types:

SEGMENT STEPS (define the clips in order):
- "image_segment": Ken-Burns zoom on a still image.
    Fields: order (int), image_path (str), duration_sec (float), zoom ("zoom_in"|"zoom_out"), \
zoom_speed (float 0-0.01), max_zoom (float 1.0-2.0), fps (int), caption_text (str|null)
- "video_segment": Trim/scale a video clip (B-roll).
    Fields: order (int), video_path (str), duration_sec (float), fps (int), caption_text (str|null)
- "color_segment": Solid-color placeholder.
    Fields: order (int), color_hex (str), duration_sec (float), fps (int)

TRANSITION (applied between all adjacent segments):
- "transition": Fields: effect (str, e.g. "fade","slideleft","slideright","dissolve","circleopen"), \
duration_sec (float 0.1-2.0)

POST-PROCESSING STEPS (applied after segment assembly, in order):
- "intro_clip": Fields: clip_path (str)
- "outro_clip": Fields: clip_path (str)
- "text_overlay": Fields: text (str), font_size (int), font_color (str), border_width (int), \
border_color (str), x (str), y (str), start_sec (float), duration_sec (float), font_path (str|null)
- "logo_overlay": Fields: logo_path (str), position ("top-right"|"top-left"|"bottom-right"|"bottom-left"), \
size_pct (float 0.01-0.5), opacity (float 0-1), padding_px (int)
- "subtitle_burn": Fields: subtitle_path (str), subtitle_format ("ass"|"srt")
- "audio_mux": Fields: audio_path (str), codec (str, default "aac")
- "music_mix": Fields: music_path (str), volume (float 0-1), loop (bool)
- "thumbnail": Fields: time_sec (float), quality (int 1-31)

Every step MUST include a "type" field matching one of the types above.

Top-level plan fields:
- version: "1.0"
- resolution: e.g. "1920x1080"
- fps: 24
- ffmpeg_preset: e.g. "medium"
- steps: [...list of steps...]

Rules:
1. Keep segment order sequential starting from 0.
2. Use creative zoom directions and speeds to make the video dynamic.
3. Vary transition effects if appropriate for the product tone.
4. Place title overlay in the first 3 seconds and CTA overlay in the last 4 seconds.
5. Always include an audio_mux step if narration audio is provided.
6. Always include a thumbnail step.
7. Output ONLY valid JSON, no markdown fences, no explanation."""

_USER_PROMPT = """\
Product description: {product_description}

Storyboard:
{storyboard_json}

Available assets:
- Audio narration: {audio_path}
- Background music: {music_path}
- ASS subtitles: {subtitle_path}
- Brand logo: {logo_path}
- Brand font: {font_path}
- Intro clip: {intro_path}
- Outro clip: {outro_path}

Target resolution: {resolution}
FFmpeg preset: {ffmpeg_preset}

Generate the editing plan JSON."""


def generate_plan_with_llm(
    *,
    product_description: str,
    storyboard: list[StoryboardSegment],
    effects_config: VideoEffectsConfig,
    aspect_ratio: str = '16:9',
    audio_path: Path | None = None,
    music_path: Path | None = None,
    ass_subtitle_path: Path | None = None,
    ffmpeg_preset: str = 'medium',
    project_id: str = '',
    resolve_asset_fn: 'callable | None' = None,
    bedrock_client=None,
    bedrock_model: str = 'amazon.nova-lite-v1:0',
    use_mock: bool = False,
) -> EditingPlan:
    """Generate an EditingPlan using the LLM, with deterministic fallback.

    Args:
        product_description: Text description of the product.
        storyboard: Pipeline storyboard segments.
        effects_config: Current effects configuration.
        aspect_ratio: Target aspect ratio.
        audio_path: Path to narration audio.
        music_path: Path to background music.
        ass_subtitle_path: Path to ASS subtitle file.
        ffmpeg_preset: FFmpeg preset.
        project_id: Project ID for asset resolution.
        resolve_asset_fn: Asset path resolver function.
        bedrock_client: boto3 bedrock-runtime client.
        bedrock_model: Bedrock model ID.
        use_mock: If True, skip LLM and return deterministic plan.

    Returns:
        An EditingPlan, either LLM-generated or deterministic fallback.
    """
    # Build the deterministic plan as fallback (always available)
    fallback = deterministic_plan(
        storyboard=storyboard,
        effects_config=effects_config,
        aspect_ratio=aspect_ratio,
        audio_path=audio_path,
        music_path=music_path,
        ass_subtitle_path=ass_subtitle_path,
        ffmpeg_preset=ffmpeg_preset,
        project_id=project_id,
        resolve_asset_fn=resolve_asset_fn,
    )

    if use_mock or bedrock_client is None:
        logger.info('LLM planner: using deterministic fallback (mock=%s, client=%s)',
                     use_mock, bedrock_client is not None)
        return fallback

    try:
        plan = _invoke_llm(
            product_description=product_description,
            storyboard=storyboard,
            effects_config=effects_config,
            resolution=fallback.resolution,
            audio_path=audio_path,
            music_path=music_path,
            ass_subtitle_path=ass_subtitle_path,
            ffmpeg_preset=ffmpeg_preset,
            project_id=project_id,
            resolve_asset_fn=resolve_asset_fn,
            bedrock_client=bedrock_client,
            bedrock_model=bedrock_model,
        )
        logger.info('LLM planner: successfully generated plan with %d steps', len(plan.steps))
        return plan

    except Exception as exc:
        logger.warning('LLM planner failed, using deterministic fallback: %s', exc)
        return fallback


def _invoke_llm(
    *,
    product_description: str,
    storyboard: list[StoryboardSegment],
    effects_config: VideoEffectsConfig,
    resolution: str,
    audio_path: Path | None,
    music_path: Path | None,
    ass_subtitle_path: Path | None,
    ffmpeg_preset: str,
    project_id: str,
    resolve_asset_fn,
    bedrock_client,
    bedrock_model: str,
) -> EditingPlan:
    """Call the LLM and parse the response into an EditingPlan."""

    # Build storyboard JSON for the prompt
    storyboard_data = []
    for idx, seg in enumerate(storyboard):
        entry: dict = {
            'order': idx,
            'script_line': seg.script_line,
            'duration_sec': seg.duration_sec,
            'media_type': seg.media_type or 'image',
        }
        if seg.media_type == 'video' and seg.video_path:
            entry['video_path'] = seg.video_path
        elif resolve_asset_fn and seg.image_asset_id:
            resolved = resolve_asset_fn(seg.image_asset_id, project_id)
            if resolved and Path(resolved).exists():
                entry['image_path'] = str(resolved)
        storyboard_data.append(entry)

    user_prompt = _USER_PROMPT.format(
        product_description=product_description,
        storyboard_json=json.dumps(storyboard_data, indent=2),
        audio_path=str(audio_path) if audio_path else 'None',
        music_path=str(music_path) if music_path else 'None',
        subtitle_path=str(ass_subtitle_path) if ass_subtitle_path else 'None',
        logo_path=str(effects_config.logo_path) if effects_config.logo_path else 'None',
        font_path=str(effects_config.brand_font_path) if effects_config.brand_font_path else 'None',
        intro_path=str(effects_config.intro_clip_path) if effects_config.intro_clip_path else 'None',
        outro_path=str(effects_config.outro_clip_path) if effects_config.outro_clip_path else 'None',
        resolution=resolution,
        ffmpeg_preset=ffmpeg_preset,
    )

    body = json.dumps({
        'messages': [
            {'role': 'user', 'content': [{'text': user_prompt}]},
        ],
        'system': [{'text': _SYSTEM_PROMPT}],
        'inferenceConfig': {'maxTokens': 4096, 'temperature': 0.7},
    })

    response = bedrock_client.invoke_model(
        modelId=bedrock_model,
        contentType='application/json',
        accept='application/json',
        body=body,
    )

    resp_body = json.loads(response['body'].read())
    raw_text = resp_body.get('output', {}).get('message', {}).get('content', [{}])[0].get('text', '')

    # Strip markdown fences if present
    cleaned = raw_text.strip()
    if cleaned.startswith('```'):
        lines = cleaned.split('\n')
        lines = lines[1:]  # remove opening fence
        if lines and lines[-1].strip() == '```':
            lines = lines[:-1]
        cleaned = '\n'.join(lines)

    plan = EditingPlan.from_json(cleaned)

    # Validate: must have at least one segment
    if not plan.segment_steps:
        raise ValueError('LLM plan has no segment steps')

    return plan
