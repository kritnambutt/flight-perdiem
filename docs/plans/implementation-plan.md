# Implementation Plan — Per Diem Validation System

Plan to build the system described in [../REQUIREMENTS.md](../REQUIREMENTS.md)
and [../flows/system-flow.md](../flows/system-flow.md). Phased so each phase is
independently testable against the real example files in `../example-files/`.

## Guiding principles

- **Human-in-the-loop first:** ship validation + exception report before any
  auto-write to the master report.
- **Test against real data each phase:** the three example workbooks and the
  sample roster are the acceptance fixtures.
- **Config-driven rules:** routes, flight numbers, rate, cycle month, thresholds
  all live in config (R2/F13), never hard-coded.
- **Deterministic & idempotent:** same inputs → same outputs; re-runs safe (N2).

## Constraint: zero-cost, self-hosted on Raspberry Pi

Everything must run **on the user's own Raspberry Pi with no paid services** — no
cloud OCR, no per-request API fees. This is feasible because the roster is a
**machine-printed report** (not handwriting): the date range, staff ID, name,
generated date, and flight grid are all printed text that local OCR reads well
with good preprocessing. The only annotation is the **red rectangle**, which is
detected by **colour segmentation (OpenCV)** — not OCR at all.

> Note: the **Google Sheets / Drive APIs are free** within normal quotas, so
> reading the form responses and roster attachments stays within the zero-cost
> goal. No Google Cloud Vision / paid OCR is used.

## Suggested stack (all free / open-source, ARM-friendly)

- **Python 3** — runs on Raspberry Pi OS (64-bit recommended).
- **Excel:** `openpyxl` (+ `pandas` if helpful) to read forms and write the
  master report, preserving the existing layout.
- **OCR:** **Tesseract** (`pytesseract`) — free, offline, ARM packages in apt.
  Roster text is printed, so Tesseract + preprocessing is sufficient.
- **Image preprocessing & red-box detection:** **OpenCV** + **Pillow** —
  deskew, grayscale, threshold/denoise for OCR; HSV colour masking to find the
  red rectangle and map it to day columns. All local, all free.
- **PDF rosters:** `PyMuPDF` (fitz) or `pdf2image` + poppler — free, render PDF
  pages to images for the same pipeline.
- **Google ingestion:** Google Sheets + Drive API via a service account /
  OAuth — **free tier**, no billing.
- **Optional accuracy upgrade (still free, only if Tesseract underperforms):**
  **PaddleOCR** or **EasyOCR** run locally. Both are heavier on a Pi (more
  RAM/CPU); keep Tesseract as the default and benchmark before adopting.
- **Web frontend (staff-facing, §6.6):**
  - **Backend/API:** **FastAPI** (Python, same language as the engine — the API
    just calls the engine library) + **Uvicorn**. Lightweight on a Pi.
  - **Background jobs:** a worker process polling a **Postgres** job table
    (status, progress, results); FastAPI BackgroundTasks acceptable for the
    simplest start. Avoid Redis/Celery unless needed — keep the Pi footprint
    small.
  - **Frontend UI:** **React + Vite + pnpm** SPA (TypeScript), styled with
    **Tailwind CSS**, built to static files and **served by FastAPI** (no nginx).
    (Locked — see [../architecture/architecture.md](../architecture/architecture.md).)
  - **State store:** **PostgreSQL** (via SQLAlchemy + Alembic) for runs,
    per-claim verdicts, manual overrides, audit trail, and config — runs as its
    own container with a persistent volume.
  - **Serving & deployment:** **Docker + docker-compose** at the repo root
    (`api` FastAPI/Uvicorn serving SPA + REST, `worker`, `db` Postgres), arm64
    images on the Pi 5. The Pi's **existing Cloudflare Tunnel** handles DNS/TLS —
    add a new hostname → `localhost:8000`; no nginx, no open ports, no cloudflared
    container. See the architecture doc.

### Architecture (engine vs. app)
Build the validation **engine as a reusable library/CLI** (Phases 1–7). The web
app (Phases 8–9) is a thin layer on top: the API triggers engine runs as
background jobs, stores state in **PostgreSQL**, and the UI reads/writes that
state. This keeps the core testable and lets CLI/cron and the website share one
codebase.

