.DEFAULT_GOAL := help

# ── Config ──────────────────────────────────────────────────────────────────
COMPOSE  := docker compose
API      := flight-perdiem-api-1
WORKER   := flight-perdiem-worker-1
VENV     := backend/.venv
PY       := $(VENV)/bin/python
PIP      := $(VENV)/bin/pip

# ── Help ────────────────────────────────────────────────────────────────────
.PHONY: help
help:
	@echo ""
	@echo "  Flight Per Diem — available commands"
	@echo ""
	@echo "  First-time setup"
	@echo "    make setup              Copy .env.example → .env"
	@echo "    make install            Install backend venv + frontend node_modules"
	@echo "    make auth-drive         Authenticate gcloud Drive access (run once on Pi)"
	@echo ""
	@echo "  Local dev (no Docker)"
	@echo "    make backend-install    Create venv and install Python deps"
	@echo "    make backend-dev        Run FastAPI locally on :8000 (with reload)"
	@echo "    make worker-dev         Run the pipeline worker locally (processes PENDING runs)"
	@echo "    make backend-migrate    Run Alembic migrations against local DB"
	@echo "    make frontend-install   Install pnpm dependencies"
	@echo "    make frontend-dev       Run Vite dev server on :5173"
	@echo ""
	@echo "  Docker"
	@echo "    make up                 Build images and start all services"
	@echo "    make down               Stop and remove containers"
	@echo "    make restart            Restart api + worker"
	@echo "    make build              Rebuild images without starting"
	@echo "    make logs               Tail logs for api + worker"
	@echo "    make ps                 Show running containers"
	@echo ""
	@echo "  Database"
	@echo "    make migrate            Run Alembic migrations inside api container"
	@echo "    make psql               Open psql shell into the perdiem database"
	@echo "    make reset-data         Wipe all run data + uploaded files (asks to confirm)"
	@echo ""
	@echo "  ML (Roster Intelligence — off-Pi, run on dev machine)"
	@echo "    make ml-dataset         Build labelled dataset from workbooks (PD-ML-002)"
	@echo "    make ml-train-triage    Train triage classifier from dataset (PD-ML-004)"
	@echo "    make ml-train-doctype   Train doc-type classifier from fixture images (PD-ML-005)"
	@echo "    make ml-train-donut     Fine-tune Donut reader — needs GPU + transformers (PD-ML-006)"
	@echo "    make ml-export-donut    Export trained Donut to ONNX + int8 (PD-ML-006)"
	@echo "    make ml-bench-donut     Benchmark ONNX inference on CPU/Pi (PD-ML-006)"
	@echo "    make ml-eval            Evaluate extractor/decision backend on held-out month"
	@echo "    (pass extra flags via ARGS='...')"
	@echo ""
	@echo "  Testing & quality"
	@echo "    make test               Engine unit tests (no DB required)"
	@echo "    make test-all           All tests including API integration tests"
	@echo "    make lint               Run ruff linter"
	@echo "    make format             Format code with ruff"
	@echo ""
	@echo "  Deploy"
	@echo "    make deploy             Pull, rebuild, and restart (production)"
	@echo "    make deploy-logs        Deploy then tail logs"
	@echo ""
	@echo "  Cleanup"
	@echo "    make clean              Remove containers (keeps volumes)"
	@echo "    make clean-all          Remove containers + all volumes"
	@echo ""

# ── First-time setup ─────────────────────────────────────────────────────────
.PHONY: setup
setup:
	@if [ -f .env ]; then \
		echo ".env already exists — skipping. Edit it manually if needed."; \
	else \
		cp .env.example .env; \
		echo ".env created from .env.example — fill in the values before continuing."; \
	fi

.PHONY: install
install: backend-install frontend-install

.PHONY: auth-drive
auth-drive:
	$(PY) scripts/auth_drive.py

# ── Local dev ────────────────────────────────────────────────────────────────
.PHONY: backend-install
backend-install:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip --quiet
	$(PIP) install -r backend/requirements.txt -r backend/requirements-dev.txt --quiet
	$(PIP) install -e backend/ --quiet
	@echo "Backend venv ready at $(VENV)"

.PHONY: backend-dev
backend-dev: check-env check-venv
	cd backend && set -a && . ../.env && set +a && \
	  ../.venv/bin/uvicorn perdiem.web.main:app --host 127.0.0.1 --port 8000 --reload

.PHONY: worker-dev
worker-dev: check-env check-venv
	cd backend && set -a && . ../.env && set +a && \
	  ../.venv/bin/python -m perdiem.worker.runner

.PHONY: backend-migrate
backend-migrate: check-env check-venv
	cd backend && set -a && . ../.env && set +a && \
	  ../.venv/bin/alembic upgrade head

.PHONY: frontend-install
frontend-install:
	cd frontend && pnpm install

.PHONY: frontend-dev
frontend-dev:
	@lsof -ti:5173 | xargs kill -9 2>/dev/null || true
	cd frontend && pnpm dev --port 5173 --strictPort

# ── Docker ───────────────────────────────────────────────────────────────────
.PHONY: up
up: check-env
	$(COMPOSE) up -d --build --remove-orphans

.PHONY: down
down:
	$(COMPOSE) down

.PHONY: restart
restart:
	$(COMPOSE) restart api worker

.PHONY: build
build:
	$(COMPOSE) build

.PHONY: logs
logs:
	$(COMPOSE) logs -f api worker

.PHONY: ps
ps:
	$(COMPOSE) ps

# ── Database ─────────────────────────────────────────────────────────────────
.PHONY: migrate
migrate:
	docker exec $(API) sh -c "cd /app/backend && alembic upgrade head"

