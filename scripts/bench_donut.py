"""Benchmark Donut ONNX inference on Pi-class CPU (PD-ML-006 task 4).

Run on the Pi (or any machine) after exporting ONNX:

    python scripts/bench_donut.py \\
        --onnx-dir data/ml/models/donut-onnx \\
        --image    "docs/example-files/IMG_4481 - Rattanaporn Boonin (correct format).jpeg"

Optional: also time the original HuggingFace torch model (on the export machine):

    python scripts/bench_donut.py \\
        --onnx-dir  data/ml/models/donut-onnx \\
        --torch-dir data/ml/models/donut \\
        --image     <roster>

Prefer quantised artefacts (*_q8.onnx) when available; falls back to fp32.
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

DONUT_PROMPT = "<s_perdiem_roster>"
MAX_NEW_TOKENS = 512


def _bench_onnx(onnx_dir: str, image_path: str, n: int) -> None:
    try:
        import numpy as np
        import onnxruntime as ort
        from PIL import Image as PilImage
        from transformers import DonutProcessor
    except ImportError as exc:
        print(f"  skipped — missing dep: {exc}")
        return

    model_dir = Path(onnx_dir)
    proc_dir = model_dir / "processor"

    enc_name = "encoder_q8.onnx" if (model_dir / "encoder_q8.onnx").exists() else "encoder.onnx"
    dec_name = "decoder_q8.onnx" if (model_dir / "decoder_q8.onnx").exists() else "decoder.onnx"
    enc_file = str(model_dir / enc_name)
    dec_file = str(model_dir / dec_name)
    print(f"  encoder : {enc_name}  ({Path(enc_file).stat().st_size / 1e6:.1f} MB)")
    print(f"  decoder : {dec_name}  ({Path(dec_file).stat().st_size / 1e6:.1f} MB)")

    processor = DonutProcessor.from_pretrained(str(proc_dir))
    image = PilImage.open(image_path).convert("RGB")
    pixel_values = processor(image, return_tensors="np").pixel_values.astype(np.float32)

    enc_sess = ort.InferenceSession(enc_file)
    dec_sess = ort.InferenceSession(dec_file)

    eos_id = processor.tokenizer.eos_token_id
    prompt_ids: list[int] = processor.tokenizer(DONUT_PROMPT, add_special_tokens=False)["input_ids"]

    enc_times: list[float] = []
    dec_times: list[float] = []
    tok_counts: list[int] = []

    for i in range(n):
        # --- encode ---
        t0 = time.perf_counter()
        enc_out = enc_sess.run(None, {"pixel_values": pixel_values})[0]
        enc_times.append(time.perf_counter() - t0)

        # --- decode (greedy, full-sequence at each step) ---
        generated = list(prompt_ids)
        d0 = time.perf_counter()
        for _ in range(MAX_NEW_TOKENS):
            input_ids = np.array([generated], dtype=np.int64)
            logits = dec_sess.run(None, {
                "input_ids": input_ids,
                "encoder_hidden_states": enc_out,
            })[0]
            next_id = int(np.argmax(logits[0, -1]))
            if next_id == eos_id:
                break
            generated.append(next_id)
        dec_times.append(time.perf_counter() - d0)
        tok_counts.append(len(generated) - len(prompt_ids))

        if n > 1:
            total = enc_times[-1] + dec_times[-1]
            print(f"  run {i+1}/{n}: enc {enc_times[-1]*1e3:.0f} ms  "
                  f"dec {dec_times[-1]*1e3:.0f} ms  "
                  f"tokens {tok_counts[-1]}  total {total*1e3:.0f} ms")

    avg_enc = sum(enc_times) / n
    avg_dec = sum(dec_times) / n
    avg_tok = sum(tok_counts) / n
    avg_total = avg_enc + avg_dec
    tps = avg_tok / avg_dec if avg_dec > 0 else 0

    print(f"\n  avg encode   {avg_enc*1e3:.0f} ms")
    print(f"  avg decode   {avg_dec*1e3:.0f} ms  ({avg_tok:.0f} tokens, {tps:.1f} tok/s)")
    print(f"  avg total    {avg_total*1e3:.0f} ms")
    _verdict(avg_total)


def _bench_torch(torch_dir: str, image_path: str, n: int) -> None:
    try:
        import torch
        from PIL import Image as PilImage
        from transformers import DonutProcessor, VisionEncoderDecoderModel
    except ImportError as exc:
        print(f"  skipped — missing dep: {exc}")
        return

    print(f"  model : {torch_dir}")
    processor = DonutProcessor.from_pretrained(torch_dir)
    model = VisionEncoderDecoderModel.from_pretrained(torch_dir)
    model.eval()

    image = PilImage.open(image_path).convert("RGB")
    pixel_values = processor(image, return_tensors="pt").pixel_values
    prompt_ids = processor.tokenizer(
        DONUT_PROMPT, add_special_tokens=False, return_tensors="pt",
    )["input_ids"]

    total_times: list[float] = []
    tok_counts: list[int] = []

    with torch.no_grad():
        for i in range(n):
            t0 = time.perf_counter()
            out = model.generate(
                pixel_values,
                decoder_input_ids=prompt_ids,
                max_length=MAX_NEW_TOKENS,
                early_stopping=True,
                pad_token_id=processor.tokenizer.pad_token_id,
                eos_token_id=processor.tokenizer.eos_token_id,
                use_cache=True,
                num_beams=1,
                return_dict_in_generate=True,
            )
            elapsed = time.perf_counter() - t0
            total_times.append(elapsed)
            tok_counts.append(out.sequences.shape[1])
            if n > 1:
                print(f"  run {i+1}/{n}: {elapsed*1e3:.0f} ms  tokens {tok_counts[-1]}")

    avg_total = sum(total_times) / n
    avg_tok = sum(tok_counts) / n
    tps = avg_tok / avg_total if avg_total > 0 else 0
    print(f"\n  avg total    {avg_total*1e3:.0f} ms  ({avg_tok:.0f} tokens, {tps:.1f} tok/s)")
    _verdict(avg_total)


def _verdict(total_s: float) -> None:
    if total_s < 10:
        print("  Pi verdict   FAST — well within batch budget")
    elif total_s < 30:
        print("  Pi verdict   OK — acceptable for batch processing")
    elif total_s < 60:
        print("  Pi verdict   SLOW — consider reducing max_length or image size")
    else:
        print("  Pi verdict   TOO SLOW — consider lighter backbone or Tesseract-only fallback")


def main() -> None:
    ap = argparse.ArgumentParser(description="Benchmark Donut ONNX on CPU")
    ap.add_argument("--onnx-dir", required=True,
                    help="ONNX model directory produced by export_donut_onnx.py")
    ap.add_argument("--torch-dir", default=None,
                    help="Optional HuggingFace dir for torch baseline comparison")
    ap.add_argument("--image", required=True, help="Roster image path")
    ap.add_argument("--n", type=int, default=3,
                    help="Runs to average (default: 3; use 1 on Pi to save time)")
    args = ap.parse_args()

    image = str(Path(args.image).expanduser())
    print(f"Image: {image}\n")

    print("[ONNX inference]")
    _bench_onnx(args.onnx_dir, image, args.n)

    if args.torch_dir:
        print("\n[Torch inference — baseline]")
        _bench_torch(args.torch_dir, image, args.n)


if __name__ == "__main__":
    main()
