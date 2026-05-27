# 🗂 Epic Overview — EP-VALID (Validation Engine)

The Validation epic is the heart of the system: given a claim and its extracted
roster, decide **per claimed day** whether the per diem is payable. It applies
rules **R1–R8** (and the name-matching rule **R5a**) and emits a verdict with the
deciding rule recorded for audit. It is a **pure library** — no I/O — so it is
heavily unit-tested.

See [../../REQUIREMENTS.md](../../REQUIREMENTS.md) (§5 rules, §6.3) and
[../../plans/implementation-plan.md](../../plans/implementation-plan.md) (Phase 4).

| Story ID    | Title                                  | Reqs                         | Status      |
| ----------- | -------------------------------------- | ---------------------------- | ----------- |
| PD-VAL-001  | Eligibility rules engine               | R1, R2, R4, R6, R8, F7       | ✅ Done     |
| PD-VAL-002  | Identity & fuzzy name matching         | R5, R5a                      | ✅ Done     |
| PD-VAL-003  | Out-and-back pairing across days       | R3, F8                       | ✅ Done     |

**Verdict model (shared):** each claimed day → `VALID`, `VALID (back-claim)`,
`NEEDS_REVIEW(reason)`, or `INVALID(reason)`, each tagged with the rule that
decided it.

**Inputs:** `Claim` (Ingestion) + `ExtractedRoster` + `RedAnnotation` (RosterOCR).
**Outputs:** per-day `Verdict` list → consumed by [Reporting](../Reporting/overview.md).

**Rule recap**
- **R1/R2** route DMK↔HKT only, configurable flight numbers (rotate monthly).
- **R3** outbound day N pairs with return day N+1 = 2 payable days.
- **R4** roster generated date must be after the claimed date(s).
- **R5/R5a** roster must belong to the submitter; staff ID is authoritative,
  names matched fuzzily.
- **R6** roster date range must cover the claimed days.
- **R8** flown month ≠ cycle → back-claim routing + REMARK.
