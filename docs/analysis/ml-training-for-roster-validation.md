# ML Training for Roster Validation — Where It Helps and How to Build It

**Date:** 2026-05-25
**Status:** Analysis / proposal (no code changed)
**Question (from the user):** Validation doesn't work reliably. Rosters are attached
as PDFs/images of wildly varying quality (small, large, poor) and format. We already
have validation *history* (verdicts + human decisions) and a master reference workbook
(`Posting Perdiem of CCD 2026.xlsx`). **How do we implement ML training to fix this?**

---

## TL;DR

1. **The validation rules (R1–R8) are not the thing that's broken.** The forensic
   analysis of a real run ([valid-roster-marked-invalid-r5.md](valid-roster-marked-invalid-r5.md))
   shows **92 of 93 INVALIDs were R5 staff-ID mismatches caused by OCR misreads**, and
   most NEEDS_REVIEW were R1/R4 caused by the **flight grid not being detected at all**.
   The bottleneck is **roster field extraction from images**, i.e. a *document-AI / computer-vision*
   problem — not the rule predicates.

2. **So "ML training" should mean: replace the brittle Tesseract-regex extractor with a
   learned roster reader**, plus a small object detector for the red box, plus (optionally)
   a triage model that learns from your human-override history what to auto-pass vs. send
   to review. The rules stay as the deterministic, auditable layer on top.

3. **Your labelled dataset already exists** — in the **three response workbooks**: the
   Posting Base/Late forms carry the admin's per-submission decision and rejection reasons,
   and `Posting Perdiem of CCD 2026.xlsx` is the approved-payable answer key, across **~75
   monthly sheets back to 2018** (thousands of rows). The DB `overrides`/`verdicts` are a
   *minor* future source by comparison. The single most important first step is
   **assembling/normalising this history**, not model selection.

4. **Sequence it correctly.** ML extraction is the right long-term lever, but it needs
   labelled data you don't yet have packaged. Ship the cheap deterministic fixes first
   (they raise the floor *and* generate clean labels for free), accumulate labels, then
   train. Don't start with a 2B-param vision-LLM on a Raspberry Pi.

This document is the map for that.

---

## 1. Reframing: what is actually failing

| Pipeline stage | File | Failure mode today | Is this an ML problem? |
|---|---|---|---|
| Download roster | `engine/drive.py` | slow, serial | No — engineering ([run-pipeline-performance.md](run-pipeline-performance.md)) |
| Preprocess image | `engine/ocr/preprocess.py` | one fixed orient→upscale→denoise→binarise recipe for every image, regardless of quality | **Partly** — quality-adaptive preprocessing helps; learned binarisation is overkill |
| Read header fields (staff ID, name, date range, generated date) | `engine/ocr/extract.py` (`_extract_crew_line`, `_extract_date_range`, …) | regex over Tesseract text; staff ID routinely read at **0.60 conf** or **wrong token located**; name often blank | **Yes — core ML target** |
| Read the flight grid (day → legs) | `engine/ocr/extract.py` (`_extract_grid_from_words`) | tiny cells often **not detected at all** → "no flights" → R1 NEEDS_REVIEW | **Yes — core ML target** |
| Detect the red claimed-days box | `engine/ocr/redbox.py` | HSV heuristic; not wired into the worker | **Low — red box is OPTIONAL**; the form's claimed-days column is authoritative. Keep as cross-check only |
| Is this even a valid roster doc? | (none) | no classifier; invalid/garbage images fall through as low-confidence noise | **Yes — easy classifier win** |
| Rules R1–R8, pairing, dedup | `engine/rules.py`, `pairing.py`, `dedup.py` | mostly correct; R5 has a confidence-gating **bug** (separate fix) | **No — keep deterministic + auditable (N1)** |

**Conclusion:** ML effort should be concentrated on *turning a roster image into a clean
structured record* (`ExtractedRoster` in `engine/models.py`). Everything downstream already
works once the inputs are trustworthy.

> ⚠️ **Do the R5 confidence-gate fix regardless** (see the other analysis doc). It is a
> one-line rule change that converts dozens of false INVALIDs into reviewable items and
> is independent of any ML work.

---

## 2. What ML can buy you — three workstreams

Ranked by impact-per-effort.

