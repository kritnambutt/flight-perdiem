#!/bin/sh
# Run Alembic migrations then start the FastAPI server.
# Using `exec` so uvicorn replaces this shell as PID 1 (proper signal handling).
set -e
cd /app/backend
echo "[entrypoint] Running database migrations..."
alembic upgrade head
echo "[entrypoint] Migrations done. Starting API server."
exec uvicorn perdiem.web.main:app --host 0.0.0.0 --port 8000
