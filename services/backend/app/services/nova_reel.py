from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

import boto3
from botocore.exceptions import ClientError

from app.config import Settings

logger = logging.getLogger(__name__)


class NovaReelService:
    """Service for generating video clips using Amazon Nova Reel."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._bedrock_client = boto3.client(
            'bedrock',
            region_name=settings.aws_region,
        )
        self._s3_client = boto3.client(
            's3',
            region_name=settings.aws_region,
        )

    async def generate_batch(
        self,
        tasks: List[Tuple[int, int, Any]],
        project_id: str,
    ) -> Dict[int, Path]:
        """Generate Nova Reel video clips for a batch of tasks.

        Args:
            tasks: List of (scene_index, scene_order, storyboard_segment) tuples
            project_id: Project ID for storage paths

        Returns:
            Dict mapping scene_order -> local clip path
        """
        if not tasks or not self._settings.use_nova_reel:
            return {}

        logger.info('Starting Nova Reel batch generation for %d tasks', len(tasks))

        # Step 1: Start async invocations concurrently
        invocation_tasks = []
        for scene_index, scene_order, storyboard_segment in tasks:
            image_prompt = getattr(storyboard_segment, 'visual_requirements', '') or 'Product in lifestyle setting'
            invocation_tasks.append(
                self._start_async_invocation(scene_order, image_prompt)
            )

        try:
            # Wait for all invocations to start
            invocation_ids = await asyncio.gather(*invocation_tasks, return_exceptions=True)
            
            # Filter out failed invocations
            pending_tasks = []
            for i, (scene_index, scene_order, _) in enumerate(tasks):
                result = invocation_ids[i]
                if isinstance(result, Exception):
                    logger.error('Failed to start Nova Reel invocation for scene %d: %s', scene_order, result)
                    continue
                if result:
                    pending_tasks.append((scene_order, result))
                else:
                    logger.warning('No invocation ID returned for scene %d', scene_order)

            if not pending_tasks:
                logger.error('No Nova Reel invocations were started successfully')
                return {}

            # Step 2: Single unified polling loop
            clip_map = await self._poll_and_download(pending_tasks, project_id)
            
            logger.info('Nova Reel batch generation completed: %d/%d clips generated', 
                       len(clip_map), len(tasks))
            return clip_map

        except Exception as e:
            logger.error('Nova Reel batch generation failed: %s', e)
            return {}

    async def _start_async_invocation(self, scene_order: int, image_prompt: str) -> str | None:
        """Start an async Nova Reel invocation."""
        try:
            # Prepare the request for Nova Reel
            request_body = {
                "input": {
                    "prompt": image_prompt,
                    "duration_seconds": 5,  # Fixed 5-second duration
                    "aspect_ratio": "16:9",  # Default aspect ratio
                },
                "outputConfig": {
                    "s3Location": {
                        "bucketName": self._settings.nova_reel_output_bucket,
                        "objectKey": f"nova-reel-output/{scene_order:03d}.mp4"
                    }
                }
            }

            response = self._bedrock_client.start_async_invoke(
                modelId='amazon.nova-reel-v1:0',
                requestBody=json.dumps(request_body)
            )

            invocation_id = response.get('invocationArn')
            if invocation_id:
                # Extract just the ID from the ARN for easier handling
                invocation_id = invocation_id.split('/')[-1]
                logger.info('Started Nova Reel invocation for scene %d: %s', scene_order, invocation_id)
                return invocation_id
            else:
                logger.error('No invocation ID in response for scene %d', scene_order)
                return None

        except ClientError as e:
            logger.error('Failed to start Nova Reel invocation for scene %d: %s', scene_order, e)
            return None
        except Exception as e:
            logger.error('Unexpected error starting Nova Reel invocation for scene %d: %s', scene_order, e)
            return None

    async def _poll_and_download(
        self,
        pending_tasks: List[Tuple[int, str]],
        project_id: str,
    ) -> Dict[int, Path]:
        """Poll for completion and download completed clips."""
        # Map scene_order -> invocation_id
        task_map = {scene_order: inv_id for scene_order, inv_id in pending_tasks}
        
        # Track completion status
        completed = set()
        failed = set()
        clip_map: Dict[int, Path] = {}

        # Storage paths
        storage_root = self._settings.local_data_dir / self._settings.local_storage_dir
        clips_dir = storage_root / 'projects' / project_id / 'clips'
        clips_dir.mkdir(parents=True, exist_ok=True)

        # Polling loop with timeout (typically 90-180 seconds)
        start_time = time.time()
        max_wait_seconds = 300  # 5 minute timeout
        
        while len(completed) + len(failed) < len(pending_tasks):
            if time.time() - start_time > max_wait_seconds:
                logger.warning('Nova Reel polling timeout after %d seconds', max_wait_seconds)
                break

            # Poll each pending invocation
            for scene_order, invocation_id in pending_tasks:
                if scene_order in completed or scene_order in failed:
                    continue

                try:
                    response = self._bedrock_client.get_async_invoke(
                        invocationArn=f'arn:aws:bedrock:us-east-1:amazon.nova-reel-v1:0/invocation/{invocation_id}'
                    )
                    
                    status = response.get('status', 'Unknown')
                    
                    if status == 'Completed':
                        # Download the clip
                        clip_path = clips_dir / f'nova_reel_{scene_order:03d}.mp4'
                        success = await self._download_clip(invocation_id, clip_path)
                        
                        if success:
                            clip_map[scene_order] = clip_path
                            completed.add(scene_order)
                            logger.info('Nova Reel clip ready for scene %d', scene_order)
                        else:
                            failed.add(scene_order)
                            logger.error('Failed to download Nova Reel clip for scene %d', scene_order)
                    
                    elif status == 'Failed':
                        failed.add(scene_order)
                        logger.error('Nova Reel invocation failed for scene %d: %s', 
                                     scene_order, response.get('failureMessage', 'Unknown error'))
                    
                    elif status in ['InProgress', 'Submitted']:
                        # Still processing, continue polling
                        pass
                    
                    else:
                        logger.warning('Unknown Nova Reel status for scene %d: %s', scene_order, status)

                except ClientError as e:
                    logger.error('Failed to poll Nova Reel invocation for scene %d: %s', scene_order, e)
                    failed.add(scene_order)

            # Wait before next poll iteration
            if len(completed) + len(failed) < len(pending_tasks):
                await asyncio.sleep(10)  # Poll every 10 seconds

        logger.info('Nova Reel polling complete: %d completed, %d failed', 
                   len(completed), len(failed))
        return clip_map

    async def _download_clip(self, invocation_id: str, output_path: Path) -> bool:
        """Download a completed Nova Reel clip from S3."""
        try:
            # Construct the S3 key for the output
            s3_key = f"nova-reel-output/{invocation_id}.mp4"
            
            # Download from S3
            self._s3_client.download_file(
                Bucket=self._settings.nova_reel_output_bucket,
                Key=s3_key,
                Filename=str(output_path)
            )
            
            # Verify the downloaded file
            if output_path.exists() and output_path.stat().st_size > 1000:  # Minimum 1KB
                logger.info('Downloaded Nova Reel clip: %s', output_path.name)
                return True
            else:
                logger.error('Downloaded Nova Reel clip is empty or missing: %s', output_path)
                return False

        except ClientError as e:
            logger.error('Failed to download Nova Reel clip %s: %s', invocation_id, e)
            return False
        except Exception as e:
            logger.error('Unexpected error downloading Nova Reel clip %s: %s', invocation_id, e)
            return False