### Raspberry Pi sizing notes
- Prefer a **Pi 4/5 with ≥4 GB RAM**; OCR + OpenCV are CPU-bound.
- Process rosters **sequentially or with a small worker pool**; cache downloads
  to avoid rework (supports idempotent re-runs, N2).
- A monthly cycle is a **batch job** (run on demand / nightly cron), not a
  latency-sensitive service — the Pi handles this comfortably.

---

## Phase 0 — Project setup & fixtures
**Goal:** repo skeleton, config, and a local copy of test fixtures.

- [ ] Project structure (`src/`, `tests/`, `config/`, `data/`).
- [ ] `config.yaml`: routes, outbound/return flight numbers, rate (400),
      cycle month, name-match threshold.
- [ ] Pin dependencies; reproducible venv.
- [ ] Copy example workbooks + sample roster into a `tests/fixtures/` set.

**Done when:** `make test` runs an empty suite green; config loads.

---

## Phase 1 — Form ingestion (F1, F2)
**Goal:** read both response workbooks into a normalised claim model.

- [ ] Reader for **Posting Base** sheet (per-month tab) → rows.
- [ ] Reader for **Late Submission** sheet (per-month tab) → rows.
- [ ] Normalise to a `Claim` model: timestamp, email, staff_id, name, position,
      base, claim_type, claim_month, **claimed_days[]** (parse
      `วันที่ 2, วันที่ 3` → `[2, 3]`), roster_links[], remarks, source
      (POSTING_BASE | LATE), source_row_ref.
- [ ] Handle multiple comma-separated roster links per response.
- [ ] Tolerate trailing spaces / mixed Thai-English columns (N4).

**Done when:** parsing `MARCH 26` / `FEBRUARY 26` tabs yields correct
`Claim` objects for all sample rows, validated in tests.

---

## Phase 2 — Roster retrieval (F3)
**Goal:** fetch attachment bytes from Drive links.

- [ ] Drive auth via service account.
- [ ] Resolve `drive.google.com/open?id=...` → download (JPEG/PNG/PDF).
- [ ] Local cache by file id (avoid re-download; supports idempotent re-runs).
- [ ] Graceful handling of dead/permission-denied links → `NEEDS_REVIEW`.

**Done when:** given a sample response, the roster image is downloaded and
cached; a broken link produces a clean review flag, not a crash.

---

## Phase 3 — Roster OCR & annotation detection (F4, F5, F6)
**Goal:** turn a roster image into structured data + confidence — **fully local
(Tesseract + OpenCV), no paid service.**

- [ ] **Preprocess (OpenCV/Pillow):** orient/deskew, grayscale, threshold,
      denoise, upscale low-res photos — biggest lever for printed-text accuracy.
- [ ] Extract header **date range** (`01/03/2026 - 31/03/2026`) via Tesseract.
- [ ] Extract **staff ID** + **name** from the crew line.
- [ ] Extract **generated date** from the footer (`Generated on …`).
- [ ] Extract the **flight grid**: per day → list of `(flight_no, orig, dest,
      time)`. Use the report's column layout to segment day cells before OCR.
- [ ] **Red rectangle/oval detection (OpenCV HSV mask, not OCR):** isolate red
      pixels, find the bounding contour, map its x-range to day column(s) (F5).
- [ ] Per-field **confidence score** (Tesseract word confidences + regex
      sanity, e.g. staff ID is 7 digits, dates parse); below threshold →
      `NEEDS_REVIEW` (F6).
- [ ] Robustness: rotation/deskew, contrast normalise, handle JPEG artefacts
      (N6). Benchmark Tesseract on the sample set; only consider local
      PaddleOCR/EasyOCR if accuracy is inadequate (still free, heavier on Pi).

**Done when:** the sample roster yields staff `1009759`, name
`RATTANAPORN BOONIN`, range `01/03/2026–31/03/2026`, generated `2026-03-09`,
the `27/03 FD3012 DMK→HKT` / `28/03 FD3006 HKT→DMK` legs, and the red box mapped
to 27–28 Mar — all with confidence scores.

---

## Phase 4 — Validation engine (F7, F8, R1–R8, R5a)
**Goal:** per-claimed-day verdicts. **Pure functions, no I/O — heavily unit
tested.**

