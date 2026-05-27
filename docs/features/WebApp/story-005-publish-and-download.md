| Property     | Value                                              |
| ------------ | -------------------------------------------------- |
| Story ID     | PD-WEB-005                                         |
| Title        | Publish & download reports                         |
| Epic         | EP-WEB — Web Application                           |
| Dependencies | PD-REP-002 (writers), PD-WEB-001 (runs)            |
| Story Type   | Feature                                            |
| Source       | REQUIREMENTS.md → §6.6 (F20)                       |

## 🗂 Epic Overview — EP-WEB

See [overview.md](./overview.md). This story lets staff export the finished
artifacts: the master report sheet and the exception report.

## 📝 Feature Overview — PD-WEB-005

### User Story

```gherkin
As an admin
I want to download the master report and exception report for the month
So that I can hand the payable list to payroll and act on exceptions
```

### Pre-conditions

- A run has produced `CrewResult`s and verdicts (Reporting epic).
- Report writers (PD-REP-002) are available.

### Scope

#### Included

- **Generate/download** the master report `.xlsx` for the selected month (F20).
- **Generate/download** the exception report.
- Generation reflects the latest state **after** manual overrides (re-aggregated).
- Download is auth-gated.

#### Excluded

- The writing logic itself (PD-REP-002) — this story exposes it over HTTP + UI.

## 🎯 Acceptance Criteria

### Functional Requirements

1. **Master download (F20)** — `GET /api/runs/{id}/report` streams the month's
   master `.xlsx` in the §4.3 layout.
2. **Exception download** — `GET /api/runs/{id}/exceptions/export` streams the
   exception report.
3. **Up-to-date** — exports include the effect of any approvals/overrides made in
   the review UI (PD-WEB-003).
4. **Idempotent content** — re-downloading without new changes yields identical content.
5. **Auth-gated** — only signed-in staff can download (PII).

### Error Scenarios

- Download requested before the run finished → clear "not ready" response.
- Report generation fails (e.g. workbook locked) → surface a clear error, no partial file.

## 🧩 Technical Documentation

### Endpoints

```
GET /api/runs/{id}/report             -> master .xlsx (attachment)
GET /api/runs/{id}/exceptions/export  -> exception report (xlsx/csv)
```

### Frontend

- Download buttons on `ResultsPage.tsx` (master) and `ExceptionsPage.tsx`
  (exceptions); disabled until the run is `done`.

## 🔨 Implementation Plan

1. 📝 **TODO** Report endpoints calling PD-REP-002 writers; stream as attachments.
2. 📝 **TODO** Ensure re-aggregation runs after overrides before export.
3. 📝 **TODO** UI download buttons + ready-state gating.
4. 📝 **TODO** Tests: post-override content correctness; not-ready handling.

## 🏗 Structure

```
backend/perdiem/web/routes/reports.py
frontend/src/pages/ResultsPage.tsx      # download controls
```

## 📌 Notes

- **Fresh file confirmed** — both reports are generated on demand as `.xlsx`
  bytes and streamed as HTTP attachments. No in-place editing, no locking, no
  shared master workbook to maintain. See PD-REP-002 for the writer interface.
