#!/usr/bin/env python3
"""Fine-tune the Donut roster reader (PD-ML-006) — run OFF-PI on a GPU machine.

Requires:
    pip install transformers torch accelerate

On Google Colab (free T4 GPU):
    !git clone <repo> && cd flight-perdiem
    !pip install transformers torch accelerate
    !cd backend && python ../scripts/train_donut.py --epochs 5 --synthetic-n 500

Usage:
    python scripts/train_donut.py
    python scripts/train_donut.py --out data/ml/models/donut --epochs 10
    python scripts/train_donut.py --synthetic-n 1000 --aug-per-image 4
    python scripts/train_donut.py --vision-jsonl data/ml/datasets/2026-05/vision.jsonl

After training, export to ONNX for Pi inference:
    python scripts/export_donut_onnx.py --model data/ml/models/donut
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_BACKEND = _REPO / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from perdiem.config import settings  # noqa: E402


def _anchor(p: str) -> str:
    return p if not p or Path(p).is_absolute() else str(_REPO / p)


def main(argv: list[str] | None = None) -> int:
    import logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        default=_anchor(settings.donut_model_path),
        help="Output directory for the trained HuggingFace model",
    )
    parser.add_argument(
        "--base-model",
        default="naver-clova-ix/donut-base",
        help="HuggingFace model ID to fine-tune from",
    )
    parser.add_argument(
        "--dataset-version",
        default=settings.dataset_version or "2026-05",
        help="Dataset version label (informational; used to locate vision.jsonl)",
    )
    parser.add_argument(
        "--vision-jsonl",
        default="",
        help="Path to vision.jsonl with real labelled roster rows (optional)",
    )
    parser.add_argument("--synthetic-n", type=int, default=500, help="Synthetic images to generate")
    parser.add_argument("--aug-per-image", type=int, default=3, help="Augmented variants per image")
    parser.add_argument("--epochs", type=int, default=5)
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--lr", type=float, default=5e-5)
    parser.add_argument("--max-length", type=int, default=512)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args(argv)

    # Resolve vision.jsonl: explicit flag > default dataset path
    vision_jsonl = args.vision_jsonl
    if not vision_jsonl:
        default_path = (
            Path(_anchor(settings.ml_dataset_dir))
            / args.dataset_version
            / "vision.jsonl"
        )
        if default_path.exists():
            vision_jsonl = str(default_path)

    # Import after arg parse so --help works without torch installed.
    try:
        from ml.donut.train import DonutTrainConfig, train
    except ImportError as exc:
        print(f"ERROR: {exc}")
        print("Install training deps: pip install transformers torch accelerate")
        return 1

    cfg = DonutTrainConfig(
        base_model=args.base_model,
        n_synthetic=args.synthetic_n,
        n_synthetic_aug=args.aug_per_image,
        max_length=args.max_length,
        batch_size=args.batch_size,
        learning_rate=args.lr,
        epochs=args.epochs,
        seed=args.seed,
    )

    print(f"Fine-tuning Donut roster reader")
    print(f"  base model    : {cfg.base_model}")
    print(f"  synthetic     : {cfg.n_synthetic} images × {cfg.n_synthetic_aug} augmentations")
    print(f"  vision rows   : {vision_jsonl or '(none — using synthetic only)'}")
    print(f"  epochs        : {cfg.epochs}  batch={cfg.batch_size}  lr={cfg.learning_rate}")
    print(f"  output        : {args.out}")
    print()

    train(
        args.out,
        dataset_version=args.dataset_version,
        vision_jsonl=vision_jsonl,
        cfg=cfg,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
