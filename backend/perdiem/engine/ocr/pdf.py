"""PDF rasterisation using PyMuPDF (fitz)."""
from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger(__name__)


def rasterise_pdf(path: str, dpi: int = 150) -> list[np.ndarray]:
    """
    Render each page of a PDF to a BGR numpy image array.

    Returns a list of arrays (one per page). Blank pages are included;
    the caller decides which page(s) to process.
    """
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:
        raise ImportError("PyMuPDF is required for PDF support: pip install PyMuPDF") from exc

    mat = fitz.Matrix(dpi / 72, dpi / 72)
    pages: list[np.ndarray] = []
    with fitz.open(path) as doc:
        for page in doc:
            pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB)
            arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
            # PyMuPDF returns RGB; convert to BGR for OpenCV compatibility
            import cv2
            pages.append(cv2.cvtColor(arr, cv2.COLOR_RGB2BGR))
    return pages
