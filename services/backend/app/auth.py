from __future__ import annotations

from dataclasses import dataclass

import jwt
from fastapi import Depends, Header, HTTPException, status

from app.config import Settings, get_settings


@dataclass(frozen=True)
class AuthUser:
  user_id: str


def _extract_bearer_token(authorization: str | None) -> str:
  if not authorization:
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Missing Authorization header')

  scheme, _, token = authorization.partition(' ')
  if scheme.lower() != 'bearer' or not token:
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Invalid bearer token')
  return token


def _verify_clerk_token(token: str, settings: Settings) -> AuthUser:
  try:
    jwks_client = jwt.PyJWKClient(settings.clerk_jwks_url)
    signing_key = jwks_client.get_signing_key_from_jwt(token)

    decode_kwargs: dict[str, object] = {
      'algorithms': ['RS256'],
      'key': signing_key.key,
      'options': {'require': ['sub']},
    }

    if settings.clerk_audience:
      decode_kwargs['audience'] = settings.clerk_audience

    if settings.clerk_issuer:
      decode_kwargs['issuer'] = settings.clerk_issuer

    payload = jwt.decode(token, **decode_kwargs)
  except Exception as exc:  # pragma: no cover - depends on upstream token/jwks
    import logging
    logging.getLogger("novareel.api").warning(f"Token verification failed: {exc}")
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Token verification failed') from exc

  subject = payload.get('sub')
  if not isinstance(subject, str) or not subject:
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Invalid token subject')

  return AuthUser(user_id=subject)


def get_current_user(
  authorization: str | None = Header(default=None),
  x_dev_user: str | None = Header(default=None),
  settings: Settings = Depends(get_settings),
) -> AuthUser:
  if settings.auth_disabled:
    return AuthUser(user_id=x_dev_user or 'beta-user')

  token = _extract_bearer_token(authorization)
  return _verify_clerk_token(token, settings)
