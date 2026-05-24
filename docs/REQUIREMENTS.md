# Cabin Crew Per Diem Validation System — Requirements

## 1. Purpose

Cabin crew at AirAsia (DMK base) claim **per diem / sector allowance** for
"posting" duty (flying away from home base and staying overnight). Today the
admin team validates each claim by hand: open the Google Form response, open the
attached roster screenshot, read the flight schedule, check the dates, remove
duplicates, and copy the valid result into a master report.

This system **automates the analysis and validation** of those claims so the
admin only reviews exceptions instead of every submission.

The output of the system is a per-month, per-crew list of **valid, de-duplicated
per diem days and the amount payable**, in the same shape as the existing master
report (`Posting Perdiem of CCD 2026.xlsx`).

---

## 2. Glossary

| Term | Meaning |
|------|---------|
| Per diem / Sector allowance | Daily allowance paid when crew is posted away from base overnight. Rate observed in data: **400 THB / day** (e.g. a 2-day trip = 800 THB). |
| Roster / Schedule report | "Personal Crew Schedule Report" PDF/image the crew downloads from the internal crew system and attaches to the form as proof. |
| Posting trip | An out-and-back away from base: outbound **DMK → HKT** on day _N_, overnight at HKT, return **HKT → DMK** on day _N+1_. One trip = 2 claimable days. |
| Generated date | The "Generated on …" timestamp printed at the bottom of the roster. Proves when the roster snapshot was produced. |
| Posting Base form | Google Form for **on-time** claims for the current cycle. |
| Late Submission form | Google Form for claims submitted **after** the normal cutoff (back-claims for prior months). |
| Claim cycle | Per diem is reconciled one month in arrears: while working in **March**, crew clarify/claim for **February**. |

---

## 3. Actors

- **Cabin crew (submitter):** fills the Google Form, attaches their roster image.
- **Admin / validator (system user):** operates the system through the **web
  frontend** — triggers a cycle run, watches progress, reviews flagged claims,
  approves/overrides, and publishes/downloads the result report.
- **System service account:** Google account
  `kantaphajasuwan@airasia.com` — the account authorised to read the form
  response sheets and the Google Drive roster attachments.

> The system is delivered as a **web application self-hosted on the Raspberry
> Pi** (see §6.6 and the implementation plan). Staff use a browser; no CLI
> knowledge required. The CLI/batch run remains available underneath for
> automation.

---

## 4. Data Sources (example files in `docs/example-files/`)

### 4.1 Posting Base form responses — `Posting Base Perdiem & Sector Allowance (Responses).xlsx`
On-time claims. One worksheet per month (`MARCH 26`, `FEBRUARY 26`, …) plus the
raw `Form Responses 26` sheet. Columns:

| # | Column (raw, Thai where applicable) | Meaning |
|---|--------------------------------------|---------|
| 1 | Timestamp | Form submission datetime |
| 2 | Email Address | Submitter email |
| 3 | เงื่อนไขการเบิก | Claim condition (admin note) |
| 4 | Name - Surname | Crew name |
| 5 | Employee Code | **Staff ID** (e.g. `1043862`) |
| 6 | Position | Cabin Crew / Senior Cabin Crew |
| 7 | Permanent at Base | Home base (DMK) |
| 8 | เลือกประเภทการเบิกเงิน | Claim type (Posting Base / Layover / Irregularity of Sector Allowance) |
| 9 | เดือนที่จะเบิก … | Month being claimed (e.g. `MARCH 2026`) |
| 10 | ช่วงวันที่เบิก … | **Claimed day list** within the month, e.g. `วันที่ 2, วันที่ 3` (= the 2nd, 3rd) |
| 11 | รวมจำนวนวันที่ไป Posting | Crew-stated total posting days |
| 12 | กรุณาแนบตารางบิน (Roster) | **Google Drive link(s)** to roster image(s); may contain multiple comma-separated links |
| 13 | เพิ่มหมายเหตุ | Crew remark (optional) |
| 14 | (status link) | Link to status-tracking sheet |
| 15 | Remark | Admin decision note (e.g. `จ่ายเงิน` = paid) |

