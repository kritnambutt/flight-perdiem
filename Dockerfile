# ============================================================================
# Stage 1 — Build the React SPA
# ============================================================================
FROM node:20-alpine AS spa-builder

WORKDIR /spa
RUN npm install -g pnpm --quiet

COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY frontend/ .
RUN pnpm build


# ============================================================================
# Stage 2 — Python runtime (arm64-compatible, runs on Raspberry Pi 5)
# ============================================================================
FROM python:3.12-slim AS runtime

WORKDIR /app

# ── System packages ──────────────────────────────────────────────────────────
# tesseract-ocr: OCR engine used by the roster extraction pipeline
# tesseract-ocr-eng: English language pack
# libgl1, libglib2.0-0: OpenCV runtime dependencies
# curl, gnupg, apt-transport-https: needed to add the Google Cloud apt repo
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-eng \
    libgl1 \
    libglib2.0-0 \
    curl \
    gnupg \
    apt-transport-https \
    && rm -rf /var/lib/apt/lists/*

# ── Google Cloud CLI ─────────────────────────────────────────────────────────
# Required so the worker can call `gcloud auth print-access-token` at runtime
# to download roster attachments from Google Drive.
# The host's ~/.config/gcloud is mounted read-only (see docker-compose.yml).
RUN echo "deb [signed-by=/usr/share/keyrings/cloud.google.asc] \
    https://packages.cloud.google.com/apt cloud-sdk main" \
    | tee /etc/apt/sources.list.d/google-cloud-sdk.list \
    && curl -fsSL https://packages.cloud.google.com/apt/doc/apt-key.gpg \
       -o /usr/share/keyrings/cloud.google.asc \
    && apt-get update \
    && apt-get install -y --no-install-recommends google-cloud-cli \
    && rm -rf /var/lib/apt/lists/*

# ── Python dependencies ───────────────────────────────────────────────────────
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Application code ──────────────────────────────────────────────────────────
COPY backend/ ./backend/

# Copy the compiled SPA from stage 1
COPY --from=spa-builder /spa/dist ./frontend/dist/

# ── Entrypoint ────────────────────────────────────────────────────────────────
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# ── Environment ───────────────────────────────────────────────────────────────
ENV PYTHONPATH=/app/backend
ENV SPA_DIR=/app/frontend/dist
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

# Default: api mode (run migrations + start server).
# Override with `python -m perdiem.worker` for the worker container.
CMD ["/entrypoint.sh"]
