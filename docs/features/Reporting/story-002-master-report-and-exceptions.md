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
def write_master(results: list[CrewResult], month: str) -> bytes:
    """Return master report .xlsx as bytes for HTTP streaming download."""

def write_exceptions(verdicts: list[DayVerdict], claims: list[Claim], month: str) -> bytes:
    """Return exception report .xlsx as bytes for HTTP streaming download."""
```

## 🔨 Implementation Plan

1. ✅ **DONE** `write_master()` — openpyxl workbook with status banner (row 1), header row (row 2), and data rows; all §4.3 columns present.
2. ✅ **DONE** `format_periods()` — newline-joined `DD Month YYYY - DD Month YYYY` text, single-day shorthand.
3. ✅ **DONE** Idempotency by design — each call generates a fresh workbook from current `CrewResult[]`; no in-place editing.
4. ✅ **DONE** `write_exceptions()` — INVALID + NEEDS_REVIEW verdicts with rule, reason, source ref, claimed date, roster link; VALID/VALID_BACKCLAIM excluded.
5. ✅ **DONE** Tests: bytes returned, correct sheet name, header row, crew data, multi-range period, sequential item numbers, empty cycle (25 tests, all pass).

## 🏗 Structure

```
backend/perdiem/engine/
└── report.py         # write_master + write_exceptions + format_periods (F11, F12)
tests/engine/
└── test_report.py    # 25 unit tests
```

## 📌 Notes / Open Questions

- Both reports generated on demand as bytes — no file locking, no in-place editing. Admin downloads via web UI (PD-WEB-005). ✅ Confirmed.
- `Cross Checked by Supervisor` column left blank; filled after web review by the WebApp epic (PD-WEB-003). Pending implementation.
