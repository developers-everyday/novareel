"""Celery configuration — entry point for Celery workers.

Usage:
  celery -A celery_config worker --loglevel=info
"""

from app.tasks import register_celery_tasks

app = register_celery_tasks()