### WS-1 — Roster reader (image → structured fields)  ★ highest impact
Replace `_extract_crew_line` / `_extract_date_range` / `_extract_generated_date` /
`_extract_grid_*` with a model that takes the roster page and emits the same JSON the
`ExtractedRoster` dataclass expects:

```json
{
  "staff_id": "1044229",
  "name": "NAPAPORN PANSANDAENG",
  "start_date": "2026-08-01", "end_date": "2026-08-31",
  "generated_at": "2026-08-11T19:36",
  "grid": { "6": [{"flight_no":"FD3012","orig":"DMK","dest":"HKT","time":"A17:00"}], "7": [...] }
}
```

This is the **decisive** workstream — it directly attacks the 92 R5 misreads and the
"no flights detected" R1/R4 reviews.

### WS-2 — Region detector (red box is **optional**)  ★ low / secondary
The red annotation the crew draws is **optional** — many submissions don't have one, and
the **authoritative source of claimed days is the form's claimed-days column**
(`ช่วงวันที่เบิก…` → e.g. `"วันที่ 2, วันที่ 3"`), already parsed by ingestion. The red box
is, at most, a **cross-check signal** when present. So treat red-box detection as a
nice-to-have, not a dependency, and do **not** build a training pipeline around it.

What *is* worth a small detector here is **region proposal** — localising the header block
and the grid block so WS-1 can crop its inputs (reading two small crops is far more robust
than reading a whole noisy page). If WS-1 is done with an OCR-free model (Donut) that reads
the whole page anyway, even this is optional. Net: keep the existing OpenCV red-box
heuristic as-is for the cross-check, and only add region detection if WS-1 needs the crops.

### WS-3 — Decision-triage + rejection-reason model  ★ most data-rich; do-able now
Two related classifiers trained on the **multi-year admin-decision history** that already
lives in the response workbooks (see §3 — this is the richest, most immediately usable
label source you have):

- **Triage:** given a claim's features + rule outputs, predict
  **`AUTO_PASS | AUTO_REJECT | SEND_TO_REVIEW`**, learned from the admin's per-submission
  disposition column (`จ่ายเงิน` paid / `ไม่จ่ายเงิน` rejected / `รอแก้ไข` defer-and-back-claim).
- **Rejection-reason:** when not approved, predict *why* — and the admins' own free-text
  remarks already map onto your rule taxonomy (e.g. `ไม่มีวันที่ด้านล่างซ้ายมือ` "no date
  bottom-left" → **R4** generated-date; `กรณีเบิกไม่ตรงเดือน` "claimed wrong month" → **R8**;
  `ลงข้อมูลซ้ำ` "duplicate entry" → **R7**; `ต้องแนบ full roster` → attach-full-roster).

Neither replaces the auditable rules — they *route* uncertain cases, shrink the review
queue, and (the reason model) give the reviewer a ranked "likely problem" hint. This is
the workstream that most directly consumes "the result validated by staff," and unlike
WS-1 it needs **no roster images** — only the spreadsheet text — so it has by far the most
training data available today.

---

## 3. The data you already have (your training set, hiding in plain sight)

> **Correction to an earlier assumption:** the richest labels are **not** in the database
> (`overrides`/`verdicts` only contain runs the *new* system has executed — likely little
> or nothing yet). They are in the **three response workbooks themselves**, which carry
> **~75+ monthly sheets going back to 2018** — on the order of **thousands of
> admin-validated submissions**. That is your real training corpus.

### 3.1 The actual schema (inspected from the AUGUST 2025 sheets)

**Posting Base (on-time) — `Posting Base … (Responses).xlsx`** (~100–120 rows/month sheet):

| Col | Field | Use |
|---|---|---|
| Timestamp, Email | submission metadata | provenance |
| `Name - Surname`, `Employee Code` | claimed identity | **identity label** (X for R5) |
| Position, `Permanent at Base` | role / base | feature |
| claim-type (`เลือกประเภทการเบิกเงิน`) | layover vs posting-base etc. | feature |
| month (`เดือนที่จะเบิก…`) | cycle month | R8 feature |
| **claimed days** (`ช่วงวันที่เบิก…` → `"วันที่ 2, วันที่ 3"`) | **authoritative claimed-day list** | the y-days to validate (NOT the red box) |
| total days (`รวมจำนวนวันที่ไป Posting`) | crew's own day count | cross-check |
| **roster link(s)** (`กรุณาแนบตารางบิน`) | Google Drive URL(s) | the **X image** for WS-1 |
| crew remark | free text | feature |
| **`Remark` (last col)** | **admin disposition** | **gold decision label (WS-3)** |

