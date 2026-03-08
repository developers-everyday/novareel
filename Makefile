.PHONY: help dev-web dev-api dev-worker test-backend run-once-worker

help:
	@echo "Targets: dev-web dev-api dev-worker test-backend run-once-worker"

dev-web:
	cd apps/web && npm run dev

dev-api:
	cd services/backend && uvicorn app.main:app --reload --port 8000

dev-worker:
	cd services/backend && python worker.py

test-backend:
	cd services/backend && pytest

run-once-worker:
	cd services/backend && python -c "import worker; print(worker.run_once())"
