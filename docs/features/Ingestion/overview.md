# 🗂 Epic Overview — EP-INGEST (Form Ingestion & Roster Retrieval)

The Ingestion epic covers getting raw per diem claims **into** the system: reading
the two Google Form response workbooks for a cycle month and downloading every
roster attachment the crew linked from Google Drive. It is the first stage of the
pipeline and everything downstream (OCR, validation, reporting) depends on it.

See [../../REQUIREMENTS.md](../../REQUIREMENTS.md) (§4 Data Sources, §6.1) and
[../../plans/implementation-plan.md](../../plans/implementation-plan.md) (Phases 1–2).

| Story ID    | Title                                         | Reqs        | Status      |
| ----------- | --------------------------------------------- | ----------- | ----------- |
| PD-ING-001  | Form response ingestion (Posting Base + Late) | F1, F2      | 📝 Planned  |
| PD-ING-002  | Roster attachment retrieval from Drive        | F3          | 📝 Planned  |

**Pipeline position:** `Ingest → Extract (OCR) → Validate → Aggregate → Report`.
This epic produces a normalised `Claim` list plus locally cached roster files,
which [RosterOCR](../RosterOCR/overview.md) then reads.

**Key context**
- Two forms feed the same cycle: **Posting Base** (on-time) and **Late
  Submission** (back-claims). Both must be ingested and merged.
- Claims are reconciled one month in arrears (working in March → claim February).
- All Google access uses the service account `kantaphajasuwan@airasia.com`
  (free Sheets/Drive API tier).
- Forms mix Thai/English; column headers are partly Thai.
