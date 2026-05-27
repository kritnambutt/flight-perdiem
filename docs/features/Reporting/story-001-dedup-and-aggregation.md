| Property     | Value                                              |
| ------------ | -------------------------------------------------- |
| Story ID     | PD-REP-001                                         |
| Title        | De-duplication & per-crew aggregation              |
| Epic         | EP-REPORT — Dedup, Aggregation & Reporting         |
| Dependencies | PD-VAL-001/002/003 verdicts                        |
| Story Type   | Feature                                            |
| Source       | REQUIREMENTS.md → §5 (R7), §6.4 (F9, F10)          |

## 🗂 Epic Overview — EP-REPORT

See [overview.md](./overview.md). This story collapses all valid per-day verdicts
into unique payable days per crew and computes the amount.

## 📝 Feature Overview — PD-REP-001

### User Story

```gherkin
As the per diem validation system
I want to merge all submissions and count each (staff, date) only once
So that crew who submit multiple times are paid correctly, never twice

As an admin
I want validated days grouped into date ranges with totals
So that the result reads like the existing master report
```

### Pre-conditions

- Per-day verdicts exist for every claim in the cycle (Validation epic).

### Scope

#### Included

- Merge verdicts from **Posting Base + Late Submission + re-submissions**.
- **De-duplicate** payable days by unique `(staff_id, calendar_date)` (R7).
- Reconcile the crew-stated day list vs roster-proven days; flag mismatches.
- Group each crew's unique payable days into **consecutive date ranges**.
- Compute `Days` (unique count) and `Total Perdiem = Days × rate`.
- Carry back-claim REMARKs through to the result.

#### Excluded

- Writing the `.xlsx` / exception files (PD-REP-002).
- The validation rules themselves (Validation epic).

## 🎯 Acceptance Criteria

### Functional Requirements

1. **Merge** — all sources for the cycle are combined before dedup.
2. **Dedup (R7)** — a `(staff_id, date)` that is payable in multiple submissions
   counts **once**. Keep an audit link to each contributing submission.
3. **Reconcile (F9)** — where the crew-stated days differ from roster-proven
   days, the difference is recorded as a review note (not silently dropped).
4. **Range grouping** — consecutive unique days merge into ranges, multiple
   ranges per crew preserved (e.g. `26–31 Jan` + `10–11 Feb` + `17–21 Feb`).
5. **Amounts (F10)** — `Days` = count of unique payable days; `Total Perdiem =
   Days × rate` (rate from config, default 400 THB).
6. **Determinism** — stable ordering so re-runs produce identical rows (N2).

### Error Scenarios

- Same day valid in Posting Base and Late → counted once; REMARK notes the source.
- Crew claims 3 days but roster proves 2 → pay 2, flag the 3rd for review.
- Overlapping ranges across submissions → merged, not double-counted.

## 🧩 Technical Documentation

### Result model

```python
@dataclass
class CrewResult:
    staff_id: str
    name: str
    email: str
    periods: list[tuple[date, date]]   # merged ranges
    days: int                          # unique payable day count
    total_thb: int                     # days * rate
    remark: str | None                 # back-claim / reconciliation notes
```

### Interface

```python
def aggregate(verdicts: list[DayVerdict], claims: list[Claim], cfg) -> list[CrewResult]: ...
```

### Algorithm

1. Filter to `VALID` / `VALID_BACKCLAIM` day verdicts.
2. Build the set of unique `(staff_id, date)`.
3. Group by `staff_id`; sort dates; merge consecutive into ranges.
4. `days = len(unique dates)`, `total = days * rate`.
5. Attach REMARKs (back-claim months, reconciliation mismatches).

## 🔨 Implementation Plan

1. ✅ **DONE** Merge all claim_verdicts; unique `(staff_id, date)` dedup — first writer wins.
2. ✅ **DONE** `_merge_consecutive()` collapses sorted dates into consecutive `(start, end)` ranges.
3. ✅ **DONE** `days = len(unique dates)`; `total_thb = days × rate` (from `RulesConfig.rate_thb_per_day`).
4. ✅ **DONE** Reconciliation note: when claimed count > payable count, difference flagged in `remark`.
5. ✅ **DONE** Tests: dedup, range grouping, amounts, back-claim remarks, multi-crew ordering (23 tests, all pass).

## 🏗 Structure

```
backend/perdiem/engine/
└── dedup.py          # aggregate() + _merge_consecutive() (R7, F9, F10)
tests/engine/
└── test_dedup.py     # 23 unit tests
```

## 📌 Notes / Open Questions

- Rate confirmed flat **400 THB/day** in `RulesConfig.rate_thb_per_day`. Update if rank/route-dependent (REQUIREMENTS §9 Q1) — one field to change, no logic rewrite needed.
