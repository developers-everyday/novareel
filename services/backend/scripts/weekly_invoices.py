from __future__ import annotations

from datetime import UTC, datetime

from app.config import get_settings
from app.repositories.factory import build_repository


PRICE_PER_VIDEO_USD = 2.9


def main() -> None:
  settings = get_settings()
  repo = build_repository(settings)

  month = datetime.now(UTC).strftime('%Y-%m')
  summaries = repo.list_usage_for_month(month, settings.monthly_video_quota)

  print(f'NovaReel manual invoice run for {month}')
  if not summaries:
    print('No usage rows found.')
    return

  for usage in summaries:
    amount = round(usage.videos_generated * PRICE_PER_VIDEO_USD, 2)
    print(
      f"owner={usage.owner_id} videos={usage.videos_generated} "
      f"quota={usage.quota_limit} remaining={usage.remaining} amount_usd={amount}"
    )


if __name__ == '__main__':
  main()
