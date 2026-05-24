| Property     | Value                                              |
| ------------ | -------------------------------------------------- |
| Story ID     | PD-WEB-003                                         |
| Title        | Results dashboard & exception review UI            |
| Epic         | EP-WEB — Web Application                           |
| Dependencies | PD-WEB-001 (runs), PD-REP-001/002, React + Tailwind|
| Story Type   | Feature                                            |
| Source       | REQUIREMENTS.md → §6.6 (F17, F18, F19)             |

## 🗂 Epic Overview — EP-WEB

See [overview.md](./overview.md). This is the core human-in-the-loop screen:
staff see payable results and work through flagged claims.

## 📝 Feature Overview — PD-WEB-003

### User Story

```gherkin
As an admin
I want to see per-crew validated results for the month
So that I can confirm the payable totals at a glance

As an admin
I want a review queue of flagged claims with the roster image and the failing rule
So that I can quickly judge and approve, reject, or correct each one
```

### Pre-conditions

- A completed (or in-progress) run with verdicts and results in Postgres.
- Auth in place (PD-WEB-002).

### Scope

#### Included

- **Results dashboard (F17):** per-crew rows (Period, Days, Total Perdiem) + cycle totals.
- **Exception queue (F18):** each `NEEDS_REVIEW` / `INVALID` claim showing the
  **roster image preview**, extracted fields, the **failing rule + reason**, and
  OCR confidence.
- **Approve / reject / correct (F19):** per-claim actions; the decision is
  recorded (who/when/why) and triggers **re-aggregation** (idempotent).
- Filters: by verdict, by failing rule, by crew.

#### Excluded

- Generating/downloading the report file (PD-WEB-005).
- Editing config (PD-WEB-004).

## 🎯 Acceptance Criteria

### Functional Requirements

1. **Dashboard (F17)** — lists `CrewResult`s for the selected run; shows total
   crew, total days, total THB; sortable/searchable.
2. **Exception list (F18)** — each item shows roster thumbnail (click → full
   preview, auth-gated), extracted staff ID/name/dates, `rule`, `reason`,
   `confidence`, and crew/admin remarks.
3. **Decision (F19)** — approve / reject / correct (e.g. adjust claimed days);
   `POST /api/claims/{id}/decision` stores `decided_by/at/note`.
4. **Re-aggregation** — after a decision, results recompute deterministically
   (no double counting); dashboard reflects the change.
5. **Auditability** — every override is written to the audit trail (PD-WEB-004).

### Error Scenarios

- Roster image missing/unreachable → show the failure state, allow reject/manual note.
- Concurrent decisions on the same claim → last write wins with audit of both, or
  optimistic-locking error surfaced.
- Correcting days that re-trigger rules → re-validate the affected claim.

## 🧩 Technical Documentation

### Endpoints

```
GET  /api/runs/{id}/results        -> CrewResult[]
GET  /api/runs/{id}/exceptions     -> flagged claims (+rule, reason, confidence, roster ref)
GET  /api/rosters/{file_id}        -> image bytes (auth-gated, PII)
POST /api/claims/{id}/decision     { decision, note, corrected_days? } -> updated verdict
```

### Frontend

- `ResultsPage.tsx` (dashboard), `ExceptionsPage.tsx` (queue), components
  `RosterPreview`, `VerdictBadge`, `DecisionControls`; Tailwind styling.

## 🔨 Implementation Plan

1. 📝 **TODO** Results + exceptions read endpoints.
2. 📝 **TODO** Auth-gated roster image endpoint serving from the cache volume.
3. 📝 **TODO** Decision endpoint → store override → re-aggregate.
4. 📝 **TODO** ResultsPage (totals, sort, search).
5. 📝 **TODO** ExceptionsPage (preview, rule/reason, decision controls, filters).
6. 📝 **TODO** Tests: decision → re-aggregation correctness.

## 🏗 Structure

```
backend/perdiem/web/routes/{exceptions,claims,reports}.py
frontend/src/pages/{ResultsPage,ExceptionsPage}.tsx
frontend/src/components/{RosterPreview,VerdictBadge,DecisionControls}.tsx
```

## 📌 Notes / Open Questions

- Does an approval set `Cross Checked by Supervisor = CHECKED (OK)` in the master
  sheet automatically? (ties to PD-REP-002).
- Correction scope: only adjust claimed days, or also override a specific rule outcome?
