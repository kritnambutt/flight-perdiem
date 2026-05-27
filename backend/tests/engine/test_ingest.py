"""Integration tests for the ingest module against real example fixtures."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from perdiem.engine.ingest import read_late_submission, read_posting_base
from perdiem.engine.models import Claim

FIXTURES = Path(__file__).parent.parent.parent.parent / "docs" / "example-files"
PB_PATH = str(FIXTURES / "Posting Base Perdiem & Sector Allowance (Responses).xlsx")
LATE_PATH = str(
    FIXTURES / "Late Submission Perdiem & Irregularity of Sector Allowance (Responses).xlsx"
)


@pytest.fixture(scope="module")
def pb_march26() -> list[Claim]:
    return read_posting_base(PB_PATH, "MARCH 2026")


@pytest.fixture(scope="module")
def pb_february26() -> list[Claim]:
    return read_posting_base(PB_PATH, "FEBRUARY 2026")


@pytest.fixture(scope="module")
def late_march26() -> list[Claim]:
    return read_late_submission(LATE_PATH, "MARCH 2026")


@pytest.fixture(scope="module")
def late_february26() -> list[Claim]:
    return read_late_submission(LATE_PATH, "FEBRUARY 2026")


class TestReadPostingBase:
    def test_returns_claims(self, pb_march26):
        assert len(pb_march26) > 0

    def test_all_have_posting_base_source(self, pb_march26):
        assert all(c.source == "POSTING_BASE" for c in pb_march26)

    def test_source_row_ref_format(self, pb_march26):
        for c in pb_march26:
            assert "!" in c.source_row_ref

    def test_staff_id_is_string_integer(self, pb_march26):
        ids_with_value = [c.staff_id for c in pb_march26 if c.staff_id is not None]
        assert len(ids_with_value) > 0
        for sid in ids_with_value:
            assert sid.isdigit(), f"staff_id should be digits only, got: {sid!r}"

    def test_claimed_days_are_ints(self, pb_march26):
        for c in pb_march26:
            assert all(isinstance(d, int) for d in c.claimed_days)

    def test_claimed_days_sorted(self, pb_march26):
        for c in pb_march26:
            assert c.claimed_days == sorted(c.claimed_days)

    def test_claimed_days_in_valid_range(self, pb_march26):
        for c in pb_march26:
            assert all(1 <= d <= 31 for d in c.claimed_days), (
                f"Day out of range in {c.source_row_ref}: {c.claimed_days}"
            )

    def test_roster_links_are_urls(self, pb_march26):
        for c in pb_march26:
            for link in c.roster_links:
                assert link.startswith("http"), f"Bad link: {link!r}"

    def test_claim_month_is_uppercase(self, pb_march26):
        for c in pb_march26:
            assert c.claim_month == c.claim_month.upper()

    def test_multiple_roster_links(self, pb_february26):
        multi = [c for c in pb_february26 if len(c.roster_links) > 1]
        assert len(multi) > 0, "Expected at least one claim with multiple roster links"

    def test_missing_month_returns_empty(self):
        claims = read_posting_base(PB_PATH, "JUNE 1900")
        assert claims == []

    def test_name_not_blank(self, pb_march26):
        assert all(c.name != "" for c in pb_march26)

    def test_email_not_blank(self, pb_march26):
        assert all(c.email != "" for c in pb_march26)

    def test_february26_has_claims(self, pb_february26):
        assert len(pb_february26) > 0


class TestReadLateSubmission:
    def test_returns_claims(self, late_march26):
        assert len(late_march26) > 0

    def test_all_have_late_source(self, late_march26):
        assert all(c.source == "LATE" for c in late_march26)

    def test_staff_id_is_string_integer(self, late_march26):
        ids_with_value = [c.staff_id for c in late_march26 if c.staff_id is not None]
        assert len(ids_with_value) > 0
        for sid in ids_with_value:
            assert sid.isdigit(), f"staff_id should be digits only, got: {sid!r}"

    def test_claimed_days_sorted(self, late_march26):
        for c in late_march26:
            assert c.claimed_days == sorted(c.claimed_days)

    def test_claim_month_normalised(self, late_march26):
        # Late submission months are normalised — should not contain "วันที่"
        for c in late_march26:
            assert "วันที่" not in c.claim_month

    def test_claim_month_not_empty(self, late_march26):
        non_empty = [c for c in late_march26 if c.claim_month != ""]
        assert len(non_empty) > 0

    def test_missing_month_returns_empty(self):
        claims = read_late_submission(LATE_PATH, "JUNE 1900")
        assert claims == []

    def test_february26_has_claims(self, late_february26):
        assert len(late_february26) > 0

    def test_roster_links_are_urls(self, late_march26):
        for c in late_march26:
            for link in c.roster_links:
                assert link.startswith("http"), f"Bad link: {link!r}"
