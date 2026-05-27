"""Red annotation detection — HSV colour masking + day-column mapping.

The red rectangle/oval some crew draw on their roster is OPTIONAL.
Absence of a red mark is the normal case; callers must use the form's
claimed-day list (col 10) as the primary source of claimed days.
When a red mark IS found, its detected days are returned so the Validation
layer can cross-check them against the form list.
"""
from __future__ import annotations

import logging

import cv2
import numpy as np

from perdiem.engine.models import GridGeometry, RedAnnotation

logger = logging.getLogger(__name__)

# Two red hue bands at the ends of the HSV hue wheel
_RED_LOWER1 = np.array([0,   70,  50], dtype=np.uint8)
_RED_UPPER1 = np.array([10, 255, 255], dtype=np.uint8)
_RED_LOWER2 = np.array([170,  70,  50], dtype=np.uint8)
_RED_UPPER2 = np.array([180, 255, 255], dtype=np.uint8)

_MORPH_KERNEL = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))

_MIN_CONTOUR_AREA = 800        # px² — ignore isolated specks
_MAX_AREA_FRACTION = 0.40      # ignore if >40 % of image area (background noise)
_MIN_OVERLAP_FRACTION = 0.15   # column must overlap at least 15 % of its width


def _red_mask(bgr: np.ndarray) -> np.ndarray:
    """Return binary mask of red pixels (both hue-wheel ends), morphologically closed."""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    mask = cv2.bitwise_or(
        cv2.inRange(hsv, _RED_LOWER1, _RED_UPPER1),
        cv2.inRange(hsv, _RED_LOWER2, _RED_UPPER2),
    )
    return cv2.morphologyEx(mask, cv2.MORPH_CLOSE, _MORPH_KERNEL)


def _valid_boxes(
    contours: tuple,
    image_area: int,
) -> list[tuple[int, int, int, int]]:
    """Return (x, y, w, h) bounding boxes of contours that pass size/aspect filters."""
    boxes = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < _MIN_CONTOUR_AREA:
            continue
        if area > _MAX_AREA_FRACTION * image_area:
            continue
        x, y, w, h = cv2.boundingRect(cnt)
        aspect = w / max(h, 1)
        if aspect < 0.2 or aspect > 15.0:
            continue
        boxes.append((x, y, w, h))
    return boxes


def _map_to_days(
    bbox: tuple[int, int, int, int],
    geometry: GridGeometry,
) -> set[int]:
    """Return day numbers whose column x-range overlaps the annotation bbox."""
    x, _y, w, _h = bbox
    ann_left, ann_right = x, x + w
    claimed: set[int] = set()
    for day, (col_left, col_right) in geometry.columns.items():
        col_w = col_right - col_left
        if col_w <= 0:
            continue
        overlap = min(ann_right, col_right) - max(ann_left, col_left)
        if overlap / col_w >= _MIN_OVERLAP_FRACTION:
            claimed.add(day)
    return claimed


def detect_red_annotation(
    image: np.ndarray,
    grid_geometry: GridGeometry,
) -> RedAnnotation:
    """
    Detect the optional red rectangle/oval the crew drew on the roster.

    image         — original BGR colour image from orient_and_upscale(); must
                    NOT be the binarised OCR image (colour channels required).
    grid_geometry — day-column x-boundaries from extract_grid_geometry();
                    must be in the same coordinate space as image.

    Returns a RedAnnotation.  When no mark is found (the normal case for most
    rosters) claimed_days is empty and confidence is 0.0 — the caller should
    then use the form's claimed-day list exclusively.
    """
    if image is None or image.ndim < 3:
        logger.debug("detect_red_annotation: image is None or not colour")
        return RedAnnotation(claimed_days=set(), confidence=0.0, bbox=None)

    h, w = image.shape[:2]
    image_area = h * w

    mask = _red_mask(image)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes = _valid_boxes(contours, image_area)

    if not boxes:
        return RedAnnotation(claimed_days=set(), confidence=0.0, bbox=None)

    # Accumulate claimed days across all valid annotation boxes
    all_claimed: set[int] = set()
    for box in boxes:
        all_claimed |= _map_to_days(box, grid_geometry)

    # Primary bbox = largest box by area
    primary = max(boxes, key=lambda b: b[2] * b[3])

    if not all_claimed:
        # Box(es) found but none overlap a known column — treat as not found
        return RedAnnotation(claimed_days=set(), confidence=0.2, bbox=primary)

    # Confidence: 0.6 base + fill-ratio bonus up to 0.95
    mask_pixels = int(cv2.countNonZero(mask))
    total_box_area = sum(b[2] * b[3] for b in boxes)
    fill_ratio = min(1.0, mask_pixels / max(1, total_box_area))
    confidence = min(0.95, 0.6 + 0.35 * fill_ratio)

    logger.debug(
        "detect_red_annotation: claimed_days=%s confidence=%.2f boxes=%d",
        sorted(all_claimed), confidence, len(boxes),
    )
    return RedAnnotation(claimed_days=all_claimed, confidence=confidence, bbox=primary)
