| Property     | Value                                              |
| ------------ | -------------------------------------------------- |
| Story ID     | PD-PLAT-002                                        |
| Title        | Docker + Cloudflare deployment on Pi 5             |
| Epic         | EP-PLAT — Persistence & Deployment                 |
| Dependencies | Docker, docker-compose, existing Cloudflare Tunnel |
| Story Type   | Infrastructure                                     |
| Source       | architecture.md → "Containers & deployment"; plan Phase 10 (N8)|

## 🗂 Epic Overview — EP-PLAT

See [overview.md](./overview.md). This story packages and runs all services on
the Pi 5 and exposes the app through the Pi's existing Cloudflare Tunnel.

## 📝 Feature Overview — PD-PLAT-002

### User Story

```gherkin
As the operator
I want all services to run on the Pi 5 with one docker compose command
So that deployment is simple, reproducible, and costs nothing

As the operator
I want the app reachable via a Cloudflare hostname with no open ports
So that staff can use it securely without exposing my home network
```

### Pre-conditions

- Docker + docker-compose on the Pi 5 (arm64).
- The Pi already runs `cloudflared` with a configured tunnel.
- Google service-account JSON available as a mounted secret.

### Scope

#### Included

- **Multi-stage api image:** `node:20-alpine` builds the SPA (`pnpm build`),
  `python:3.12-slim` adds Tesseract/OpenCV + backend and serves `dist/` via
  FastAPI `StaticFiles`.
- **docker-compose at repo root:** `api`, `worker`, `db` (postgres:16-alpine);
  shared `roster-cache` + `output` volumes; `pgdata` volume; `db` healthcheck;
  `restart: unless-stopped`.
- `api` published on **`127.0.0.1:8000`** only.
- **Cloudflare:** add a **new public hostname** on the existing tunnel →
  `http://localhost:8000` (no cloudflared container, no token in repo, no port
  forwarding).
- Migrations applied on deploy (`docker compose run --rm api <migrate>`).
- `.env` documented (DATABASE_URL, POSTGRES_PASSWORD, secrets path).

#### Excluded

- App features (other epics).
- Schema definition (PD-PLAT-001).

## 🎯 Acceptance Criteria

### Functional Requirements

1. **Build** — `docker compose up -d --build` builds arm64 images and starts api,
   worker, db.
2. **One origin** — FastAPI serves the SPA **and** REST; no nginx, no CORS layer.
3. **Localhost binding** — api is reachable only on `127.0.0.1:8000`; nothing
   exposed to LAN/internet directly.
4. **Cloudflare** — adding a hostname → `localhost:8000` on the existing tunnel
   makes the app reachable over HTTPS; no new tunnel/token.
5. **Persistence & restart** — `pgdata`/`roster-cache`/`output` survive restarts;
   `restart: unless-stopped` brings services back after reboot.
6. **Migrations** — schema is applied/upgraded as part of deploy.

### Error Scenarios

- db not healthy yet → api/worker wait on the healthcheck before starting.
- Build fails on arm64 (wheel availability) → use 64-bit base + `buildx`; document fix.
- Secret missing → fail fast with a clear message (don't start half-configured).

## 🧩 Technical Documentation

### docker-compose (root, sketch)

```yaml
services:
  api:
    build: .
    command: uvicorn perdiem.web:app --host 0.0.0.0 --port 8000
    env_file: .env
    depends_on: { db: { condition: service_healthy } }
    volumes:
      - roster-cache:/data/cache
      - output:/data/output
      - ./secrets/google-credentials.json:/run/secrets/google.json:ro
    ports: ["127.0.0.1:8000:8000"]
    restart: unless-stopped
  worker:
    build: .
    command: python -m perdiem.worker
    env_file: .env
    depends_on: { db: { condition: service_healthy } }
    volumes:
      - roster-cache:/data/cache
      - output:/data/output
      - ./secrets/google-credentials.json:/run/secrets/google.json:ro
    restart: unless-stopped
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: perdiem
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: perdiem
    volumes: [ "pgdata:/var/lib/postgresql/data" ]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U perdiem"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: unless-stopped
volumes: { pgdata: {}, roster-cache: {}, output: {} }
```

### Cloudflare exposure

- In the Cloudflare dashboard, on the Pi's existing tunnel, add a **public
  hostname** (e.g. `perdiem.example.com`) → service `http://localhost:8000`.
- Optionally enable **Cloudflare Access** in front for an extra auth layer.

## 🔨 Implementation Plan

1. 📝 **TODO** Multi-stage api Dockerfile (node build SPA → python serves dist/).
2. 📝 **TODO** Root `docker-compose.yml` (api, worker, db) + volumes + healthcheck.
3. 📝 **TODO** `.env.example` + secret mount; localhost port binding.
4. 📝 **TODO** Migration step in deploy flow.
5. 📝 **TODO** Add Cloudflare hostname → localhost:8000; verify HTTPS reachability.
6. 📝 **TODO** Reboot test (restart policy) + arm64 build validation.

## 🏗 Structure

```
flight-perdiem/
├── Dockerfile             # multi-stage: SPA build -> python runtime (serves dist/)
├── docker-compose.yml     # api + worker + db
├── .env.example
└── secrets/               # google-credentials.json (gitignored)
```

## 📌 Notes / Open Questions

- Confirm the Pi's tunnel can target `localhost:8000` (host network) vs needing
  the container IP — `ports: 127.0.0.1:8000:8000` publishes to the host, so the
  host-level cloudflared reaches it at `localhost:8000`.
- Phase 7 (scheduled/batch runs) — if wanted, schedule via host cron calling
  `docker compose run --rm worker ...` rather than systemd (supersedes the older
  systemd note in the plan).
