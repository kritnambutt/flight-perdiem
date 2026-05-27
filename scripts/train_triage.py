#!/usr/bin/env python3
"""Train the triage + reason classifier (PD-ML-004) from a built dataset.

Trains on the dataset's train+val splits (never test — no leakage) and writes a JSON
artifact scored at inference by the pure `perdiem.engine.triage`. Off-Pi step.

Examples:
    python scripts/train_triage.py --dataset-version dev
    python scripts/train_triage.py --dataset-version 2026-05 --out data/ml/models/triage.json
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_BACKEND = _REPO / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from ml.eval.e2e import load_text_rows  # noqa: E402
from ml.triage.train import save_artifact, train  # noqa: E402
from perdiem.config import settings  # noqa: E402


def _anchor(p: str) -> str:
    return p if not p or Path(p).is_absolute() else str(_REPO / p)


def _latest_version(root: Path) -> str | None:
    if not root.is_dir():
        return None
    versions = [d.name for d in root.iterdir() if (d / "text.jsonl").exists()]
    return max(versions) if versions else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-version", default=settings.dataset_version or None)
    parser.add_argument("--out", default=settings.triage_model_path)
    parser.add_argument("--review-band", type=float, default=settings.triage_review_band)
    parser.add_argument("--autopass-precision", type=float, default=0.90)
    args = parser.parse_args(argv)

    root = Path(_anchor(settings.ml_dataset_dir))
    version = args.dataset_version or _latest_version(root)
    if not version:
        parser.error(f"no dataset under {root}; build one with PD-ML-002 first")
    dataset_dir = root / version

    train_rows = load_text_rows(dataset_dir, split="train")
    val_rows = load_text_rows(dataset_dir, split="val")
    print(f"Training triage on '{version}': {len(train_rows)} train / {len(val_rows)} val …")

    result = train(
        train_rows,
        val_rows,
        dataset_version=version,
        autopass_target_precision=args.autopass_precision,
        review_band=args.review_band,
    )
    out_path = _anchor(args.out)
    save_artifact(result.artifact, out_path)

    th = result.artifact["thresholds"]
    print(f"  features        : {len(result.artifact['feature_names'])}")
    print(f"  triage classes  : {result.artifact['triage']['classes']}")
    print(f"  reason classes  : {result.artifact['reason']['classes']}")
    print(f"  autopass_min_conf: {th['autopass_min_conf']} (review_band {th['review_band']})")
    print(f"  artifact → {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
