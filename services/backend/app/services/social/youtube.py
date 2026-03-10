"""YouTube Data API v3 integration for video publishing."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.services.social.base import SocialPublisher, SocialPublishError

logger = logging.getLogger(__name__)


class YouTubePublisher(SocialPublisher):
  """Publish videos to YouTube via the Data API v3."""

  def __init__(self, access_token: str):
    self._access_token = access_token

  def publish_video(
    self,
    video_path: str,
    metadata: dict[str, Any],
    thumbnail_path: str | None = None,
  ) -> dict[str, Any]:
    """Upload a video to YouTube.

    Args:
      video_path: Local path to the MP4 file.
      metadata: Must include 'title', 'description', 'tags', 'category'.
      thumbnail_path: Optional local path to custom thumbnail.

    Returns:
      Dict with 'video_id', 'url', 'status'.
    """
    import httpx

    video_file = Path(video_path)
    if not video_file.exists():
      raise SocialPublishError(f'Video file not found: {video_path}')

    title = metadata.get('title', 'Untitled Video')
    description = metadata.get('description', '')
    tags = metadata.get('tags', [])
    category_id = self._resolve_category_id(metadata.get('category', 'Science & Technology'))

    # Step 1: Start resumable upload
    import json
    snippet = {
      'snippet': {
        'title': title[:100],
        'description': description[:5000],
        'tags': tags[:500],
        'categoryId': category_id,
      },
      'status': {
        'privacyStatus': metadata.get('privacy', 'private'),
        'selfDeclaredMadeForKids': False,
      },
    }

    try:
      # Initiate resumable upload
      init_response = httpx.post(
        'https://www.googleapis.com/upload/youtube/v3/videos',
        params={'uploadType': 'resumable', 'part': 'snippet,status'},
        headers={
          'Authorization': f'Bearer {self._access_token}',
          'Content-Type': 'application/json',
          'X-Upload-Content-Type': 'video/mp4',
          'X-Upload-Content-Length': str(video_file.stat().st_size),
        },
        content=json.dumps(snippet),
        timeout=30.0,
      )
      init_response.raise_for_status()

      upload_url = init_response.headers.get('Location')
      if not upload_url:
        raise SocialPublishError('YouTube did not return a resumable upload URL')

      # Step 2: Upload video bytes
      with open(video_file, 'rb') as f:
        upload_response = httpx.put(
          upload_url,
          content=f.read(),
          headers={'Content-Type': 'video/mp4'},
          timeout=600.0,
        )
        upload_response.raise_for_status()

      result = upload_response.json()
      video_id = result.get('id', '')

      # Step 3: Optionally upload custom thumbnail
      if thumbnail_path and video_id:
        self._upload_thumbnail(video_id, thumbnail_path)

      return {
        'video_id': video_id,
        'url': f'https://www.youtube.com/watch?v={video_id}',
        'status': result.get('status', {}).get('uploadStatus', 'unknown'),
      }

    except httpx.HTTPStatusError as exc:
      logger.exception('YouTube upload failed with status %d', exc.response.status_code)
      raise SocialPublishError(f'YouTube API error: {exc.response.status_code}') from exc
    except Exception as exc:
      logger.exception('YouTube upload failed')
      raise SocialPublishError(str(exc)) from exc

  def get_auth_url(self, redirect_uri: str, state: str = '') -> str:
    """Not used directly — auth is handled via OAuthManager."""
    raise NotImplementedError('Use OAuthManager.get_youtube_auth_url() instead')

  def handle_callback(self, code: str, redirect_uri: str) -> dict[str, Any]:
    """Not used directly — auth is handled via OAuthManager."""
    raise NotImplementedError('Use OAuthManager.exchange_youtube_code() instead')

  def refresh_access_token(self, refresh_token: str) -> dict[str, Any]:
    """Not used directly — auth is handled via OAuthManager."""
    raise NotImplementedError('Use OAuthManager.refresh_youtube_token() instead')

  def _upload_thumbnail(self, video_id: str, thumbnail_path: str) -> None:
    """Upload a custom thumbnail for a video."""
    import httpx

    thumb_file = Path(thumbnail_path)
    if not thumb_file.exists():
      logger.warning('Thumbnail file not found: %s', thumbnail_path)
      return

    try:
      with open(thumb_file, 'rb') as f:
        response = httpx.post(
          'https://www.googleapis.com/upload/youtube/v3/thumbnails/set',
          params={'videoId': video_id},
          headers={
            'Authorization': f'Bearer {self._access_token}',
            'Content-Type': 'image/jpeg',
          },
          content=f.read(),
          timeout=30.0,
        )
        response.raise_for_status()
        logger.info('Custom thumbnail uploaded for video %s', video_id)
    except Exception:
      logger.warning('Thumbnail upload failed for video %s', video_id)

  @staticmethod
  def _resolve_category_id(category_name: str) -> str:
    """Map human-readable category name to YouTube category ID."""
    categories = {
      'Film & Animation': '1',
      'Autos & Vehicles': '2',
      'Music': '10',
      'Pets & Animals': '15',
      'Sports': '17',
      'Travel & Events': '19',
      'Gaming': '20',
      'People & Blogs': '22',
      'Comedy': '23',
      'Entertainment': '24',
      'News & Politics': '25',
      'Howto & Style': '26',
      'Education': '27',
      'Science & Technology': '28',
      'Nonprofits & Activism': '29',
    }
    return categories.get(category_name, '28')
