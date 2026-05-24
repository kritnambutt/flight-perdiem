# 🗂 Epic Overview — EP-WEB (Web Application: API + React UI)

The WebApp epic is how staff actually use the system: a self-hosted web app where
they sign in, start a cycle run, watch live progress, review and override flagged
claims, and publish/download the report — no command line. It is a **thin layer**
over the engine (Ingestion → Validation → Reporting), exposed via FastAPI and a
React + Vite + Tailwind SPA, with state in PostgreSQL.

See [../../REQUIREMENTS.md](../../REQUIREMENTS.md) (§6.6, F14–F22) and
[../../plans/implementation-plan.md](../../plans/implementation-plan.md) (Phases 8–9).

| Story ID    | Title                                   | Reqs            | Status      |
| ----------- | --------------------------------------- | --------------- | ----------- |
| PD-WEB-001  | Run orchestration & background jobs     | F15, F16        | 📝 Planned  |
| PD-WEB-002  | Authentication                          | F14             | 📝 Planned  |
| PD-WEB-003  | Results dashboard & exception review UI | F17, F18, F19   | 📝 Planned  |
| PD-WEB-004  | Config & audit screens                  | F21, F22        | 📝 Planned  |
| PD-WEB-005  | Publish & download reports              | F20             | 📝 Planned  |

**Stack:** FastAPI + Uvicorn (serves the built SPA **and** the REST API on one
origin), React + Vite + pnpm + **Tailwind CSS**, PostgreSQL, a worker process for
the long pipeline. Deployed via Docker, exposed through the Pi's existing
Cloudflare Tunnel — see [Platform](../Platform/overview.md).

**Key context**
- A cycle run is slow (download + OCR) → it must run as a **background job** so
  the UI never blocks (F15/F16); the SPA polls for progress.
- Human-in-the-loop (N3): the UI surfaces everything uncertain for review.
- Roster images are PII (N5): previews are auth-gated.
