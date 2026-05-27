"""Tests for the doc-type / quality classifier (PD-ML-005).

Covers:
  - Feature extraction (no crash, correct keys, expected ranges)
  - Train → serialize → pure inference round-trip on synthetic data
  - safe_classify_doc fallback behaviour (disabled, missing model)
  - Fixture-based smoke tests on known-good and known-bad images
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from ml.doctype.augment import augment_image, make_unreadable_variants
from ml.doctype.train import (
    CLASSES,
    build_feature_rows,
    save_artifact,
    train,
)
from perdiem.engine.ocr.doctype import (
    DocTypeConfig,
    NUMERIC_FEATURES,
    classify_doc,
    extract_image_features,
    safe_classify_doc,
)

FIXTURES = Path("docs/example-files/roster-attached-files")
CORRECT = FIXTURES / "correct"
INCORRECT = FIXTURES / "incorrect"


# ---------------------------------------------------------------------------
# Feature extraction
# ---------------------------------------------------------------------------

def _blank_image(w: int = 400, h: int = 300, value: int = 255) -> np.ndarray:
    """Create a plain-colour BGR test image."""
    import cv2
    img = np.full((h, w, 3), value, dtype=np.uint8)
    return img


def test_feature_keys_match_numeric_features() -> None:
    img = _blank_image()
    feats = extract_image_features(img)
    assert set(feats.keys()) == set(NUMERIC_FEATURES)


def test_feature_values_are_floats() -> None:
    feats = extract_image_features(_blank_image())
    for k, v in feats.items():
        assert isinstance(v, float), f"{k} is not float"


def test_blank_white_image_features() -> None:
    feats = extract_image_features(_blank_image(value=255))
    assert feats["mean_brightness"] > 0.95
    assert feats["dark_ratio"] < 0.05
    assert feats["blue_band_score"] < 0.10


def test_log_dims_increase_with_size() -> None:
    small = extract_image_features(_blank_image(100, 80))
    large = extract_image_features(_blank_image(2000, 1500))
    assert large["log_width"] > small["log_width"]
    assert large["log_height"] > small["log_height"]


def test_edge_density_nonzero_for_grid_image() -> None:
    """An image with drawn lines should have higher edge density than blank."""
    import cv2
    img = _blank_image(400, 300, 255)
    for y in range(0, 300, 20):
        cv2.line(img, (0, y), (400, y), (0, 0, 0), 1)
    for x in range(0, 400, 20):
        cv2.line(img, (x, 0), (x, 300), (0, 0, 0), 1)
    feats_grid = extract_image_features(img)
    feats_blank = extract_image_features(_blank_image(400, 300, 255))
    assert feats_grid["edge_density"] > feats_blank["edge_density"]


def test_blue_band_score_for_blue_header() -> None:
    """Image with a blue top band should score higher than a white one."""
    img = _blank_image(400, 300, 255)
    img[:60, :] = [180, 80, 40]  # BGR: blue dominant
    feats = extract_image_features(img)
    feats_plain = extract_image_features(_blank_image(400, 300, 255))
    assert feats["blue_band_score"] > feats_plain["blue_band_score"]


# ---------------------------------------------------------------------------
# Augmentation
# ---------------------------------------------------------------------------

def test_augment_returns_correct_count() -> None:
    img = _blank_image()
    variants = augment_image(img, n=5, seed=42)
    assert len(variants) == 5


def test_augment_produces_valid_ndarrays() -> None:
    img = _blank_image(200, 150)
    for aug in augment_image(img, n=3, seed=0):
        assert isinstance(aug, np.ndarray)
        assert aug.ndim == 3


def test_make_unreadable_variants() -> None:
    img = _blank_image(400, 300)
    variants = make_unreadable_variants(img, n=4)
    assert 1 <= len(variants) <= 4
    for v in variants:
        assert isinstance(v, np.ndarray)


# ---------------------------------------------------------------------------
# Synthetic train → infer round-trip
# ---------------------------------------------------------------------------

def _make_synthetic_rows() -> list[tuple[dict, str]]:
    """Generate clearly separable feature rows for the 3 classes."""
    rows: list[tuple[dict, str]] = []
    base = {k: 0.0 for k in NUMERIC_FEATURES}

    for _ in range(40):
        # VALID_ROSTER: large, blue band, high edge density, bright
        feats = {**base,
                 "log_width": 7.5, "log_height": 7.2, "aspect_ratio": 1.4,
                 "mean_brightness": 0.88, "brightness_std": 0.18,
                 "edge_density": 0.12, "blue_band_score": 0.25,
                 "dark_ratio": 0.08, "color_std": 30.0,
                 "row_variance_mean": 0.04, "col_variance_mean": 0.03}
        rows.append((feats, "VALID_ROSTER"))

        # NOT_A_ROSTER: small, no blue band, low edge density
        feats2 = {**base,
                  "log_width": 5.5, "log_height": 5.2, "aspect_ratio": 0.75,
                  "mean_brightness": 0.55, "brightness_std": 0.25,
                  "edge_density": 0.03, "blue_band_score": 0.00,
                  "dark_ratio": 0.30, "color_std": 50.0,
                  "row_variance_mean": 0.01, "col_variance_mean": 0.01}
        rows.append((feats2, "NOT_A_ROSTER"))

        # UNREADABLE: very small, near-black, no edges
        feats3 = {**base,
                  "log_width": 3.0, "log_height": 2.8, "aspect_ratio": 1.0,
                  "mean_brightness": 0.04, "brightness_std": 0.02,
                  "edge_density": 0.00, "blue_band_score": 0.00,
                  "dark_ratio": 0.97, "color_std": 2.0,
                  "row_variance_mean": 0.00, "col_variance_mean": 0.00}
        rows.append((feats3, "UNREADABLE"))
    return rows


@pytest.fixture(scope="module")
def model_path(tmp_path_factory) -> str:
    rows = _make_synthetic_rows()
    result = train(rows, rows, dataset_version="test")
    path = str(tmp_path_factory.mktemp("doctype") / "doctype.json")
    save_artifact(result.artifact, path)
    return path


_PERMISSIVE = DocTypeConfig(enabled=True, min_conf=0.10)


def test_artifact_has_required_keys(model_path: str) -> None:
    with open(model_path) as fh:
        art = json.load(fh)
    assert art["model"] == "softmax-logreg"
    assert art["classes"] == CLASSES
    assert set(art["feature_names"]) == set(NUMERIC_FEATURES)
    assert "W" in art and "b" in art


def test_classifies_valid_roster(model_path: str) -> None:
    feats = {k: 0.0 for k in NUMERIC_FEATURES}
    feats.update({"log_width": 7.5, "log_height": 7.2, "aspect_ratio": 1.4,
                  "mean_brightness": 0.88, "brightness_std": 0.18,
                  "edge_density": 0.12, "blue_band_score": 0.25,
                  "dark_ratio": 0.08, "color_std": 30.0,
                  "row_variance_mean": 0.04, "col_variance_mean": 0.03})
    img = _blank_image()   # dummy — we override with a pre-loaded model artifact
    # Build x directly from known features
    with open(model_path) as fh:
        artifact = json.load(fh)
    import numpy as np
    names = artifact["feature_names"]
    standardize = artifact["standardize"]
    W = np.array(artifact["W"])
    b = np.array(artifact["b"])
    x = np.zeros(len(names))
    for i, name in enumerate(names):
        v = float(feats.get(name, 0.0))
        if name in standardize:
            mean, std = standardize[name]
            v = (v - mean) / std if std else 0.0
        x[i] = v
    logits = np.clip(x @ W.T + b, -30, 30)
    logits -= logits.max()
    probs = np.exp(logits) / np.exp(logits).sum()
    pred = artifact["classes"][int(np.argmax(probs))]
    assert pred == "VALID_ROSTER"


def test_classifies_unreadable(model_path: str) -> None:
    feats = {k: 0.0 for k in NUMERIC_FEATURES}
    feats.update({"log_width": 3.0, "log_height": 2.8, "mean_brightness": 0.04,
                  "brightness_std": 0.02, "dark_ratio": 0.97})
    with open(model_path) as fh:
        artifact = json.load(fh)
    import numpy as np
    names = artifact["feature_names"]
    standardize = artifact["standardize"]
    W = np.array(artifact["W"])
    b = np.array(artifact["b"])
    x = np.zeros(len(names))
    for i, name in enumerate(names):
        v = float(feats.get(name, 0.0))
        if name in standardize:
            mean, std = standardize[name]
            v = (v - mean) / std if std else 0.0
        x[i] = v
    logits = np.clip(x @ W.T + b, -30, 30)
    logits -= logits.max()
    probs = np.exp(logits) / np.exp(logits).sum()
    pred = artifact["classes"][int(np.argmax(probs))]
    assert pred == "UNREADABLE"


# ---------------------------------------------------------------------------
# safe_classify_doc fallback behaviour
# ---------------------------------------------------------------------------

def test_safe_classify_disabled_returns_none(model_path: str) -> None:
    cfg = DocTypeConfig(enabled=False, model_path=model_path)
    assert safe_classify_doc("/any/path.jpg", cfg) is None


def test_safe_classify_missing_model_returns_none() -> None:
    cfg = DocTypeConfig(enabled=True, model_path="/no/such/model.json")
    assert safe_classify_doc("/any/path.jpg", cfg) is None


def test_safe_classify_missing_file_returns_unreadable(model_path: str) -> None:
    cfg = DocTypeConfig(enabled=True, model_path=model_path)
    result = safe_classify_doc("/no/such/image.jpg", cfg)
    assert result is not None
    assert result.label == "UNREADABLE"


def test_safe_classify_none_path_returns_none(model_path: str) -> None:
    cfg = DocTypeConfig(enabled=True, model_path=model_path)
    assert safe_classify_doc(None, cfg) is None


# ---------------------------------------------------------------------------
# Fixture-based smoke tests (skipped if fixtures are absent)
# ---------------------------------------------------------------------------

@pytest.fixture
def correct_images() -> list[Path]:
    if not CORRECT.is_dir():
        pytest.skip("correct/ fixture directory not found")
    return [p for p in CORRECT.iterdir()
            if p.suffix.lower() in {".jpg", ".jpeg", ".png"}]


@pytest.fixture
def incorrect_invalid_images() -> list[Path]:
    if not INCORRECT.is_dir():
        pytest.skip("incorrect/ fixture directory not found")
    return [p for p in INCORRECT.iterdir()
            if p.suffix.lower() in {".jpg", ".jpeg", ".png"}
            and "invalid formatted" in p.name.lower()]


def test_correct_fixtures_have_extractable_features(correct_images) -> None:
    for path in correct_images:
        import cv2
        img = cv2.imread(str(path))
        if img is None:
            continue
        feats = extract_image_features(img)
        assert feats["log_width"] > 0, f"zero log_width for {path.name}"
        assert feats["edge_density"] >= 0


def test_incorrect_invalid_fixtures_have_lower_blue_band(
    correct_images, incorrect_invalid_images,
) -> None:
    """'invalid formatted' images should score lower on the blue-band feature
    than correct roster images (on average) — validates feature discriminability."""
    import cv2
    def mean_blue_band(paths):
        scores = []
        for p in paths:
            img = cv2.imread(str(p))
            if img is not None:
                scores.append(extract_image_features(img)["blue_band_score"])
        return sum(scores) / len(scores) if scores else 0.0

    avg_correct = mean_blue_band(correct_images)
    avg_invalid = mean_blue_band(incorrect_invalid_images)
    # The blue band (crew header) is distinctive for valid rosters.
    # This is an average comparison; individual outliers are fine.
    assert avg_correct >= avg_invalid, (
        f"Expected correct rosters to score >= invalid on blue_band_score: "
        f"correct={avg_correct:.3f}, invalid={avg_invalid:.3f}"
    )


def test_build_feature_rows_with_fixtures(correct_images) -> None:
    import cv2
    pairs = [(cv2.imread(str(p)), "VALID_ROSTER") for p in correct_images[:2]
             if cv2.imread(str(p)) is not None]
    if not pairs:
        pytest.skip("no loadable correct fixtures")
    rows = build_feature_rows(pairs, augment_per_image=3)
    assert len(rows) > len(pairs)
    assert all(isinstance(feats, dict) and isinstance(lbl, str) for feats, lbl in rows)
