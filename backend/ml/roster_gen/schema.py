"""Data model for a synthetic crew schedule roster (PD-ML-006).

`SyntheticRosterData` is the ground-truth record: it drives both the PIL
renderer (image input for Donut) and `to_label_json()` (target output the
model learns to decode).  Keeping both in the same object guarantees the
training pair is always consistent.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass
class SyntheticLeg:
    flight_no: str  # "FD3012"
    orig: str       # "DMK"
    dest: str       # "HKT"
    dep_time: str   # "06:00"


@dataclass
class SyntheticRosterData:
    staff_id: str               # 7-digit string, e.g. "1234567"
    name: str                   # "SOMCHAI JAIDEE"
    position: str               # "CC" | "SC" | "FO" | "CP"
    base: str                   # "DMK"
    start_date: date
    end_date: date
    generated_at: datetime
    grid: dict[int, list[SyntheticLeg]] = field(default_factory=dict)
    # day_of_month (1-31) → legs flown that day

    def to_label_json(self) -> dict:
        """Serialize to the JSON format Donut should learn to output.

        Keys and date formats match what `_parse_donut_output()` in
        `perdiem.engine.ocr.ml_extract` expects, so training and inference
        parsing never drift.
        """
        return {
            "staff_id": self.staff_id,
            "name": self.name,
            "start_date": self.start_date.strftime("%d/%m/%Y"),
            "end_date": self.end_date.strftime("%d/%m/%Y"),
            "generated_at": self.generated_at.strftime("%b %d, %Y %H:%M"),
            "grid": {
                str(day): [
                    {
                        "fn": leg.flight_no,
                        "from": leg.orig,
                        "to": leg.dest,
                        "time": leg.dep_time,
                    }
                    for leg in legs
                ]
                for day, legs in sorted(self.grid.items())
            },
        }
