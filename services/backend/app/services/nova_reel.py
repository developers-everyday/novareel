from __future__ import annotations

import asyncio
import base64
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
            'bedrock-runtime',
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
        job_id: str,
    ) -> Dict[int, Path]:
        """Generate Nova Reel video clips for a batch of tasks.

        Args:
            tasks: List of (scene_index, scene_order, storyboard_segment, image_prompt) tuples
            project_id: Project ID for storage paths
            job_id: Job ID for storage paths

        Returns:
            Dict mapping scene_order -> local clip path
        """
        if not tasks or not self._settings.use_nova_reel:
            return {}

        logger.info('Starting Nova Reel batch generation for %d tasks', len(tasks))

        # Step 1: Start async invocations concurrently
        invocation_tasks = []
        
        # Instantiate VideoService once for the entire batch
        from app.services.video import VideoService
        video_svc = VideoService(self._settings)
        
        for scene_index, scene_order, storyboard_segment, image_prompt in tasks:
            image_asset_id = getattr(storyboard_segment, 'image_asset_id', None)
            
            # Resolve image bytes if asset_id is available
            image_bytes = None
            if image_asset_id and project_id:
                image_path = video_svc._resolve_asset_path(image_asset_id, project_id)
                if image_path and image_path.exists():
                    image_bytes = image_path.read_bytes()
            
            invocation_tasks.append(
                self._start_async_invocation(scene_order, image_prompt, image_bytes)
            )

        try:
            # Wait for all invocations to start
            invocation_ids = await asyncio.gather(*invocation_tasks, return_exceptions=True)
            
            # Filter out failed invocations
            pending_tasks = []
            for i, (scene_index, scene_order, _, _) in enumerate(tasks):
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
            clip_map = await self._poll_and_download(pending_tasks, project_id, job_id)
            
            logger.info('Nova Reel batch generation completed: %d/%d clips generated', 
                       len(clip_map), len(tasks))
            return clip_map

        except Exception as e:
            logger.error('Nova Reel batch generation failed: %s', e)
            return {}

    async def _start_async_invocation(self, scene_order: int, image_prompt: str, image_bytes: bytes | None) -> str | None:
        """Start an async Nova Reel invocation."""
        try:
            # Prepare the request for Nova Reel
            if image_bytes:
                # Image-to-video mode
                request_body = {
                    "taskType": "IMAGE_VIDEO",
                    "imageToVideoParams": {
                        "text": image_prompt,
                        "images": [
                            {
                                "format": "jpeg" if image_bytes[0] == 0xFF else "png",
                                "source": {
                                    "bytes": base64.b64encode(image_bytes).decode("utf-8")
                                }
                            }
                        ]
                    },
                    "videoGenerationConfig": {
                        "durationSeconds": 6,
                        "fps": 24,
                        "dimension": "1280x720",
                    },
                    "outputDataConfig": {
                        "s3OutputDataConfig": {
                            "s3Uri": f"s3://{self._settings.nova_reel_output_bucket}/nova-reel-output/scene-{scene_order:03d}/"
                        }
                    }
                }
            else:
                # Text-only fallback (should not happen in normal operation)
                request_body = {
                    "taskType": "TEXT_VIDEO",
                    "textToVideoParams": {
                        "text": image_prompt,
                    },
                    "videoGenerationConfig": {
                        "durationSeconds": 6,
                        "fps": 24,
                        "dimension": "1280x720",
                    },
                    "outputDataConfig": {
                        "s3OutputDataConfig": {
                            "s3Uri": f"s3://{self._settings.nova_reel_output_bucket}/nova-reel-output/scene-{scene_order:03d}/"
                        }
                    }
                }

            # Separate model input from output configuration
            model_input = {k: v for k, v in request_body.items() if k != 'outputDataConfig'}
            response = self._bedrock_client.start_async_invoke(
                modelId='amazon.nova-reel-v1:0',
                modelInput=model_input,
                outputDataConfig=request_body['outputDataConfig'],
            )

            invocation_arn = response.get('invocationArn')
            if invocation_arn:
                logger.info('Started Nova Reel invocation for scene %d: %s', scene_order, invocation_arn)
                return invocation_arn
            else:
                logger.error('No invocation ARN in response for scene %d', scene_order)
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
        job_id: str,
    ) -> Dict[int, Path]:
        """Poll for completion and download completed clips."""
        # Track completion status
        completed = set()
        failed = set()
        clip_map: Dict[int, Path] = {}

        # Storage paths
        storage_root = self._settings.local_data_dir / self._settings.local_storage_dir
        clips_dir = storage_root / 'projects' / project_id / 'clips' / job_id
        clips_dir.mkdir(parents=True, exist_ok=True)

        # Polling loop with timeout (typically 90-180 seconds)
        start_time = time.time()
        max_wait_seconds = 300  # 5 minute timeout
        
        while len(completed) + len(failed) < len(pending_tasks):
            if time.time() - start_time > max_wait_seconds:
                logger.warning('Nova Reel polling timeout after %d seconds', max_wait_seconds)
                break

            # Poll each pending invocation
            for scene_order, invocation_arn in pending_tasks:
                if scene_order in completed or scene_order in failed:
                    continue

                try:
                    response = self._bedrock_client.get_async_invoke(
                        invocationArn=invocation_arn
                    )
                    
                    status = response.get('status', 'Unknown')
                    
                    if status == 'Completed':
                        # Get the actual S3 URI Nova Reel wrote to
                        output_uri = response.get('outputDataConfig', {}) \
                                           .get('s3OutputDataConfig', {}) \
                                           .get('s3Uri', '')
                        
                        if not output_uri:
                            logger.error('Scene %d: get_async_invoke returned no outputDataConfig s3Uri', scene_order)
                            failed.add(scene_order)
                            continue
                            
                        clip_path = clips_dir / f'nova_reel_{scene_order:03d}.mp4'
                        success = await self._download_clip_from_uri(output_uri, clip_path)
                        
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

    async def _download_clip_from_uri(self, s3_uri: str, output_path: Path) -> bool:
        """Download a completed Nova Reel clip using the S3 URI from the response."""
        try:
            # Parse s3://bucket/key
            without_scheme = s3_uri.removeprefix('s3://')
            bucket, _, key = without_scheme.partition('/')
            # Nova Reel outputs a file named 'output.mp4' inside the prefix folder
            if not key.endswith('.mp4'):
                key = key.rstrip('/') + '/output.mp4'

            self._s3_client.download_file(
                Bucket=bucket,
                Key=key,
                Filename=str(output_path),
            )
            if output_path.exists() and output_path.stat().st_size > 1000:
                logger.info('Downloaded Nova Reel clip: %s', output_path.name)
                return True
            logger.error('Downloaded Nova Reel clip is empty or missing: %s', output_path)
            return False
        except ClientError as e:
            logger.error('Failed to download Nova Reel clip %s: %s', s3_uri, e)
            return False
        except Exception as e:
            logger.error('Unexpected error downloading Nova Reel clip %s: %s', s3_uri, e)
            return False
