| Property     | Value                                                        |
| ------------ | ------------------------------------------------------------ |
| Story ID     | PD-ING-001                                                   |
| Title        | Form response ingestion (Posting Base + Late Submission)     |
| Epic         | EP-INGEST — Form Ingestion & Roster Retrieval                |
| Dependencies | Python, openpyxl/pandas, Google Sheets API, SQLAlchemy       |
| Story Type   | Feature                                                      |
| Source       | REQUIREMENTS.md → §4.1, §4.2, §6.1 (F1, F2)                  |

## 🗂 Epic Overview — EP-INGEST

See [overview.md](./overview.md). This story is the entry point of the whole
pipeline: it turns the two Google Form response sheets into a clean list of
`Claim` records for a cycle month.

## 📝 Feature Overview — PD-ING-001

### User Story

```gherkin
As the per diem validation system
I want to read the Posting Base and Late Submission form responses for a cycle month
So that every crew claim is captured as a structured record for validation

As an admin
I want both on-time and late submissions merged into one cycle
So that back-claims are reconciled together and nothing is missed
```

### Pre-conditions

- Service account `kantaphajasuwan@airasia.com` can read both response workbooks.
- The cycle month is selected (e.g. "February 2026").
- PostgreSQL is reachable for persisting parsed claims.

### Scope

#### Included

- Read **Posting Base** workbook — per-month tab (e.g. `MARCH 26`) + raw
  `Form Responses 26`.
- Read **Late Submission** workbook — per-month tab + raw `Form Responses 80`.
- Parse each row into a normalised `Claim` model.
- Parse the Thai claimed-day field `วันที่ 2, วันที่ 3` → `[2, 3]`.
- Tag each claim with its `source` (`POSTING_BASE` | `LATE`).
- Tolerate trailing/double spaces, mixed Thai/English, blank rows.
- Persist parsed claims into the `claims` table for a run.

#### Excluded

- Downloading roster attachments (see PD-ING-002).
- OCR / validation / dedup (later epics).
- Editing the Google Sheets (read-only).

## 🎯 Acceptance Criteria

### Functional Requirements

1. **Source reading (F1)**
   - Authenticate via the service account; read by sheet name for the cycle month.
   - If the month tab is missing in a workbook, record a warning and continue
     with whatever sources exist (don't abort the run).
2. **Field parsing (F2)** — map columns to the `Claim` model:
   - `timestamp`, `email`, `staff_id` (Employee Code), `name`, `position`,
     `base`, `claim_type`, `claim_month`, `claimed_days[]`, `roster_links[]`,
     `crew_remark`, `admin_remark`.
   - Posting Base and Late Submission have **different column layouts** — handle
     each with its own mapping (Late has `Operating Base`, different Thai
     headers, `Status`).
3. **Claimed-day parsing**
   - `วันที่ 2, วันที่ 3` → `[2, 3]`; handle long lists (e.g. 24 days) and stray spaces.
   - Combine with `claim_month` to produce concrete dates downstream.
4. **Multiple roster links**
   - The attachment cell may hold several comma-separated Drive links → split
     into `roster_links[]` (download handled in PD-ING-002).
5. **Source tagging**
   - Every claim records whether it came from Posting Base or Late Submission.

### Error Scenarios

- Missing/blank Employee Code → claim flagged `NEEDS_REVIEW(missing staff id)`,
  not dropped.
- Unparseable timestamp or day list → keep the row, flag for review.
- Workbook unreachable / auth failure → fail the run with a clear message.
- Date serial out of range (seen in sample data) → coerce/skip the cell safely.

## 🧩 Technical Documentation

### Claim model (engine dataclass)

```python
@dataclass
class Claim:
    source: Literal["POSTING_BASE", "LATE"]
    source_row_ref: str          # workbook!sheet!row for audit
    timestamp: datetime | None
    email: str
    staff_id: str | None         # Employee Code
    name: str
    position: str | None
    base: str | None
    claim_type: str | None
    claim_month: str             # e.g. "FEBRUARY 2026"
    claimed_days: list[int]      # [2, 3]
    roster_links: list[str]
    crew_remark: str | None
    admin_remark: str | None
```

### Column mapping (Posting Base)

| Sheet column (Thai/English)                 | Claim field    |
| ------------------------------------------- | -------------- |
| Timestamp                                   | timestamp      |
| Email Address                               | email          |
| Name - Surname                              | name           |
| Employee Code                               | staff_id       |
| Position                                    | position       |
| Permanent at Base                           | base           |
| เลือกประเภทการเบิกเงิน                        | claim_type     |
| เดือนที่จะเบิก …                              | claim_month    |
| ช่วงวันที่เบิก …                              | claimed_days   |
| กรุณาแนบตารางบิน (Roster)                     | roster_links   |
| เพิ่มหมายเหตุ (ถ้ามี)                          | crew_remark    |
| Remark                                      | admin_remark   |

> Late Submission uses `Operating Base`, `กรุณาระบุเดือนที่ทำการเบิกล่าช้า`
> (late month), `ช่วงวันที่ทำการเบิกล่าช้า` (day list), and a `Status` column —
> mapped by a separate adapter.

### Interfaces

```python
def read_posting_base(path: str, cycle_month: str) -> list[Claim]: ...
def read_late_submission(path: str, cycle_month: str) -> list[Claim]: ...
def ingest_cycle(cycle_month: str) -> list[Claim]:
    """Read both sources, return the merged claim list (no dedup yet)."""
```

## 🔨 Implementation Plan

1. 📝 **TODO** Google Sheets access via service account (read-only) + config for workbook IDs.
2. 📝 **TODO** Posting Base adapter (column map → `Claim`).
3. 📝 **TODO** Late Submission adapter (its own column map).
4. 📝 **TODO** Thai day-list parser (`วันที่ N` → ints) with unit tests.
5. 📝 **TODO** Robustness: trailing spaces, blank rows, bad date serials.
6. 📝 **TODO** Persist claims to `claims` table keyed by run.
7. 📝 **TODO** Tests against `docs/example-files` fixtures (MARCH 26 / FEBRUARY 26).

## 🏗 Structure

```
backend/perdiem/engine/
├── ingest.py            # read_posting_base, read_late_submission, ingest_cycle
└── parsing/
    └── thai_dates.py    # "วันที่ 2, วันที่ 3" -> [2, 3]
```

## 📌 Notes / Open Questions

- Confirm the canonical workbook IDs / how the cycle month maps to tab names
  (naming is inconsistent across years, e.g. `FEBUARY 2025`).
- `claim_type` values include `Posting Base`, `Layover allowance`,
  `Irregularity of Sector Allowance` — do all follow the same rules? (REQUIREMENTS §9 Q4).
