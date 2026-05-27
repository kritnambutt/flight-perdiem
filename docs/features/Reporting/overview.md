# 🗂 Epic Overview — EP-REPORT (Dedup, Aggregation & Reporting)

The Reporting epic turns per-day verdicts into the **payable result**: it merges
all submissions for a cycle, de-duplicates by `(staff ID, date)`, aggregates per
crew into date ranges + day counts + amounts, and writes the master report in the
existing workbook shape — plus an exception report for everything that needs
attention.

See [../../REQUIREMENTS.md](../../REQUIREMENTS.md) (§4.3, §6.4) and
[../../plans/implementation-plan.md](../../plans/implementation-plan.md) (Phases 5–6).

| Story ID    | Title                                  | Reqs            | Status      |
| ----------- | -------------------------------------- | --------------- | ----------- |
| PD-REP-001  | De-duplication & per-crew aggregation  | R7, F9, F10     | ✅ Done     |
| PD-REP-002  | Master report + exception report output| F11, F12        | ✅ Done     |

**Inputs:** per-day `DayVerdict`s from [Validation](../Validation/overview.md)
across **all** submissions (Posting Base + Late + re-submissions).
**Outputs:** the master `.xlsx` (per-month sheet) + an exception report; both
surfaced in the [WebApp](../WebApp/overview.md).

**Key context**
- Crew re-submit; dedup by unique `(staff ID, calendar date)` is mandatory (R7).
- Rate observed at **400 THB/day** (2-day trip = 800).
- The master report has one sheet per month; historical sheets must not be
  disturbed. Re-runs must be idempotent (N2).
