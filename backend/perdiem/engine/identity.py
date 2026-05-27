"""Identity check: R5 (staff ID) and R5a (fuzzy name matching).

PD-VAL-002 — staff ID is the strong key; name is fuzzy-matched with tolerance
for abbreviations, initials, Thai/English transliteration variants.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

from perdiem.engine.config import RulesConfig
from perdiem.engine.models import Claim, ExtractedRoster


@dataclass
class IdentityResult:
    staff_id_match: bool
    name_score: float           # 0..1
    decision: Literal["MATCH", "REVIEW", "REJECT"]
    reason: str | None


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------


def normalize(name: str) -> str:
    """Lowercase, strip diacritics, collapse whitespace, remove punctuation."""
    # NFD decompose → drop combining chars (diacritics)
    nfd = unicodedata.normalize("NFD", name)
    no_diacritics = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    lower = no_diacritics.lower()
    # strip punctuation (keep letters, digits, spaces)
    no_punct = re.sub(r"[^\w\s]", " ", lower)
    return re.sub(r"\s+", " ", no_punct).strip()


# ---------------------------------------------------------------------------
# Surname prefix / initial check
# ---------------------------------------------------------------------------


def _split_first_surname(norm: str) -> tuple[str, str]:
    """Return (first_name, rest_of_name) from a normalised name string."""
    parts = norm.split()
    if not parts:
        return "", ""
    return parts[0], " ".join(parts[1:])


def _surname_prefix_match(a_sur: str, b_sur: str) -> bool:
    """True when the shorter surname is a prefix of or initial for the longer."""
    if not a_sur or not b_sur:
        return False
    short, long_ = (a_sur, b_sur) if len(a_sur) <= len(b_sur) else (b_sur, a_sur)
    if long_.startswith(short):
        return True
    # single-letter initial
    return len(short) == 1 and long_[0] == short[0]


# ---------------------------------------------------------------------------
# Fuzzy score
# ---------------------------------------------------------------------------


def _fuzzy_score(a: str, b: str) -> float:
    """Token-set similarity in [0, 1]. Falls back to Jaccard on import error."""
    try:
        from rapidfuzz.fuzz import token_set_ratio

        return token_set_ratio(a, b) / 100.0
    except ImportError:
        tokens_a, tokens_b = set(a.split()), set(b.split())
        union = tokens_a | tokens_b
        return len(tokens_a & tokens_b) / len(union) if union else 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def check_identity(
    claim: Claim, roster: ExtractedRoster, cfg: RulesConfig
) -> IdentityResult:
    """
    Apply R5 (staff ID exact match) and R5a (fuzzy name match).

    Decision policy:
    - Staff ID mismatch, roster read *confidently* → REJECT  (INVALID — wrong person)
    - Staff ID mismatch, roster read *uncertainly*→ REVIEW  (PD-ML-001: likely OCR misread)
    - Staff ID matches, name cannot be read       → REVIEW
    - Staff ID matches, name above threshold      → MATCH
    - Staff ID matches, name below threshold      → REVIEW  (never hard-reject on name)
    """
    form_id = (claim.staff_id or "").strip()
    roster_id = (roster.staff_id.value or "").strip()

    # Missing ID on either side
    if not form_id or not roster_id:
        return IdentityResult(
            staff_id_match=False,
            name_score=0.0,
            decision="REVIEW",
            reason="missing staff ID on form or roster",
        )

    # R5: exact ID match
    if form_id != roster_id:
        # PD-ML-001: only hard-reject when the roster ID was read confidently. A
        # low-confidence / mis-located OCR read must not silently reject an
        # otherwise-valid claim (N1: anything uncertain is surfaced for review,
        # never silently guessed). A confident mismatch is a genuine wrong person.
        if roster.staff_id.confidence < cfg.staff_id_reject_min_confidence:
            return IdentityResult(
                staff_id_match=False,
                name_score=0.0,
                decision="REVIEW",
                reason=(
                    f"staff ID uncertain (OCR {roster.staff_id.confidence:.2f}): "
                    f"form={form_id!r} roster={roster_id!r} — verify against roster"
                ),
            )
        return IdentityResult(
            staff_id_match=False,
            name_score=0.0,
            decision="REJECT",
            reason=f"staff ID mismatch: form={form_id!r} roster={roster_id!r}",
        )

    # R5a: name check — staff ID already matched
    roster_name_raw = roster.name.value or ""
    if not roster_name_raw.strip():
        return IdentityResult(
            staff_id_match=True,
            name_score=0.0,
            decision="REVIEW",
            reason="name unreadable on roster",
        )

    form_norm = normalize(claim.name)
    roster_norm = normalize(roster_name_raw)

    # Try first-name + surname prefix/initial check
    form_first, form_sur = _split_first_surname(form_norm)
    roster_first, roster_sur = _split_first_surname(roster_norm)

    if form_first == roster_first and _surname_prefix_match(form_sur, roster_sur):
        return IdentityResult(
            staff_id_match=True, name_score=1.0, decision="MATCH", reason=None
        )

    # Handle first/last order swap: compare reversed splits
    if roster_first == form_sur and _surname_prefix_match(roster_sur, form_first):
        return IdentityResult(
            staff_id_match=True, name_score=1.0, decision="MATCH", reason=None
        )

    # Fuzzy fallback
    score = _fuzzy_score(form_norm, roster_norm)
    if score >= cfg.name_match_threshold:
        return IdentityResult(
            staff_id_match=True, name_score=score, decision="MATCH", reason=None
        )

    return IdentityResult(
        staff_id_match=True,
        name_score=score,
        decision="REVIEW",
        reason=(
            f"name mismatch: form={claim.name!r} roster={roster_name_raw!r}"
            f" (score={score:.2f})"
        ),
    )
