#!/usr/bin/env python3
"""Build the labelled ML dataset from the three workbooks (PD-ML-002).

Writes a versioned, reproducible dataset under ``$ML_DATASET_DIR/<version>/``:

    text.jsonl           # text/decision rows (all history, no image)
    vision.jsonl         # rows whose roster image resolves to a cached file
    manifest.json        # source hashes, counts, labelling-rule version
    quality_report.md    # auditable rows-per-sheet / label-coverage report

The dataset is PII (names, schedules) and stays local — ``data/`` is gitignored.

Examples:
    python scripts/build_ml_dataset.py --version v1
    python scripts/build_ml_dataset.py \
        --posting-base "docs/example-files/Posting Base ... (Responses).xlsx" \
        --late         "docs/example-files/Late Submission ... (Responses).xlsx" \
        --ccd          "docs/example-files/Posting Perdiem of CCD 2026.xlsx" \
        --version 2026-05 --roster-cache /data/cache
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

# Resolve everything against the repo root so the script works from any CWD (run from
# the repo root, or `cd backend` per the Makefile convention).
_REPO = Path(__file__).resolve().parent.parent
_BACKEND = _REPO / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from ml.dataset.build import build_dataset  # noqa: E402
from ml.dataset.quality_report import render_quality_report  # noqa: E402
from perdiem.config import settings  # noqa: E402

_EXAMPLES = _REPO / "docs" / "example-files"
_DEFAULT_PB = _EXAMPLES / "Posting Base Perdiem & Sector Allowance (Responses).xlsx"
_DEFAULT_LATE = (
    _EXAMPLES / "Late Submission Perdiem & Irregularity of Sector Allowance (Responses).xlsx"
)
_DEFAULT_CCD = _EXAMPLES / "Posting Perdiem of CCD 2026.xlsx"


def _anchor(p: str) -> str:
    """Resolve a relative path against the repo root (absolute paths pass through)."""
    return p if not p or Path(p).is_absolute() else str(_REPO / p)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _json_default(obj: object) -> str:
    if isinstance(obj, date | datetime):
        return obj.isoformat()
    raise TypeError(f"Not JSON serialisable: {type(obj)!r}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--posting-base", default=settings.posting_base_path or str(_DEFAULT_PB))
    parser.add_argument("--late", default=settings.late_submission_path or str(_DEFAULT_LATE))
    parser.add_argument("--ccd", default=settings.ccd_master_path or str(_DEFAULT_CCD))
    parser.add_argument(
        "--version",
        default=settings.dataset_version or datetime.now().strftime("%Y%m%d"),
        help="dataset version tag (default: DATASET_VERSION env or today's date)",
    )
    parser.add_argument(
        "--out-dir",
        default=settings.ml_dataset_dir,
        help=f"output root (default: {settings.ml_dataset_dir})",
    )
    parser.add_argument(
        "--rate",
        type=int,
        default=settings.rate_thb_per_day,
        help=f"THB per approved day (default: {settings.rate_thb_per_day})",
    )
    parser.add_argument(
        "--roster-cache",
        default=settings.roster_cache_dir,
        help="cached roster dir for the vision split; pass empty to skip vision",
    )
    args = parser.parse_args(argv)

    # Anchor relative paths to the repo root so CWD doesn't matter.
    pb_path, late_path, ccd_path = _anchor(args.posting_base), _anchor(args.late), _anchor(args.ccd)
    cache = _anchor(args.roster_cache) if args.roster_cache else ""
    cache = cache if cache and Path(cache).is_dir() else None

    print(f"Building dataset '{args.version}' …")
    result = build_dataset(
        pb_path=pb_path,
        late_path=late_path,
        ccd_path=ccd_path,
        version=args.version,
        rate_thb_per_day=args.rate,
        roster_cache_dir=cache,
    )

    out_dir = Path(_anchor(args.out_dir)) / args.version
    out_dir.mkdir(parents=True, exist_ok=True)

    _write_jsonl(out_dir / "text.jsonl", [r.to_jsonable() for r in result.text_rows])
    _write_jsonl(out_dir / "vision.jsonl", [r.to_jsonable() for r in result.vision_rows])
    (out_dir / "manifest.json").write_text(
        json.dumps(result.manifest, indent=2, ensure_ascii=False, default=_json_default),
        encoding="utf-8",
    )
    (out_dir / "quality_report.md").write_text(
        render_quality_report(result), encoding="utf-8"
    )

    print(f"  text rows  : {result.stats.text_rows}")
    print(f"  vision rows: {result.stats.vision_rows}")
    print(f"  unparsed sheets: {len(result.stats.unparsed_sheets)}")
    print(f"  written to : {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
