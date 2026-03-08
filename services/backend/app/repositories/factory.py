from app.config import Settings
from app.repositories.base import Repository
from app.repositories.dynamo import DynamoRepository
from app.repositories.local import LocalRepository


def build_repository(settings: Settings) -> Repository:
  if settings.storage_backend == 'dynamodb':
    return DynamoRepository(settings)
  return LocalRepository(settings)
