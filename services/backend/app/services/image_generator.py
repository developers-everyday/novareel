"""AI image generation service using Amazon Nova 2 Omni.

Nova 2 Omni can take a product image + text prompt and generate a new
contextual/lifestyle image showing the product in a scene described by
the prompt.  This enables brand campaign visuals without stock footage.
"""

from __future__ import annotations

import base64
import logging
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.config import Settings

logger = logging.getLogger(__name__)


class ImageGenerator:
    """Generate contextual brand campaign images using Nova 2 Omni.

    Given a product image and a scene description, generates a new image
    showing the product in the described context (e.g., "skincare serum
    on a marble bathroom counter with morning light").
    """

    def __init__(self, settings: 'Settings'):
        self._settings = settings
        self._client = None

    def _get_client(self):
        """Lazy-init Bedrock client."""
        if self._client is None and not self._settings.use_mock_ai:
            import boto3
            self._client = boto3.client(
                'bedrock-runtime', region_name=self._settings.aws_region,
            )
        return self._client

    def generate_scene_image(
        self,
        *,
        product_image_path: Path | None = None,
        scene_description: str,
        visual_requirements: str = '',
        product_description: str = '',
        output_path: Path,
        aspect_ratio: str = '16:9',
    ) -> Path | None:
        """Generate a contextual image for a video scene.

        Args:
            product_image_path: Path to the source product image (optional —
                if provided, the generated image will incorporate the product).
            scene_description: Text description of the desired scene.
            visual_requirements: Additional visual details from the script.
            output_path: Where to save the generated image.
            aspect_ratio: Target aspect ratio for dimension guidance.

        Returns:
            Path to the generated image, or None on failure.
        """
        if self._settings.use_mock_ai:
            # In mock mode, return None so pipeline keeps the product image
            # instead of showing a solid-color placeholder
            logger.info('Mock mode: skipping AI image generation, keeping product image')
            return None

        client = self._get_client()
        if client is None:
            return None

        try:
            return self._invoke_canvas(
                client=client,
                product_image_path=product_image_path,
                scene_description=scene_description,
                visual_requirements=visual_requirements,
                product_description=product_description,
                output_path=output_path,
                aspect_ratio=aspect_ratio,
            )
        except Exception as exc:
            logger.warning('Nova Canvas image generation failed: %s', exc)
            return None

    def _invoke_canvas(
        self,
        *,
        client,
        product_image_path: Path | None,
        scene_description: str,
        visual_requirements: str,
        product_description: str = '',
        output_path: Path,
        aspect_ratio: str,
    ) -> Path | None:
        """Call Nova Canvas via invoke_model to generate an image."""
        import json

        model_id = self._settings.bedrock_model_image

        # Nova Canvas supported dimensions (width x height)
        dims = {
            '16:9': (1280, 720),
            '1:1': (1024, 1024),
            '9:16': (720, 1280),
        }
        width, height = dims.get(aspect_ratio, (1280, 720))

        prompt = f'{scene_description}'
        if product_description:
            prompt += f'. Product: {product_description[:200]}'
        if visual_requirements:
            prompt += f'. {visual_requirements}'
        prompt += '. Photorealistic, well-lit, professional marketing photography. Do not include any text, words, letters, labels, or watermarks in the image.'

        negative_prompt = 'text, words, letters, numbers, labels, logos, watermarks, branding, captions, titles, subtitles, typography, writing, stamps'

        # Choose task type based on whether we have a reference image
        if product_image_path and product_image_path.exists():
            # IMAGE_VARIATION: generate a new image inspired by the reference
            ref_bytes = product_image_path.read_bytes()
            ref_b64 = base64.b64encode(ref_bytes).decode('utf-8')

            payload = {
                'taskType': 'IMAGE_VARIATION',
                'imageVariationParams': {
                    'text': prompt[:512],
                    'negativeText': negative_prompt,
                    'images': [ref_b64],
                    'similarityStrength': 0.7,
                },
                'imageGenerationConfig': {
                    'numberOfImages': 1,
                    'width': width,
                    'height': height,
                    'quality': 'standard',
                },
            }
        else:
            # TEXT_IMAGE: generate from text prompt only
            payload = {
                'taskType': 'TEXT_IMAGE',
                'textToImageParams': {
                    'text': prompt[:512],
                    'negativeText': negative_prompt,
                },
                'imageGenerationConfig': {
                    'numberOfImages': 1,
                    'width': width,
                    'height': height,
                    'quality': 'standard',
                },
            }

        response = client.invoke_model(
            modelId=model_id,
            contentType='application/json',
            accept='application/json',
            body=json.dumps(payload),
        )

        resp_body = json.loads(response['body'].read())
        images = resp_body.get('images', [])

        if images:
            img_bytes = base64.b64decode(images[0])
            if len(img_bytes) > 100:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(img_bytes)
                logger.info('Nova Canvas generated image: %s (%d bytes)', output_path, len(img_bytes))
                return output_path

        # Check for error
        error = resp_body.get('error')
        if error:
            logger.warning('Nova Canvas returned error: %s', error)

        logger.warning('Nova Canvas response did not contain images')
        return None

    def _generate_mock_image(self, output_path: Path, aspect_ratio: str) -> Path | None:
        """Generate a solid-color placeholder image via ffmpeg for mock mode."""
        ffmpeg_path = shutil.which('ffmpeg')
        if not ffmpeg_path:
            return None

        dims = {
            '16:9': '1920x1080',
            '1:1': '1080x1080',
            '9:16': '1080x1920',
        }
        resolution = dims.get(aspect_ratio, '1920x1080')

        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Generate a gradient-like placeholder image
        result = subprocess.run(
            [
                ffmpeg_path, '-y',
                '-f', 'lavfi',
                '-i', f'color=c=#2563EB:s={resolution}',
                '-frames:v', '1',
                '-q:v', '2',
                str(output_path),
            ],
            capture_output=True, check=False,
        )

        if result.returncode == 0 and output_path.exists() and output_path.stat().st_size > 100:
            logger.info('Mock image generated: %s', output_path)
            return output_path

        logger.warning('Mock image generation failed')
        return None

    def generate_scene_video_from_image(
        self,
        *,
        image_path: Path,
        duration_sec: float,
        output_path: Path,
        aspect_ratio: str = '16:9',
    ) -> Path | None:
        """Convert a generated image into a video segment with Ken-Burns effect.

        This is used to turn an AI-generated image into a video segment
        that can be inserted into the storyboard.

        Args:
            image_path: Path to the generated image.
            duration_sec: Duration of the video segment.
            output_path: Where to save the video segment.
            aspect_ratio: Target aspect ratio.

        Returns:
            Path to the video segment, or None on failure.
        """
        ffmpeg_path = shutil.which('ffmpeg')
        if not ffmpeg_path or not image_path.exists():
            return None

        dims = {
            '16:9': ('1920', '1080'),
            '1:1': ('1080', '1080'),
            '9:16': ('1080', '1920'),
        }
        width, height = dims.get(aspect_ratio, ('1920', '1080'))

        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Simple zoom-in effect on the generated image
        vf = (
            f'scale=8000:-1,'
            f"zoompan=z='min(zoom+0.0015,1.3)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":d={int(24 * duration_sec)}:s={width}x{height}:fps=24"
        )

        result = subprocess.run(
            [
                ffmpeg_path, '-y',
                '-i', str(image_path),
                '-vf', vf,
                '-t', str(duration_sec),
                '-c:v', 'libx264',
                '-preset', self._settings.ffmpeg_preset,
                '-pix_fmt', 'yuv420p',
                '-r', '24',
                str(output_path),
            ],
            capture_output=True, check=False,
        )

        if result.returncode == 0 and output_path.exists() and output_path.stat().st_size > 100:
            logger.info('Generated scene video from AI image: %s (%.1fs)', output_path, duration_sec)
            return output_path

        logger.warning('Failed to generate video from AI image: %s',
                        result.stderr.decode('utf-8', errors='replace')[-200:])
        return None
