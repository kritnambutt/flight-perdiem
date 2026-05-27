| Property     | Value                                                          |
| ------------ | -------------------------------------------------------------- |
| Story ID     | PD-ML-002                                                      |
| Title        | Labelled dataset builder from the three workbooks              |
| Epic         | EP-ML — Roster Intelligence                                    |
| Dependencies | None (reads `docs/example-files/*.xlsx`); optional: PD-ING-002 cache, Drive creds |
| Story Type   | Infrastructure                                                 |
| Status       | ✅ Done — 5,745 text rows built from all 3 workbooks; 35 tests pass. Vision split pending a populated roster cache (PD-ING-002). |
| Source       | REQUIREMENTS.md → §4.1–4.3 (the three workbooks), §5 (R1–R8)   |

## 🗂 Epic Overview — EP-ML

See [overview.md](./overview.md). **This is the first ML build.** It assembles the
ground-truth dataset every other Track-B story trains and evaluates on, from the years of
admin-validated history in the three response workbooks. It depends on **nothing but the
workbooks** — not on Phase 0, not on the database.

## 📝 Feature Overview — PD-ML-002

### User Story

```gherkin
As the ML programme
I want a versioned, normalised dataset built by joining the three workbooks across all monthly sheets
So that triage, doc-type, and roster-reader models train on real admin decisions and approved outcomes — not hand-labelled toys
```

### Pre-conditions

- `docs/example-files/` holds the three workbooks (Posting Base, Late Submission, CCD master).
- (Optional, for the image-backed split) Drive read access or a populated roster file cache.

### Scope

#### Included

- Parse **every monthly sheet** of Posting Base + Late Submission + CCD master (sheets back
  to 2018), tolerant of inconsistent sheet names (`AUGUST 2025`, `AUG 2025`, `FEBUARY 2025`…).
- **Join** form rows ⨝ master on `(staff_id, cycle month)` to attach the approved outcome.
- **Normalise** the messy free-text: Thai/English month names, the disposition column, and
  claimed-days (`วันที่ 2, วันที่ 3` → `[2,3]`) into canonical fields.
- Emit **two datasets**: (a) **text/decision** rows (all history, no image) and (b)
  **vision** rows (subset whose roster Drive link resolves to a cached image).
- Tag every row: `split (train/val/test)`, `label_source (admin_remark | master_reconciled
  | regex_bootstrap)`, and provenance (`source_workbook!sheet!row`).
- A **data-quality report** (rows per sheet, label coverage, unmatched joins, blank-Remark
  counts) so labelling assumptions are auditable.

#### Excluded

- Any model training (PD-ML-003+). OCR of the roster images themselves (the vision split
  only records the *image path* + derived field labels; reading them is PD-ML-006).

## 🎯 Acceptance Criteria

### Functional Requirements

1. **Multi-sheet ingest:** all monthly sheets across the three workbooks are read; a sheet
   whose name can't be parsed to a month is reported, not silently dropped.
2. **Join & outcome:** each form submission is matched to its master row when paid; produces
   `approved: bool`, `approved_periods`, `approved_days`, `total_thb` (THB = days × rate).
3. **Disposition label (the gold WS-3 label):** the admin Remark/status text is mapped to a
   canonical class — `APPROVED | REJECTED | DEFER_BACKCLAIM | REVIEW` — plus a free-text
   reason and a derived `rule_hint ∈ {R4,R6,R7,R8,DOC_INCOMPLETE,OUT_OF_SCOPE,NONE}` (see
   the remark→rule map below).
4. **Claimed-days + month normalisation:** Thai/English months → canonical
   `("MONTH", YEAR)`; `วันที่ N` lists → `list[int]`.
5. **Identity registry:** the master's crew-data sheets produce a `staff_id → name` map for
   R5/R5a reconciliation and as identity labels.
6. **Two splits written** (text, vision) in a documented schema (Parquet/JSONL), each row
   carrying `split` and `label_source`; splits are **by crew/month**, never random by day.
7. **Versioned & reproducible:** output under `data/ml/datasets/<version>/`; a manifest
   records source file hashes, row counts, and the labelling-rule version.

### Validation Rules

- **Blank-Remark rule (CONFIRM with admins):** a form row with **blank Remark but present in
  the master** ⇒ `APPROVED`; annotated ⇒ parse the disposition/reason. The rule is a single
  documented function so it can be changed in one place.
- Rate is config-driven (default 400 THB/day) — never hard-coded.
- Rows with no resolvable roster image are still kept in the **text** split (most history).

### Error Scenarios

- Drive link dead / file missing → row excluded from the **vision** split, kept in **text**,
  flagged in the quality report.
- Master has no matching crew/month → `approved=False, label_source=admin_remark` (decision
  taken from the form), flagged as `unmatched_master`.
- Duplicate submissions (`ลงข้อมูลซ้ำ`) → preserved with `rule_hint=R7` (a real label, not noise).

## 🧩 Technical Documentation

### Dataset row models (outside the engine — pure data prep)

```python
@dataclass
class TextRow:
    provenance: str                 # "<workbook>!<sheet>!<row>"
    source: Literal["POSTING_BASE", "LATE"]
    staff_id: str | None
    name: str
    cycle_month: tuple[str, int]    # ("AUGUST", 2025)
    claimed_days: list[int]
    claim_type: str | None
    crew_remark: str | None
    disposition: Literal["APPROVED","REJECTED","DEFER_BACKCLAIM","REVIEW"]
    reason_text: str | None
    rule_hint: str                  # R4/R6/R7/R8/DOC_INCOMPLETE/OUT_OF_SCOPE/NONE
    approved: bool
    approved_periods: list[tuple[date, date]]
    approved_days: int
    total_thb: int
    split: Literal["train","val","test"]
    label_source: Literal["admin_remark","master_reconciled","regex_bootstrap"]

@dataclass
class VisionRow:
    provenance: str
    image_path: str                 # cached roster file
    fields: dict                    # staff_id/name/date_range/generated_at/grid labels (weak)
    label_source: str
    split: str
```

