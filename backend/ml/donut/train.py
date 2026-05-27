"""Fine-tune Donut on synthetic + real roster images (PD-ML-006).

Run off-Pi on a machine with a GPU or Apple Silicon (MPS).
Required: pip install transformers torch accelerate

Training strategy
-----------------
* Synthetic data from ml/roster_gen is the majority source (generated on-the-fly,
  no PII). Real vision rows from vision.jsonl are mixed in when available.
* Each example: (roster image, DONUT_PROMPT) → JSON from to_label_json()
* Base model: naver-clova-ix/donut-base fine-tuned as VisionEncoderDecoder.

Device priority: CUDA (NVIDIA) > MPS (Apple Silicon) > CPU
"""
from __future__ import annotations

import json
import logging
import os
import random
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import torch
import torch.utils.data
from PIL import Image as PilImage

logger = logging.getLogger(__name__)

DONUT_PROMPT = "<s_perdiem_roster>"
_LABEL_KEY = "label_json"


# ---------------------------------------------------------------------------
# Training configuration
# ---------------------------------------------------------------------------

@dataclass
class DonutTrainConfig:
    base_model: str = "naver-clova-ix/donut-base"
    n_synthetic: int = 500
    n_synthetic_aug: int = 3
    max_length: int = 512
    image_size: tuple = (1280, 960)   # (width, height)
    batch_size: int = 2
    learning_rate: float = 5e-5
    epochs: int = 5
    warmup_steps: int = 100
    seed: int = 42


def _best_device() -> str:
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


# ---------------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------------

def _synthetic_examples(
    n: int,
    aug_per_image: int,
    image_dir: Path,
    rng: random.Random,
) -> list[dict[str, Any]]:
    from ml.doctype.augment import augment_image
    from ml.roster_gen.generate import generate_roster
    from ml.roster_gen.renderer import render_roster
    import cv2

    examples: list[dict] = []
    for i in range(n):
        data = generate_roster(rng)
        img = render_roster(data)
        label = json.dumps(data.to_label_json(), ensure_ascii=False)
        orig_path = image_dir / f"syn_{i:05d}.jpg"
        cv2.imwrite(str(orig_path), img)
        examples.append({"image_path": str(orig_path), "target": label})
        for j, aug in enumerate(augment_image(img, n=aug_per_image, seed=i)):
            aug_path = image_dir / f"syn_{i:05d}_aug{j}.jpg"
            cv2.imwrite(str(aug_path), aug)
            examples.append({"image_path": str(aug_path), "target": label})
    return examples


