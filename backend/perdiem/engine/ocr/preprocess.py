"""Image preprocessing for roster OCR: orient, upscale, denoise, binarise."""
from __future__ import annotations

import logging

import cv2
import numpy as np

logger = logging.getLogger(__name__)


def load_image(path: str) -> np.ndarray:
    """Load an image file into a BGR numpy array."""
    img = cv2.imread(path)
    if img is None:
        raise ValueError(f"Cannot load image: {path}")
    return img


def to_gray(img: np.ndarray) -> np.ndarray:
    """Convert BGR/BGRA image to single-channel grayscale."""
    if len(img.shape) == 2:
        return img
    if img.shape[2] == 4:
        img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def auto_orient(img: np.ndarray, lang: str = "eng") -> np.ndarray:
    """Detect and correct 90/180/270° rotation using Tesseract OSD."""
    try:
        import pytesseract
        from PIL import Image as PilImage

        pil = PilImage.fromarray(img)
        osd = pytesseract.image_to_osd(pil, lang=lang, output_type=pytesseract.Output.DICT)
        angle = int(osd.get("rotate", 0))
        if angle == 90:
            return cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
        if angle == 180:
            return cv2.rotate(img, cv2.ROTATE_180)
        if angle == 270:
            return cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
    except Exception as exc:
        logger.debug("OSD orientation detection failed: %s", exc)
    return img


def upscale(img: np.ndarray, min_width: int = 2000) -> np.ndarray:
    """Upscale image so its width is at least min_width pixels."""
    h, w = img.shape[:2]
    if w < min_width:
        scale = min_width / w
        img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    return img


def denoise(img: np.ndarray) -> np.ndarray:
    """Apply fast non-local means denoising to a grayscale image."""
    return cv2.fastNlMeansDenoising(img, h=10, templateWindowSize=7, searchWindowSize=21)


def binarise(img: np.ndarray) -> np.ndarray:
    """Adaptive threshold to produce a clean black-on-white binary image."""
    return cv2.adaptiveThreshold(
        img, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        blockSize=15,
        C=8,
    )


def orient_and_upscale(
    img: np.ndarray,
    min_width: int = 2000,
    lang: str = "eng",
    *,
    auto_orient_enabled: bool = True,
) -> np.ndarray:
    """
    Orient and upscale a BGR image without stripping colour channels.
    Use this before red-annotation detection; the output shares the same
    coordinate space as the OCR word boxes.
    """
    if auto_orient_enabled:
        img = auto_orient(img, lang=lang)
    return upscale(img, min_width=min_width)


def preprocess(
    img: np.ndarray,
    min_width: int = 2000,
    lang: str = "eng",
    *,
    denoise_enabled: bool = True,
    auto_orient_enabled: bool = True,
) -> np.ndarray:
    """
    Full preprocessing pipeline:
    orient → upscale → grayscale → (denoise) → binarise.
    Returns a binary grayscale image suitable for Tesseract.

    `denoise_enabled` / `auto_orient_enabled` (PD-ML-001) let callers skip the
    two heaviest steps; both default to True so behaviour is unchanged.
    """
    if auto_orient_enabled:
        img = auto_orient(img, lang=lang)
    img = upscale(img, min_width=min_width)
    gray = to_gray(img)
    if denoise_enabled:
        gray = denoise(gray)
    return binarise(gray)
