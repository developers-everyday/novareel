"""OAuth flow handling + encrypted token storage."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)


def encrypt_token(token: str, encryption_key: str) -> str:
  """Encrypt a token string using Fernet symmetric encryption.

  Args:
    token: The plaintext token to encrypt.
    encryption_key: A Fernet-compatible key (base64-encoded 32 bytes).

  Returns:
    Encrypted token as a string.
  """
  from cryptography.fernet import Fernet
  f = Fernet(encryption_key.encode() if isinstance(encryption_key, str) else encryption_key)
  return f.encrypt(token.encode()).decode()


def decrypt_token(encrypted_token: str, encryption_key: str) -> str:
  """Decrypt a Fernet-encrypted token string.

  Args:
    encrypted_token: The encrypted token.
    encryption_key: The Fernet key used for encryption.

  Returns:
    Decrypted plaintext token.
  """
  from cryptography.fernet import Fernet
  f = Fernet(encryption_key.encode() if isinstance(encryption_key, str) else encryption_key)
  return f.decrypt(encrypted_token.encode()).decode()


class OAuthManager:
  """Manages OAuth flows and token lifecycle for social media connections."""

  def __init__(
    self,
    *,
    google_client_id: str,
    google_client_secret: str,
    redirect_base_url: str,
    encryption_key: str,
  ):
    self._google_client_id = google_client_id
    self._google_client_secret = google_client_secret
    self._redirect_base_url = redirect_base_url.rstrip('/')
    self._encryption_key = encryption_key

  def get_youtube_auth_url(self, state: str = '') -> str:
    """Generate Google OAuth consent URL for YouTube access."""
    from urllib.parse import urlencode

    params = {
      'client_id': self._google_client_id,
      'redirect_uri': f'{self._redirect_base_url}/v1/social/auth/youtube/callback',
      'response_type': 'code',
      'scope': 'https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly',
      'access_type': 'offline',
      'prompt': 'consent',
    }
    if state:
      params['state'] = state

    return f'https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}'

  def exchange_youtube_code(self, code: str) -> dict[str, Any]:
    """Exchange authorization code for Google OAuth tokens.

    Returns dict with:
      - access_token: str
      - refresh_token: str
      - expires_in: int (seconds)
      - encrypted_access_token: str
      - encrypted_refresh_token: str
      - token_expires_at: datetime
      - platform_user_id: str
      - platform_username: str
    """
    import httpx

    token_url = 'https://oauth2.googleapis.com/token'
    redirect_uri = f'{self._redirect_base_url}/v1/social/auth/youtube/callback'

    response = httpx.post(token_url, data={
      'client_id': self._google_client_id,
      'client_secret': self._google_client_secret,
      'code': code,
      'grant_type': 'authorization_code',
      'redirect_uri': redirect_uri,
    })
    response.raise_for_status()
    token_data = response.json()

    access_token = token_data['access_token']
    refresh_token = token_data.get('refresh_token', '')
    expires_in = token_data.get('expires_in', 3600)

    # Fetch YouTube channel info
    channel_info = self._fetch_youtube_channel_info(access_token)

    return {
      'access_token': access_token,
      'refresh_token': refresh_token,
      'expires_in': expires_in,
      'encrypted_access_token': encrypt_token(access_token, self._encryption_key),
      'encrypted_refresh_token': encrypt_token(refresh_token, self._encryption_key) if refresh_token else '',
      'token_expires_at': datetime.now(UTC) + timedelta(seconds=expires_in),
      'platform_user_id': channel_info.get('id', ''),
      'platform_username': channel_info.get('title', ''),
    }

  def refresh_youtube_token(self, encrypted_refresh_token: str) -> dict[str, Any]:
    """Refresh an expired YouTube access token.

    Returns dict with:
      - access_token: str
      - encrypted_access_token: str
      - expires_in: int
      - token_expires_at: datetime
    """
    import httpx

    refresh_token = decrypt_token(encrypted_refresh_token, self._encryption_key)

    response = httpx.post('https://oauth2.googleapis.com/token', data={
      'client_id': self._google_client_id,
      'client_secret': self._google_client_secret,
      'refresh_token': refresh_token,
      'grant_type': 'refresh_token',
    })
    response.raise_for_status()
    token_data = response.json()

    access_token = token_data['access_token']
    expires_in = token_data.get('expires_in', 3600)

    return {
      'access_token': access_token,
      'encrypted_access_token': encrypt_token(access_token, self._encryption_key),
      'expires_in': expires_in,
      'token_expires_at': datetime.now(UTC) + timedelta(seconds=expires_in),
    }

  def _fetch_youtube_channel_info(self, access_token: str) -> dict[str, str]:
    """Fetch the authenticated user's YouTube channel info."""
    import httpx

    try:
      response = httpx.get(
        'https://www.googleapis.com/youtube/v3/channels',
        params={'part': 'snippet', 'mine': 'true'},
        headers={'Authorization': f'Bearer {access_token}'},
      )
      response.raise_for_status()
      items = response.json().get('items', [])
      if items:
        snippet = items[0].get('snippet', {})
        return {
          'id': items[0].get('id', ''),
          'title': snippet.get('title', ''),
        }
    except Exception:
      logger.exception('Failed to fetch YouTube channel info')

    return {'id': '', 'title': ''}