.PHONY: psql
psql: check-env
	@PGPASSWORD=$$(grep ^POSTGRES_PASSWORD .env | cut -d= -f2) \
	  docker exec -it wedding-yokyo-db-1 \
	  psql -U perdiem -d perdiem

# Wipe all run data (runs, claims, verdicts, overrides, audit) and on-disk files
# (uploads, reports, roster cache). DESTRUCTIVE — prompts before deleting.
# Pass flags via ARGS, e.g.  make reset-data ARGS="--yes --include-config"
# Keep the downloaded rosters (no Drive re-download): make reset-data ARGS="--keep-cache"
.PHONY: reset-data
reset-data: check-env check-venv
	cd backend && set -a && . ../.env && set +a && \
	  ../.venv/bin/python ../scripts/reset_data.py $(ARGS)

# ── ML (Roster Intelligence) ───────────────────────────────────────────────────
# Build the labelled ML dataset from the 3 workbooks (PD-ML-002) into
# data/ml/datasets/<version>/. PII — stays local (data/ is gitignored).
# Pass flags via ARGS, e.g.  make ml-dataset ARGS="--version 2026-05"
#   include the vision split:  make ml-dataset ARGS="--roster-cache data/cache"
.PHONY: ml-dataset
ml-dataset: check-env check-venv
	cd backend && set -a && . ../.env && set +a && \
	  ../.venv/bin/python ../scripts/build_ml_dataset.py $(ARGS)

# Train triage classifier from a pre-built JSONL dataset (PD-ML-004).
# Requires ml-dataset to have been run first.
# Pass flags via ARGS, e.g.  make ml-train-triage ARGS="--dataset-version 2026-05"
.PHONY: ml-train-triage
ml-train-triage: check-env check-venv
	cd backend && set -a && . ../.env && set +a && \
	  ../.venv/bin/python ../scripts/train_triage.py $(ARGS)

# Train doc-type / quality classifier from fixture images (PD-ML-005).
# No dataset build step needed — reads directly from docs/example-files/.
# Pass flags via ARGS, e.g.  make ml-train-doctype ARGS="--augment 20"
.PHONY: ml-train-doctype
ml-train-doctype: check-env check-venv
	cd backend && set -a && . ../.env && set +a && \
	  ../.venv/bin/python ../scripts/train_doctype.py $(ARGS)

# Fine-tune the Donut roster reader (PD-ML-006) — run OFF-PI on a GPU machine.
# Requires: pip install transformers torch accelerate
# Pass flags via ARGS, e.g.  make ml-train-donut ARGS="--epochs 10 --synthetic-n 1000"
.PHONY: ml-train-donut
ml-train-donut: check-env check-venv
	cd backend && set -a && . ../.env && set +a && \
	  ../.venv/bin/python ../scripts/train_donut.py $(ARGS)

# Export fine-tuned Donut to ONNX + int8 (PD-ML-006 task 4) — run OFF-PI on the export machine.
# Requires: pip install transformers torch onnx onnxruntime
# Pass flags via ARGS, e.g.  make ml-export-donut ARGS="--model data/ml/models/donut --out data/ml/models/donut-onnx"
.PHONY: ml-export-donut
ml-export-donut: check-env check-venv
	cd backend && set -a && . ../.env && set +a && \
	  ../.venv/bin/python ../scripts/export_donut_onnx.py $(ARGS)

# Benchmark Donut ONNX inference (PD-ML-006 task 4) — run on Pi or any CPU machine.
# Requires: pip install onnxruntime transformers
# Pass flags via ARGS, e.g.  make ml-bench-donut ARGS="--onnx-dir data/ml/models/donut-onnx --image docs/example-files/IMG_4481..."
.PHONY: ml-bench-donut
ml-bench-donut: check-env check-venv
	cd backend && set -a && . ../.env && set +a && \
	  ../.venv/bin/python ../scripts/bench_donut.py $(ARGS)

# Score an extractor or decision backend against the held-out test month (PD-ML-003).
# Pass flags via ARGS, e.g.  make ml-eval ARGS="--triage-model data/ml/models/triage.json"
.PHONY: ml-eval
ml-eval: check-env check-venv
	cd backend && set -a && . ../.env && set +a && \
	  ../.venv/bin/python ../scripts/eval_ml.py $(ARGS)

# ── Testing & quality ────────────────────────────────────────────────────────
.PHONY: test
test: check-venv
	cd backend && ../.venv/bin/pytest tests/ -m "not integration" -v

.PHONY: test-all
test-all: check-venv
	cd backend && ../.venv/bin/pytest tests/ -v

.PHONY: lint
lint: check-venv
	cd backend && ../.venv/bin/ruff check .

.PHONY: format
format: check-venv
	cd backend && ../.venv/bin/ruff format .

# ── Deploy ───────────────────────────────────────────────────────────────────
.PHONY: deploy
deploy:
	./scripts/deploy.sh

.PHONY: deploy-logs
deploy-logs:
	./scripts/deploy.sh --logs

# ── Cleanup ──────────────────────────────────────────────────────────────────
.PHONY: clean
clean:
	$(COMPOSE) down --remove-orphans

.PHONY: clean-all
clean-all:
	$(COMPOSE) down --volumes --remove-orphans

# ── Internal guards ───────────────────────────────────────────────────────────
.PHONY: check-env
check-env:
	@if [ ! -f .env ]; then \
		echo "ERROR: .env not found. Run 'make setup' first."; \
		exit 1; \
	fi

.PHONY: check-venv
check-venv:
	@if [ ! -f $(VENV)/bin/python ]; then \
		echo "ERROR: venv not found. Run 'make backend-install' first."; \
		exit 1; \
	fi