**Late Submission (back-claim) — `Late Submission … (Responses).xlsx`** (~15–20 rows/month):
same shape, plus the **late-claimed month** is free-text Thai/English
(`กรกฎาคม` / `July` / `JULY 2025`) → needs normalisation; the disposition lives in the
`remark2`/status columns (`จ่ายเงิน…`, `จ่ายรอบตกเบิกกันยายน`, `รอแก้ไข…`).

**Master report — `Posting Perdiem of CCD 2026.xlsx`** (one sheet per cycle, e.g. `AUG 2025`,
~80–100 rows): the **answer key for approved/paid claims**:

| Col | Field | Use |
|---|---|---|
| `New ID No.` | staff_id | **identity answer key** |
| `Employee name` | name | identity answer key |
| `Period` | approved date range(s), newline-separated multi-range | **approved payable days (end-to-end y)** |
| `Days`, `Total Perdiem (THB)` | count and amount (THB = days × 400; 2 days → 800 ✓) | reconciliation target |
| `Cross Checked by Supervisor` | almost always `CHECKED (OK)` | inclusion ⇒ approved |
| `REMARK` | Thai back-claim note (`ตกเบิกเดือนพฤษภาคม`) | R8 back-claim label |

Plus crew-registry sheets (`New Crew data`, `Crew Data`) — the standing `staff_id ↔ name`
master used for R5/R5a.

### 3.2 The admin disposition column = free decision labels

The Posting Base `Remark` column is the supervisor's per-submission decision. Real values
seen in JUNE 2025 (the cleanest sheet — 106 rows):

```
80  จ่ายเงิน                                   → APPROVED / paid
21  รอแก้ไข และทำจ่ายตกเบิกหลังจากที่เอกสารสมบูรณ์  → DEFER: fix, then pay as back-claim
 4  ไม่จ่ายเงิน                                  → REJECTED
 1  รอการตรวจสอบจากแอดมินอีกท่าน                   → SEND_TO_REVIEW (second admin)
```

And in other months the remark doubles as the **rejection reason**, which maps onto your
rule taxonomy almost 1:1 — i.e. the history *validates the rule set* and labels a
reason-classifier:

| Real remark (Thai) | Meaning | Rule |
|---|---|---|
| `ไม่มีวันที่ด้านล่างซ้ายมือ` | "no date at bottom-left" (generated date missing/unreadable) | **R4** |
| `กรณีเบิกไม่ตรงเดือน (เดือน ก.ค.)…` | "claimed in wrong month" | **R8** |
| `ลงข้อมูลซ้ำ` | "duplicate entry" | **R7** |
| `ต้องแนบ full roster` / `ต้องแนบ Full roster` | "must attach the full roster" | doc-completeness |
| `ตารางบินไม่อัพเดทจนถึงวันที่ขอเบิก` | "roster not updated through claimed date" | **R4/R6** |
| `กรณีเครื่อง AOG ลูกเรือต้องเบิกผ่านระบบ…` | "AOG case — claim via another system" | out-of-scope exception |

> **Labelling nuance to confirm with the admins:** on some month sheets only the *exception*
> rows are annotated and approved rows are left **blank**. Treat **blank Remark + present in
> the master report ⇒ APPROVED**; annotated ⇒ read the disposition/reason. Cross-referencing
> each form row against the master (was this crew paid that month?) disambiguates blanks.

### 3.3 Two label tiers, and the image-availability asymmetry

- **Text labels are abundant** (every monthly sheet, 2018→2026) → WS-3 (triage +
  rejection-reason) and identity reconciliation can train on **thousands** of rows **with
  no images at all**. This is why WS-3 is the most immediately trainable.
- **Roster images are the scarce input** — only rows whose Google Drive links still
  resolve (and only recent ones are cached at `data/cache/<file_id>.<ext>`). So WS-1's real
  training set is bounded by how many roster files you can actually fetch; **synthetic +
  augmented rosters (§3.5) matter most precisely here.**

### 3.4 Turning history into per-field labels for WS-1 (the key trick)

