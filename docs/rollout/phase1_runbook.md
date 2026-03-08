# NovaReel Phase 1 Rollout Runbook

## Timeline (2026)

- Week 1: Mar 2 - Mar 8
- Week 2: Mar 9 - Mar 15
- Week 3: Mar 16 - Mar 22
- Week 4: Mar 23 - Mar 29
- Week 5: Mar 30 - Apr 5
- Week 6: Apr 6 - Apr 12

## Wave Plan

- Wave 1 (Apr 6-7): 5 internal design partners
- Wave 2 (Apr 8-10): 20 invited sellers
- Wave 3 (Apr 11-12): expand to 50 sellers if wave 2 gates pass

## Go/No-Go Gates

- Activation rate >= 60% (`signed up -> first generated video in 48h`)
- Video generation success >= 90%
- p50 generation <= 120 sec
- p95 API error rate < 2%

## Operator Checklist

1. Confirm `api` and `worker` health endpoints and logs are clean.
2. Confirm queue depth and processing throughput are stable.
3. Confirm storage write/read path works for generated assets.
4. Verify usage accounting is incrementing exactly once per completed job.
5. Review retry and dead-letter activity in `/v1/admin/overview` and `/v1/admin/dead-letters`.
6. Run manual invoice script weekly:
   - `python services/backend/scripts/weekly_invoices.py`
7. Collect activation and failure metrics before moving to next wave.

## Rollback Plan

1. Pause new invitations.
2. Keep existing users read-only if generation failure rate spikes.
3. Toggle `NOVAREEL_AUTH_DISABLED` only in dev; keep production auth enabled.
4. Revert to `NOVAREEL_USE_MOCK_AI=true` if Bedrock dependency becomes unstable.
5. Announce incident summary and ETA to design partners.