### Remark → rule map (seed; extend as new remarks appear)

| Remark substring (Thai) | Canonical | rule_hint |
|---|---|---|
| `จ่ายเงิน` | APPROVED | NONE |
| `ไม่จ่ายเงิน` | REJECTED | (varies) |
| `รอแก้ไข` / `ทำจ่ายตกเบิก` | DEFER_BACKCLAIM | R8 |
| `รอการตรวจสอบจากแอดมินอีกท่าน` | REVIEW | NONE |
| `ไม่มีวันที่ด้านล่างซ้ายมือ` | REJECTED | R4 |
| `กรณีเบิกไม่ตรงเดือน` | REJECTED | R8 |
| `ลงข้อมูลซ้ำ` | REJECTED | R7 |
| `ต้องแนบ full roster` | REJECTED | DOC_INCOMPLETE |
| `กรณีเครื่อง AOG` | REJECTED | OUT_OF_SCOPE |

### Required Configuration

- `RATE_THB_PER_DAY` (default 400). `ML_DATASET_DIR` (default `data/ml/datasets`).
- `DATASET_VERSION` tag; `WORKBOOK_PATHS` (default `docs/example-files/*.xlsx`).

### Security Requirements

- The dataset contains **PII** (names, schedules). It stays **local**; never committed to
  git (add `data/ml/` to `.gitignore`); not uploaded to any cloud service.

## 🔨 Implementation Plan

1. ✅ **DONE** Workbook readers (openpyxl) tolerant of messy sheet names → `(month, year)` (`readers.py`, `normalise.parse_sheet_month`).
2. ✅ **DONE** Field normalisers: Thai/Eng months, `วันที่ N` day lists, disposition→class (`normalise.py`; reuses the engine's Thai-date parsers).
3. ✅ **DONE** Master parser: `Period` (multi-range, newline) → `list[(date,date)]`, days, THB (`normalise.parse_period`, `readers.read_master_sheet`).
4. ✅ **DONE** Join + blank-Remark labelling rule (single documented function `join.apply_blank_remark_rule`).
5. ✅ **DONE** Identity registry from crew-data sheets (`readers.read_identity_registry`).
6. ✅ **DONE** Roster-link resolver → cached image path (vision split); skip+flag if missing (`build._resolve_cached_image`, reuses `engine.drive.extract_file_id`).
7. ✅ **DONE** Crew/month split assignment + manifest + data-quality report (`build._split_for`, `build.build_dataset`, `quality_report.py`).
8. ✅ **DONE** Write JSONL + manifest.json + quality_report.md (`scripts/build_ml_dataset.py`); unit + integration tests on AUGUST 2025 fixtures (`tests/ml/test_dataset.py`).

### Build findings (first run on `docs/example-files`)

- **5,745 text rows**, ~76 monthly sheets across the two form workbooks; the 2 `Form
  Responses` tabs are reported as unparsed, not dropped (AC-1).
- **Disposition column is not stably named:** in Posting Base the `จ่ายเงิน` decision
  lands in a column whose *header is a status-link URL* (the literal "Remark" column is
  usually blank); in Late Submission it lives in the second free-text note
  (`เพิ่มหมายเหตุ (ถ้ามี) 2`). `readers._harvest_admin_text` solves this by joining the
  trailing non-URL cells after the roster upload rather than chasing the header.
- **Disposition mixes action + reason:** a remark like "รอแก้ไข และทำจ่ายตกเบิก |
  ไม่มีวันที่ด้านล่างซ้ายมือ" is a *defer* with an *R4* reason. `classify_disposition`
  scans two ordered tables (`ACTION_RULES`, `REASON_RULES`) so disposition and rule_hint
  don't collapse. AUG-2025 distribution: APPROVED 92, REJECTED R4 9, R8 6, DEFER 5, …
- **Master coverage is partial:** only ~43 of the CCD master's monthly sheets hold real
  crew rows (the rest are `#N/A` template sheets). So `unmatched_master` is high and is
  surfaced in the quality report as the join-gap signal (per the error scenario), while
  the gold disposition label still comes from the abundant admin-remark text.

## 🏗 Structure

```
backend/ml/dataset/                # NOT in perdiem/engine — pure data prep
├── readers.py        # workbook + sheet-name parsing
├── normalise.py      # months, day-lists, disposition→class, remark→rule map
├── join.py           # form ⨝ master, blank-Remark rule
├── build.py          # orchestrates → TextRow/VisionRow, splits, manifest
└── quality_report.py
scripts/build_ml_dataset.py        # CLI entry → data/ml/datasets/<version>/
backend/tests/ml/test_dataset.py
```

## 📌 Notes / Open Questions

- **Confirm the blank-Remark = approved rule** with the admins (decision gate in overview).
- Image labels in `VisionRow.fields` are **weak/derived** (identity from approved form,
  grid bootstrapped then corrected against master `Period`) — record `label_source` so
  PD-ML-006 can weight them.
- Historical roster images are the scarce part; expect the vision split ≪ the text split.
