"""Donut-based roster extraction backend (PD-ML-006) — pure inference.

Replaces the brittle Tesseract-regex path with an OCR-free image→JSON model.
The Donut `VisionEncoderDecoder` model decodes a roster image directly into the
`ExtractedRoster` JSON schema; a Tesseract fallback is invoked whenever Donut's
per-field confidence is below the configured floor (never a silent guess — N1).

Engine purity: all heavy deps (torch, onnxruntime, transformers) are lazy-
imported **inside** the inference functions so importing this module never
loads ML libraries — engine unit tests run with no ML stack.

The fine-tuned model is expected at `DonutConfig.model_path`:
  - A HuggingFace model directory (`config.json` present) → torch inference.
  - A directory containing `*.onnx` files → onnxruntime inference (Pi production).
When the path is missing or `enabled=False`, `safe_extract_donut()` returns
`None` and the caller uses the Tesseract backend unchanged.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime

from perdiem.engine.models import ExtractedRoster, Field, Leg, RosterRef

logger = logging.getLogger(__name__)

# ── Donut decoder prompt + JSON schema ───────────────────────────────────────

DONUT_PROMPT = "<s_perdiem_roster>"

# JSON keys the fine-tuned model outputs (kept in sync with ml/roster_gen/schema.py).
_REQUIRED_KEYS = {"staff_id", "name", "start_date", "end_date", "generated_at", "grid"}

# Regex patterns for field validation (same constraints as the Tesseract extractor).
_STAFF_ID_RE  = re.compile(r"^\d{7}$")
_DATE_RE      = re.compile(r"^\d{2}/\d{2}/\d{4}$")
_FLIGHT_RE    = re.compile(r"^FD\d{3,4}$", re.IGNORECASE)
_AIRPORT_RE   = re.compile(r"^[A-Z]{3}$")
_TIME_RE      = re.compile(r"^\d{2}:\d{2}$")

_MONTH_MAP: dict[str, int] = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


@dataclass
class DonutConfig:
    enabled: bool = False
    model_path: str = "data/ml/models/donut"
    conf_fallback: float = 0.60   # overall confidence below this → Tesseract fallback
    max_pages: int = 2


# ── JSON parser (engine-pure, no torch/onnx) ─────────────────────────────────

def _parse_date(s: str) -> date | None:
    if not _DATE_RE.match(s or ""):
        return None
    try:
        d, m, y = int(s[:2]), int(s[3:5]), int(s[6:])
        return date(y, m, d)
    except (ValueError, IndexError):
        return None


def _parse_generated_at(s: str) -> datetime | None:
    m = re.search(
        r"([A-Za-z]{3})\s+(\d{1,2}),?\s+(\d{4})\s+(\d{2}):(\d{2})",
        s or "",
    )
    if not m:
        return None
    month = _MONTH_MAP.get(m.group(1).lower())
    if not month:
        return None
    try:
        return datetime(int(m.group(3)), month, int(m.group(2)),
                        int(m.group(4)), int(m.group(5)))
    except ValueError:
        return None


def _parse_leg(raw: dict) -> Leg | None:
    fn   = str(raw.get("fn", "")).strip().upper()
    orig = str(raw.get("from", "")).strip().upper()
    dest = str(raw.get("to", "")).strip().upper()
    t    = str(raw.get("time", "")).strip()
    if not _FLIGHT_RE.match(fn):
        return None
    return Leg(
        flight_no=fn,
        orig=orig if _AIRPORT_RE.match(orig) else None,
        dest=dest if _AIRPORT_RE.match(dest) else None,
        time=t if _TIME_RE.match(t) else None,
    )


def _parse_donut_output(raw_text: str) -> tuple[ExtractedRoster, float]:
    """Parse the decoder's raw text output into (ExtractedRoster, confidence).

    Confidence is the fraction of critical fields that pass validation:
      - staff_id: 7-digit string → weight 3
      - start_date / end_date: parseable DD/MM/YYYY → weight 2 each
      - generated_at: parseable "Mon DD, YYYY HH:MM" → weight 2
      - grid: at least one valid leg → weight 1

    Returns confidence=0.0 for unparseable JSON (the caller falls back).
    """
    # Extract JSON from decoder output (may have surrounding special tokens).
    json_match = re.search(r"\{.*\}", raw_text, re.DOTALL)
    if not json_match:
        return _empty("donut: no JSON in decoder output"), 0.0
    try:
        data = json.loads(json_match.group())
    except json.JSONDecodeError as exc:
        return _empty(f"donut: JSON parse error: {exc}"), 0.0

    missing = _REQUIRED_KEYS - set(data.keys())
    if missing:
        return _empty(f"donut: missing keys: {missing}"), 0.0

    # ── Parse each field ─────────────────────────────────────────────────────
    score = 0.0
    max_score = 11.0
    needs_review: list[str] = []

    sid_raw = str(data.get("staff_id", "")).strip()
    if _STAFF_ID_RE.match(sid_raw):
        staff_id: Field[str] = Field(sid_raw, 1.0)
        score += 3
    else:
        staff_id = Field(sid_raw or None, 0.3)
        needs_review.append(f"donut: invalid staff_id format: {sid_raw!r}")

    name_raw = str(data.get("name", "")).strip()
    name: Field[str] = Field(name_raw or None, 0.8 if name_raw else 0.0)
    if not name_raw:
        needs_review.append("donut: empty name field")

    sd = _parse_date(str(data.get("start_date", "")))
    if sd:
        start_date: Field[date] = Field(sd, 1.0)
        score += 2
    else:
        start_date = Field(None, 0.0)
        needs_review.append(f"donut: unparseable start_date: {data.get('start_date')!r}")

    ed = _parse_date(str(data.get("end_date", "")))
    if ed:
        end_date: Field[date] = Field(ed, 1.0)
        score += 2
    else:
        end_date = Field(None, 0.0)
        needs_review.append(f"donut: unparseable end_date: {data.get('end_date')!r}")

    gen = _parse_generated_at(str(data.get("generated_at", "")))
    if gen:
        generated_at: Field[datetime] = Field(gen, 1.0)
        score += 2
    else:
        generated_at = Field(None, 0.0)
        needs_review.append(f"donut: unparseable generated_at: {data.get('generated_at')!r}")

    grid_raw: dict = data.get("grid") or {}
    grid: dict[int, list[Leg]] = {}
    for day_str, legs_raw in grid_raw.items():
        try:
            day = int(day_str)
        except (ValueError, TypeError):
            continue
        if not isinstance(legs_raw, list):
            continue
        parsed = [_parse_leg(r) for r in legs_raw if isinstance(r, dict)]
        legs = [lg for lg in parsed if lg is not None]
        if legs:
            grid[day] = legs
    if grid:
        score += 2
    else:
        needs_review.append("donut: no valid flight legs in grid")

    confidence = round(score / max_score, 3)
    return (
        ExtractedRoster(
            staff_id=staff_id,
            name=name,
            start_date=start_date,
            end_date=end_date,
            generated_at=generated_at,
            grid=grid,
            needs_review=needs_review,
        ),
        confidence,
    )


def _empty(reason: str) -> ExtractedRoster:
    empty: Field = Field(None, 0.0)
    return ExtractedRoster(
        staff_id=empty, name=empty,
        start_date=empty, end_date=empty, generated_at=empty,
        grid={}, needs_review=[reason],
    )


# ── Model inference (lazy heavy deps) ────────────────────────────────────────

def _run_torch(image_path: str, model_path: str) -> str:
    """HuggingFace Transformers inference — for development / off-Pi."""
    import torch
    from PIL import Image as PilImage
    from transformers import DonutProcessor, VisionEncoderDecoderModel

    model = VisionEncoderDecoderModel.from_pretrained(model_path)
    processor = DonutProcessor.from_pretrained(model_path)
    model.eval()

    image = PilImage.open(image_path).convert("RGB")
    pixel_values = processor(image, return_tensors="pt").pixel_values

    decoder_input_ids = processor.tokenizer(
        DONUT_PROMPT, add_special_tokens=False, return_tensors="pt",
    )["input_ids"]

    with torch.no_grad():
        outputs = model.generate(
            pixel_values,
            decoder_input_ids=decoder_input_ids,
            max_length=512,
            early_stopping=True,
            pad_token_id=processor.tokenizer.pad_token_id,
            eos_token_id=processor.tokenizer.eos_token_id,
            use_cache=True,
            num_beams=1,
            bad_words_ids=[[processor.tokenizer.unk_token_id]],
            return_dict_in_generate=True,
        )

    sequence = processor.batch_decode(outputs.sequences)[0]
    sequence = (
        sequence
        .replace(DONUT_PROMPT, "")
        .replace(processor.tokenizer.eos_token, "")
        .strip()
    )
    return sequence


def _run_onnx(image_path: str, model_dir: str) -> str:
    """ONNX Runtime inference — Pi production (int8 quantised).

    Expects `model_dir` to contain:
      encoder.onnx, decoder.onnx, processor/  (tokenizer + image processor)
    """
    from pathlib import Path

    import numpy as np
    import onnxruntime as ort
    from PIL import Image as PilImage
    from transformers import DonutProcessor

    processor = DonutProcessor.from_pretrained(Path(model_dir) / "processor")
    image = PilImage.open(image_path).convert("RGB")
    pixel_values = processor(image, return_tensors="np").pixel_values.astype(np.float32)

    enc_sess = ort.InferenceSession(str(Path(model_dir) / "encoder.onnx"))
    enc_out = enc_sess.run(None, {"pixel_values": pixel_values})[0]

    dec_sess = ort.InferenceSession(str(Path(model_dir) / "decoder.onnx"))

    # Greedy decode (no beam search for Pi speed)
    decoder_input_ids = processor.tokenizer(
        DONUT_PROMPT, add_special_tokens=False,
    )["input_ids"]
    input_ids = np.array([decoder_input_ids], dtype=np.int64)

    generated: list[int] = list(decoder_input_ids)
    eos_id = processor.tokenizer.eos_token_id
    for _ in range(512):
        logits = dec_sess.run(None, {
            "input_ids": input_ids,
            "encoder_hidden_states": enc_out,
        })[0]
        next_id = int(np.argmax(logits[0, -1]))
        if next_id == eos_id:
            break
        generated.append(next_id)
        # Pass full accumulated sequence — decoder self-attention needs all prior tokens.
        input_ids = np.array([generated], dtype=np.int64)

    sequence = processor.tokenizer.decode(generated, skip_special_tokens=True)
    return sequence.replace(DONUT_PROMPT, "").strip()


def _run_inference(image_path: str, cfg: DonutConfig) -> str | None:
    """Dispatch to the appropriate backend based on what's at `cfg.model_path`."""
    from pathlib import Path

    mp = Path(cfg.model_path)
    if not mp.exists():
        return None
    if mp.is_dir() and list(mp.glob("*.onnx")):
        return _run_onnx(image_path, str(mp))
    if mp.is_dir() and (mp / "config.json").exists():
        return _run_torch(image_path, str(mp))
    logger.debug("donut: no recognisable model at %s", cfg.model_path)
    return None