def _vision_examples(vision_jsonl: Path, split: str = "train") -> list[dict[str, Any]]:
    if not vision_jsonl.exists():
        return []
    examples: list[dict] = []
    with vision_jsonl.open(encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            if row.get("split") != split:
                continue
            img_path = row.get("local_path") or row.get("image_path")
            label = row.get(_LABEL_KEY)
            if not img_path or not Path(img_path).exists() or not label:
                continue
            target = json.dumps(label) if isinstance(label, dict) else str(label)
            examples.append({"image_path": img_path, "target": target})
    logger.info("Loaded %d real vision examples", len(examples))
    return examples


class RosterDataset(torch.utils.data.Dataset):
    """PyTorch Dataset wrapping synthetic + real roster examples."""

    def __init__(self, examples: list[dict], processor: Any, max_length: int) -> None:
        self.examples = examples
        self.processor = processor
        self.max_length = max_length

    def __len__(self) -> int:
        return len(self.examples)

    def __getitem__(self, idx: int) -> dict:
        ex = self.examples[idx]
        image = PilImage.open(ex["image_path"]).convert("RGB")
        pixel_values = self.processor(image, return_tensors="pt").pixel_values.squeeze(0)

        encoding = self.processor.tokenizer(
            ex["target"],
            add_special_tokens=False,
            max_length=self.max_length,
            padding="max_length",
            truncation=True,
            return_tensors="pt",
        )
        labels = encoding.input_ids.squeeze(0).clone()
        labels[labels == self.processor.tokenizer.pad_token_id] = -100
        return {"pixel_values": pixel_values, "labels": labels}


# ---------------------------------------------------------------------------
# Training entry-point
# ---------------------------------------------------------------------------

def train(
    output_dir: str,
    *,
    dataset_version: str = "",
    vision_jsonl: str = "",
    cfg: DonutTrainConfig | None = None,
) -> None:
    """Fine-tune Donut and save to `output_dir` (HuggingFace model directory)."""
    from transformers import (
        Seq2SeqTrainer,
        Seq2SeqTrainingArguments,
        VisionEncoderDecoderModel,
    )
    try:
        from transformers import DonutProcessor
    except ImportError:
        from transformers import AutoProcessor as DonutProcessor  # type: ignore[no-redef]

    cfg = cfg or DonutTrainConfig()
    rng = random.Random(cfg.seed)
    device = _best_device()
    os.makedirs(output_dir, exist_ok=True)
    logger.info("Device: %s", device)

    # ── Load base model + processor ─────────────────────────────────────────
    logger.info("Loading base model: %s", cfg.base_model)
    processor = DonutProcessor.from_pretrained(cfg.base_model)
    model = VisionEncoderDecoderModel.from_pretrained(cfg.base_model)

    processor.image_processor.size = {
        "height": cfg.image_size[1],
        "width": cfg.image_size[0],
    }

    # Register the task-specific prompt token if not already present.
    if DONUT_PROMPT not in processor.tokenizer.get_vocab():
        processor.tokenizer.add_special_tokens({"additional_special_tokens": [DONUT_PROMPT]})
        model.decoder.resize_token_embeddings(len(processor.tokenizer))

    model.config.decoder_start_token_id = processor.tokenizer.convert_tokens_to_ids(DONUT_PROMPT)
    model.config.pad_token_id = processor.tokenizer.pad_token_id
    model.config.eos_token_id = processor.tokenizer.eos_token_id

    # ── Precision flags — fp16 needs CUDA, bf16 works on CUDA + MPS ─────────
    use_fp16 = device == "cuda"
    use_bf16 = device == "mps" and hasattr(torch, "bfloat16")

    # ── Assemble dataset ────────────────────────────────────────────────────
    with tempfile.TemporaryDirectory(prefix="donut_syn_") as tmp:
        image_dir = Path(tmp)
        logger.info("Generating %d synthetic rosters (aug=%d) …", cfg.n_synthetic, cfg.n_synthetic_aug)
        syn = _synthetic_examples(cfg.n_synthetic, cfg.n_synthetic_aug, image_dir, rng)

        real = _vision_examples(Path(vision_jsonl)) if vision_jsonl else []
        if real:
            logger.info("Mixing in %d real vision examples", len(real))

        all_examples = syn + real
        rng.shuffle(all_examples)

        n_val = max(1, int(len(all_examples) * 0.10))
        val_examples  = all_examples[:n_val]
        train_examples = all_examples[n_val:]
        logger.info(
            "Dataset: %d train + %d val (synthetic=%d real=%d)",
            len(train_examples), len(val_examples), len(syn), len(real),
        )

        train_ds = RosterDataset(train_examples, processor, cfg.max_length)
        val_ds   = RosterDataset(val_examples,   processor, cfg.max_length)

        # ── Training arguments (transformers 5.x uses eval_strategy) ────────
        train_kwargs: dict[str, Any] = dict(
            output_dir=output_dir,
            num_train_epochs=cfg.epochs,
            per_device_train_batch_size=cfg.batch_size,
            per_device_eval_batch_size=cfg.batch_size,
            learning_rate=cfg.learning_rate,
            warmup_steps=cfg.warmup_steps,
            predict_with_generate=True,
            fp16=use_fp16,
            bf16=use_bf16,
            save_strategy="epoch",
            load_best_model_at_end=True,
            logging_steps=50,
            seed=cfg.seed,
            dataloader_num_workers=0,   # avoid fork issues on macOS
        )
        # Handle both transformers 4.x (evaluation_strategy) and 5.x (eval_strategy).
        try:
            Seq2SeqTrainingArguments(eval_strategy="epoch", output_dir=output_dir)
            train_kwargs["eval_strategy"] = "epoch"
        except TypeError:
            train_kwargs["evaluation_strategy"] = "epoch"

        training_args = Seq2SeqTrainingArguments(**train_kwargs)

        trainer = Seq2SeqTrainer(
            model=model,
            args=training_args,
            train_dataset=train_ds,
            eval_dataset=val_ds,
        )

        logger.info("Starting training on %s …", device)
        trainer.train()

    # ── Save ─────────────────────────────────────────────────────────────────
    model.save_pretrained(output_dir)
    processor.save_pretrained(output_dir)
    logger.info("Model saved to %s", output_dir)
    print(f"\nDone — model at {output_dir}")
    print("Next: export to ONNX with  scripts/export_donut_onnx.py  (PD-ML-006 task 4)")
