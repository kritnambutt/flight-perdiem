"""OCR result cache keyed by (file_id, backend, model_version) (PD-ML-007).

Serialises an `ExtractedRoster` to a JSON sidecar on disk so re-running the
same cycle re-uses the already-computed fields rather than invoking Tesseract
or Donut again (N2 idempotency).

Cache key: SHA-1 of "<file_id>:<backend>:<model_version>" — changing the
backend or retraining the model (bumps model_version) naturally invalidates
stale cache entries without manual cleanup.

The cache directory is gitignored (`data/ml/ocr_cache`).  The engine module
has no side effects; the cache lives here, in the ocr/ sub-package, still
engine-pure because it only touches the filesystem — no DB or network.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import date, datetime
from pathlib import Path

from perdiem.engine.models import ExtractedRoster, Field, Leg

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# (De)serialisation — ExtractedRoster ↔ JSON dict
# ---------------------------------------------------------------------------

def _field_to_json(f: Field) -> dict:
    v = f.value
    if isinstance(v, (date, datetime)):
        v = v.isoformat()
    return {"value": v, "conf": f.confidence}


def _field_from_json(d: dict, cast=None) -> Field:
    raw = d.get("value")
    conf = float(d.get("conf", 0.0))
    if raw is None or cast is None:
        return Field(raw, conf)
    try:
        return Field(cast(raw), conf)
    except (ValueError, TypeError):
        return Field(None, 0.0)


def _parse_date(s: str) -> date:
    return date.fromisoformat(s)


def _parse_datetime(s: str) -> datetime:
    return datetime.fromisoformat(s)


def _grid_to_json(grid: dict[int, list[Leg]]) -> dict:
    return {
        str(day): [
            {"fn": lg.flight_no, "orig": lg.orig, "dest": lg.dest, "time": lg.time}
            for lg in legs
        ]
        for day, legs in sorted(grid.items())
    }


def _grid_from_json(raw: dict) -> dict[int, list[Leg]]:
    grid: dict[int, list[Leg]] = {}
    for day_str, legs_raw in (raw or {}).items():
        try:
            day = int(day_str)
        except (ValueError, TypeError):
            continue
        legs = [
            Leg(
                flight_no=str(lg.get("fn", "")),
                orig=lg.get("orig"),
                dest=lg.get("dest"),
                time=lg.get("time"),
            )
            for lg in (legs_raw or [])
            if isinstance(lg, dict)
        ]
        if legs:
            grid[day] = legs
    return grid


def to_dict(r: ExtractedRoster, *, backend: str = "", cached_at: str = "") -> dict:
    """Serialise an ExtractedRoster to a JSON-compatible dict."""
    return {
        "_cached_at": cached_at,
        "_backend": backend,
        "staff_id": _field_to_json(r.staff_id),
        "name": _field_to_json(r.name),
        "start_date": _field_to_json(r.start_date),
        "end_date": _field_to_json(r.end_date),
        "generated_at": _field_to_json(r.generated_at),
        "grid": _grid_to_json(r.grid),
        "needs_review": list(r.needs_review),
    }


def from_dict(d: dict) -> ExtractedRoster:
    """Deserialise an ExtractedRoster from a JSON-compatible dict."""
    return ExtractedRoster(
        staff_id=_field_from_json(d.get("staff_id", {})),
        name=_field_from_json(d.get("name", {})),
        start_date=_field_from_json(d.get("start_date", {}), _parse_date),
        end_date=_field_from_json(d.get("end_date", {}), _parse_date),
        generated_at=_field_from_json(d.get("generated_at", {}), _parse_datetime),
        grid=_grid_from_json(d.get("grid", {})),
        needs_review=list(d.get("needs_review") or []),
    )


# ---------------------------------------------------------------------------
# Cache read / write
# ---------------------------------------------------------------------------

def _cache_key(file_id: str, backend: str, model_version: str) -> str:
    payload = f"{file_id}:{backend}:{model_version}".encode()
    return hashlib.sha1(payload).hexdigest()


def _cache_path(cache_dir: str, key: str) -> Path:
    return Path(cache_dir) / f"{key}.json"


def load_cached(
    cache_dir: str,
    file_id: str,
    backend: str,
    model_version: str,
) -> ExtractedRoster | None:
    """Return a cached `ExtractedRoster`, or None on miss / corrupt entry."""
    if not file_id:
        return None
    path = _cache_path(cache_dir, _cache_key(file_id, backend, model_version))
    if not path.exists():
        return None
    try:
        with path.open(encoding="utf-8") as fh:
            return from_dict(json.load(fh))
    except Exception as exc:
        logger.warning("OCR cache read error %s: %s — recomputing", path, exc)
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        return None


def store_cached(
    cache_dir: str,
    file_id: str,
    backend: str,
    model_version: str,
    result: ExtractedRoster,
) -> None:
    """Write an ExtractedRoster to the cache.  Silently skips on any I/O error."""
    if not file_id:
        return
    try:
        os.makedirs(cache_dir, exist_ok=True)
        path = _cache_path(cache_dir, _cache_key(file_id, backend, model_version))
        payload = to_dict(
            result,
            backend=backend,
            cached_at=datetime.now(__import__("datetime").timezone.utc).isoformat(),
        )
        with path.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh)
    except Exception as exc:
        logger.warning("OCR cache write error for %s: %s", file_id, exc)
