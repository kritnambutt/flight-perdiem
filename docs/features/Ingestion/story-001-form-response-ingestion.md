| Property     | Value                                                        |
| ------------ | ------------------------------------------------------------ |
| Story ID     | PD-ING-001                                                   |
| Title        | Form response ingestion (Posting Base + Late Submission)     |
| Epic         | EP-INGEST — Form Ingestion & Roster Retrieval                |
| Dependencies | Python, openpyxl                                             |
| Story Type   | Feature                                                      |
| Source       | REQUIREMENTS.md → §4.1, §4.2, §6.1 (F1, F2)                  |

## 🗂 Epic Overview — EP-INGEST

See [overview.md](./overview.md). This story is the entry point of the whole
pipeline: it turns the two Google Form response sheets into a clean list of
`Claim` records for a cycle month.

## 📝 Feature Overview — PD-ING-001

### User Story

```gherkin
As an admin
I want to upload the Posting Base and Late Submission Excel files for a cycle month
So that the system can parse every crew claim into a structured record for validation

As an admin
I want both on-time and late submissions merged into one cycle
So that back-claims are reconciled together and nothing is missed
```

### Pre-conditions

- Admin has downloaded the current month's Excel files from Google Sheets
  (`kantaphajasuwan@airasia.com`) and has them ready to upload.
- The cycle month is selected (e.g. "February 2026").
- The two files match the expected workbook format (correct sheet names and headers).

> **Why manual download:** AirAsia's Google Workspace org policy blocks all
> external API access to Sheets and Drive. Admin downloads manually from the
> browser and uploads to the system. See REQUIREMENTS.md §3 for full rationale.

### Scope

#### Included

- Accept **two uploaded `.xlsx` files** — Posting Base and Late Submission —
  and validate they match the expected format before parsing.
- Read the per-month tab (e.g. `MARCH 26`) from each workbook.
- Parse each row into a normalised `Claim` model.
- Parse the Thai claimed-day field `วันที่ 2, วันที่ 3` → `[2, 3]`.
- Normalise the Late Submission `claim_month` field (Thai/English/Buddhist-year
  mixed formats → canonical `"FEBRUARY 2026"`).
- Tag each claim with its `source` (`POSTING_BASE` | `LATE`).
- Tolerate trailing/double spaces, mixed Thai/English, blank rows.
- Persist parsed claims into the `claims` table for a run.

#### Excluded

- Downloading roster attachments (see PD-ING-002).
- OCR / validation / dedup (later epics).
- Any live Google Sheets or Drive API calls (no API access in this story).

## 🎯 Acceptance Criteria

### Functional Requirements

1. **Source reading (F1)**
   - Accept two uploaded `.xlsx` files. Validate each has at least one
     recognisable month-tab and the expected header columns; reject with a
     clear error message if the wrong file is uploaded.
   - Read the tab matching the selected cycle month. If the tab is missing,
     log a warning and continue with whatever sources exist (don't abort).
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

- Wrong file uploaded (not a recognised response workbook) → reject before
  parsing with a clear error: "Expected Posting Base workbook, got …".
- Missing/blank Employee Code → claim flagged `NEEDS_REVIEW(missing staff id)`,
  not dropped.
- Unparseable timestamp or day list → keep the row, flag for review.
- Month tab not found in the uploaded file → log a warning, return empty list
  for that source (don't abort the run).
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

1. ✅ **DONE** File-based ingestion — accepts uploaded Excel files, no Google API needed.
   - `perdiem/config.py` holds `POSTING_BASE_PATH` / `LATE_SUBMISSION_PATH` (env vars
     pointing to local `.xlsx` files for dev/test).
   - `ingest_cycle(cycle_month, pb_path, late_path)` takes explicit file paths — the web
     layer will pass the uploaded file paths at runtime.

   ### How the admin prepares the files (each cycle)

   AirAsia's Google Workspace org policy blocks all external API access to Sheets and Drive,
   so the admin downloads the files manually before each run.

   **Step 1 — Download Posting Base responses**
   1. Open the **Posting Base** Google Sheet as `kantaphajasuwan@airasia.com`.
   2. **File → Download → Microsoft Excel (.xlsx)**.
   3. Save as e.g. `posting-base-march-26.xlsx`.

   **Step 2 — Download Late Submission responses**
   1. Open the **Late Submission** Google Sheet as `kantaphajasuwan@airasia.com`.
   2. **File → Download → Microsoft Excel (.xlsx)**.
   3. Save as e.g. `late-submission-march-26.xlsx`.

   **Step 3 — Upload to the system**
   Upload both files via the web UI when starting a run (F15). The system validates
   the format and selects the correct month tab automatically.

   > **Drive access for roster images** is set up separately in **PD-ING-002**
   > using `gcloud auth login --enable-gdrive-access` — see that story.

2. ✅ **DONE** Posting Base adapter (`ingest.py` → `read_posting_base`).
   - Header-keyword column detection (robust across sheet layout changes over years).
   - Staff ID coerced from Excel float (`1012357.0`) → string integer (`"1012357"`).
3. ✅ **DONE** Late Submission adapter (`ingest.py` → `read_late_submission`).
   - Separate column matchers for the different Thai headers.
   - `claim_month` normalised from Thai names / English abbreviations / Buddhist year.
4. ✅ **DONE** Thai day-list parser (`parsing/thai_dates.py`).
   - `parse_thai_day_list`: `"วันที่ 2, วันที่ 3"` → `[2, 3]`; handles 24-day lists,
     duplicates, stray spaces.
   - `normalize_claim_month`: Thai/English/Buddhist-year → `"FEBRUARY 2026"`.
   - 24 unit tests, all passing.
5. ✅ **DONE** Robustness: trailing/double spaces, blank rows, bad date serials handled
   (`_str_or_none`, `_parse_timestamp`, `all(v is None)` row skip).
6. 📝 **TODO** Persist claims to `claims` table keyed by run.
   Deferred to **PD-PLAT-001** (DB schema story). `ingest_cycle` currently returns
   `list[Claim]`; the persistence layer will wrap it.
7. ✅ **DONE** Tests against `docs/example-files` fixtures (MARCH 26 / FEBRUARY 26).
   - 23 integration tests against real Excel files + 24 unit tests = **47 tests, all passing**.
   - `backend/tests/engine/test_ingest.py` and `test_thai_dates.py`.

## 🏗 Structure

```
backend/perdiem/engine/
├── ingest.py            # read_posting_base, read_late_submission, ingest_cycle
└── parsing/
    └── thai_dates.py    # "วันที่ 2, วันที่ 3" -> [2, 3]
```

## 📌 Notes / Open Questions

- Tab naming is inconsistent across years (`FEBUARY 2025` typo, mixed case `March 26` vs
  `MARCH 26`). Handled: `_find_sheet()` in `ingest.py` uses case-insensitive + typo-tolerant
  matching. Confirmed working against real fixtures.
- `claim_type` values include `Posting Base`, `Layover allowance`,
  `Irregularity of Sector Allowance` — do all follow the same rules? (REQUIREMENTS §9 Q4).
- **No Google Sheets API** — replaced by manual download + upload. If the org policy
  ever relaxes, `ingest_cycle` can be extended to accept a workbook ID + credentials
  without changing the parsing logic.