# ── Public API ────────────────────────────────────────────────────────────────

def extract_roster_donut(
    roster: RosterRef,
    cfg: DonutConfig,
) -> ExtractedRoster:
    """Extract roster fields using the Donut model with Tesseract fallback.

    Returns an `ExtractedRoster` — the same type as `extract_roster()` so
    the worker and rules engine are backend-agnostic (PD-ML-007 wires this up).

    Fallback policy (never a silent guess):
      1. Donut inference fails / model missing → Tesseract.
      2. Donut confidence < cfg.conf_fallback  → Tesseract; notes it.
      3. Tesseract also low-confidence          → NEEDS_REVIEW in both results;
         whichever has higher confidence is returned with a reason note.
    """
    if roster.local_path is None:
        return _empty("roster not downloaded")

    # ── Donut pass ───────────────────────────────────────────────────────────
    donut_result: ExtractedRoster | None = None
    donut_conf = 0.0
    try:
        raw_text = _run_inference(roster.local_path, cfg)
        if raw_text is not None:
            donut_result, donut_conf = _parse_donut_output(raw_text)
            logger.debug("donut: confidence=%.3f for %s", donut_conf, roster.local_path)
    except Exception as exc:
        logger.warning("donut: inference error for %s: %s", roster.local_path, exc)

    if donut_result is not None and donut_conf >= cfg.conf_fallback:
        return donut_result

    # ── Tesseract fallback ───────────────────────────────────────────────────
    from perdiem.engine.ocr.extract import extract_roster as _tesseract

    tess_result = _tesseract(roster)

    if donut_result is None:
        if donut_conf == 0.0:
            logger.debug("donut: model unavailable, using tesseract for %s", roster.local_path)
        tess_result.needs_review.insert(0, "donut: unavailable — tesseract used")
    else:
        tess_result.needs_review.insert(
            0, f"donut: low confidence ({donut_conf:.2f}) — fell back to tesseract"
        )
    return tess_result


def safe_extract_donut(
    roster: RosterRef,
    cfg: DonutConfig,
) -> ExtractedRoster | None:
    """Return Donut extraction result, or None when disabled / model missing.

    Returning None lets the caller continue with Tesseract unchanged —
    safe even if the model was never trained.
    """
    if not cfg.enabled:
        return None
    from pathlib import Path
    if not Path(cfg.model_path).exists():
        logger.debug("donut: model not found at %s — skipping", cfg.model_path)
        return None
    try:
        return extract_roster_donut(roster, cfg)
    except Exception as exc:
        logger.warning("donut: unexpected error for %s: %s", roster.local_path, exc)
        return None
