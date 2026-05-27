"""Randomised `SyntheticRosterData` factory (PD-ML-006).

Generates realistic but synthetic crew schedule data: 7-digit staff IDs,
Thai-English names, valid out-and-back DMK↔HKT flight pairs on consecutive
days, and a generated-date that is always ≥ the last claimed date (R4).
"""
from __future__ import annotations

import random
from calendar import monthrange
from datetime import date, datetime, timedelta

from ml.roster_gen.schema import SyntheticLeg, SyntheticRosterData

# ── Static pools ─────────────────────────────────────────────────────────────

_NAMES = [
    "SOMCHAI JAIDEE", "MALEE SRISAWAT", "WANCHAI BURANASIRI",
    "NATTAYA PHONGPHAN", "KITTISAK WONGSIRI", "APINYA THONGDEE",
    "PIYAPONG SUKSAMRAN", "SIRIPORN CHANPEN", "YUTTANA PRACHAK",
    "WANNISA BOONSONG", "CHAIWAT SIRIPHAN", "LADAWAN KONGKAEW",
    "SURACHET MEECHAI", "PATCHARAPORN NILPAN", "VORAWIT SUNTHORN",
    "KANNIKAR RODPET", "NATCHAPOL JITTRAPON", "ORAWAN PHAKDEE",
    "THITIPHAT WONGWAI", "KANYA CHAROENSUK", "PRAPAS TANARAK",
    "BUSARA WIMOLRAT", "THANAWAT SRIKARN", "NAREERAT CHANTIP",
    "AEKACHAI SOMBUN", "WARISA BORIBOON", "RATTANAPORN BOONIN",
    "SAWAROS PHANICHVIBUL", "KANATSANAN WICHITTHARARAK", "CHANICHA SONGKRIT",
]

_POSITIONS = ["CC", "CC", "CC", "SC", "FO", "CP"]

# Out-and-back DMK↔HKT pairs (outbound leg, return leg next day).
# Each tuple: (out_fn, out_orig, out_dest, out_time, ret_fn, ret_orig, ret_dest, ret_time)
_FLIGHT_PAIRS: list[tuple] = [
    ("FD3012", "DMK", "HKT", "06:00", "FD3013", "HKT", "DMK", "08:30"),
    ("FD3018", "DMK", "HKT", "13:00", "FD3019", "HKT", "DMK", "15:30"),
    ("FD3020", "DMK", "HKT", "16:00", "FD3021", "HKT", "DMK", "18:30"),
    ("FD3022", "DMK", "HKT", "07:30", "FD3023", "HKT", "DMK", "10:00"),
]


def generate_roster(
    rng: random.Random | None = None,
    *,
    year: int = 2026,
    month: int = 2,
) -> SyntheticRosterData:
    """Return one randomised `SyntheticRosterData` for the given month."""
    rng = rng or random.Random()

    name = rng.choice(_NAMES)
    staff_id = f"1{rng.randint(100_000, 999_999)}"
    position = rng.choice(_POSITIONS)

    days_in_month = monthrange(year, month)[1]
    start = date(year, month, 1)
    end = date(year, month, days_in_month)

    # Generated date is always after the roster end date (R4: proof of print)
    gen_day_offset = rng.randint(1, 10)
    gen_date = end + timedelta(days=gen_day_offset)
    generated_at = datetime(
        gen_date.year, gen_date.month, gen_date.day,
        rng.randint(8, 22), rng.randint(0, 59),
    )

    # Grid: out-and-back pairs on consecutive days, with rest gaps
    grid: dict[int, list[SyntheticLeg]] = {}
    day = 1
    while day < days_in_month:
        if rng.random() < 0.50 and day + 1 <= days_in_month:
            pair = rng.choice(_FLIGHT_PAIRS)
            grid[day] = [SyntheticLeg(pair[0], pair[1], pair[2], pair[3])]
            grid[day + 1] = [SyntheticLeg(pair[4], pair[5], pair[6], pair[7])]
            day += 2 + rng.randint(0, 3)  # rest days between pairs
        else:
            day += 1

    return SyntheticRosterData(
        staff_id=staff_id,
        name=name,
        position=position,
        base="DMK",
        start_date=start,
        end_date=end,
        generated_at=generated_at,
        grid=grid,
    )


def generate_batch(
    n: int,
    *,
    year: int = 2026,
    month: int = 2,
    seed: int | None = None,
) -> list[SyntheticRosterData]:
    """Return `n` unique synthetic rosters for the given month."""
    rng = random.Random(seed)
    return [generate_roster(rng, year=year, month=month) for _ in range(n)]