You rarely hand-type answers — you **derive** them by joining the three workbooks:

- **Identity (staff_id, name):** the form row carries the *claimed* identity; the master
  confirms the *approved* identity. For any approved claim, that identity is the correct
  content of the attached roster → label for the image (weak supervision: approval
  transfers the known-good identity onto the image).
- **Date-range / generated-date:** unambiguous on approved rosters; bootstrap with the
  current regex on the clean `correct/` set, hand-fix the rest. A few hundred suffices.
- **Grid (day → legs):** the expensive one. Bootstrap from the current extractor, then
  **correct only where it disagrees with the approved `Period`/`Days` in the master** — the
  master tells you which days *must* contain a qualifying DMK↔HKT pair, so you label exactly
  where the model is wrong (active learning).
- **Doc-type / quality:** `correct/` vs `incorrect/` folders + the rejected form rows give
  "valid roster vs not" labels.

> **Action:** build a one-off export script (`scripts/build_ml_dataset.py`, *outside* the
> pure engine) that, for every monthly sheet, joins **Posting Base ⨝ Late ⨝ master** on
> `(staff_id, cycle month)`, resolves each roster Drive link to a cached image where
> possible, and writes two versioned datasets:
> (a) **text/decision** rows (all history, no image needed) → `features, disposition,
> reason, approved_days`; and (b) **vision** rows (image-backed subset) → `image_path,
> fields.json`. Tag every row with `split (train/val/test)` and `label_source
> (admin_remark | master_reconciled | regex_bootstrap)` so gold admin labels outweigh
> bootstrapped ones. Normalise the messy Thai/English month + disposition free-text into a
> canonical taxonomy here (this is the bulk of the work, not the modelling).

### 3.5 The cheapest way to get *more* roster images: synthesise them
The roster is a **machine-printed, templated crew-schedule report** (consistent layout,
known fonts, fixed columns). That means you can **generate thousands of synthetic rosters**
with known ground truth and then apply realistic *degradations* to mimic the variable
quality you see in the wild:

- render the template with randomised staff IDs/names/flights/dates → perfect labels,
- then augment: downscale + re-upscale (small-image blur), JPEG recompression, perspective
  warp + glare (phone photo), Moiré/screenshot artefacts, rotation, partial crops.

Synthetic + augmented data is the standard fix for "format/quality varies a lot" and is
free. It is especially powerful for the **grid** (the hardest real-label task).

---

## 4. Model choices (with the Raspberry Pi 5 reality check)

**Hard constraints** (from `objective.md`): runs on **Pi 5 (arm64, no GPU)**, **zero
recurring cost**, **local & free**, and rosters are **PII** (names + schedules) — so
**no sending images to cloud OCR/LLM APIs**. That rules out the easy "just call GPT-4V"
path for production. Training can happen off-Pi (your laptop / a free Colab / a borrowed
GPU); **inference must be light** because it runs in the batch worker on the Pi.

| Approach | What it is | Training data need | Pi-5 inference | Verdict |
|---|---|---|---|---|
| **A. Fix deterministic pipeline first** (no ML) | Confidence-gate R5, drop redundant OCR pass, quality-adaptive preprocess, tune grid detector | none | fast | **Do this first** — raises the floor, generates labels |
| **B. Donut** (OCR-free image→JSON, `naver-clova-ix/donut`) | One model maps page→structured JSON; no separate OCR step | ~300–1000 labelled rosters (synthetic helps) | Slow-ish on CPU (~seconds/page) but **batch is fine**; quantise/ONNX | **Best long-term fit** for WS-1 — output *is* the schema |
| **C. LayoutLMv3 / fine-tuned token classifier** | Needs OCR words+boxes (keep Tesseract), classifies each token into field roles | similar; needs box-level labels | moderate | Good if you keep Tesseract; more labelling than Donut |
| **D. TrOCR** (line transformer) | Better text recognition for the *cells/header* where Tesseract fails | line-image→text pairs | moderate | Use as a **targeted** recogniser for hard regions, not whole-page |
| **E. Small object detector** (YOLOv8-n / RT-DETR / classical) for red box + regions | Localises red mark, header, grid | tens–hundreds of boxes | fast (nano models) | **Yes for WS-2** |
| **F. Tiny tabular classifier** (gradient-boosted trees / small MLP) for triage | Learns auto-pass/review from rule outputs + override history | your override rows | trivially fast | **Yes for WS-3** |
| **G. Local small VLM** (e.g. Qwen2-VL-2B via llama.cpp/ONNX) | Prompt-driven structured extraction, no training | none (zero-shot) or LoRA | **minutes/image on Pi CPU** — likely too slow for 137 claims | Prototype/oracle only, not Pi production |

