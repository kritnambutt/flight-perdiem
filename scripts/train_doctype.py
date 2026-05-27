#!/usr/bin/env python3
"""Train the doc-type / quality classifier (PD-ML-005) from fixture images.

Unlike the triage model, this classifier is image-based: it reads labelled
examples directly from docs/example-files/roster-attached-files/ rather than
a pre-built JSONL dataset.  It can therefore be re-trained any time new fixture
images are added to those directories, with no separate dataset-build step.

Label assignment:
  correct/                      → VALID_ROSTER
  incorrect/*invalid formatted* → NOT_A_ROSTER
  incorrect/*                   → VALID_ROSTER (valid roster that fails rules,
                                   not a doc-type problem)
  (UNREADABLE examples are synthesised via extreme augmentation)

The output is a JSON artifact consumed by the pure perdiem.engine.ocr.doctype
scorer — no ONNX or ML runtime needed at inference time.

Usage:
    python scripts/train_doctype.py
    python scripts/train_doctype.py --out data/ml/models/doctype.json
    python scripts/train_doctype.py --augment 15 --val-split 0.2
    python scripts/train_doctype.py --correct-dir path/to/correct \\
                                    --incorrect-dir path/to/incorrect
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_BACKEND = _REPO / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import random  # noqa: E402

from ml.doctype.train import (  # noqa: E402
    CLASSES,
    build_feature_rows,
    load_fixture_images,
    save_artifact,
    train,
)
from perdiem.config import settings  # noqa: E402


def _anchor(p: str) -> str:
    """Resolve a relative path against the repo root."""
    return p if not p or Path(p).is_absolute() else str(_REPO / p)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--correct-dir",
        default=str(_REPO / "docs/example-files/roster-attached-files/correct"),
        help="Directory of VALID_ROSTER fixture images",
    )
    parser.add_argument(
        "--incorrect-dir",
        default=str(_REPO / "docs/example-files/roster-attached-files/incorrect"),
        help="Directory of NOT_A_ROSTER / VALID_ROSTER fixture images",
    )
    parser.add_argument(
        "--out",
        default=_anchor(settings.doctype_model_path),
        help="Output path for the JSON model artifact",
    )
    parser.add_argument(
        "--augment",
        type=int,
        default=12,
        help="Number of augmented variants to generate per fixture image (default 12)",
    )
    parser.add_argument(
        "--val-split",
        type=float,
        default=0.20,
        help="Fraction of augmented rows to hold out as validation (default 0.20)",
    )
    parser.add_argument(
        "--min-conf",
        type=float,
        default=settings.doctype_min_conf,
        help="Minimum confidence threshold written into the artifact (default from settings)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducible train/val split",
    )
    args = parser.parse_args(argv)

    # ── Load fixtures ────────────────────────────────────────────────────────
    print(f"Loading fixtures …")
    print(f"  correct   → {args.correct_dir}")
    print(f"  incorrect → {args.incorrect_dir}")
    image_label_pairs = load_fixture_images(args.correct_dir, args.incorrect_dir)
    if not image_label_pairs:
        print("ERROR: no fixture images loaded. "
              "Check --correct-dir and --incorrect-dir paths.")
        return 1

    label_counts = {lbl: sum(1 for _, l in image_label_pairs if l == lbl) for lbl in CLASSES}
    print(f"  fixtures loaded: {len(image_label_pairs)} "
          f"({', '.join(f'{lbl}: {n}' for lbl, n in label_counts.items() if n)})")

    # ── Build feature rows with augmentation ────────────────────────────────
    print(f"Extracting features (augment={args.augment} variants per image) …")
    rows = build_feature_rows(image_label_pairs, augment_per_image=args.augment)

    # ── Train / val split ───────────────────────────────────────────────────
    rng = random.Random(args.seed)
    rng.shuffle(rows)
    n_val = max(1, int(len(rows) * args.val_split))
    val_rows = rows[:n_val]
    train_rows = rows[n_val:]

    row_dist = lambda split: ", ".join(  # noqa: E731
        f"{lbl}: {sum(1 for _, l in split if l == lbl)}" for lbl in CLASSES
    )
    print(f"  train: {len(train_rows)} rows ({row_dist(train_rows)})")
    print(f"  val:   {len(val_rows)} rows ({row_dist(val_rows)})")

    # ── Train ────────────────────────────────────────────────────────────────
    # Derive a version tag from the dataset source (no JSONL needed).
    version = f"fixtures-{len(image_label_pairs)}img-aug{args.augment}"
    print(f"Training doctype classifier (version '{version}') …")
    result = train(
        train_rows,
        val_rows,
        dataset_version=version,
        min_conf=args.min_conf,
    )

    # ── Save ─────────────────────────────────────────────────────────────────
    out_path = args.out
    save_artifact(result.artifact, out_path)

    val_acc = result.artifact.get("val_accuracy")
    print()
    print("  doctype classifier trained")
    print(f"  features   : {len(result.artifact['feature_names'])}")
    print(f"  classes    : {result.artifact['classes']}")
    print(f"  train rows : {result.train_rows}")
    print(f"  val rows   : {result.val_rows}")
    if val_acc is not None:
        print(f"  val acc    : {val_acc * 100:.1f}%")
    print(f"  min_conf   : {result.artifact['thresholds']['min_conf']}")
    print(f"  artifact → {out_path}")
    print()
    print("To enable in the worker:")
    print("  Set DOCTYPE_ENABLED=true in your .env")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
