# Flight Per Diem Validation — Project Objectives

A self-hosted system that validates cabin-crew **per diem (sector allowance)**
claims for AirAsia (DMK base), replacing a slow, fully manual review. Crew submit
claims via Google Forms and attach their crew schedule report (roster); the system
reads the submissions, OCRs the rosters, validates each claimed day against the
per diem rules, de-duplicates across submissions, and produces the payable master
report. Runs entirely on a Raspberry Pi 5 at zero recurring cost.

See `docs/REQUIREMENTS.md` for the authoritative spec.

## Core Capabilities

1. **Form ingestion** — read the **Posting Base** (on-time) and **Late
   Submission** (back-claim) Google Form response workbooks for a cycle month and
   normalise each row into a claim. Reconciled one month in arrears (work in March
   → claim February).
2. **Roster retrieval** — download each claim's roster attachment from Google
   Drive (via the service account `kantaphajasuwan@airasia.com`).
3. **Roster OCR** — extract date range, staff ID, name, generated date, and the
   flight grid (Tesseract + OpenCV); detect the **red box** the crew drew around
   claimed days.
4. **Validation** — apply the eligibility rules (R1–R8): DMK↔HKT route only,
   configurable rotating flight numbers, out-and-back N/N+1 pairing, generated-date
   proof, staff-ID-authoritative fuzzy name matching, period coverage, month routing.
5. **De-duplication & reporting** — count each unique `(staff ID, date)` once,
   aggregate per crew into ranges + days + amount (≈400 THB/day), write the master
   report and an exception report.
6. **Web app** — staff sign in, pick a month, run the pipeline (background job),
   watch progress, review/override flagged claims, and download the report.

## Technical Requirements

- Host on **Raspberry Pi 5** (arm64), no paid cloud services; optimised for low
  resources (batch workload, bounded concurrency).
- **Local, free OCR** (Tesseract + OpenCV) — the roster is machine-printed text.
- **PostgreSQL** for runs, verdicts, overrides, audit, config.
- Exposed via the Pi's **existing Cloudflare Tunnel** (no nginx, no open ports).
- Human-in-the-loop: the system assists; anything uncertain is surfaced for review,
  never silently guessed.

## Development Guidelines

- **Backend:** Python + **FastAPI** (serves the SPA **and** the REST API), local
  dev in **venv**. The validation **engine is a pure library** reused by the API,
  the worker, and any CLI.
- **Frontend:** **React + Vite + pnpm + Tailwind CSS** (SPA), built to static
  files and served by FastAPI.
- **Deployment:** Docker compose at the repo root (`api`, `worker`, `db`).
- Bilingual data (Thai/English names, remarks, months) must be handled in parsing,
  matching, and output.
