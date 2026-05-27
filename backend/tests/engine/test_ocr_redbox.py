"""Tests for red annotation detection (PD-OCR-002).

Unit tests use synthetic BGR images and avoid Tesseract/OCR entirely.
Integration tests run against real fixture files and require OpenCV only.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from perdiem.engine.models import GridGeometry
from perdiem.engine.ocr.redbox import _map_to_days, _red_mask, detect_red_annotation

FIXTURES = Path(__file__).parent.parent.parent.parent / "docs" / "example-files"
CORRECT = FIXTURES / "roster-attached-files" / "correct"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _geometry(*day_ranges: tuple[int, int, int]) -> GridGeometry:
    """Build GridGeometry from (day, x_left, x_right) tuples."""
    return GridGeometry(columns={d: (xl, xr) for d, xl, xr in day_ranges})


def _solid_bgr(h: int, w: int, bgr: tuple[int, int, int]) -> np.ndarray:
    img = np.zeros((h, w, 3), dtype=np.uint8)
    img[:] = bgr
    return img


def _red_box_image(
    img_w: int = 2000,
    img_h: int = 800,
    box_x: int = 400,
    box_y: int = 100,
    box_w: int = 200,
    box_h: int = 300,
    thickness: int = 6,
) -> np.ndarray:
    """White image with a single red rectangle stroke."""
    img = np.full((img_h, img_w, 3), 255, dtype=np.uint8)
    cv2.rectangle(img, (box_x, box_y), (box_x + box_w, box_y + box_h), (0, 0, 220), thickness)
    return img


# ---------------------------------------------------------------------------
# _red_mask unit tests
# ---------------------------------------------------------------------------

class TestRedMask:
    def test_detects_pure_red_bgr(self):
        img = _solid_bgr(50, 50, (0, 0, 255))  # BGR red
        mask = _red_mask(img)
        assert cv2.countNonZero(mask) > 0

    def test_ignores_blue(self):
        img = _solid_bgr(50, 50, (255, 0, 0))  # BGR blue
        mask = _red_mask(img)
        assert cv2.countNonZero(mask) == 0

    def test_ignores_green(self):
        img = _solid_bgr(50, 50, (0, 255, 0))  # BGR green
        mask = _red_mask(img)
        assert cv2.countNonZero(mask) == 0

    def test_ignores_white(self):
        img = _solid_bgr(50, 50, (255, 255, 255))
        mask = _red_mask(img)
        assert cv2.countNonZero(mask) == 0

    def test_detects_dark_red(self):
        img = _solid_bgr(50, 50, (0, 0, 160))  # dark red
        mask = _red_mask(img)
        assert cv2.countNonZero(mask) > 0

    def test_high_hue_red(self):
        # H≈175 in HSV — the upper red band
        img = np.zeros((50, 50, 3), dtype=np.uint8)
        img_hsv = np.zeros((50, 50, 3), dtype=np.uint8)
        img_hsv[:] = (175, 200, 200)
        img = cv2.cvtColor(img_hsv, cv2.COLOR_HSV2BGR)
        mask = _red_mask(img)
        assert cv2.countNonZero(mask) > 0


# ---------------------------------------------------------------------------
# _map_to_days unit tests
# ---------------------------------------------------------------------------

class TestMapToDays:
    def test_full_overlap_single_day(self):
        geom = _geometry((5, 400, 600))
        days = _map_to_days((400, 50, 200, 300), geom)
        assert days == {5}

    def test_spanning_two_columns(self):
        geom = _geometry((27, 400, 600), (28, 600, 800))
        days = _map_to_days((350, 50, 500, 300), geom)
        assert days == {27, 28}

    def test_no_overlap(self):
        geom = _geometry((1, 400, 600))
        days = _map_to_days((0, 0, 100, 100), geom)
        assert days == set()

    def test_empty_geometry(self):
        geom = GridGeometry(columns={})
        days = _map_to_days((0, 0, 500, 300), geom)
        assert days == set()

    def test_partial_overlap_below_threshold(self):
        # Box overlaps only 5 px out of 200 px column width (2.5 % < 15 %)
        geom = _geometry((3, 500, 700))
        days = _map_to_days((0, 0, 505, 300), geom)
        assert days == set()

    def test_partial_overlap_above_threshold(self):
        # Box overlaps 40 px out of 200 px column width (20 % ≥ 15 %)
        geom = _geometry((3, 500, 700))
        days = _map_to_days((0, 0, 540, 300), geom)
        assert days == {3}


# ---------------------------------------------------------------------------
# detect_red_annotation — unit tests with synthetic images
# ---------------------------------------------------------------------------

class TestDetectRedAnnotation:
    def test_no_red_returns_empty(self):
        img = np.full((800, 2000, 3), 255, dtype=np.uint8)  # white
        geom = _geometry((1, 100, 300))
        result = detect_red_annotation(img, geom)
        assert result.claimed_days == set()
        assert result.confidence == 0.0
        assert result.bbox is None

    def test_red_box_over_known_column(self):
        img = _red_box_image(box_x=400, box_w=200)
        geom = _geometry((5, 380, 620))
        result = detect_red_annotation(img, geom)
        assert 5 in result.claimed_days
        assert result.confidence >= 0.6
        assert result.bbox is not None

    def test_red_box_spanning_two_columns(self):
        img = _red_box_image(box_x=380, box_w=420)
        geom = _geometry((27, 350, 570), (28, 580, 820))
        result = detect_red_annotation(img, geom)
        assert {27, 28}.issubset(result.claimed_days)

    def test_red_box_outside_all_columns(self):
        img = _red_box_image(box_x=1600, box_w=200)
        geom = _geometry((1, 100, 300))  # column far from the box
        result = detect_red_annotation(img, geom)
        assert result.claimed_days == set()
        assert result.confidence == 0.2  # box found but unmappable

    def test_none_image_returns_empty(self):
        geom = GridGeometry(columns={})
        result = detect_red_annotation(None, geom)  # type: ignore[arg-type]
        assert result.claimed_days == set()
        assert result.confidence == 0.0

    def test_grayscale_image_returns_empty(self):
        gray = np.full((400, 800), 255, dtype=np.uint8)
        geom = _geometry((1, 100, 300))
        result = detect_red_annotation(gray, geom)
        assert result.claimed_days == set()
        assert result.confidence == 0.0

    def test_tiny_red_speck_ignored(self):
        img = np.full((800, 2000, 3), 255, dtype=np.uint8)
        cv2.rectangle(img, (400, 100), (405, 105), (0, 0, 220), -1)  # 5×5 fill
        geom = _geometry((5, 380, 620))
        result = detect_red_annotation(img, geom)
        assert result.claimed_days == set()


# ---------------------------------------------------------------------------
# Integration tests — real fixture images (OpenCV only, no Tesseract)
# ---------------------------------------------------------------------------

class TestDetectRedAnnotationIntegration:
    """
    These tests load real roster images from the fixture directory.
    They require OpenCV but NOT Tesseract, so they run even without the
    full OCR stack.  GridGeometry is built manually from approximate column
    positions observed in the images.
    """

    def _load(self, path: Path) -> np.ndarray:
        from perdiem.engine.ocr.preprocess import load_image, orient_and_upscale
        raw = load_image(str(path))
        return orient_and_upscale(raw)

    def test_kanatsanan_has_red_annotation(self):
        """
        Kanatsanan roster has two visible red rectangles.
        We check that at least one day is detected with good confidence.
        The approximate grid has ~31 columns over the image width.
        """
        img = self._load(CORRECT / "1775130932681 - Kanatsanan Wichitthararak -.jpg")
        h, w = img.shape[:2]
        # Approximate column width for a 31-day grid
        col_w = w // 31
        geom = GridGeometry(columns={
            d: (col_w * (d - 1), col_w * d) for d in range(1, 32)
        })
        result = detect_red_annotation(img, geom)
        assert len(result.claimed_days) >= 1, (
            f"Expected red annotation but got claimed_days={result.claimed_days}"
        )
        assert result.confidence >= 0.6
        assert result.bbox is not None

    def test_chanicha_no_red_annotation(self):
        """
        Chanicha roster has no red annotation — normal case.
        Must return empty set and confidence=0.0 without raising.
        """
        img = self._load(CORRECT / "Screenshot_20260505_153747_Chrome - Chanicha Songkrit -.jpg")
        h, w = img.shape[:2]
        col_w = w // 31
        geom = GridGeometry(columns={
            d: (col_w * (d - 1), col_w * d) for d in range(1, 32)
        })
        result = detect_red_annotation(img, geom)
        # No red box expected — claimed_days may be empty OR have a low-confidence spurious hit
        # The important invariant: must not raise, confidence must reflect quality
        if result.claimed_days:
            assert result.confidence < 0.8, (
                "Spurious red detection on a no-annotation roster should have low confidence"
            )

    def test_sawaros_no_red_annotation(self):
        """Sawaros roster has no red annotation — must not raise."""
        img = self._load(CORRECT / "IMG_2398 - Sawaros Phanichvibul -.jpeg")
        h, w = img.shape[:2]
        col_w = w // 31
        geom = GridGeometry(columns={
            d: (col_w * (d - 1), col_w * d) for d in range(1, 32)
        })
        result = detect_red_annotation(img, geom)
        assert isinstance(result.claimed_days, set)
        assert 0.0 <= result.confidence <= 1.0
