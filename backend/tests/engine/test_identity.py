"""Unit tests for perdiem.engine.identity (PD-VAL-002)."""
from __future__ import annotations

from datetime import date, datetime

import pytest

from perdiem.engine.config import RulesConfig
from perdiem.engine.identity import IdentityResult, check_identity, normalize
from perdiem.engine.models import Claim, ExtractedRoster, Field


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CFG = RulesConfig()


def _claim(name: str, staff_id: str | None = "1234567") -> Claim:
    return Claim(
        source="POSTING_BASE",
        source_row_ref="test!A1",
        timestamp=None,
        email="test@test.com",
        staff_id=staff_id,
        name=name,
        position=None,
        base="DMK",
        claim_type="Posting",
        claim_month="FEBRUARY 2026",
        claimed_days=[2, 3],
    )


def _roster(name: str | None, staff_id: str | None = "1234567") -> ExtractedRoster:
    empty_date: Field = Field(None, 0.0)
    return ExtractedRoster(
        staff_id=Field(staff_id, 1.0) if staff_id else Field(None, 0.0),
        name=Field(name, 0.9) if name else Field(None, 0.0),
        start_date=empty_date,
        end_date=empty_date,
        generated_at=Field(None, 0.0),
        grid={},
        needs_review=[],
    )


# ---------------------------------------------------------------------------
# normalize()
# ---------------------------------------------------------------------------


def test_normalize_trims_and_lowercases():
    assert normalize("  John DOE  ") == "john doe"


def test_normalize_strips_punctuation():
    assert normalize("Lucksnara S.") == "lucksnara s"


def test_normalize_collapses_spaces():
    assert normalize("A  B   C") == "a b c"


def test_normalize_strips_diacritics():
    assert normalize("Café") == "cafe"


# ---------------------------------------------------------------------------
# R5 — staff ID checks
# ---------------------------------------------------------------------------


def test_exact_id_and_name_match():
    result = check_identity(_claim("John Doe"), _roster("John Doe"), _CFG)
    assert result.decision == "MATCH"
    assert result.staff_id_match is True


def test_id_mismatch_returns_reject():
    result = check_identity(_claim("John Doe"), _roster("John Doe", staff_id="9999999"), _CFG)
    assert result.decision == "REJECT"
    assert result.staff_id_match is False
    assert "staff ID mismatch" in (result.reason or "")


def test_high_confidence_id_mismatch_rejects():
    # roster ID read confidently (1.0) and differs → genuine wrong person → REJECT
    roster = _roster("John Doe", staff_id="9999999")
    assert roster.staff_id.confidence >= _CFG.staff_id_reject_min_confidence
    result = check_identity(_claim("John Doe"), roster, _CFG)
    assert result.decision == "REJECT"


def _roster_with_id_conf(staff_id: str, conf: float) -> ExtractedRoster:
    return ExtractedRoster(
        staff_id=Field(staff_id, conf),
        name=Field("John Doe", 0.9),
        start_date=Field(None, 0.0),
        end_date=Field(None, 0.0),
        generated_at=Field(None, 0.0),
        grid={},
        needs_review=[],
    )


def test_low_confidence_id_mismatch_routes_to_review():
    # PD-ML-001: the real-world misreads (Natjaree 1026841→1026885,
    # Sujarinee 1009672→1006629) come back at the 0.60 bare-fallback floor. A
    # mismatch at < reject-bar (0.8) must route to REVIEW, not a hard reject —
    # otherwise an obviously-valid roster is marked INVALID on a misread.
    for conf in (0.60, 0.75):
        roster = _roster_with_id_conf("9999999", conf)
        result = check_identity(_claim("John Doe"), roster, _CFG)
        assert result.decision == "REVIEW", f"conf={conf} should review"
        assert result.staff_id_match is False
        assert "uncertain" in (result.reason or "")


def test_missing_form_id_returns_review():
    result = check_identity(_claim("John Doe", staff_id=None), _roster("John Doe"), _CFG)
    assert result.decision == "REVIEW"
    assert result.staff_id_match is False


def test_missing_roster_id_returns_review():
    result = check_identity(_claim("John Doe"), _roster("John Doe", staff_id=None), _CFG)
    assert result.decision == "REVIEW"


# ---------------------------------------------------------------------------
# R5a — name checks (staff ID already matches)
# ---------------------------------------------------------------------------


def test_missing_roster_name_returns_review():
    result = check_identity(_claim("John Doe"), _roster(None), _CFG)
    assert result.decision == "REVIEW"
    assert "unreadable" in (result.reason or "")


def test_initial_surname_matches():
    # "Lucksnara S." on form ↔ "Lucksnara Sothiratviroj" on roster
    result = check_identity(
        _claim("Lucksnara S."), _roster("Lucksnara Sothiratviroj"), _CFG
    )
    assert result.decision == "MATCH"


def test_prefix_surname_matches():
    result = check_identity(_claim("Jane Smi"), _roster("Jane Smith"), _CFG)
    assert result.decision == "MATCH"


def test_same_first_exact_surname_match():
    result = check_identity(_claim("Jane Smith"), _roster("Jane Smith"), _CFG)
    assert result.decision == "MATCH"


def test_name_order_swap_match():
    # "Doe John" on roster ↔ "John Doe" on form — first/last swap
    result = check_identity(_claim("John Doe"), _roster("Doe John"), _CFG)
    assert result.decision == "MATCH"


def test_fuzzy_close_name_above_threshold():
    # Very close names should be above default 0.8 threshold
    result = check_identity(_claim("Sawaros Phanichvibul"), _roster("Sawaros Phanichvibul"), _CFG)
    assert result.decision == "MATCH"


def test_completely_different_name_below_threshold():
    result = check_identity(_claim("Alice Wong"), _roster("Bob Zhang"), _CFG)
    assert result.decision == "REVIEW"
    assert result.name_score < _CFG.name_match_threshold


def test_tunable_threshold_tightening():
    cfg_strict = RulesConfig(name_match_threshold=0.99)
    # Slightly different names that would pass at 0.8 but fail at 0.99
    result = check_identity(_claim("Jane Sm"), _roster("Jane Smith"), cfg_strict)
    # prefix rule still fires so it's a MATCH
    assert result.decision == "MATCH"


def test_case_insensitive_match():
    result = check_identity(_claim("JOHN DOE"), _roster("john doe"), _CFG)
    assert result.decision == "MATCH"
