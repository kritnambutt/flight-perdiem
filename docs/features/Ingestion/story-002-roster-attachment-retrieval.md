| Property     | Value                                                  |
| ------------ | ------------------------------------------------------ |
| Story ID     | PD-ING-002                                             |
| Title        | Roster attachment retrieval from Google Drive          |
| Epic         | EP-INGEST — Form Ingestion & Roster Retrieval          |
| Dependencies | Python, Google Drive API, local cache volume           |
| Story Type   | Feature                                                |
| Source       | REQUIREMENTS.md → §6.1 (F3); plan Phase 2              |

## 🗂 Epic Overview — EP-INGEST

See [overview.md](./overview.md). This story downloads the roster image/PDF each
claim links, so the OCR epic has local files to read.

## 📝 Feature Overview — PD-ING-002

### User Story

```gherkin
As the per diem validation system
I want to download each claim's roster attachment from Google Drive
So that the roster can be OCR'd and the claim validated against flown duty
```

### Pre-conditions

- `Claim.roster_links[]` are populated (PD-ING-001).
- Service account can read the linked Drive files.
- A persistent `roster-cache` volume exists.

### Scope

#### Included

- Resolve `drive.google.com/open?id=...` (and `/file/d/<id>/`) → file id.
- Download each attachment (JPEG, PNG, PDF).
- Support **multiple links per claim**.
- **Cache by file id** so re-runs skip re-download (idempotency, N2).
- Detect content type; mark PDFs for rasterisation in the OCR epic.
- Graceful handling of dead/permission-denied links.

#### Excluded

- OCR and red-box detection (RosterOCR epic).
- PDF→image rasterisation (handled at OCR time).

## 🎯 Acceptance Criteria

### Functional Requirements

1. **Link resolution** — parse all common Drive URL shapes to a file id; ignore
   non-Drive URLs with a recorded warning.
2. **Download (F3)** — fetch bytes; store at `cache/<file_id>.<ext>`; record the
   local path + content type on the claim's roster reference.
3. **Multiple attachments** — every link in `roster_links[]` is downloaded and
   tracked separately.
4. **Caching** — if `cache/<file_id>` exists, reuse it; never re-download in the
   same or a later run.
5. **Resilience** — a broken/forbidden link yields `NEEDS_REVIEW(roster
   unreachable)` for that claim, and the run continues.

### Error Scenarios

- 404 / permission denied → review flag, no crash.
- Unsupported MIME (e.g. HTML error page) → review flag.
- Partial download / network blip → retry a bounded number of times, then flag.
- Duplicate file id across claims → downloaded once, referenced by both.

## 🧩 Technical Documentation

### Roster reference

```python
@dataclass
class RosterRef:
    source_url: str
    file_id: str | None
    local_path: str | None       # cache/<file_id>.<ext>
    content_type: str | None     # image/jpeg | image/png | application/pdf
    status: Literal["OK", "UNREACHABLE", "UNSUPPORTED"]
```

### Interface

```python
def fetch_rosters(claim: Claim) -> list[RosterRef]:
    """Download all roster attachments for a claim, using the cache."""
```

### Storage

| Setting        | Value                                  |
| -------------- | -------------------------------------- |
| Cache location | `roster-cache` volume → `/data/cache`  |
| Key convention | `<file_id>.<ext>`                      |
| Auth           | Google service account (read-only)     |

## 🔨 Implementation Plan

1. 📝 **TODO** Drive URL → file-id parser (multiple URL shapes) + tests.
2. 📝 **TODO** Drive download via service account; content-type sniffing.
3. 📝 **TODO** File-id cache (skip if present); store `RosterRef`.
4. 📝 **TODO** Bounded retry + clear review flags for failures.
5. 📝 **TODO** Tests with mocked Drive responses (image, pdf, 403, html).

## 🏗 Structure

```
backend/perdiem/engine/
└── drive.py            # fetch_rosters, url->id, cache, retries
```

## 📌 Notes / Open Questions

- Should very large PDFs be page-limited before OCR? (defer to RosterOCR).
- Confirm cache retention policy — keep indefinitely vs prune after N months.
