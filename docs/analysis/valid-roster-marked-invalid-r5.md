# Valid-Looking Roster Marked INVALID — R5 Identity vs. OCR Misread

**Date:** 2026-05-25
**Status:** Diagnosed — fix proposed, not yet applied
**Symptom:** A roster that, to a human, is clearly valid — generated **11 Aug**, showing
**DMK→HKT and HKT→DMK on 06–07 Aug** — is marked **INVALID** by the pipeline. The user asked
whether this is an image-quality problem.

---

## Short Answer

It is **not** about the flights or the dates. The claim was hard-rejected by **R5 (identity)**
because the staff ID the OCR read **off the roster** did not match the staff ID on the **form**.
OCR quality is the upstream trigger, but the decisive problem is a **rule bug**: `check_identity`
treats a *low-confidence* OCR staff ID as authoritative and hard-rejects on mismatch, instead of
sending an uncertain read to review.

---

## Investigation

### 1. What the verdicts actually say

For the completed `AUGUST 2025` run (`c43c204b…`), the INVALID verdicts break down as:

```
INVALID by rule:   R5 = 92,  R6 = 1
NEEDS_REVIEW:      R1 = 163, R4 = 49, R6 = 15

Sample INVALID reasons:
  [R5] staff ID mismatch: form='1040506' roster='1006428'
  [R5] staff ID mismatch: form='1038746' roster='1023582'
  [R5] staff ID mismatch: form='1001233' roster='1004957'
```

**92 of 93 INVALIDs are R5 staff-ID mismatches.** Not R1 (route), not R3 (pairing), not R2
(generated date). The flights and dates were never the reason.

### 2. The identity rule hard-rejects on mismatch — ignoring confidence

`engine/identity.py::check_identity`:

```python
roster_id = (roster.staff_id.value or "").strip()
...
if form_id != roster_id:
    return IdentityResult(decision="REJECT", reason=f"staff ID mismatch: form={form_id!r} roster={roster_id!r}")
```

The comparison uses `roster.staff_id.value` (the OCR result) but **never looks at
`roster.staff_id.confidence`**. Any mismatch → `REJECT` → `INVALID`, even when the OCR was unsure.

### 3. OCR reads staff IDs unreliably (live evidence)

Running `extract_roster` on five cached rosters from this run:

| Roster | staff_id read | confidence | name | flight grid |
|--------|---------------|-----------|------|-------------|
| #1 | `1420231` | **0.60** | – | 0 days ("no flights detected") |
| #2 | `1044229` | 0.90 | NAPAPORN, PANSANDAENG | 10 days ✓ |
| #3 | `1004569` | 0.80 | CHUTIKUL, KHRUAKHAM | 0 days |
| #4 | `1006629` | **0.60** | – | 7 days |
| #5 | `1110210` | **0.60** | – | 0 days |

Only **1 of 5** extracted cleanly. Staff IDs are routinely read at **0.60 confidence** (the engine's
own floor), and the flight grid is frequently not detected at all. A 0.60-confidence number is, by the
engine's own standard, "uncertain" — yet R5 treats it as gospel and hard-rejects.

### 4. Why the magnitude looks wrong

`form='1040506' roster='1006428'` differ in several digits — too many for a one-character slip. That
points to the extractor **locating the wrong token** on the page (grabbing a different number — e.g.
from an adjacent label or the wrong line) rather than a clean digit misread. Either way it is an OCR
**extraction** failure, not a real identity conflict.

---

## Root Cause

1. **Primary (rule bug):** `check_identity` rejects on `form_id != roster_id` **without gating on
   `roster.staff_id.confidence`**. A low-confidence / mis-located OCR read of the roster's staff ID
   becomes a hard INVALID. This contradicts the project principle *"anything uncertain is surfaced for
   review, never silently guessed"* (N1, objective.md) — here an uncertain read silently **rejects**.

2. **Upstream (OCR quality):** staff-ID extraction is unreliable (often 0.60 confidence) and the flight
   grid often isn't detected (`grid_days=0`). This is what produces the wrong/low-confidence IDs in the
   first place, and also why even identity-matching claims fall to NEEDS_REVIEW on R1/R3/R4.

3. **Visibility gap:** `repository.write_verdicts` persists `extracted=None`
   (`db/repository.py:147`), so the Exceptions "OCR fields" panel is always blank. A reviewer can't see
   *what* the OCR read (e.g. `roster staff_id=1006428 @0.60`), making these false rejects hard to
   understand from the UI.

So for the user's specific roster: the crew, flights (DMK↔HKT 06–07 Aug) and generated date (11 Aug)
are all fine. OCR misread the **staff-ID number** at low confidence, and R5 hard-rejected on the
mismatch.

---

## Recommended Fix (not yet applied — touches engine validation semantics)

1. **Gate R5 rejection on confidence.** In `check_identity`, only `REJECT` on a mismatch when the
   roster staff ID was read with **high confidence** (≥ `cfg.ocr_confidence_threshold`). When the
   extracted ID is below threshold (or empty), return `REVIEW` with a reason like
   *"staff ID unreadable / low confidence — verify against roster"*. A confident, genuine mismatch
   (wrong person) still hard-rejects.

   ```python
   if form_id != roster_id:
       if roster.staff_id.confidence < cfg.ocr_confidence_threshold:
           return IdentityResult(decision="REVIEW",
               reason=f"staff ID uncertain (OCR {roster.staff_id.confidence:.2f}): "
                      f"form={form_id!r} roster={roster_id!r}")
       return IdentityResult(decision="REJECT", reason=...)  # confident mismatch
   ```

2. **Persist `extracted`.** Store the OCR fields (at least staff_id/name/dates + confidences) on the
   verdict so reviewers can see the read in the Exceptions panel and the false-reject is self-evident.

3. **Improve grid/staff-ID extraction (longer term).** The "no flights detected" rate is high; the
   grid detector and the staff-ID field locator need tuning. Wiring red-box detection (still absent in
   the worker) will also let the crew's red-boxed days drive validation instead of the form list.

Items (1) and (2) would turn most of these 92 false INVALIDs into NEEDS_REVIEW with visible OCR
context — correct per the human-in-the-loop design — without weakening genuine wrong-person rejection.

---

## Key Takeaway

INVALID here means **"OCR-read roster staff ID ≠ form staff ID"**, not "bad flights." The engine is
hard-rejecting on an unreliable OCR value it should be treating as uncertain. Confidence-gate R5 (and
persist the extracted fields) so low-confidence reads go to review, where a human can confirm the
obviously-valid roster.
