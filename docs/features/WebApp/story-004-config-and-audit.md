| Property     | Value                                              |
| ------------ | -------------------------------------------------- |
| Story ID     | PD-WEB-004                                         |
| Title        | Config & audit screens                             |
| Epic         | EP-WEB — Web Application                           |
| Dependencies | PD-WEB-002 (auth), PostgreSQL config + audit tables|
| Story Type   | Feature                                            |
| Source       | REQUIREMENTS.md → §6.6 (F21, F22); §5 (R2/F13); §7 (N1)|

## 🗂 Epic Overview — EP-WEB

See [overview.md](./overview.md). Two supporting screens: editing the
monthly-rotating config without touching files, and browsing the decision audit trail.

## 📝 Feature Overview — PD-WEB-004

### User Story

```gherkin
As an admin
I want to update the qualifying flight numbers, routes, rate and thresholds from the UI
So that I can keep up with the monthly flight-number rotation without editing config files

As an admin
I want to browse the audit trail of how each claim was decided
So that I can explain or revisit any payment or rejection
```

### Pre-conditions

- Auth in place; config + audit persisted in Postgres.

### Scope

#### Included

- **Config screen (F21/F13):** view/edit qualifying routes, the **rotating
  flight-number set** (out/return), per diem rate, name-match + OCR thresholds.
- Config validation on save (e.g. flight numbers well-formed); changes versioned/audited.
- **Audit view (F22/N1):** per-decision trail — rule applied, source response
  ref, roster reference, confidence, and any manual override (who/when/why).
- Filter audit by run, crew, rule, or decision type.

#### Excluded

- Applying config (the engine reads it at run start — Validation epic).

## 🎯 Acceptance Criteria

### Functional Requirements

1. **View config (F21)** — current routes, flight numbers, rate, thresholds shown.
2. **Edit config** — staff can update values; saved to the `config` table;
   validated; a config change is itself audited.
3. **Rotation support** — updating next month's flight numbers is a simple form
   edit, no redeploy.
4. **Audit list (F22)** — every decision row shows `rule`, `reason`,
   `source_row_ref`, `roster_ref`, `confidence`, and override details if any.
5. **Traceability (N1)** — each payable/rejected outcome links back to its source
   response and roster image.

### Error Scenarios

- Invalid config (malformed flight number, non-numeric rate) → reject save with a message.
- Config edited mid-run → applies to the **next** run, not the in-flight one
  (document this clearly).

## 🧩 Technical Documentation

### Endpoints

```
GET  /api/config      -> { routes, flight_numbers, rate, thresholds }
PUT  /api/config      { ... } -> updated config (audited)
GET  /api/audit       ?run=&claim=&rule=  -> audit entries
```

### Frontend

- `ConfigPage.tsx` (forms with validation), `AuditPage.tsx` (filterable table);
  Tailwind styling.

## 🔨 Implementation Plan

1. 📝 **TODO** Config read/update endpoints + validation; write config-change audit.
2. 📝 **TODO** Audit query endpoint with filters.
3. 📝 **TODO** ConfigPage form (routes, flight numbers, rate, thresholds).
4. 📝 **TODO** AuditPage filterable table linking to source + roster.
5. 📝 **TODO** Tests: config validation; "applies next run" semantics.

## 🏗 Structure

```
backend/perdiem/web/routes/{config,audit}.py
frontend/src/pages/{ConfigPage,AuditPage}.tsx
```

## 📌 Notes / Open Questions

- Keep a config **history** (versioned) so a past run's config can be reconstructed
  for audit? Recommended.