- [ ] R5 identity: staff ID exact; R5a name normalise + fuzzy/initial match
      (`Lucksnara S.` ↔ `Lucksnara Sothiratviroj`).
- [ ] R6 period coverage.
- [ ] R1/R2 route + configurable flight-number membership.
- [ ] R3 out-and-back pairing across consecutive days (incl. month boundary,
      e.g. 31 Jan→1 Feb) (F8).
- [ ] R4 generated-date > claimed-date proof.
- [ ] R8 month routing (cycle vs back-claim, REMARK tagging).
- [ ] Emit `VALID | VALID(back-claim) | NEEDS_REVIEW(reason) |
      INVALID(reason)`, each with the deciding rule recorded (N1).

**Done when:** a unit-test matrix covers each rule pass/fail, including the
name-abbreviation and month-boundary cases.

---

## Phase 5 — De-duplication & aggregation (F9, R7, F10)
**Goal:** collapse all submissions into payable per-crew results.

- [ ] Merge Posting Base + Late Submission + re-submissions for the cycle.
- [ ] De-dup by unique `(staff_id, date)`.
- [ ] Reconcile crew-stated day list vs roster-proven days → flag mismatches.
- [ ] Merge consecutive days into `Period` ranges (multi-range, newline-joined).
- [ ] Compute `Days` and `Total Perdiem = Days × rate`.

**Done when:** running the Feb cycle over sample data reproduces de-duplicated
per-crew day counts and amounts matching the expected master-report figures.

---

## Phase 6 — Output: master report + exceptions (F11, F12)
**Goal:** write results without harming history.

- [ ] Append/update the month worksheet in the master report shape
      (Item, New ID No., Employee name, Period, Days, Total Perdiem, Email,
      Cross Checked, REMARK) — **leave historical sheets untouched**.
- [ ] Idempotent writes keyed by staff ID (re-run replaces, never duplicates) (N2).
- [ ] **Exception report** (separate sheet/file): every REJECT / NEEDS_REVIEW
      with failing rule, source response, roster reference, confidence.

**Done when:** a generated month sheet matches the expected layout; re-running
is a no-op; exceptions are actionable.

---

## Phase 7 — Orchestration, audit & ops (N1, N2, N5)
**Goal:** one-command run + traceability, **running on the Raspberry Pi**.

- [ ] CLI: `run --month "February 2026"` driving the full pipeline.
- [ ] Audit log per decision: response ref, roster ref, rule, confidence.
- [ ] Summary at end: counts of VALID / back-claim / review / reject.
- [ ] Secrets handling for Google creds; treat roster PII per N5.
- [ ] **Pi deployment** (detailed below).

**Done when:** a single command processes a cycle end-to-end on the Pi and emits
the master sheet + exception report + audit log.

### 7.1 Pi deployment in detail

The Raspberry Pi is the **sole server** — no external paid dependency. Two ways
to run, sharing the same code:

1. **On-demand CLI** — the admin SSHes in and runs a cycle manually:
   ```bash
   perdiem run --month "February 2026"
   ```
   Use this for the monthly reconciliation and for re-runs after fixing
   exceptions (re-runs are idempotent, N2).

2. **Scheduled batch job** — the same command on a timer so new form responses
   are processed automatically (e.g. nightly). Prefer a **systemd timer** over
   cron (better logging via `journalctl`, dependency ordering, auto-restart).

#### System packages (apt — all free, ARM builds available)

```bash
sudo apt update
sudo apt install -y \
  python3 python3-venv python3-pip \
  tesseract-ocr \
  libgl1 libglib2.0-0 \      # OpenCV runtime deps
  poppler-utils              # PDF rasterisation (pdf2image)
```

- 64-bit Raspberry Pi OS recommended (wider wheel availability for `opencv` /
  `numpy`).
- Install Python deps in a venv: `python3 -m venv .venv && .venv/bin/pip install
  -r requirements.txt` (`pytesseract`, `opencv-python-headless`, `pillow`,
  `openpyxl`, `pandas`, Google API client). Use **`opencv-python-headless`** (no
  GUI libs — lighter on a headless Pi).

#### Layout on the Pi

