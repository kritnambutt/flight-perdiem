"""Tests for the synthetic roster generator (PD-ML-006)."""
from __future__ import annotations

import json
from calendar import monthrange
from datetime import date

import numpy as np
import pytest

from ml.roster_gen.generate import generate_batch, generate_roster
from ml.roster_gen.renderer import render_roster
from ml.roster_gen.schema import SyntheticLeg, SyntheticRosterData


# ---------------------------------------------------------------------------
# Schema / label JSON
# ---------------------------------------------------------------------------

def test_to_label_json_keys():
    roster = generate_roster(year=2026, month=2)
    label = roster.to_label_json()
    assert set(label.keys()) == {"staff_id", "name", "start_date", "end_date", "generated_at", "grid"}


def test_to_label_json_date_format():
    roster = generate_roster(year=2026, month=2)
    label = roster.to_label_json()
    assert label["start_date"] == "01/02/2026"
    assert label["end_date"] == "28/02/2026"


def test_to_label_json_grid_keys_are_strings():
    roster = generate_roster(year=2026, month=2)
    label = roster.to_label_json()
    for k in label["grid"].keys():
        assert isinstance(k, str), f"grid key should be str, got {type(k)}"


def test_to_label_json_leg_fields():
    leg = SyntheticLeg("FD3012", "DMK", "HKT", "06:00")
    roster = SyntheticRosterData(
        staff_id="1234567", name="TEST CREW", position="CC", base="DMK",
        start_date=date(2026, 2, 1), end_date=date(2026, 2, 28),
        generated_at=__import__("datetime").datetime(2026, 3, 1, 10, 0),
        grid={15: [leg]},
    )
    label = roster.to_label_json()
    leg_label = label["grid"]["15"][0]
    assert leg_label == {"fn": "FD3012", "from": "DMK", "to": "HKT", "time": "06:00"}


def test_label_json_is_json_serialisable():
    roster = generate_roster(year=2026, month=3)
    label = roster.to_label_json()
    dumped = json.dumps(label)
    assert isinstance(dumped, str)


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------

def test_generate_roster_staff_id_format():
    for _ in range(20):
        r = generate_roster()
        assert len(r.staff_id) == 7, f"staff_id should be 7 digits: {r.staff_id}"
        assert r.staff_id.isdigit()
        assert r.staff_id.startswith("1")


def test_generate_roster_date_range_covers_full_month():
    r = generate_roster(year=2026, month=5)
    assert r.start_date == date(2026, 5, 1)
    days_in_may = monthrange(2026, 5)[1]
    assert r.end_date == date(2026, 5, days_in_may)


def test_generate_roster_generated_at_after_end_date():
    for _ in range(10):
        r = generate_roster()
        assert r.generated_at.date() > r.end_date, (
            f"generated_at {r.generated_at.date()} must be after end_date {r.end_date}"
        )


def test_generate_roster_grid_days_within_month():
    r = generate_roster(year=2026, month=2)
    days_in_month = monthrange(2026, 2)[1]
    for day in r.grid:
        assert 1 <= day <= days_in_month, f"grid day {day} out of range"


def test_generate_roster_grid_legs_are_dmk_hkt():
    import random
    rng = random.Random(42)
    for _ in range(30):
        r = generate_roster(rng)
        for legs in r.grid.values():
            for leg in legs:
                assert leg.orig in {"DMK", "HKT"}, f"unexpected orig: {leg.orig}"
                assert leg.dest in {"DMK", "HKT"}, f"unexpected dest: {leg.dest}"
                assert leg.flight_no.startswith("FD")


def test_generate_batch_returns_correct_count():
    batch = generate_batch(10, seed=0)
    assert len(batch) == 10
    for r in batch:
        assert isinstance(r, SyntheticRosterData)


def test_generate_batch_reproducible():
    a = generate_batch(5, seed=99)
    b = generate_batch(5, seed=99)
    for ra, rb in zip(a, b):
        assert ra.staff_id == rb.staff_id
        assert ra.name == rb.name


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------

def test_render_returns_ndarray():
    roster = generate_roster(year=2026, month=2)
    img = render_roster(roster)
    assert isinstance(img, np.ndarray)


def test_render_correct_dimensions():
    roster = generate_roster(year=2026, month=2)
    img = render_roster(roster)
    assert img.shape[2] == 3, "expected BGR (3 channels)"
    assert img.shape[1] == 1600, f"expected width 1600, got {img.shape[1]}"
    assert img.shape[0] == 1200, f"expected height 1200, got {img.shape[0]}"


def test_render_not_all_white():
    """The image should contain non-white pixels (header band, text, grid)."""
    roster = generate_roster(year=2026, month=2)
    img = render_roster(roster)
    white_fraction = (img == 255).all(axis=2).mean()
    assert white_fraction < 0.95, "rendered image looks mostly blank"


def test_render_different_rosters_differ():
    """Two distinct rosters should produce different images."""
    r1 = generate_roster(year=2026, month=2)
    r2 = generate_roster(year=2026, month=3)
    i1 = render_roster(r1)
    i2 = render_roster(r2)
    assert not np.array_equal(i1, i2)


def test_render_does_not_crash_empty_grid():
    """Rosters with no flights (all OFF) should render without error."""
    import datetime
    roster = SyntheticRosterData(
        staff_id="1999999", name="NO FLIGHTS CREW", position="CC", base="DMK",
        start_date=date(2026, 2, 1), end_date=date(2026, 2, 28),
        generated_at=datetime.datetime(2026, 3, 1, 8, 0),
        grid={},
    )
    img = render_roster(roster)
    assert img.shape[0] > 0