### 4.2 Late Submission form responses — `Late Submission Perdiem & Irregularity of Sector Allowance (Responses).xlsx`
Back-claims for earlier months; must also be folded into the cycle being
reconciled. One worksheet per month + raw `Form Responses 80`. Columns mirror
4.1 with: `Operating Base`, `กรุณาเลือกประเภทการเบิกที่ล่าช้ากว่ากำหนด` (late
claim type), `กรุณาระบุเดือนที่ทำการเบิกล่าช้า` (late month), claimed day list,
roster/medical-certificate attachment link, `Status`, `Remark`.

### 4.3 Master result report — `Posting Perdiem of CCD 2026.xlsx`
The **output**: the cleaned, validated, payable list. One worksheet per month
(`MARCH 26`, `FEBRUARY 26`, …). Header row + columns:

| Column | Meaning |
|--------|---------|
| Item | Row number |
| New ID No. | Staff ID |
| Employee name | Crew name |
| Period | Validated date range(s), one per line, e.g. `1 March 2026 - 2 March 2026` (multiple ranges separated by newline) |
| Days | Total validated days |
| Total Perdiem (THB) | `Days × 400` |
| Email Address | Crew email |
| Cross Checked by Supervisor | `CHECKED (OK)` etc. |
| REMARK | Notes (e.g. `ตกเบิกเดือนมกราคม` = back-claim for January) |

Each sheet carries a status banner: `Last updated : … (Status : OPEN | CLOSED)`.

### 4.4 Roster image — `IMG_4481 - Rattanaporn Boonin (correct format).jpeg`
"Personal Crew Schedule Report". Reference layout the OCR must handle:

- **Header band:** `01/03/2026 - 31/03/2026 (All times in Local Station)` — the
  report **date range** (full month).
- **Crew line:** `1009759 RATTANAPORN, BOONIN  DMK, CC, FD…` — **staff ID**,
  **name**, base, rank.
- **Calendar grid:** one column per day. Each day cell = report time, then one or
  more flight legs `FD#### ORIG DEST <time> [aircraft]`, then duty-end time.
  Example claimed pair (red-circled): **27/03 `FD3012 DMK HKT`** and
  **28/03 `FD3006 HKT DMK`**.
- **Red annotation:** the crew draws a **red rectangle/oval** around the day
  column(s) they are claiming.
- **Footer:** `Generated on  Mar 09, 2026 19:36` — the **generated date**.

> Image quality varies (phone photos, rotation, glare, compression). OCR must be
> robust and must flag low-confidence extractions for manual review rather than
> silently guessing.

---

## 5. Per Diem Eligibility Rules

A claimed day is payable **only** when all of the following hold.

### R1 — Qualifying route
Only the **DMK ↔ HKT** posting counts.
- Outbound: **DMK → HKT**
- Return: **HKT → DMK**

No other route (DMK→DAD, DMK→DPS, DMK→SIN, etc.) qualifies, even if the crew
flew it.

### R2 — Qualifying flight numbers (rotating set)
The leg must use one of the recognised flight numbers. The set rotates month to
month, so it must be **configurable**, not hard-coded. Known values:

- **DMK → HKT:** `FD3013`, `FD3015`
- **HKT → DMK:** `FD3026`, `FD3006`, `FD3038`, `FD3084`

### R3 — Out-and-back pairing across consecutive days
A valid posting is an **outbound DMK→HKT on day _N_ paired with a return
HKT→DMK on day _N+1_**. When an outbound DMK→HKT is found, the system must
**automatically look at the next day** for the matching return.
- A matched pair yields **2 payable days** (day _N_ and day _N+1_).
- An outbound with no next-day return (or vice versa) is **incomplete** → flag,
  do not auto-pay.

### R4 — Roster proves the claim (generated-date check)
The roster's **Generated date must be later than the claimed per diem date(s)**
— i.e. the snapshot was produced after the flight, so it reflects flown (not
merely scheduled) duty. Each red-marked / claimed day must be **earlier than**
the generated date. Days on/after the generated date → flag as unproven.

### R5 — Document identity match
The roster must belong to the submitter:
- roster **staff ID == form Employee Code** (primary, exact key), and
- roster **name** matches form **Name-Surname** under **fuzzy / partial-name
  matching** (see R5a).

