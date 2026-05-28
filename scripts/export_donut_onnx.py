"""Export fine-tuned Donut to ONNX + int8 quantise (PD-ML-006 task 4).

Run on the GPU machine where training completed (Colab or similar):

    python scripts/export_donut_onnx.py \\
        --model data/ml/models/donut \\
        --out   data/ml/models/donut-onnx

Output layout::

    <out>/
        encoder.onnx        (float32)
        decoder.onnx        (float32)
        encoder_q8.onnx     (int8 quantised)
        decoder_q8.onnx     (int8 quantised)
        processor/          (tokenizer + image processor for onnxruntime inference)

Copy the quantised pair + processor/ to the Pi, then set
DONUT_ENABLED=true and DONUT_MODEL_PATH pointing to the out dir.

Required (GPU machine):
    pip install transformers torch onnx onnxruntime
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Module wrappers (cleanly exportable sub-graphs)
# ---------------------------------------------------------------------------

def _make_encoder_wrapper(model):
    import torch

    class _Enc(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.encoder = model.encoder

        def forward(self, pixel_values: torch.Tensor) -> torch.Tensor:
            return self.encoder(pixel_values).last_hidden_state

    return _Enc()


def _make_decoder_wrapper(model):
    """Decoder wrapper without KV cache (full-sequence, compatible with _run_onnx).

    Dynamic axes on input_ids and encoder_hidden_states let the exported graph
    handle any sequence length — the inference loop in ml_extract._run_onnx()
    passes the full accumulated token list at each step.
    """
    import torch

    class _Dec(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.decoder = model.decoder

        def forward(
            self,
            input_ids: torch.Tensor,
            encoder_hidden_states: torch.Tensor,
        ) -> torch.Tensor:
            return self.decoder(
                input_ids=input_ids,
                encoder_hidden_states=encoder_hidden_states,
                use_cache=False,
            ).logits

    return _Dec()


# ---------------------------------------------------------------------------
# Export helpers
# ---------------------------------------------------------------------------

def _export_encoder(model, h: int, w: int, out_dir: Path, opset: int) -> Path:
    import torch

    wrapper = _make_encoder_wrapper(model)
    wrapper.eval()
    dummy = torch.zeros(1, 3, h, w)

    out_path = out_dir / "encoder.onnx"
    print(f"  exporting encoder  → {out_path}")
    with torch.no_grad():
        torch.onnx.export(
            wrapper,
            (dummy,),
            str(out_path),
            input_names=["pixel_values"],
            output_names=["encoder_hidden_states"],
            dynamic_axes={"pixel_values": {0: "batch"}},
            opset_version=opset,
            do_constant_folding=True,
        )
    print(f"  encoder.onnx       {out_path.stat().st_size / 1e6:.1f} MB")
    return out_path


def _export_decoder(
    model,
    enc_seq_len: int,
    enc_hidden: int,
    out_dir: Path,
    opset: int,
) -> Path:
    import torch

    wrapper = _make_decoder_wrapper(model)
    wrapper.eval()
    dummy_ids = torch.zeros(1, 4, dtype=torch.long)
    dummy_enc = torch.zeros(1, enc_seq_len, enc_hidden)

    out_path = out_dir / "decoder.onnx"
    print(f"  exporting decoder  → {out_path}")
    with torch.no_grad():
        torch.onnx.export(
            wrapper,
            (dummy_ids, dummy_enc),
            str(out_path),
            input_names=["input_ids", "encoder_hidden_states"],
            output_names=["logits"],
            dynamic_axes={
                "input_ids":             {0: "batch", 1: "dec_seq"},
                "encoder_hidden_states": {0: "batch", 1: "enc_seq"},
                "logits":                {0: "batch", 1: "dec_seq"},
            },
            opset_version=opset,
            do_constant_folding=True,
        )
    print(f"  decoder.onnx       {out_path.stat().st_size / 1e6:.1f} MB")
    return out_path


def _quantise(fp32_path: Path) -> Path:
    from onnxruntime.quantization import QuantType, quantize_dynamic

    q_path = fp32_path.with_name(fp32_path.stem + "_q8.onnx")
    print(f"  quantising         {fp32_path.name} → {q_path.name}")
    quantize_dynamic(str(fp32_path), str(q_path), weight_type=QuantType.QInt8)
    print(f"  {q_path.name:<20} {q_path.stat().st_size / 1e6:.1f} MB")
    return q_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Export Donut to ONNX + int8")
    ap.add_argument("--model", default="data/ml/models/donut",
                    help="Fine-tuned HuggingFace model dir (default: data/ml/models/donut)")
    ap.add_argument("--out", default="data/ml/models/donut-onnx",
                    help="Output dir for ONNX artefacts (default: data/ml/models/donut-onnx)")
    ap.add_argument("--opset", type=int, default=14,
                    help="ONNX opset version (default: 14)")
    ap.add_argument("--image-size", default="960,1280",
                    help="H,W matching training config (default: 960,1280)")
    ap.add_argument("--skip-quantize", action="store_true",
                    help="Export fp32 only (skip int8 quantisation)")
    args = ap.parse_args()

    try:
        import torch
        from transformers import DonutProcessor, VisionEncoderDecoderModel
    except ImportError:
        sys.exit("Missing deps — run: pip install transformers torch onnx onnxruntime")

    model_path = Path(args.model)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    h, w = (int(x) for x in args.image_size.split(","))

    print(f"Loading model from {model_path} …")
    model = VisionEncoderDecoderModel.from_pretrained(str(model_path))
    processor = DonutProcessor.from_pretrained(str(model_path))
    model.eval()

    # Processor (tokenizer + image processor) — required for onnxruntime inference
    proc_dir = out_dir / "processor"
    print(f"Saving processor   → {proc_dir}")
    processor.save_pretrained(str(proc_dir))

    print("\n[Encoder]")
    enc_path = _export_encoder(model, h, w, out_dir, args.opset)

    # Probe encoder output shape for the decoder dummy
    import torch
    with torch.no_grad():
        enc_out = model.encoder(torch.zeros(1, 3, h, w)).last_hidden_state
    enc_seq, enc_hid = enc_out.shape[1], enc_out.shape[2]
    print(f"  enc output shape   seq={enc_seq}  hidden={enc_hid}")

    print("\n[Decoder]")
    dec_path = _export_decoder(model, enc_seq, enc_hid, out_dir, args.opset)

    if not args.skip_quantize:
        print("\n[Quantisation — int8]")
        enc_q = _quantise(enc_path)
        dec_q = _quantise(dec_path)
        total_mb = (enc_q.stat().st_size + dec_q.stat().st_size) / 1e6
        print(f"\n  Combined int8 size {total_mb:.1f} MB  (target < 500 MB)")
    else:
        total_mb = (enc_path.stat().st_size + dec_path.stat().st_size) / 1e6
        print(f"\n  Combined fp32 size {total_mb:.1f} MB  (quantisation skipped)")

    print(f"\nDone.  ONNX artefacts at: {out_dir}")
    print("Next steps:")
    print("  1. Copy *_q8.onnx + processor/ to the Pi under data/ml/models/donut-onnx/")
    print("  2. Run scripts/bench_donut.py --onnx-dir <path> --image <roster>")
    print("  3. Set DONUT_ENABLED=true  DONUT_MODEL_PATH=<path> in .env")


if __name__ == "__main__":
    main()
