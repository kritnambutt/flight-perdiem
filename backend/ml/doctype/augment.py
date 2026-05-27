"""Image augmentation for the doc-type classifier dataset (PD-ML-005).

Generates synthetic variants from each labelled image to compensate for the
small fixture set.  Augmentations mimic real-world quality variance:
  - JPEG re-compression (WhatsApp forwarding, screenshot artefacts)
  - Down/upscale (low-res phone photos, small thumbnails)
  - Small rotations (tilted phone shots)
  - Brightness and contrast shifts (glare, dark rooms)
  - Gaussian noise (sensor noise, compression block artefacts)

Returns raw BGR numpy arrays; callers should call extract_image_features() on
each augmented image to build the training matrix.
"""
from __future__ import annotations

import io
import random


def _jpeg_recompress(img: "np.ndarray", quality: int) -> "np.ndarray":  # type: ignore[name-defined]
    import cv2
    import numpy as np
    _, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return cv2.imdecode(np.frombuffer(buf.tobytes(), np.uint8), cv2.IMREAD_COLOR)


def _rotate(img: "np.ndarray", angle_deg: float) -> "np.ndarray":  # type: ignore[name-defined]
    import cv2
    import numpy as np
    h, w = img.shape[:2]
    cx, cy = w // 2, h // 2
    M = cv2.getRotationMatrix2D((cx, cy), angle_deg, 1.0)
    return cv2.warpAffine(img, M, (w, h), borderValue=(255, 255, 255))


def _scale(img: "np.ndarray", factor: float) -> "np.ndarray":  # type: ignore[name-defined]
    import cv2
    h, w = img.shape[:2]
    new_w = max(20, int(w * factor))
    new_h = max(20, int(h * factor))
    small = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
    if factor < 1.0:
        return cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)
    return small


def _brightness(img: "np.ndarray", delta: float) -> "np.ndarray":  # type: ignore[name-defined]
    import numpy as np
    shifted = img.astype(np.float32) + delta * 255.0
    return np.clip(shifted, 0, 255).astype(np.uint8)


def _noise(img: "np.ndarray", sigma: float) -> "np.ndarray":  # type: ignore[name-defined]
    import numpy as np
    noise = np.random.normal(0, sigma * 255.0, img.shape).astype(np.float32)
    return np.clip(img.astype(np.float32) + noise, 0, 255).astype(np.uint8)


def augment_image(img: "np.ndarray", n: int = 8, seed: int | None = None) -> list["np.ndarray"]:  # type: ignore[name-defined]
    """Return up to `n` augmented variants of `img` (BGR ndarray).

    The original image is NOT included — callers add it separately to keep
    the label counts correct.  All operations are independent so the full
    set of `n` variants is diverse rather than compounded.
    """
    rng = random.Random(seed)
    variants: list = []

    ops = [
        lambda x: _jpeg_recompress(x, rng.randint(20, 55)),
        lambda x: _jpeg_recompress(x, rng.randint(55, 75)),
        lambda x: _scale(x, rng.uniform(0.25, 0.50)),
        lambda x: _scale(x, rng.uniform(0.50, 0.80)),
        lambda x: _rotate(x, rng.uniform(-8, 8)),
        lambda x: _brightness(x, rng.uniform(0.10, 0.30)),
        lambda x: _brightness(x, rng.uniform(-0.30, -0.10)),
        lambda x: _noise(x, rng.uniform(0.03, 0.10)),
        lambda x: _scale(_jpeg_recompress(x, 30), rng.uniform(0.4, 0.6)),
        lambda x: _noise(_brightness(x, rng.uniform(-0.15, 0.15)), rng.uniform(0.02, 0.06)),
    ]

    rng.shuffle(ops)
    for op in ops[:n]:
        try:
            out = op(img)
            if out is not None and out.size > 0:
                variants.append(out)
        except Exception:
            pass
        if len(variants) >= n:
            break

    return variants


def make_unreadable_variants(img: "np.ndarray", n: int = 4) -> list["np.ndarray"]:  # type: ignore[name-defined]
    """Generate UNREADABLE-class examples via extreme degradation.

    Used to seed the UNREADABLE class when no truly corrupt fixtures exist.
    Produces images that are so badly degraded that field extraction would be
    meaningless: severe downscale, near-black, near-white, extreme JPEG.
    """
    import cv2
    import numpy as np

    h, w = img.shape[:2]
    variants = []

    # Extreme downscale → pixelated thumbnail
    tiny = cv2.resize(img, (max(8, w // 20), max(8, h // 20)), interpolation=cv2.INTER_AREA)
    if tiny.size > 0:
        variants.append(tiny)

    # Near-black (overexposure inverse — very dark)
    dark = np.clip(img.astype(np.float32) * 0.05, 0, 255).astype(np.uint8)
    variants.append(dark)

    # Near-white (washed out)
    white = np.clip(img.astype(np.float32) * 0.05 + 240, 0, 255).astype(np.uint8)
    variants.append(white)

    # Extreme JPEG artefacts
    _, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 2])
    ugly = cv2.imdecode(np.frombuffer(buf.tobytes(), np.uint8), cv2.IMREAD_COLOR)
    if ugly is not None:
        variants.append(ugly)

    return variants[:n]
