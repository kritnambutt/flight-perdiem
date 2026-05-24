| Property     | Value                                              |
| ------------ | -------------------------------------------------- |
| Story ID     | PD-REP-002                                         |
| Title        | Master report + exception report output            |
| Epic         | EP-REPORT — Dedup, Aggregation & Reporting         |
| Dependencies | PD-REP-001 (CrewResult), openpyxl                  |
| Story Type   | Feature                                            |
| Source       | REQUIREMENTS.md → §4.3, §6.4 (F11, F12)            |

## 🗂 Epic Overview — EP-REPORT

See [overview.md](./overview.md). This story writes the payable results into the
existing master workbook shape and produces an actionable exception report.

## 📝 Feature Overview — PD-REP-002

### User Story

```gherkin
As an admin
I want validated results written into the monthly master report sheet
So that the payable list matches the format payroll already uses

As an admin
I want a clear exception report of everything rejected or needing review
So that I can act on just the problem claims
```

### Pre-conditions

- `CrewResult[]` produced by PD-REP-001.
- Access to the master workbook (`Posting Perdiem of CCD`) layout.

### Scope

#### Included

- Write/append a **per-month worksheet** matching the master report columns:
  `Item, New ID No., Employee name, Period, Days, Total Perdiem (THB), Email
  Address, Cross Checked by Supervisor, REMARK`.
- Multi-range `Period` rendered as newline-joined ranges
  (e.g. `26 January 2026 - 31 January 2026` ⏎ `10 February 2026 - 11 February 2026`).
- **Do not disturb** historical sheets.
- **Idempotent** writes keyed by staff ID (re-run replaces, never duplicates).
- Produce a separate **exception report** (sheet/file): every `INVALID` /
  `NEEDS_REVIEW` with the failing rule, source response ref, roster reference,
  and OCR confidence.

#### Excluded

- The dedup/aggregation logic (PD-REP-001).
- Manual override handling (WebApp epic) — though overrides feed re-aggregation.

## 🎯 Acceptance Criteria

### Functional Requirements

1. **Master sheet (F11)** — a month sheet is created/updated with exactly the
   master columns and formatting; status banner (`Last updated … (Status: OPEN)`).
2. **Period formatting** — consecutive ranges, newline-separated, day-month-year
   text matching existing rows.
3. **History safe** — other month sheets are untouched; only the target month is
   written.
4. **Idempotency (N2)** — re-running a cycle replaces the month's rows
   deterministically; no duplicate `Item`s or crew rows.
5. **Exception report (F12)** — lists each problem claim with `rule`, `reason`,
   `source_row_ref`, `roster_ref`, `confidence`, and crew/admin remarks.

### Error Scenarios

- Master workbook locked/open elsewhere → write to a temp copy, surface a clear error.
- Crew appears in both payable and exception lists (some days valid, some not) →
  represented in both, consistently.
- Empty cycle (no valid claims) → still emit headers + (possibly empty) exception report.

## 🧩 Technical Documentation

### Master columns (from §4.3)

| Column | Source |
| ------ | ------ |
| Item | row index |
| New ID No. | `CrewResult.staff_id` |
| Employee name | `CrewResult.name` |
| Period | merged ranges (newline-joined) |
| Days | `CrewResult.days` |
| Total Perdiem (THB) | `CrewResult.total_thb` |
| Email Address | `CrewResult.email` |
| Cross Checked by Supervisor | default blank / `CHECKED (OK)` after review |
| REMARK | `CrewResult.remark` |

### Interface

```python
def write_master(results: list[CrewResult], month: str, workbook_path: str) -> None: ...
def write_exceptions(verdicts: list[DayVerdict], claims, month: str, out_path: str) -> None: ...
```

## 🔨 Implementation Plan

1. 📝 **TODO** openpyxl writer for the month sheet (columns + banner) preserving history.
2. 📝 **TODO** Period range formatter (newline-joined, DD Month YYYY).
3. 📝 **TODO** Idempotent month-sheet replace keyed by staff ID.
4. 📝 **TODO** Exception report writer (rule, source, roster ref, confidence).
5. 📝 **TODO** Tests: history untouched, re-run no-op, multi-range periods.

## 🏗 Structure

```
backend/perdiem/engine/
└── report.py         # write_master + write_exceptions (F11, F12)
```

## 📌 Notes / Open Questions

- Write into the **existing** workbook in place, or emit a fresh file the admin
  pastes/imports? (Affects locking + backup strategy.)
- `Cross Checked by Supervisor` — set automatically after web review (WebApp), or left blank?
