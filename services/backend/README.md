# NovaReel Backend

FastAPI service + async worker for NovaReel Phase 1 private beta.

## Run locally

```bash
cd services/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
uvicorn app.main:app --reload --port 8000
```

In a separate terminal:

```bash
cd services/backend
source .venv/bin/activate
python worker.py
```

## Key env vars

- `NOVAREEL_STORAGE_BACKEND` (`local` | `dynamodb`)
- `NOVAREEL_QUEUE_BACKEND` (`poll` | `sqs`)
- `NOVAREEL_AUTH_DISABLED` (`true` | `false`)
- `NOVAREEL_LOCAL_DATA_DIR` (defaults to `services/backend/data`)
- `NOVAREEL_PUBLIC_API_BASE_URL` (defaults to `http://localhost:8000`)