**Recommended stack:**
- **WS-1:** **Donut fine-tuned** on synthetic+real rosters → emits the `ExtractedRoster`
  JSON directly. Fallback to the existing Tesseract path when the model's own confidence
  is low (never guess — N1).
- **WS-2:** **YOLOv8-nano** (or even the existing OpenCV HSV detector, improved) for the
  red box + a header/grid region proposal that crops inputs for Donut.
- **WS-3:** **LightGBM** triage classifier on rule features + override labels.

> A pragmatic interim: use a **local small VLM as a labelling oracle off-Pi** to
> pre-fill field JSON for human review — speeds up dataset creation a lot — while the
> *production* extractor stays the lightweight fine-tuned Donut/Tesseract on the Pi.

---

## 5. Training & evaluation setup

### Metrics that matter (per field, not one global accuracy)
- **staff_id:** exact-match accuracy (this is the one that caused the 92 false INVALIDs).
- **name:** normalised match rate (reuse `identity.normalize`) + fuzzy score distribution.
- **date_range / generated_date:** exact-match.
- **grid:** per-day leg precision/recall (did we find the DMK↔HKT pair on the right day?).
- **doc-type/quality classifier:** ROC-AUC; tune the threshold for "send to review".
- **End-to-end (the real KPI):** on a held-out month, **% of claims whose final payable
  days match the CCD master without human intervention**, and the **review-queue size**.
  Track machine-vs-human disagreement rate — that is the number the business feels.

### Splits & leakage
Split **by crew/month**, never by random day — the same roster's days must not straddle
train/test. Hold out at least one whole cycle month as the final test set.

### Train off-Pi, infer on-Pi
- Train on laptop/Colab; **export to ONNX and quantise (int8)**; run via `onnxruntime`
  (arm64 wheels exist) in the worker.
- Keep it a **batch** job — latency per image is fine; throughput is bounded by the
  existing `OCR_CONCURRENCY` process pool ([run-pipeline-performance.md](run-pipeline-performance.md)).
- Cache model outputs by `file_id` exactly like the proposed OCR cache (N2 idempotency).

---

## 6. Integration — keep the engine pure

`.claude/rules/backend-standards.md` is explicit: the engine is a **pure library**, and
`engine/ocr/` already isolates extraction. So ML slots in cleanly:

- Define an extractor **interface** that returns `ExtractedRoster` (the dataclass already
  exists in `engine/models.py`). Today's implementation is `extract_roster()`.
- Add `engine/ocr/ml_extract.py` as a **second backend** behind the same interface; the
  model file is a versioned asset loaded from a path in `config.py` (env-driven, like
  every other threshold — never hard-code).
- The worker picks the backend via config: `OCR_BACKEND=tesseract|donut|hybrid`. Hybrid =
  run ML, fall back to Tesseract when ML confidence < threshold; both still emit
  per-field `Field(value, confidence)` so the **R5 confidence gate and N1 auditability are
  preserved**. The rules, pairing, dedup, and reporting code do **not change**.
- **Engine stays free of torch/onnx at import time** — lazy-import inside `ml_extract.py`
  (the existing code already lazy-imports `pytesseract`/`cv2`), so engine unit tests run
  with no heavy ML deps.
- Training scripts, dataset builders, and notebooks live **outside** `perdiem/engine/`
  (e.g. `ml/` or `scripts/`) — they are not part of the pure library.

---

## 7. Phased roadmap

**Phase 0 — Stop the bleeding (no ML, ~days).**
Confidence-gate R5; persist `extracted` on verdicts so reviewers see what OCR read; drop
the redundant `image_to_string` pass; make denoise/OSD adaptive. *Outcome:* fewer false
INVALIDs **and** every run now logs clean field-level data you can mine for labels.

**Phase 1 — Dataset + eval harness (~1–2 weeks).**
Build `scripts/build_ml_dataset.py` (joins claims/verdicts/overrides + CCD master + cached
images). Define the held-out test month and the per-field metrics. Measure the *current*
extractor against it — that is your baseline. **No model training yet** — you can't improve
what you can't measure.