```
/opt/perdiem/            # app code (git checkout)
  .venv/                 # virtualenv
  config.yaml            # routes, flight numbers, rate, thresholds
/var/lib/perdiem/
  cache/                 # downloaded roster images (idempotent re-runs)
  output/                # generated master sheet + exception reports
  audit/                 # per-decision audit logs
/etc/perdiem/
  google-credentials.json   # service-account key, chmod 600, not in git
```

#### systemd timer (scheduled run)

`/etc/systemd/system/perdiem.service`:
```ini
[Unit]
Description=Per diem validation batch
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=perdiem
WorkingDirectory=/opt/perdiem
EnvironmentFile=/etc/perdiem/perdiem.env   # e.g. GOOGLE_APPLICATION_CREDENTIALS, cycle month
ExecStart=/opt/perdiem/.venv/bin/perdiem run --month "${CYCLE_MONTH}"
```

`/etc/systemd/system/perdiem.timer`:
```ini
[Unit]
Description=Run per diem validation nightly

[Timer]
OnCalendar=*-*-* 02:00:00     # daily 02:00; adjust to monthly if preferred
Persistent=true                # catch up if the Pi was off

[Install]
WantedBy=timers.target
```

Enable and inspect:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now perdiem.timer
systemctl list-timers perdiem.timer      # next run
journalctl -u perdiem.service -e         # last run logs
```

> Cron alternative (if preferred over systemd):
> `0 2 * * * cd /opt/perdiem && CYCLE_MONTH="February 2026" .venv/bin/perdiem run --month "$CYCLE_MONTH" >> /var/lib/perdiem/audit/cron.log 2>&1`

#### Operational notes

- **Secrets:** service-account JSON in `/etc/perdiem/` (`chmod 600`, owner
  `perdiem`); never commit. Roster images contain PII — keep `cache/` private
  (N5).
- **Backups:** the master report is the source of truth — back up
  `/var/lib/perdiem/output/` (and push to Drive if desired; Drive API is free).
- **Resource fit:** batch job, not a service — a Pi 4/5 (≥4 GB) processes a
  month comfortably; the download cache avoids re-OCR on re-runs.
- **Fully offline-capable** except the Google Sheets/Drive reads, which use the
  free API tier — no paid component anywhere.

---

## Phase 8 — Web backend: API + jobs + state (F14–F16, F19, F22)
**Goal:** expose the engine over HTTP so the website can drive it. Thin layer —
the API calls the Phase 1–6 engine library; no business logic duplicated.

- [ ] **FastAPI** app with **PostgreSQL** state (SQLAlchemy + Alembic): runs,
      per-claim verdicts, manual overrides, audit entries.
- [ ] **Auth** (F14): login; restrict to allowed staff accounts. Sessions/tokens.
- [ ] `POST /runs` — start a cycle run for a month as a **background job**
      (BackgroundTasks or worker); returns a run id (F15).
- [ ] `GET /runs/{id}` — status + progress + counts (queued→downloading→OCR→
      validating→done) for live updates (F16).
- [ ] `GET /runs/{id}/results` — per-crew validated results.
- [ ] `GET /runs/{id}/exceptions` — flagged claims + failing rule + confidence +
      roster image reference (F18 data).
- [ ] `POST /claims/{id}/decision` — approve / reject / correct; record who/when/
      why; trigger re-aggregation (F19, idempotent N2).
- [ ] `GET /runs/{id}/report` — generate/download master sheet + exception report
      (F20).
- [ ] `GET/PUT /config` — routes, flight numbers, rate, thresholds (F21/F13).
- [ ] `GET /audit` — decision trail (F22, N1).

**Done when:** a full cycle can be driven end-to-end via API calls (no UI yet),
verified by API tests against the sample fixtures.

---

## Phase 9 — Web frontend: staff UI (F15–F22, N7)
**Goal:** non-technical staff run and review everything in a browser.

- [ ] **Run screen:** pick cycle month → **Run**; show live progress + counts
      (F15/F16).
- [ ] **Results dashboard:** per-crew Period / Days / Total Perdiem + totals
      (F17).
- [ ] **Exception queue:** each flagged claim with **roster image preview**,
      extracted fields, **failing rule**, OCR confidence (F18).
- [ ] **Approve / override / correct** controls per claim → re-aggregate (F19).
- [ ] **Publish/Download** master report + exception report (F20).
- [ ] **Config screen** for routes / rotating flight numbers / rate / thresholds
      (F21).
- [ ] **Audit view** (F22).
- [ ] UI: **React + Vite + pnpm** SPA styled with **Tailwind CSS** (locked).

**Done when:** a staff member completes a full cycle — run, review exceptions,
override, download report — without touching the CLI.

---

## Phase 10 — Deployment on Pi 5 via Docker + Cloudflare (N8)
**Goal:** run all services on the Pi 5 with `docker compose`, exposed through
Cloudflare — **no nginx, no open ports**, zero-cost.

- [ ] **Multi-stage api image:** `node:20-alpine` builds the SPA (`pnpm build`),
      `python:3.12-slim` stage adds Tesseract/OpenCV + backend and serves
      `dist/` via FastAPI `StaticFiles` (SPA + REST on one origin).
- [ ] **docker-compose** (at the repo root) services: `api`, `worker`, `db`
      (postgres:16-alpine) — all arm64; `api`/`worker` share cache/output volumes
      and reach `db` over the compose network; `db` has a healthcheck + `pgdata`
      volume. Set `restart: unless-stopped` so services survive reboot.
- [ ] Publish `api` on **`127.0.0.1:8000`** only (no LAN/internet exposure).
- [ ] **Cloudflare:** the Pi already runs `cloudflared` — just add a **new public
      hostname** on the existing tunnel → `http://localhost:8000`. No cloudflared
      container, no tunnel token in the repo, no port forwarding.
