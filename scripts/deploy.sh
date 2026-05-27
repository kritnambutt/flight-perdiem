#!/usr/bin/env bash
# Deploy / update the per diem system on the Raspberry Pi.
#
# Usage:
#   ./scripts/deploy.sh          # pull latest, rebuild, restart
#   ./scripts/deploy.sh --logs   # tail logs after deploy
#
# Pre-requisites (first-time setup only):
#   1. Copy .env.example to .env and fill in values.
#   2. Run: python scripts/auth_drive.py   (one-time gcloud Drive auth)
#   3. Run: ./scripts/deploy.sh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "==> Deploying per diem system from $(pwd)"

# Verify .env exists
if [[ ! -f .env ]]; then
  echo "ERROR: .env not found. Copy .env.example to .env and fill in values."
  exit 1
fi

# Verify gcloud Drive credentials
if ! gcloud auth print-access-token --quiet &>/dev/null; then
  echo "WARNING: gcloud Drive token not found or expired."
  echo "         Run: python scripts/auth_drive.py"
fi

echo "==> Building images and starting services..."
docker compose up -d --build

echo "==> Waiting for API to be healthy..."
for i in $(seq 1 30); do
  if curl -sf http://localhost:8000/api/health >/dev/null 2>&1; then
    echo "==> API healthy."
    break
  fi
  sleep 2
done

echo "==> Deploy complete."
echo "    Swagger UI:  http://localhost:8000/api/docs"
echo "    App:         http://localhost:8000/"

if [[ "${1:-}" == "--logs" ]]; then
  docker compose logs -f api worker
fi
