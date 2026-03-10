"""Abstract interface for social media publishers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class SocialPublisher(ABC):
  """Abstract interface for social media publishing."""

  @abstractmethod
  def publish_video(
    self,
    video_path: str,
    metadata: dict[str, Any],
    thumbnail_path: str | None = None,
  ) -> dict[str, Any]:
    """Publish a video to the platform.

    Args:
      video_path: Local path to the video file.
      metadata: Platform-specific metadata dict.
      thumbnail_path: Optional local path to thumbnail image.

    Returns:
      Platform-specific response with at least 'video_id' and 'url' keys.

    Raises:
      SocialPublishError: If publishing fails.
    """
    ...

  @abstractmethod
  def get_auth_url(self, redirect_uri: str, state: str = '') -> str:
    """Generate OAuth authorization URL.

    Args:
      redirect_uri: The callback URL after auth.
      state: Optional CSRF state parameter.

    Returns:
      Authorization URL to redirect the user to.
    """
    ...

  @abstractmethod
  def handle_callback(self, code: str, redirect_uri: str) -> dict[str, Any]:
    """Exchange OAuth code for tokens.

    Args:
      code: The authorization code from the callback.
      redirect_uri: The redirect URI used in the auth request.

    Returns:
      Dict with 'access_token', 'refresh_token', 'expires_in', and platform user info.
    """
    ...

  @abstractmethod
  def refresh_access_token(self, refresh_token: str) -> dict[str, Any]:
    """Refresh an expired access token.

    Returns:
      Dict with 'access_token', 'expires_in', and optionally 'refresh_token'.
    """
    ...


class SocialPublishError(Exception):
  """Raised when social media publishing fails."""
  pass
