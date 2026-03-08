# Load Test Stub (Phase 1)

Target: 25 concurrent generation jobs.

Suggested approach:

1. Seed 25 projects with one uploaded asset each.
2. Trigger `POST /v1/projects/{id}/generate` in parallel.
3. Poll `GET /v1/jobs/{job_id}` until completion/failure.
4. Report:
   - success rate
   - p50 and p95 completion time
   - failure error_code distribution

Implement this with k6, Locust, or a custom async Python script before private beta wave 2.
