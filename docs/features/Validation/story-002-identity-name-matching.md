| Property     | Value                                              |
| ------------ | -------------------------------------------------- |
| Story ID     | PD-VAL-002                                         |
| Title        | Identity check & fuzzy name matching               |
| Epic         | EP-VALID — Validation Engine                       |
| Dependencies | PD-OCR-001 (roster staff id + name), PD-ING-001    |
| Story Type   | Feature                                            |
| Source       | REQUIREMENTS.md → §5 (R5, R5a)                     |

## 🗂 Epic Overview — EP-VALID

See [overview.md](./overview.md). This story verifies the roster belongs to the
submitter — staff ID is the strong key; names are matched with tolerance for the
real-world variations seen in submissions.

## 📝 Feature Overview — PD-VAL-002

### User Story

```gherkin
As the per diem validation system
I want to confirm the roster's staff ID and name match the form submitter
So that a crew member can't claim using someone else's roster

As an admin
I want abbreviated or differently-formatted names (e.g. "Lucksnara S." vs "Lucksnara Sothiratviroj") to still match when the staff ID matches
So that valid claims aren't rejected over harmless name formatting
```

### Pre-conditions

- Roster staff ID + name extracted (PD-OCR-001); form Employee Code + name parsed.

### Scope

#### Included

- **R5 identity:** roster `staff_id` must equal form `Employee Code` (exact key).
- **R5a name matching:** normalise + fuzzy/partial match for:
  - abbreviated/initial surname (`Lucksnara S.` ↔ `Lucksnara Sothiratviroj`),
  - trailing/double whitespace, case, diacritics / Thai⇄English transliteration,
  - first/last order swaps.
- Decision policy: **staff ID mismatch → INVALID**; name mismatch with matching
  staff ID → **NEEDS_REVIEW** (don't hard-reject on name alone).

#### Excluded

- The other eligibility rules (PD-VAL-001).

## 🎯 Acceptance Criteria

### Functional Requirements

1. **R5 staff ID** — exact match required; mismatch → `INVALID(identity mismatch)`.
2. **R5a normalisation** — before comparison: trim, collapse spaces, lowercase,
   strip punctuation; transliteration-tolerant.
3. **R5a partial surname** — match when first name matches **and** the shorter
   surname is a prefix of, or the initial of, the longer surname.
4. **R5a fuzzy fallback** — a similarity score with a **tunable threshold**;
   above → match, below → `NEEDS_REVIEW(name mismatch)`.
5. **Authority** — staff ID resolves ambiguity; a clean staff-ID match with a
   below-threshold name yields review, not rejection.

### Error Scenarios

- Roster name OCR low-confidence → `NEEDS_REVIEW(name unreadable)`, rely on staff ID.
- Two crew with same first name but different surnames → staff ID disambiguates.
- Missing staff ID on roster → `NEEDS_REVIEW` (can't apply R5 strongly).

## 🧩 Technical Documentation

### Interface

```python
@dataclass
class IdentityResult:
    staff_id_match: bool
    name_score: float          # 0..1
    decision: Literal["MATCH", "REVIEW", "REJECT"]
    reason: str | None

def check_identity(claim: Claim, roster: ExtractedRoster, cfg) -> IdentityResult: ...
```

### Matching steps

1. `normalize(name)` → trim/collapse/lowercase/strip-punct/transliterate.
2. Split into first + surname tokens; handle order swaps.
3. Surname prefix/initial rule; else token-set fuzzy ratio.
4. Combine with `staff_id_match` per the authority policy.

### Config

| Setting             | Default | Purpose                  |
| ------------------- | ------- | ------------------------ |
| `name_match_threshold` | 0.8  | fuzzy cutoff for MATCH   |

## 🔨 Implementation Plan

1. ✅ **DONE** `normalize()` (diacritics, lowercase, collapse spaces, strip punctuation).
2. ✅ **DONE** Surname prefix/initial matcher (the `Lucksnara S.` case) + first/last order swap.
3. ✅ **DONE** Fuzzy fallback via `rapidfuzz==3.9.7` token-set ratio + tunable threshold.
4. ✅ **DONE** Authority policy: ID mismatch → REJECT; name below threshold with matching ID → REVIEW.
5. ✅ **DONE** Tests: initials, order swap, diacritics, missing name, fuzzy above/below threshold (17 tests, all pass).

## 🏗 Structure

```
backend/perdiem/engine/
└── identity.py       # normalize + name match + check_identity (R5/R5a)
tests/engine/
└── test_identity.py  # 17 unit tests
```

## 📌 Notes / Open Questions

- `rapidfuzz==3.9.7` chosen (MIT, pure-wheel on arm64) and pinned in `requirements.txt`.
- `name_match_threshold` defaults to `0.8`; tune against real name variants when more data is available.
