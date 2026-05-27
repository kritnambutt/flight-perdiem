#!/usr/bin/env python3
"""Eval harness CLI (PD-ML-003) — score an extractor/decision backend on a split.

Records the frozen baseline every later model reports against. Default scores the
status-quo "review everything" decision backend on the held-out month and writes a
report under `ML_REPORT_DIR`.

Examples:
    python scripts/eval_ml.py --backend tesseract --split test
    python scripts/eval_ml.py --dataset-version 2026-05 --with-fields
    python scripts/eval_ml.py --triage-model data/ml/models/triage.json   # compare triage
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_BACKEND = _REPO / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from ml.eval.e2e import RouteFn  # noqa: E402
from ml.eval.run_baseline import evaluate_fields, run_e2e, write_report  # noqa: E402
from perdiem.config import settings  # noqa: E402


def _anchor(p: str) -> str:
    return p if not p or Path(p).is_absolute() else str(_REPO / p)


def _latest_version(datasets_root: Path) -> str | None:
    if not datasets_root.is_dir():
        return None
    versions = [d.name for d in datasets_root.iterdir() if (d / "text.jsonl").exists()]
    return max(versions) if versions else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-version", default=settings.dataset_version or None)
    parser.add_argument("--split", default="test")
    parser.add_argument("--backend", default="tesseract", help="extractor for --with-fields")
    parser.add_argument("--with-fields", action="store_true", help="also run per-field extraction")
    parser.add_argument("--triage-model", default="", help="triage artifact to compare vs baseline")
    parser.add_argument("--out-dir", default=settings.ml_report_dir)
    args = parser.parse_args(argv)

    datasets_root = Path(_anchor(settings.ml_dataset_dir))
    version = args.dataset_version or _latest_version(datasets_root)
    if not version:
        parser.error(f"no dataset found under {datasets_root}; build one with PD-ML-002 first")
    dataset_dir = datasets_root / version

    # Optional triage backend (PD-ML-004) — only if the artifact exists. We score it
    # at its calibrated threshold AND at an advisory 0.70 cut so the report shows the
    # achievable queue-reduction tradeoff even when the safe cut abstains.
    extra: dict[str, RouteFn] = {}
    triage_path = _anchor(args.triage_model) if args.triage_model else ""
    score_reason = False
    if triage_path and Path(triage_path).exists():
        from ml.triage.infer_adapter import make_route_fn
        from perdiem.config import settings as s
        from perdiem.engine.triage import TriageConfig

        calibrated = TriageConfig(
            enabled=True,
            model_path=triage_path,
            autopass_min_conf=s.triage_autopass_min_conf,
            review_band=s.triage_review_band,
        )
        advisory = TriageConfig(
            enabled=True, model_path=triage_path, autopass_min_conf=0.70, review_band=0.05
        )
        extra["triage_calibrated"] = make_route_fn(triage_path, calibrated)
        extra["triage@0.70"] = make_route_fn(triage_path, advisory)
        score_reason = True
        print(f"Comparing triage backend: {triage_path}")

    print(f"Scoring dataset '{version}' split '{args.split}' …")
    report = run_e2e(dataset_dir, split=args.split, extra_backends=extra or None)

    if score_reason:
        from ml.eval.e2e import load_text_rows as _load
        from ml.eval.run_baseline import score_reason_hint

        report.reason = score_reason_hint(triage_path, _load(dataset_dir, split=args.split))

    if args.with_fields:
        from ml.eval.e2e import load_text_rows  # noqa: F401  (kept for symmetry)
        from perdiem.engine.ocr.base import TesseractExtractor
        vision_path = dataset_dir / "vision.jsonl"
        vision_rows = []
        if vision_path.exists():
            with vision_path.open(encoding="utf-8") as f:
                vision_rows = [json.loads(line) for line in f if line.strip()]
            vision_rows = [r for r in vision_rows if r.get("split") == args.split]
        report.field_metrics = evaluate_fields(TesseractExtractor(), vision_rows)

    md_path = write_report(report, _anchor(args.out_dir))
    for name, m in report.backends.items():
        print(
            f"  {name:12} review={m.review_queue_frac:.3f} "
            f"auto_pass={m.auto_pass_frac:.3f} match={m.auto_pass_match_master:.3f} "
            f"disagree={m.disagreement_rate:.3f}"
        )
    print(f"  report → {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
