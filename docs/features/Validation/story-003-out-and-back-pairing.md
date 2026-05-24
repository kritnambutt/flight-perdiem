| Property     | Value                                              |
| ------------ | -------------------------------------------------- |
| Story ID     | PD-VAL-003                                         |
| Title        | Out-and-back pairing across consecutive days       |
| Epic         | EP-VALID — Validation Engine                       |
| Dependencies | PD-OCR-001 (flight grid), PD-VAL-001 (route/flight rules) |
| Story Type   | Feature                                            |
| Source       | REQUIREMENTS.md → §5 (R3), §6.3 (F8)               |

## 🗂 Epic Overview — EP-VALID

See [overview.md](./overview.md). This story implements the defining shape of a
posting trip: an outbound on day N **paired with** a return on day N+1, worth 2
payable days.

## 📝 Feature Overview — PD-VAL-003

### User Story

```gherkin
As the per diem validation system
I want to pair an outbound DMK→HKT on day N with a HKT→DMK return on day N+1
So that a complete posting trip counts as exactly two payable days

As an admin
I want incomplete trips (outbound with no next-day return) flagged, not auto-paid
So that I can review genuine irregularities instead of overpaying
```

### Pre-conditions

- The roster flight grid (per-day legs) is extracted (PD-OCR-001).
- Route/flight-number eligibility predicates exist (PD-VAL-001).

### Scope

#### Included

- For each qualifying **outbound DMK→HKT on day N**, look at **day N+1** for a
  qualifying **return HKT→DMK**.
- A matched pair → **2 payable days** (N and N+1).
- Pairs that **straddle a month boundary** (e.g. 31 Jan → 1 Feb) are supported.
- Unmatched outbound or orphan return → `NEEDS_REVIEW(incomplete pair)`.

#### Excluded

- Route/flight-number checks themselves (PD-VAL-001 provides the predicates).
- Dedup across submissions (Reporting epic).

## 🎯 Acceptance Criteria

### Functional Requirements

1. **Pair detection (R3)** — given a qualifying outbound on day N, search day N+1
   (including across month/year boundaries) for a qualifying return.
2. **Two-day yield** — a matched pair marks **both** N and N+1 as candidate
   payable days (subject to R4/R6/R8 from PD-VAL-001).
3. **Incomplete pair (F8)** — outbound with no next-day return, or a return with
   no prior-day outbound → `NEEDS_REVIEW(incomplete pair)`; never silently paid.
4. **Multiple trips per month** — several independent pairs in one roster are all
   detected.
5. **Month-boundary** — a 31st→1st pair is recognised and attributed to the
   correct cycle/back-claim per R8.

### Error Scenarios

- Two outbounds on consecutive days with one return → match greedily, flag the
  leftover for review.
- Same-day out-and-back (turnaround, no overnight) → not a posting pair → review
  (confirm policy with stakeholders).
- Return appears two days later (irregular) → not auto-paired → review.

## 🧩 Technical Documentation

### Interface

```python
@dataclass
class Pair:
    out_day: date
    back_day: date
    complete: bool

def find_pairs(grid: dict[int, list[Leg]], month: date, cfg) -> tuple[list[Pair], list[date]]:
    """Return matched pairs + list of unmatched/incomplete days for review."""
```

### Algorithm

1. Mark each day as having a qualifying outbound and/or return (via PD-VAL-001).
2. Walk days in order; for each outbound at N, consume a return at N+1 if present.
3. Build calendar dates from day-of-month + month (handle boundary rollover).
4. Emit complete `Pair`s + the set of unmatched days.

## 🔨 Implementation Plan

1. 📝 **TODO** Per-day qualifying-leg flags using PD-VAL-001 predicates.
2. 📝 **TODO** Greedy N / N+1 pairing with calendar-date construction.
3. 📝 **TODO** Month/year boundary handling (31 Jan → 1 Feb).
4. 📝 **TODO** Emit incomplete days as review reasons.
5. 📝 **TODO** Tests: single pair, multiple pairs, boundary pair, orphan out/return.

## 🏗 Structure

```
backend/perdiem/engine/
└── pairing.py        # find_pairs (R3, F8)
```

## 📌 Notes / Open Questions

- Confirm same-day turnaround handling (overnight required for per diem?).
- Confirm how a boundary pair's 2 days split across cycle vs back-claim reporting.
