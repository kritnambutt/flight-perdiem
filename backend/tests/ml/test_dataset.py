"""Unit + integration tests for the ML dataset builder (PD-ML-002).

Pure data-prep tests: no DB, no network — only the local workbook fixtures under
``docs/example-files`` (same fixtures the engine tests use).
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from ml.dataset.build import _split_for, build_dataset
from ml.dataset.join import apply_blank_remark_rule, build_master_index
from ml.dataset.normalise import (
    classify_disposition,
    days_in_periods,
    parse_period,
    parse_sheet_month,
)
from ml.dataset.readers import (
    read_form_sheet,
    read_identity_registry,
    read_master_sheet,
)

FIXTURES = Path(__file__).parent.parent.parent.parent / "docs" / "example-files"
PB_PATH = str(FIXTURES / "Posting Base Perdiem & Sector Allowance (Responses).xlsx")
LATE_PATH = str(
    FIXTURES / "Late Submission Perdiem & Irregularity of Sector Allowance (Responses).xlsx"
)
CCD_PATH = str(FIXTURES / "Posting Perdiem of CCD 2026.xlsx")


# ---------------------------------------------------------------------------
# Sheet-name → (month, year)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "name,expected",
    [
        ("AUGUST 2025", ("AUGUST", 2025)),
        ("AUG 2025", ("AUGUST", 2025)),
        ("MAY 26", ("MAY", 2026)),
        ("FEBRUARY 25", ("FEBRUARY", 2025)),
        ("FEBUARY 2025", ("FEBRUARY", 2025)),       # recurring typo
        ("12 December 2019", ("DECEMBER", 2019)),    # leading day prefix
        ("06 JUNE 19", ("JUNE", 2019)),
        ("SEPTEMBER 2023 ", ("SEPTEMBER", 2023)),    # trailing space
        ("April 2025", ("APRIL", 2025)),             # mixed case
    ],
)
def test_parse_sheet_month_ok(name: str, expected: tuple[str, int]) -> None:
    assert parse_sheet_month(name) == expected


@pytest.mark.parametrize(
    "name", ["Form Responses 26", "New report", "Sheet68", "New Crew data", "Crew Data"]
)
def test_parse_sheet_month_unparseable(name: str) -> None:
    assert parse_sheet_month(name) is None


# ---------------------------------------------------------------------------
# Disposition classification (the gold WS-3 label)
# ---------------------------------------------------------------------------

def test_classify_blank_returns_none() -> None:
    assert classify_disposition(None) is None
    assert classify_disposition("   ") is None


def test_classify_approve() -> None:
    assert classify_disposition("จ่ายเงิน") == ("APPROVED", "NONE")
    assert classify_disposition("จ่ายเงินเดือนกันยายน") == ("APPROVED", "NONE")


def test_classify_negation_beats_approve() -> None:
    # "ไม่จ่ายเงิน" contains "จ่ายเงิน" — the negation must win.
    assert classify_disposition("ไม่จ่ายเงิน")[0] == "REJECTED"


def test_classify_defer_with_reason_keeps_both() -> None:
    # Action = defer (back-claim), reason = R4 — they must not collapse.
    disp, hint = classify_disposition(
        "รอแก้ไข และทำจ่ายตกเบิก | ไม่มีวันที่ด้านล่างซ้ายมือ"
    )
    assert disp == "DEFER_BACKCLAIM"
    assert hint == "R4"


def test_classify_bare_reason_is_rejected() -> None:
    assert classify_disposition("ลงข้อมูลซ้ำ") == ("REJECTED", "R7")
    assert classify_disposition("ต้องแนบ full roster") == ("REJECTED", "DOC_INCOMPLETE")


def test_classify_unknown_text_routes_to_review() -> None:
    assert classify_disposition("ข้อความที่ไม่รู้จัก") == ("REVIEW", "NONE")


# ---------------------------------------------------------------------------
# Period parsing
# ---------------------------------------------------------------------------

def test_parse_period_single_range() -> None:
    assert parse_period("16 May 2025 - 17 May 2025") == [
        (date(2025, 5, 16), date(2025, 5, 17))
    ]


def test_parse_period_multi_range_newline() -> None:
    periods = parse_period("26 June 2025 - 27 June 2025\n23 August 2025 - 24 August 2025")
    assert periods == [
        (date(2025, 6, 26), date(2025, 6, 27)),
        (date(2025, 8, 23), date(2025, 8, 24)),
    ]
    assert days_in_periods(periods) == 4


def test_parse_period_blank() -> None:
    assert parse_period(None) == []
    assert parse_period("") == []


# ---------------------------------------------------------------------------
# Blank-Remark labelling rule (the decision gate)
# ---------------------------------------------------------------------------

def test_blank_remark_present_in_master_is_approved() -> None:
    disp, hint, source = apply_blank_remark_rule(None, matched_in_master=True)
    assert (disp, hint, source) == ("APPROVED", "NONE", "master_reconciled")


def test_blank_remark_absent_from_master_is_review() -> None:
    disp, _, source = apply_blank_remark_rule(None, matched_in_master=False)
    assert disp == "REVIEW"
    assert source == "admin_remark"


def test_annotated_remark_wins_over_master() -> None:
    disp, hint, source = apply_blank_remark_rule(("REJECTED", "R7"), matched_in_master=True)
    assert (disp, hint, source) == ("REJECTED", "R7", "admin_remark")


# ---------------------------------------------------------------------------
# Readers against real fixtures (AUGUST 2025)
# ---------------------------------------------------------------------------

def test_read_posting_base_august_harvests_dispositions() -> None:
    rows, month = read_form_sheet(PB_PATH, "AUGUST 2025", "POSTING_BASE")
    assert month == ("AUGUST", 2025)
    assert len(rows) > 50
    # The disposition lives in a URL-headed column — harvesting must still find it.
    dispositions = {classify_disposition(r.admin_remark)[0] for r in rows if r.admin_remark}
    assert "APPROVED" in dispositions
    # Structured fields parsed.
    first = rows[0]
    assert first.staff_id and first.staff_id.isdigit()
    assert first.roster_links and first.roster_links[0].startswith("http")


def test_read_late_august_disposition_in_second_note() -> None:
    rows, month = read_form_sheet(LATE_PATH, "AUGUST 2025", "LATE")
    assert month == ("AUGUST", 2025)
    assert any(
        classify_disposition(r.admin_remark) == ("APPROVED", "NONE")
        for r in rows
        if r.admin_remark
    )


def test_read_master_and_index_keys_by_claimed_month() -> None:
    master_rows = read_master_sheet(CCD_PATH, "AUG 2025")
    assert len(master_rows) > 50
    index = build_master_index(master_rows)
    # A back-claim flown in May 2025 (paid in the Aug report) keys on its flown month.
    may_keys = [k for k in index if k[1] == "MAY" and k[2] == 2025]
    assert may_keys, "expected at least one May-2025 claimed-month key in the master index"


def test_identity_registry_has_names() -> None:
    registry = read_identity_registry(CCD_PATH)
    assert len(registry) > 500
    named = [v for v in registry.values() if v["name_en"]]
    assert len(named) > 500


# ---------------------------------------------------------------------------
# Crew-grouped split assignment
# ---------------------------------------------------------------------------

def test_split_is_deterministic_per_crew() -> None:
    assert _split_for("1004531") == _split_for("1004531")
    assert _split_for("1004531") in {"train", "val", "test"}


# ---------------------------------------------------------------------------
# End-to-end build (no roster cache → vision split empty)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def built():
    return build_dataset(
        pb_path=PB_PATH,
        late_path=LATE_PATH,
        ccd_path=CCD_PATH,
        version="test",
        rate_thb_per_day=400,
        roster_cache_dir=None,
    )


def test_build_produces_text_rows_and_splits(built) -> None:
    assert built.stats.text_rows > 1000
    assert built.stats.vision_rows == 0  # no cache provided
    # All three splits populated and a row's split matches its crew key.
    assert set(built.stats.split_counts) == {"train", "val", "test"}


def test_build_manifest_records_source_hashes(built) -> None:
    sources = built.manifest["sources"]
    assert sources["posting_base"]["sha256"]
    assert sources["ccd_master"]["sha256"]
    assert built.manifest["labelling_rule_version"] == "1.0"
    assert built.manifest["rate_thb_per_day"] == 400


def test_build_every_row_has_valid_label(built) -> None:
    valid_disp = {"APPROVED", "REJECTED", "DEFER_BACKCLAIM", "REVIEW"}
    valid_src = {"admin_remark", "master_reconciled", "regex_bootstrap"}
    for row in built.text_rows:
        assert row.disposition in valid_disp
        assert row.label_source in valid_src
        assert row.split in {"train", "val", "test"}
        # THB is rate-driven off approved days.
        assert row.total_thb == row.approved_days * built.manifest["rate_thb_per_day"]


def test_build_unparsed_sheets_reported_not_dropped(built) -> None:
    # The "Form Responses" tabs can't be parsed to a month and must be reported.
    assert any("Form Responses" in s for s in built.stats.unparsed_sheets)