Mismatch on staff ID → reject. Name mismatch when staff ID matches → flag for
review (don't hard-reject on name alone, since staff ID is the strong key).

### R5a — Name normalisation & matching
Names are entered inconsistently across the form and the roster and must be
compared after normalisation, **not** by exact string equality. Handle at least:

- **Abbreviated / initial surname:** the form or roster may carry only a surname
  initial, e.g. form `Lucksnara S.` vs. full `Lucksnara Sothiratviroj`. Match
  when the **first name matches and the surname initial is consistent** (the
  shorter surname is a prefix of, or the initial of, the longer one).
- **Trailing whitespace / double spaces** (common in the sample data).
- **Case** differences (`chadchaya sinloy` vs `Chadchaya Sinloy`).
- **Diacritics / Thai⇄English transliteration** variance.
- **First/last order** swaps.

Recommended approach: normalise (trim, collapse spaces, lowercase, strip
punctuation), then match on first name + surname-prefix/initial; fall back to a
fuzzy similarity score with a tunable threshold. Resolve ambiguity using the
staff ID, which is authoritative.

### R6 — Period coverage
The roster's header **date range must cover** every claimed day, and the claimed
days (form field 4.1 col 10 / red rectangle) must fall inside that range.

### R7 — Uniqueness / de-duplication
Crew may submit the **same claim multiple times** (re-submissions, corrections,
once in Posting Base + once in Late Submission). Per diem must be counted **once
per unique `(staff ID, calendar date)`**. Duplicate days across any/all
submissions collapse to a single payable day.

### R8 — Correct-month routing
- Claims whose flown month ≠ the cycle month are **back-claims** → route to the
  Late Submission flow and tag the result `REMARK` accordingly (e.g.
  `ตกเบิกเดือนมกราคม`).
- The Late Submission responses for the cycle must be merged with Posting Base
  responses before de-duplication (R7).

---

## 6. Functional Requirements

### 6.1 Ingestion
- **F1.** Authenticate to Google as `kantaphajasuwan@airasia.com` and read both
  form-response workbooks (Posting Base + Late Submission) for the target month.
- **F2.** For each response, parse: timestamp, email, staff ID, name, position,
  base, claim type, claim month, claimed day list, roster link(s), remarks.
- **F3.** Download every roster attachment from the Drive link(s); support
  multiple links per response. Handle JPEG/PNG/PDF.

### 6.2 Roster extraction (OCR)
- **F4.** Extract from each roster: report **date range**, **staff ID**, **name**,
  **generated date**, and the **flight grid** (per day: flight number, origin,
  destination, time).
- **F5.** Detect the **red rectangle/oval annotation** and map it to the day
  column(s) the crew is claiming.
- **F6.** Emit a **confidence score** per extracted field; route low-confidence
  rosters to manual review.

### 6.3 Validation engine
- **F7.** Apply rules **R1–R8** to each claim and produce, per claimed day, a
  verdict: `VALID`, `INVALID(reason)`, or `NEEDS_REVIEW(reason)`.
- **F8.** Auto-pair outbound/return legs across consecutive days (R3), including
  pairs that straddle a month boundary (e.g. 31 Jan → 1 Feb).
- **F9.** De-duplicate across all submissions for the month (R7) and reconcile
  the crew-stated day list against the roster-proven days, flagging mismatches.

### 6.4 Output
- **F10.** Produce a per-month, per-crew result: validated `Period` range(s),
  `Days`, `Total Perdiem = Days × rate`, email, and a `REMARK` for exceptions
  (back-claim month, partial pair, etc.).
- **F11.** Write/append into the master report shape (§4.3) — one worksheet per
  month — without disturbing historical sheets.
- **F12.** Produce an **exception report** listing every claim that was rejected
  or needs review, with the specific failing rule, so the admin can act.

### 6.5 Configuration
- **F13.** Qualifying routes, flight-number set (R2), per diem rate, and the
  cycle month must all be **configurable** (the flight numbers rotate monthly).
  The frontend exposes these settings so staff can update the monthly flight
  numbers without editing files.

### 6.6 Web frontend (staff-facing)
The system is operated through a **self-hosted web application** so staff run the
whole per diem process from a browser — no command line.

- **F14. Authentication:** staff sign in before use (the app handles sensitive
  PII). Support a simple login; Google sign-in restricted to allowed AirAsia
  accounts is acceptable.
- **F15. Trigger a run:** a screen to **select the cycle month and start a run**;
  the heavy work (download + OCR + validate) runs as a **background job** so the
  page never blocks.
- **F16. Live progress:** show run status and progress (queued → downloading →
  OCR → validating → done), with counts of processed / VALID / review / reject.
- **F17. Results dashboard:** per-crew validated results (Period, Days, Total
  Perdiem) for the selected month, with totals.
- **F18. Exception review queue:** list every `NEEDS_REVIEW` / `INVALID` claim
  with the **roster image preview**, the extracted fields, the **failing rule**,
  and OCR confidence — so staff can judge quickly (supports N3).
- **F19. Approve / override:** staff can approve, reject, or correct a flagged
  claim from the UI; the decision is recorded (who, when, why) and the result
  re-aggregates (idempotent, N2).
- **F20. Publish / download:** export or download the master report sheet (§4.3)
  and the exception report for the month.
- **F21. Config screen:** view/edit qualifying routes, the rotating flight-number
  set, per diem rate, and thresholds (F13) from the UI.
- **F22. Audit view:** browse the per-decision audit trail (rule applied, source
  response, roster reference, confidence, any manual override) — see N1.

---

## 7. Non-Functional Requirements

- **N1. Auditability:** every payable/rejected decision must record which rule
  produced it and link back to the source response + roster image.
- **N2. Idempotency / re-runnable:** re-processing a month must not double-count
  or create duplicate result rows.
- **N3. Human-in-the-loop:** the system assists; it never silently overrides.
  Anything uncertain is surfaced, not assumed.
- **N4. Bilingual data:** form fields, remarks, and names are mixed Thai/English;
  parsing, matching, and output must handle both.
- **N5. Security:** Google credentials handled via the service account only;
  roster images may contain PII (names, staff IDs) and must be stored/handled
  accordingly.
- **N6. OCR resilience:** tolerate rotation, low resolution, glare, and JPEG
  artefacts; degrade to manual review rather than wrong answers.
- **N7. Usability:** the frontend must let a non-technical staff member run a
  full cycle and review exceptions without using the command line.
- **N8. Self-hosted & zero-cost:** the entire web app runs on the user's
  Raspberry Pi using free/open-source components; no paid hosting or services.
  Long work runs as background jobs sized for the Pi.

---

## 8. End-to-End Flow (target month = March, reconciling February claims)

Staff drive the whole flow from the **web frontend**:

1. Staff sign in and **select the cycle month**, then click **Run** (F14–F15).
2. A background job reads Posting Base + Late Submission responses for that cycle.
3. For each response: download roster image(s).
4. OCR each roster → date range, staff ID, name, generated date, flight grid,
   red-marked days.
5. Validate identity (R5), period coverage (R6), route + flight number (R1/R2),
   out-and-back pairing (R3), generated-date proof (R4), month routing (R8).
6. Merge all responses; de-duplicate by `(staff ID, date)` (R7).
7. Compute `Days` and `Total Perdiem (THB)` per crew.
8. The frontend shows **live progress**, then the **results dashboard** and the
   **exception review queue** (F16–F18).
9. Staff review flagged claims, approve/override/correct (F19); results
   re-aggregate idempotently.
10. Staff **publish/download** the master report sheet and exception report
    (F20). The master sheet is written without disturbing historical sheets.

---

## 9. Open Questions / To Confirm

1. **Per diem rate** — confirmed as **400 THB/day** from sample data. Is it fixed
   or rank/route dependent?
2. **Generated-date direction (R4)** — the sample file labelled "(correct
   format)" has a generated date (09 Mar) *earlier* than its red-marked days
   (27–28 Mar). Confirm the intended comparison: should the generated date be
   **after** all claimed dates (proof of flown duty), and was this sample chosen
   only to illustrate layout rather than a passing case?
3. **Red-annotation reliability** — is the red rectangle always present, or
   should the form's claimed-day list (col 10) be the primary source with the
   rectangle as a cross-check?
4. **Other claim types** — `Layover allowance` and `Irregularity of Sector
   Allowance` appear in the data. Do they follow the same DMK↔HKT rules, or
   separate eligibility?
5. **Multi-leg days** — some days show several legs (e.g. DMK-HKT then HKT-DMK
   then DMK-SIN). Confirm only the DMK↔HKT legs are considered and other legs are
   ignored, not disqualifying.
6. **Flight-number source of truth** — should the rotating monthly set be
   maintained manually, or fetched from an authoritative schedule?
7. **Internal crew system access** — is roster retrieval always via the Drive
   attachment, or should the system pull rosters directly from the crew system?
