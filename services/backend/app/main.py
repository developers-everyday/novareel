from __future__ import annotations

import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import v1_router
from app.config import get_settings
from app.services.storage import LocalStorageService, build_storage

logger = logging.getLogger('novareel.api')


def create_app() -> FastAPI:
  settings = get_settings()

  app = FastAPI(
    title=settings.app_name,
    version='0.1.0',
    description='NovaReel Phase 1 API for project creation, generation, and usage tracking.',
  )

  app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
  )

  app.include_router(v1_router)

  @app.exception_handler(RequestValidationError)
  async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.warning('422 Validation error on %s %s: %s', request.method, request.url.path, exc.errors())
    return await request_validation_exception_handler(request, exc)

  @app.middleware('http')
  async def request_logging_middleware(request: Request, call_next):
    request_id = request.headers.get('x-request-id') or str(uuid.uuid4())
    started = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    response.headers['x-request-id'] = request_id
    logger.info(
      'request_id=%s method=%s path=%s status=%s duration_ms=%s',
      request_id,
      request.method,
      request.url.path,
      response.status_code,
      elapsed_ms,
    )
    return response

  storage = build_storage(settings)
  if isinstance(storage, LocalStorageService):
    storage.root.mkdir(parents=True, exist_ok=True)
    app.mount('/files', StaticFiles(directory=storage.root), name='files')

  @app.get('/healthz')
  def healthcheck() -> dict[str, str]:
    return {'status': 'ok'}

  return app


app = create_app()