**Phase 2 — Easy ML wins (~1–2 weeks).**
(a) **Triage + rejection-reason classifier (WS-3)** on the text history — no images, most
data, immediate review-queue reduction. (b) Doc-type/quality classifier (valid roster vs
garbage) from `correct/`+`incorrect/` + augmentation — kills the "invalid formatted" cases.
(Region detection from WS-2 only if Phase 3 needs cropped inputs; red-box stays the
existing optional cross-check.)

**Phase 3 — Roster reader (WS-1, the main event, ~3–6 weeks).**
Synthesise+augment rosters; fine-tune Donut (or LayoutLMv3 if you keep Tesseract);
hybrid fallback; ONNX-quantise; wire behind the extractor interface. Re-measure against
the Phase-1 baseline. Target: staff_id exact-match and grid recall up enough that R5 false
rejects and R1 "no flights" reviews collapse.

**Phase 4 — Triage + reason model (WS-3, ~1 week, ongoing).**
Train LightGBM on the multi-year admin-disposition history (§3.2) to route
auto-pass/reject/review and to predict the likely rejection reason. Wire it as a *routing /
hint* layer, not a verdict source — keeps N1 auditability. Re-train periodically as new
months close (active-learning loop). **This can start as soon as Phase 1's text dataset
exists — it needs no roster images and has the most data, so consider pulling it ahead of
Phase 3.**

---

## 8. Honest caveats / decision points

- **ML is not guaranteed cheaper than good engineering here.** Because the roster is a
  fixed template, a well-tuned deterministic extractor (better grid detection,
  region-cropping, font-trained Tesseract) might get you 80% of the way for a fraction of
  the cost and complexity, with **zero** model-maintenance burden. **Treat Phase 0–1 as
  the experiment that tells you whether ML is even warranted.** If the deterministic floor
  jumps after Phase 0, you may only need WS-2 + WS-3, not the full Donut workstream.
- **Label volume is the real risk**, not modelling. Donut wants hundreds–thousands of
  examples. Synthetic generation + override mining are how you get there without armies
  of annotators — budget the time for the dataset, not the GPU.
- **PII + zero-cost forbids cloud vision APIs in production.** A cloud VLM is fine *off-Pi
  as a labelling aid* on data you're comfortable sending, but the deployed extractor must
  be local. Confirm what data may leave the box before using any hosted model.
- **Pi-5 inference budget.** Even quantised Donut is seconds/page on CPU. Fine for a
  monthly batch of ~150 claims; **not** fine if expectations are interactive. Keep it in
  the worker, keep the OCR-result cache (N2).
- **Don't let ML erode auditability (N1).** Every payable/rejected day must still carry a
  deciding **rule** + reason. ML improves the *inputs* and *routing*; the rules remain the
  explainable arbiter.

---

## 9. Concrete next actions

1. Apply the **R5 confidence-gate** fix + **persist `extracted`** (Phase 0) — independent,
   high-value, and it instruments the data you need.
2. Write `scripts/build_ml_dataset.py` to assemble the labelled datasets by joining the
   **three workbooks** (Posting Base + Late + CCD master) across their monthly sheets,
   resolving roster links to cached images where possible — text rows for all history,
   image-backed rows for WS-1 (see §3 action).
3. Stand up the **per-field eval harness** and record the current extractor's baseline on
   a held-out month.
4. **Pull WS-3 forward** — train the triage + rejection-reason classifier on the text
   history (no images needed); it shrinks the review queue immediately.
5. Decide, on that evidence, whether to invest in WS-1 (Donut) or whether WS-3 +
   deterministic tuning already clear the bar.

---

## Related

- [valid-roster-marked-invalid-r5.md](valid-roster-marked-invalid-r5.md) — proof that the
  failures are OCR-driven (92/93 INVALIDs were R5 staff-ID misreads).
- [run-pipeline-performance.md](run-pipeline-performance.md) — OCR cost/concurrency; the
  batch budget any ML inference must fit inside.
- `.claude/rules/example-files.md` — the fixture inventory that seeds the eval/label set.
- `.claude/rules/backend-standards.md` — engine-purity constraints the ML backend must respect.
