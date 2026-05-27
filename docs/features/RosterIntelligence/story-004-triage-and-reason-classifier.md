| Property     | Value                                                          |
| ------------ | -------------------------------------------------------------- |
| Story ID     | PD-ML-004                                                      |
| Title        | Triage + rejection-reason classifier (WS-3)                    |
| Epic         | EP-ML — Roster Intelligence                                    |
| Dependencies | PD-ML-002 (dataset), PD-ML-003 (eval)                          |
| Story Type   | Feature                                                        |
| Status       | ✅ Done — triage + reason classifier trained; pure inference + rules-only fallback; 9 tests pass. Ships **disabled** (advisory) pending richer features. |
| Source       | REQUIREMENTS.md → §6.3 (F7), §5 (R4/R7/R8), §7 (N1)            |

## 🗂 Epic Overview — EP-ML

See [overview.md](./overview.md). The highest-payback ML in the epic: it learns from
**thousands of historical admin decisions** to route claims (auto-pass / reject / review)
and to predict the likely rejection reason. It needs **no roster images** — only the workbook
text — so it can train as soon as the dataset exists.

## 📝 Feature Overview — PD-ML-004

### User Story

```gherkin
As an admin
I want the system to auto-pass the obvious claims, surface a ranked "likely problem" on the rest, and only queue genuinely uncertain ones
So that I spend review time on the few hard cases, not the hundreds of routine ones — exactly as past admins decided
```

### Pre-conditions

- The text dataset (PD-ML-002) with `disposition` + `rule_hint` labels exists.
- The eval harness (PD-ML-003) can score routing decisions.

### Scope

#### Included

- A **triage classifier**: features (rule outputs/flags + claim metadata) →
  `AUTO_PASS | AUTO_REJECT | SEND_TO_REVIEW`.
- A **rejection-reason classifier**: when not auto-pass → ranked `rule_hint`
  (`R4/R6/R7/R8/DOC_INCOMPLETE/OUT_OF_SCOPE`), as a reviewer **hint**.
- **Calibrated probabilities** + abstention: low-confidence → `SEND_TO_REVIEW` (never a
  silent auto-decision).
- A pure scoring function the engine/worker can call **without** training deps.

#### Excluded

- Replacing the rule verdicts (R1–R8 remain the auditable arbiter — this *routes*, not decides).
- Image features (text-only by design; image signals enter via PD-ML-006/007 later).

## 🎯 Acceptance Criteria

### Functional Requirements

1. **Triage:** on the held-out month, auto-pass precision is high enough that auto-passed
   claims rarely disagree with the master (target set during baseline review); recall of
   problems is not sacrificed (problems land in review, not auto-pass).
2. **Reason hint:** top-1/top-2 `rule_hint` accuracy reported per class; the hint is advisory
   and shown in the Exceptions UI, never used to reject.
3. **Calibration & abstention:** predicted-probability bins are calibrated; below a config
   threshold the claim is routed to `SEND_TO_REVIEW`.
4. **Auditability (N1):** the routing decision and the deciding **rule** are both recorded;
   an auto-pass still carries its rule-based verdict + reason.
5. **No training deps at inference:** the model is a serialised artifact scored by a pure
   function; engine import stays light.

### Validation Rules

- Features are derived from rule outputs + claim metadata (claim type, base, month-routing,
  dedup flag, OCR confidences) — **not** from the free-text outcome (no label leakage).
- Class imbalance handled (most rows are APPROVED); report per-class precision/recall, not
  just accuracy.

### Error Scenarios

- Unknown/garbled remark in training → mapped to `REVIEW`/`NONE`, flagged in PD-ML-002's
  quality report, not dropped.
- Model file missing at runtime → engine falls back to **rules-only** (triage disabled),
  logged; never crashes the run.

## 🧩 Technical Documentation

### Inference interface (pure; lives near the engine boundary)

```python
@dataclass
class TriageResult:
    route: Literal["AUTO_PASS","AUTO_REJECT","SEND_TO_REVIEW"]
    confidence: float
    reason_hint: list[tuple[str, float]]   # ranked rule_hints with probs

def triage(features: dict, model_path: str, cfg: TriageConfig) -> TriageResult: ...
```

### Model

- **LightGBM** (gradient-boosted trees) — tiny, fast on Pi CPU, handles mixed/tabular
  features and imbalance well; exported as a single model file.
- Trained **off-Pi** under `backend/ml/triage/`; artifact loaded at inference.

### Required Configuration

- `TRIAGE_ENABLED` (default False until validated), `TRIAGE_MODEL_PATH`,
  `TRIAGE_AUTOPASS_MIN_CONF`, `TRIAGE_REVIEW_BAND`.

### Security Requirements

- Features may include staff_id/name-derived signals (PII) — model + features stay local.

## 🔨 Implementation Plan

1. ✅ **DONE** Non-leaky feature builder (`perdiem/engine/triage.build_features`) — source/claim_type/month/day-count/links/staff-id; never reads disposition/rule_hint/approved.
2. ✅ **DONE** Train triage + reason heads (`ml/triage/train.py`) — see model note below.
3. ✅ **DONE** Abstention threshold calibrated on the val split (`ml/triage/calibrate.py`); top-2 margin band.
4. ✅ **DONE** Pure `triage()` + `safe_triage()` rules-only fallback (`perdiem/engine/triage.py`).
5. ✅ **DONE** Scored via the PD-ML-003 harness (`scripts/eval_ml.py --triage-model …`); numbers in [../../analysis/ml-baseline.md](../../analysis/ml-baseline.md).
6. 🔜 **DEFERRED to PD-ML-007** — wiring the advisory route + reason_hint into the worker/Exceptions UI. The pure scorer + config flags are ready; runtime integration is PD-ML-007's scope.

### Model note (deviation from the LightGBM spec)

Implemented as a **numpy multinomial logistic regression** (softmax) rather than
LightGBM. Rationale: it keeps the stack **numpy-only** (no new heavy dep on the Pi),
serialises to a self-describing JSON, and makes `triage()` a genuinely pure function
with **no training deps at inference** (AC-5). The triage head trains on the natural
class distribution (so APPROVED confidence is meaningful for the auto-pass cut); the
reason head is class-balanced (so rare rule_hints aren't ignored). The PD-ML-003
harness keeps the backend swappable if a tree model is later warranted.

### Finding (text-only features)

On the held-out split, text metadata alone reaches **~0.81 auto-pass precision** at
best — below a safe auto-**pay** bar — so the calibrated cut correctly **abstains**
(routes to review) and the model ships **disabled by default** (`TRIAGE_ENABLED=false`).
Its usable signal today is the **reason hint** (top-2 ≈ 0.78) and queue prioritisation.
High-precision auto-pass needs **rule-output / OCR-confidence features**, which only
exist when the pipeline runs — they enter via PD-ML-007. This is exactly the kind of
evidence-based result PD-ML-003 exists to surface.

## 🏗 Structure

```
backend/ml/triage/             # training (off-Pi) — NOT in engine
├── features.py
├── train.py
└── calibrate.py
backend/perdiem/engine/triage.py   # pure inference scorer (lazy-imports model lib)
backend/tests/ml/test_triage.py
```

## 📌 Notes / Open Questions

- **Pull this forward** — most data, no images, fastest review-queue reduction.
- Re-train as new months close (active-learning loop); track drift via PD-ML-003.
- Confirm with admins which routes are safe to **auto-pay** vs always require a human glance.
