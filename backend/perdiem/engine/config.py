"""Per-run rules configuration (routes, flight numbers, rate).

Separate from perdiem/config.py which holds environment/infra settings.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RulesConfig:
    outbound_route: tuple[str, str] = ("DMK", "HKT")
    return_route: tuple[str, str] = ("HKT", "DMK")
    outbound_flights: set[str] = field(
        default_factory=lambda: {"FD3013", "FD3015"}
    )
    return_flights: set[str] = field(
        default_factory=lambda: {"FD3026", "FD3006", "FD3038", "FD3084"}
    )
    rate_thb_per_day: int = 400
    name_match_threshold: float = 0.8
    # PD-ML-001: only hard-reject an R5 staff-ID *mismatch* when the roster ID was
    # read at or above this confidence. The reliable reads are the header-band /
    # frequency strategies (≥0.85); the bare-fallback reads sit at 0.60 and are
    # exactly the misreads that caused false INVALIDs — those route to REVIEW.
    # This is a stricter bar than the OCR field-review floor (OcrConfig=0.6) on
    # purpose: rejecting the wrong person must require a confident read.
    staff_id_reject_min_confidence: float = 0.8

    def validate(self) -> None:
        """Raise ValueError if the config is unusable at run start."""
        if not self.outbound_flights:
            raise ValueError("outbound_flights must not be empty")
        if not self.return_flights:
            raise ValueError("return_flights must not be empty")
        if not self.outbound_route or len(self.outbound_route) != 2:
            raise ValueError("outbound_route must be a 2-tuple (orig, dest)")
        if not self.return_route or len(self.return_route) != 2:
            raise ValueError("return_route must be a 2-tuple (orig, dest)")
        if not (0.0 < self.name_match_threshold <= 1.0):
            raise ValueError("name_match_threshold must be in (0, 1]")
        if not (0.0 <= self.staff_id_reject_min_confidence <= 1.0):
            raise ValueError("staff_id_reject_min_confidence must be in [0, 1]")
