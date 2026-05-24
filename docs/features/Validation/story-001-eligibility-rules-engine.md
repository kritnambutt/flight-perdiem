| Property     | Value                                              |
| ------------ | -------------------------------------------------- |
| Story ID     | PD-VAL-001                                         |
| Title        | Eligibility rules engine (route, flight no., proof, coverage, month) |
| Epic         | EP-VALID — Validation Engine                       |
| Dependencies | PD-OCR-001/002 outputs, config (flight numbers)    |
| Story Type   | Feature                                            |
| Source       | REQUIREMENTS.md → §5 (R1, R2, R4, R6, R8), §6.3 (F7)|

## 🗂 Epic Overview — EP-VALID

See [overview.md](./overview.md). This story applies the core eligibility rules
and produces a per-day verdict. Name matching (R5a) is PD-VAL-002 and pairing
(R3) is PD-VAL-003; this story orchestrates them into the final verdict.

## 📝 Feature Overview — PD-VAL-001

### User Story

```gherkin
As the per diem validation system
I want to check each claimed day against the route, flight number, roster proof, coverage and month rules
So that only genuine DMK↔HKT postings proven by the roster are marked payable

As an admin
I want each decision tagged with the rule that produced it
So that I can audit and explain why a day was paid or rejected
```

### Pre-conditions

- `ExtractedRoster` (flight grid, dates, generated date) is available.
- Config provides qualifying routes, the rotating flight-number set, and the rate.

### Scope

#### Included

- **R1 Route:** only `DMK→HKT` (out) and `HKT→DMK` (return) qualify.
- **R2 Flight numbers:** leg flight number must be in the configurable set
  (out: `FD3013, FD3015`; return: `FD3026, FD3006, FD3038, FD3084`).
- **R4 Generated-date proof:** roster generated date must be later than the
  claimed date(s).
- **R6 Period coverage:** roster date range must cover every claimed day.
- **R8 Month routing:** flown month vs cycle month → `VALID` or
  `VALID (back-claim)` with a REMARK.
- Orchestrate R5/R5a (PD-VAL-002) and R3 (PD-VAL-003) into one verdict per day.
- Record the deciding rule + reason on every verdict.

#### Excluded

- The name-matching algorithm itself (PD-VAL-002).
- The pairing algorithm itself (PD-VAL-003).
- Dedup/aggregation (Reporting epic).

## 🎯 Acceptance Criteria

### Functional Requirements

1. **R1 route** — a leg qualifies only if `(orig,dest)` ∈ {(DMK,HKT),(HKT,DMK)};
   other routes (DMK-DAD, DMK-SIN, …) are ignored, **not** disqualifying the day.
2. **R2 flight number** — the qualifying leg's flight number must be in the
   configured set for its direction; the set is **config-driven** (rotates
   monthly) and validated at run start.
3. **R4 proof** — for each claimed day, `generated_at.date()` must be strictly
   after the claimed date; otherwise `NEEDS_REVIEW(unproven: generated before claim)`.
4. **R6 coverage** — every claimed day must fall within `[start_date, end_date]`;
   otherwise `INVALID(period not covered)`.
5. **R8 month** — if the flown month ≠ cycle month → `VALID (back-claim)` and set
   REMARK (e.g. `ตกเบิกเดือนมกราคม`); else `VALID`.
6. **F7 verdict** — output one verdict per claimed day:
   `VALID | VALID(back-claim) | NEEDS_REVIEW(reason) | INVALID(reason)`, with
   `rule` and `reason` fields populated.

### Error Scenarios

- Claimed day with no qualifying leg on the roster → `NEEDS_REVIEW(no DMK-HKT leg)`.
- Generated date missing/low-confidence → `NEEDS_REVIEW` (can't prove R4).
- Outbound present but no next-day return → handled by R3 (PD-VAL-003) →
  `NEEDS_REVIEW(incomplete pair)`.
- Flight number not in set but route matches → `INVALID(flight not eligible)`.

## 🧩 Technical Documentation

### Verdict model

```python
Verdict = Literal["VALID", "VALID_BACKCLAIM", "NEEDS_REVIEW", "INVALID"]

@dataclass
class DayVerdict:
    claimed_date: date
    verdict: Verdict
    rule: str             # "R2", "R4", ...
    reason: str | None
    remark: str | None    # e.g. back-claim note
```

### Interface

```python
def validate_claim(
    claim: Claim, roster: ExtractedRoster, red: RedAnnotation, cfg: RulesConfig
) -> list[DayVerdict]: ...
```

### Config (R2/F13)

```yaml
routes:
  outbound: [DMK, HKT]
  return:   [HKT, DMK]
flight_numbers:
  outbound: [FD3013, FD3015]
  return:   [FD3026, FD3006, FD3038, FD3084]
rate_thb_per_day: 400
```

## 🔨 Implementation Plan

1. 📝 **TODO** Pure rule functions: `route_ok`, `flight_ok`, `coverage_ok`, `proof_ok`, `month_route`.
2. 📝 **TODO** Orchestrator `validate_claim` combining rules + R3 + R5a into per-day verdicts.
3. 📝 **TODO** Config loader + start-up validation of flight-number set.
4. 📝 **TODO** Unit-test matrix: each rule pass/fail; back-claim; multi-leg days; unproven date.

## 🏗 Structure

```
backend/perdiem/engine/
├── rules.py          # R1,R2,R4,R6,R8 pure predicates + validate_claim orchestrator
└── config.py         # RulesConfig (routes, flight numbers, rate)
```

## 📌 Notes / Open Questions

- **R4 direction (REQUIREMENTS §9 Q2):** the "(correct format)" sample has the
  generated date *before* the claimed days, contradicting R4. Confirm before
  finalising the comparison.
- Claim types `Layover` / `Irregularity` — same rules? (§9 Q4).
