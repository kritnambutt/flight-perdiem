# 🗂 Epic Overview — EP-PLAT (Persistence & Deployment)

The Platform epic is the foundation the rest of the system runs on: the
PostgreSQL data model that stores runs, verdicts, overrides, audit and config;
and the Docker-based deployment on the Raspberry Pi 5, exposed through the Pi's
**existing Cloudflare Tunnel** (no nginx, no open ports, zero cost).

See [../../architecture/architecture.md](../../architecture/architecture.md) and
[../../plans/implementation-plan.md](../../plans/implementation-plan.md)
(Phases 0, 7, 10; N8).

| Story ID    | Title                                  | Reqs            | Status      |
| ----------- | -------------------------------------- | --------------- | ----------- |
| PD-PLAT-001 | PostgreSQL schema & persistence        | N1, N2          | ✅ Done     |
| PD-PLAT-002 | Docker + Cloudflare deployment on Pi 5 | N8              | 📝 Planned  |

**Key context**
- DB is **PostgreSQL** (own container, `pgdata` volume), accessed via SQLAlchemy.
- Deployment is **docker-compose at the repo root**: `api` (serves SPA + REST),
  `worker`, `db`. No `cloudflared` container — the Pi already runs one; just add a
  new public hostname → `http://localhost:8000`.
- Everything free/open-source; the api is bound to `127.0.0.1:8000` and reached
  only via the host tunnel.
