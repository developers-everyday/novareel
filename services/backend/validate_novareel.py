#!/usr/bin/env python3
"""
Standalone validation script for Amazon Nova Reel integration.

This script tests:
1. AWS Bedrock permissions (StartAsyncInvoke, GetAsyncInvoke)
2. S3 write/read access to the Nova Reel output bucket
3. Nova Reel quota availability
4. End-to-end video generation and download

Usage:
    cd services/backend && source .venv/bin/activate
    python validate_novareel.py
"""

import asyncio
import json
import logging
import sys
import time
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

# Add the app directory to Python path
sys.path.insert(0, str(Path(__file__).parent / 'app'))

from app.config import get_settings

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)


class NovaReelValidator:
    """Validates Nova Reel integration end-to-end."""

    def __init__(self):
        self.settings = get_settings()
        self.bedrock_client = boto3.client(
            'bedrock-runtime',
            region_name=self.settings.aws_region,
        )
        self.s3_client = boto3.client(
            's3',
            region_name=self.settings.aws_region,
        )

    async def validate_configuration(self) -> bool:
        """Validate required configuration is present."""
        logger.info('Validating configuration...')
        
        if not self.settings.use_nova_reel:
            logger.error('NOVAREEL_USE_NOVA_REEL is not enabled')
            return False
            
        if not self.settings.nova_reel_output_bucket:
            logger.error('NOVAREEL_NOVA_REEL_OUTPUT_BUCKET is not configured')
            return False
            
        logger.info('✓ Configuration validation passed')
        return True

    async def validate_s3_access(self) -> bool:
        """Validate S3 bucket access and permissions."""
        logger.info('Validating S3 access...')
        
        bucket = self.settings.nova_reel_output_bucket
        
        try:
            # Test write permission by uploading a small test file
            test_key = 'nova-reel-test/test-file.txt'
            test_content = b'Nova Reel validation test'
            
            self.s3_client.put_object(
                Bucket=bucket,
                Key=test_key,
                Body=test_content,
                ContentType='text/plain'
            )
            logger.info('✓ S3 write access confirmed')
            
            # Test read permission
            response = self.s3_client.get_object(Bucket=bucket, Key=test_key)
            if response['Body'].read() == test_content:
                logger.info('✓ S3 read access confirmed')
            else:
                logger.error('S3 read validation failed: content mismatch')
                return False
            
            # Clean up test file
            self.s3_client.delete_object(Bucket=bucket, Key=test_key)
            logger.info('✓ S3 cleanup completed')
            
            return True
            
        except ClientError as e:
            logger.error(f'S3 access validation failed: {e}')
            return False
        except Exception as e:
            logger.error(f'Unexpected S3 error: {e}')
            return False

    async def validate_bedrock_permissions(self) -> bool:
        """Validate AWS Bedrock permissions for Nova Reel."""
        logger.info('Validating Bedrock permissions...')
        
        try:
            # Test StartAsyncInvoke permission (text-only probe — no image needed)
            model_input = {
                "taskType": "TEXT_VIDEO",
                "textToVideoParams": {
                    "text": "A simple test video of a product on a white background",
                },
                "videoGenerationConfig": {
                    "durationSeconds": 6,
                    "fps": 24,
                    "dimension": "1280x720",
                },
            }
            output_data_config = {
                "s3OutputDataConfig": {
                    "s3Uri": f"s3://{self.settings.nova_reel_output_bucket}/nova-reel-test/permissions-probe/"
                }
            }

            response = self.bedrock_client.start_async_invoke(
                modelId='amazon.nova-reel-v1:0',
                modelInput=model_input,
                outputDataConfig=output_data_config,
            )

            invocation_arn = response.get('invocationArn')
            if not invocation_arn:
                logger.error('No invocation ARN returned from StartAsyncInvoke')
                return False

            logger.info(f'✓ StartAsyncInvoke successful: {invocation_arn}')

            # Test GetAsyncInvoke permission — pass the full ARN directly
            response = self.bedrock_client.get_async_invoke(
                invocationArn=invocation_arn
            )

            status = response.get('status')
            logger.info(f'✓ GetAsyncInvoke successful: status={status}')

            return True
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'AccessDenied':
                logger.error(f'Bedrock permission denied: {e}')
            elif error_code == 'LimitExceeded':
                logger.error(f'Bedrock quota exceeded: {e}')
            else:
                logger.error(f'Bedrock API error: {e}')
            return False
        except Exception as e:
            logger.error(f'Unexpected Bedrock error: {e}')
            return False

    async def validate_end_to_end(self) -> bool:
        """Perform end-to-end validation with real video generation."""
        logger.info('Performing end-to-end validation...')
        
        try:
            # Start a real Nova Reel invocation (text-to-video)
            output_prefix = "nova-reel-test/e2e-validation/"
            model_input = {
                "taskType": "TEXT_VIDEO",
                "textToVideoParams": {
                    "text": "A sleek modern product displayed on a clean white background, professional lighting",
                },
                "videoGenerationConfig": {
                    "durationSeconds": 6,
                    "fps": 24,
                    "dimension": "1280x720",
                },
            }
            output_data_config = {
                "s3OutputDataConfig": {
                    "s3Uri": f"s3://{self.settings.nova_reel_output_bucket}/{output_prefix}"
                }
            }

            response = self.bedrock_client.start_async_invoke(
                modelId='amazon.nova-reel-v1:0',
                modelInput=model_input,
                outputDataConfig=output_data_config,
            )

            invocation_arn = response.get('invocationArn')
            if not invocation_arn:
                logger.error('Failed to start validation invocation')
                return False

            logger.info(f'Started validation invocation: {invocation_arn}')

            # Poll for completion (with timeout)
            max_wait_seconds = 180  # 3 minutes
            start_time = time.time()

            while time.time() - start_time < max_wait_seconds:
                try:
                    response = self.bedrock_client.get_async_invoke(
                        invocationArn=invocation_arn
                    )
                    
                    status = response.get('status')
                    logger.info(f'Invocation status: {status}')
                    
                    if status == 'Completed':
                        # Read the actual S3 URI from the response
                        output_uri = response.get('outputDataConfig', {}) \
                                             .get('s3OutputDataConfig', {}) \
                                             .get('s3Uri', '')
                        logger.info(f'✓ Nova Reel generation completed, output: {output_uri}')
                        break
                    elif status == 'Failed':
                        failure_message = response.get('failureMessage', 'Unknown error')
                        logger.error(f'Nova Reel generation failed: {failure_message}')
                        return False
                    elif status not in ['InProgress', 'Submitted']:
                        logger.warning(f'Unexpected status: {status}')

                    await asyncio.sleep(10)  # Wait 10 seconds between polls

                except ClientError as e:
                    logger.error(f'Polling error: {e}')
                    return False
            else:
                logger.error('End-to-end validation timed out')
                return False

            # Parse the S3 URI and download the generated video
            if not output_uri:
                logger.error('No output S3 URI in completed response')
                return False

            without_scheme = output_uri.removeprefix('s3://')
            bucket, _, key = without_scheme.partition('/')
            if not key.endswith('.mp4'):
                key = key.rstrip('/') + '/output.mp4'

            local_path = Path('validation_nova_reel.mp4')
            try:
                self.s3_client.download_file(
                    Bucket=bucket,
                    Key=key,
                    Filename=str(local_path),
                )

                if local_path.exists() and local_path.stat().st_size > 1000:
                    logger.info(f'✓ Video downloaded successfully: {local_path} ({local_path.stat().st_size} bytes)')

                    # Basic video validation using ffprobe if available
                    try:
                        import subprocess
                        result = subprocess.run([
                            'ffprobe', '-v', 'quiet', '-show_entries',
                            'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1',
                            str(local_path)
                        ], capture_output=True, text=True, check=False)

                        if result.returncode == 0:
                            duration = float(result.stdout.strip())
                            logger.info(f'✓ Video validation passed: duration={duration:.1f}s')
                        else:
                            logger.warning('ffprobe validation failed, but file exists')
                    except FileNotFoundError:
                        logger.info('ffprobe not available, skipping video validation')

                    return True
                else:
                    logger.error('Downloaded video is empty or missing')
                    return False

            finally:
                if local_path.exists():
                    local_path.unlink()

                # Clean up S3 prefix
                try:
                    self.s3_client.delete_object(Bucket=bucket, Key=key)
                except ClientError:
                    pass  # Ignore cleanup errors
            
        except Exception as e:
            logger.error(f'End-to-end validation error: {e}')
            return False

    async def run_validation(self) -> bool:
        """Run all validation steps."""
        logger.info('Starting Nova Reel validation...')
        
        steps = [
            ('Configuration', self.validate_configuration),
            ('S3 Access', self.validate_s3_access),
            ('Bedrock Permissions', self.validate_bedrock_permissions),
            ('End-to-End', self.validate_end_to_end),
        ]
        
        for step_name, step_func in steps:
            logger.info(f'\n--- {step_name} ---')
            try:
                if not await step_func():
                    logger.error(f'❌ {step_name} validation failed')
                    return False
                logger.info(f'✅ {step_name} validation passed')
            except Exception as e:
                logger.error(f'❌ {step_name} validation error: {e}')
                return False
        
        logger.info('\n🎉 All Nova Reel validations passed!')
        return True


async def main():
    """Main validation entry point."""
    validator = NovaReelValidator()
    
    try:
        success = await validator.run_validation()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        logger.info('Validation interrupted by user')
        sys.exit(1)
    except Exception as e:
        logger.error(f'Validation failed with unexpected error: {e}')
        sys.exit(1)


if __name__ == '__main__':
    asyncio.run(main())
