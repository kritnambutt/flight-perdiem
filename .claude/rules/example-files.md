# Example Files Reference

Ground-truth fixtures for OCR, validation rule, and integration tests.
All live under `docs/example-files/`.

## Root-level files

| File | Purpose |
|------|---------|
| `Posting Base Perdiem & Sector Allowance (Responses).xlsx` | On-time (Posting Base) Google Form response workbook — real submissions for the current claim month. Use as fixture for **F1/Ingestion** (story-001). |
| `Late Submission Perdiem & Irregularity of Sector Allowance (Responses).xlsx` | Back-claim (Late Submission) Google Form response workbook. Use as fixture for **F2/Ingestion** (story-001). |
| `Posting Perdiem of CCD 2026.xlsx` | CCD payroll/master reference workbook — used to look up staff IDs and validate identities (R5/R5a). |
| `IMG_4481 - Rattanaporn Boonin (correct format).jpeg` | Single correct roster image at the root — used as a quick smoke-test fixture. |

## `roster-attached-files/` — file naming convention

```
<original-filename> - <Staff Name> - <issue note or blank>.ext
```

- **Staff Name** is the crew member's display name as it appears on the roster.
- **Issue note** is blank for correct files; describes the failure reason for incorrect files.

## `roster-attached-files/correct/`

Valid rosters that the OCR + validation pipeline should fully accept.
All four files exercise different image formats (jpg/jpeg/png) and
different screen-capture sources (camera, screenshot).

| File | Staff | Notes |
|------|-------|-------|
| `1775130932681 - Kanatsanan Wichitthararak -.jpg` | Kanatsanan Wichitthararak | Numeric filename (Google Drive ID style) |
| `IMG_2398 - Sawaros Phanichvibul -.jpeg` | Sawaros Phanichvibul | iOS camera filename |
| `IMG_3711 - Kantachet Boonserm -.png` | Kantachet Boonserm | PNG screenshot |
| `Screenshot_20260505_153747_Chrome - Chanicha Songkrit -.jpg` | Chanicha Songkrit | Android Chrome screenshot |

Expected outcome: all fields extracted with high confidence; every claimed day
in the red-boxed range passes eligibility rules.

## `roster-attached-files/incorrect/`

Invalid rosters that the pipeline must reject or flag for review.
Each file targets a specific rule or failure mode.

| File | Staff | Failure mode | Rule / story |
|------|-------|-------------|-------------|
| `IMG_5771 - Minthita Kanchanapinpong - invalid formatted.jpeg` | Minthita Kanchanapinpong | Roster image is not a recognisable crew-schedule report (wrong document, unreadable layout, or missing required fields). | OCR confidence < threshold → `NEEDS_REVIEW` |
| `8B5BFFAC-55B1-412D-B081-F8504668DB93 - Raveekankate Sukasemthongdi - invalid formatted.png` | Raveekankate Sukasemthongdi | Same as above — invalid/unreadable format. Second example with a different staff member. | OCR confidence < threshold → `NEEDS_REVIEW` |
| `Screenshot_20260206_141407_Chrome - Chanicha Songkrit - invalid formatted.jpg` | Chanicha Songkrit | Same staff as the correct example above — intentional pair to test that the same person's **bad** roster is caught. | OCR/format validation |
| `IMG_5475 - Tanaporn Musikapun - submit current but attached roster perdiem late.png` | Tanaporn Musikapun | Submitted via the **on-time (Posting Base)** form but the attached roster covers the **previous month** (a late/back-claim period). Mismatch between submission form and roster period. | R8 / month-routing rule |
| `Re Aug25 - Raveekankate Sukasemthongdi - generated date less than range date.pdf` | Raveekankate Sukasemthongdi | Roster **generated date** is earlier than the roster date range — proof-of-print cannot precede the schedule it prints. | R2 / generated-date rule |

Expected outcome for all incorrect files: verdict `INVALID` or `NEEDS_REVIEW`
with the correct `rule` tag and a human-readable `reason`.

## How to use these fixtures in tests

```python
FIXTURES = Path("docs/example-files")
CORRECT  = FIXTURES / "roster-attached-files" / "correct"
INCORRECT = FIXTURES / "roster-attached-files" / "incorrect"

# Engine unit tests — no DB needed, just file paths
def test_valid_roster_accepted():
    img = CORRECT / "IMG_3711 - Kantachet Boonserm -.png"
    result = extract_roster(img)
    assert result.confidence >= CONFIDENCE_THRESHOLD

def test_generated_date_rule_rejected():
    pdf = INCORRECT / "Re Aug25 - Raveekankate Sukasemthongdi - generated date less than range date.pdf"
    verdict = validate_claim(build_claim(pdf))
    assert verdict.status == "INVALID"
    assert verdict.rule == "R2"
```

- Engine tests must run with **no DB or network** — only these local files.
- Add new fixtures here as new edge-cases are discovered; update this table.
