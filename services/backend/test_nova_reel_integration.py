#!/usr/bin/env python3
"""
Integration test for Nova Reel pipeline path.

Forces a nova_reel media decision for one scene by patching BRollDirector.plan_scenes,
then runs _fetch_stock_footage_with_director end-to-end.

Usage:
    cd services/backend && source .venv/bin/activate
    python test_nova_reel_integration.py
"""
import asyncio
import logging
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))

from app.config import get_settings
from app.models import ScriptScene, StoryboardSegment
from app.services.pipeline import _fetch_stock_footage_with_director

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

# ── Test data ────────────────────────────────────────────────────────────────

PROJECT_ID = 'c3868f58-79ba-46f5-acef-316252be9e9c'
JOB_ID     = 'nova-reel-test-001'

SCRIPT_SCENES = [
    ScriptScene(narration='Introducing the Portronics Toad 23.', visual_requirements='Product hero shot on desk'),
    ScriptScene(narration='Enjoy 10-metre wireless freedom.', visual_requirements='Mouse in motion, cable-free workspace'),
    ScriptScene(narration='Ergonomic design keeps you comfortable.', visual_requirements='Hand resting naturally on mouse'),
]

STORYBOARD = [
    StoryboardSegment(order=1, script_line=SCRIPT_SCENES[0].narration, image_asset_id='c4dd3baf-222a-495a-87f1-814924f6178e', start_sec=0.0, duration_sec=5.8),
    StoryboardSegment(order=2, script_line=SCRIPT_SCENES[1].narration, image_asset_id='8cc27817-999d-42d1-82e3-dbe5244d2ec6', start_sec=5.8, duration_sec=5.8),
    StoryboardSegment(order=3, script_line=SCRIPT_SCENES[2].narration, image_asset_id='0868f81e-2e5f-4396-8310-36feee4ceaee', start_sec=11.6, duration_sec=5.8),
]

# Force scene 2 to be nova_reel, scenes 1 and 3 stay product_closeup
MOCK_SCENE_PLAN = [
    {'media_type': 'product_closeup'},
    {'media_type': 'nova_reel', 'image_prompt': 'Wireless mouse gliding effortlessly across a modern desk, motion blur, cinematic lighting'},
    {'media_type': 'product_closeup'},
]


async def run():
    settings = get_settings()

    if not settings.use_nova_reel:
        logger.error('NOVAREEL_USE_NOVA_REEL must be true — set it in .env')
        return False

    if not settings.nova_reel_output_bucket:
        logger.error('NOVAREEL_NOVA_REEL_OUTPUT_BUCKET must be set in .env')
        return False

    # Prepare clips dir (mirrors the pipeline's own path)
    storage_root = settings.local_data_dir / settings.local_storage_dir
    clips_dir = storage_root / 'projects' / PROJECT_ID / 'clips' / JOB_ID
    clips_dir.mkdir(parents=True, exist_ok=True)

    logger.info('=' * 60)
    logger.info('Nova Reel pipeline integration test')
    logger.info('Project : %s', PROJECT_ID)
    logger.info('Job     : %s', JOB_ID)
    logger.info('Scene plan: %s', [p['media_type'] for p in MOCK_SCENE_PLAN])
    logger.info('=' * 60)

    # Patch BRollDirector.plan_scenes to return our forced plan
    with patch('app.services.broll_director.BRollDirector.plan_scenes', return_value=MOCK_SCENE_PLAN):
        updated_storyboard = await _fetch_stock_footage_with_director(
            storyboard=STORYBOARD,
            script_scenes=SCRIPT_SCENES,
            product_description='Portronics Toad 23 Wireless Optical Mouse, 2.4GHz, adjustable DPI',
            image_analysis=None,
            aspect_ratio='16:9',
            video_style='product_only',
            stock_service=None,   # not needed — no broll scenes
            orientation='landscape',
            clips_dir=clips_dir,
            settings=settings,
            project_id=PROJECT_ID,
        )

    logger.info('=' * 60)
    logger.info('Results:')
    for seg in updated_storyboard:
        logger.info(
            '  Scene %d: media_type=%-6s  video_path=%s  broll_query=%s',
            seg.order, seg.media_type,
            Path(seg.video_path).name if seg.video_path else 'None',
            seg.broll_query or 'None',
        )

    # Validate scene 2 was upgraded to a video clip
    scene2 = next((s for s in updated_storyboard if s.order == 2), None)
    if scene2 and scene2.media_type == 'video' and scene2.video_path:
        clip = Path(scene2.video_path)
        if clip.exists() and clip.stat().st_size > 1000:
            logger.info('=' * 60)
            logger.info('✅  PASS — scene 2 Nova Reel clip: %s (%.1f KB)',
                        clip.name, clip.stat().st_size / 1024)
            return True
        else:
            logger.error('❌  FAIL — clip file missing or empty: %s', scene2.video_path)
    else:
        logger.error('❌  FAIL — scene 2 was not upgraded to a video clip')
        logger.error('    media_type=%s  video_path=%s',
                     getattr(scene2, 'media_type', 'N/A'),
                     getattr(scene2, 'video_path', 'N/A'))
    return False


if __name__ == '__main__':
    ok = asyncio.run(run())
    sys.exit(0 if ok else 1)
