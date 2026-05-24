# System Flow — Automated Per Diem Validation (To-Be)

The target automated pipeline. Rules referenced (R1–R8, R5a) are defined in
[../REQUIREMENTS.md](../REQUIREMENTS.md). The system **assists**: it auto-clears
the clear-cut claims and surfaces everything uncertain for human review
(N3 — human-in-the-loop).

Staff operate this pipeline through a **self-hosted web frontend** (§6.6): they
pick the cycle month and press Run, watch live progress, then review/approve
flagged claims and download the report. The pipeline below runs as a background
job behind that UI.

## Staff interaction (web frontend)

```mermaid
flowchart LR
    L[Staff login] --> SEL[Select cycle month]
    SEL --> RUN[Click Run]
    RUN --> JOB[(Background job:<br/>pipeline below)]
    JOB --> PROG[Live progress + counts]
    PROG --> DASH[Results dashboard]
    PROG --> EXQ[Exception review queue<br/>roster preview + failing rule]
    EXQ --> OVR[Approve / override / correct]
    OVR --> REAGG[Re-aggregate idempotently]
    REAGG --> DASH
    DASH --> DL[Publish / download report]
```

## High-level pipeline

```mermaid
flowchart LR
    subgraph Ingest
      A[Read Posting Base +<br/>Late Submission responses<br/>for cycle month] --> B[Download roster<br/>attachments from Drive]
    end
    subgraph Extract
      B --> C[OCR each roster:<br/>staff ID, name, date range,<br/>generated date, flight grid]
      C --> D[Detect red annotation<br/>to claimed day columns]
      C --> E[Per-field confidence score]
    end
    subgraph Validate
      D --> F[Apply rules R1-R8]
      E --> F
      F --> G[De-duplicate by<br/>staff ID + date]
    end
    subgraph Output
      G --> H[Result rows:<br/>Period, Days, THB]
      G --> I[Exception report]
      H --> J[(Master report sheet)]
    end
```

## Detailed decision flow (per response)

```mermaid
flowchart TD
    S[Form response] --> DL[Download roster image/PDF]
    DL --> OCR[OCR + red-box detection]
    OCR --> CONF{All fields<br/>high confidence?}
    CONF -- no --> REV[NEEDS_REVIEW:<br/>low OCR confidence]

    CONF -- yes --> ID{R5 staff ID ==<br/>Employee Code?}
    ID -- no --> REJ1[REJECT: identity mismatch]
    ID -- yes --> NM{R5a name match<br/>fuzzy / initial?}
    NM -- no --> REV2[NEEDS_REVIEW: name mismatch<br/>staff ID is authoritative]
    NM -- yes --> PER{R6 roster range<br/>covers claimed days?}

    PER -- no --> REJ2[REJECT: period not covered]
    PER -- yes --> RT[For each claimed day:<br/>R1 route DMK-HKT? R2 flight no.?]
    RT --> PAIR{R3 outbound DMK-HKT has<br/>HKT-DMK on next day?}
    PAIR -- no --> REV3[NEEDS_REVIEW: incomplete pair]
    PAIR -- yes --> GEN{R4 generated date ><br/>claimed date?}
    GEN -- no --> REV4[NEEDS_REVIEW: unproven<br/>scheduled-not-flown]
    GEN -- yes --> MON{R8 flown month ==<br/>cycle month?}
    MON -- no --> BACK[VALID as back-claim<br/>tag REMARK e.g. ตกเบิก...]
    MON -- yes --> OK[VALID]

    OK --> DEDUP[R7 collapse to unique<br/>staff ID + date]
    BACK --> DEDUP
```

## De-duplication & aggregation (R7)

After per-day verdicts across **all** submissions for the cycle (Posting Base +
Late Submission + any re-submissions):

```mermaid
flowchart TD
    A[All VALID day verdicts] --> B[Key by staff ID + calendar date]
    B --> C[Keep one per key<br/>drop duplicates]
    C --> D[Group by staff ID]
    D --> E[Merge consecutive days<br/>into Period ranges]
    E --> F[Days = unique day count]
    F --> G[Total Perdiem = Days x rate 400 THB]
    G --> H[Write result row]
```

## Verdict model

| Verdict | Meaning | Lands in |
|---------|---------|----------|
| `VALID` | All rules pass | Master report (payable) |
| `VALID (back-claim)` | Passes but flown month ≠ cycle (R8) | Master report + REMARK |
| `NEEDS_REVIEW(reason)` | Plausible but uncertain (low OCR, name, incomplete pair, unproven date) | Exception report |
| `INVALID(reason)` | Hard fail (ID mismatch, period not covered, wrong route) | Exception report |

## Idempotency & audit (N1, N2)

- Re-running a cycle reproduces the same rows — keyed by `(staff ID, date)`, no
  double-counting.
- Every verdict stores: source response row, roster image reference, the rule
  that decided it, and OCR confidence — so any payment/rejection is auditable.

## Configuration surface (R2/F13)

| Setting | Example | Why configurable |
|---------|---------|------------------|
| Qualifying routes | `DMK→HKT`, `HKT→DMK` | May expand |
| Outbound flight numbers | `FD3013, FD3015` | **Rotates monthly** |
| Return flight numbers | `FD3026, FD3006, FD3038, FD3084` | **Rotates monthly** |
| Per diem rate | `400 THB/day` | Policy change |
| Cycle month | `February 2026` | Per run |
| Name-match threshold | fuzzy score cutoff | Tuning |