- [ ] (Optional) put **Cloudflare Access** in front for an extra auth layer.
- [ ] Apply migrations on deploy: `docker compose run --rm api <migrate>`.
- [ ] Serve roster image previews from the `cache/` volume via the api
      (auth-gated, PII).
- [ ] Bring up with `docker compose up -d --build`; document `.env`
      (DATABASE_URL, POSTGRES_PASSWORD, secrets path).

**Done when:** staff open the public Cloudflare hostname and run a full cycle;
`docker compose` services restart on reboot; no nginx and no paid component.

---

## Cross-cutting / risk register

| Risk | Mitigation |
|------|------------|
| OCR misreads on poor photos | Confidence threshold → manual review; OpenCV preprocessing (deskew/contrast/upscale); text is printed so Tesseract is viable; local PaddleOCR/EasyOCR as free fallback |
| Pi resource limits (RAM/CPU) | Batch/sequential processing, download cache, 64-bit OS, ≥4 GB Pi; keep OCR engine lightweight (Tesseract) |
| Red-box detection unreliable | Fall back to form's claimed-day list (col 10) as primary, red box as cross-check (see Open Q3) |
| Flight numbers rotate monthly | Config-driven set (R2); validate config at run start |
| Generated-date rule direction unclear | **Resolve Open Q2 before Phase 4** — the "(correct format)" sample contradicts R4 as written |
| Thai/English name + month parsing | Normalisation layer (R5a); test with bilingual fixtures |
| Multi-leg days (DMK-HKT + DMK-SIN same day) | Consider only DMK↔HKT legs; other legs ignored, not disqualifying (confirm Open Q5) |
| Long run blocks the web request | Run as background job; UI polls `GET /runs/{id}` for progress (F15/F16) |
| Web app adds load to the Pi | Engine stays a library; web layer is thin; Postgres tuned small (modest `shared_buffers`) + Uvicorn (serves SPA + API, no nginx); one concurrent run at a time |
| PII exposed via web | Auth-gate everything (F14); LAN-only by default; roster previews served only to logged-in staff (N5) |

## Open questions blocking build

These (from REQUIREMENTS §9) should be answered before/within the noted phase:

1. **Generated-date direction (R4)** — *blocks Phase 4.*
2. **Red box vs claimed-day list as source of truth** — *shapes Phase 3/5.*
3. **Per diem rate fixed vs rank/route dependent** — *affects Phase 5.*
4. **Layover / Irregularity claim types** — same rules or separate? *Phase 4.*
5. **Multi-leg day handling** — *Phase 4.*
