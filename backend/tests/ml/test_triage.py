"""Tests for the triage classifier (PD-ML-004) — features, training, pure inference."""
from __future__ import annotations

import pytest

from ml.triage.calibrate import select_autopass_threshold
from ml.triage.train import save_artifact, train
from perdiem.engine.triage import (
    TriageConfig,
    build_features,
    predict_reason,
    reason_target,
    safe_triage,
    triage,
    triage_target,
)

# ---------------------------------------------------------------------------
# Feature spec
# ---------------------------------------------------------------------------

def test_features_are_non_leaky() -> None:
    row = {
        "source": "LATE", "claim_type": "Layover allowance",
        "cycle_month": ["AUGUST", 2025], "claimed_days": [2, 3],
        "roster_links": ["http://x"], "staff_id": "1001",
        # Label columns that MUST NOT become features:
        "disposition": "APPROVED", "rule_hint": "NONE", "approved": True, "reason_text": "จ่ายเงิน",
    }
    feats = build_features(row)
    assert feats["src_late"] == 1.0
    assert feats["ct_layover"] == 1.0
    assert feats["month_AUGUST"] == 1.0
    assert feats["n_claimed_days"] == 2.0
    assert feats["has_staff_id"] == 1.0
    # No outcome/label leaks into the feature space.
    assert not any(k in feats for k in ("disposition", "rule_hint", "approved", "reason_text"))


def test_targets_map_disposition_and_hint() -> None:
    assert triage_target({"disposition": "APPROVED"}) == "AUTO_PASS"
    assert triage_target({"disposition": "REJECTED"}) == "AUTO_REJECT"
    assert triage_target({"disposition": "DEFER_BACKCLAIM"}) == "SEND_TO_REVIEW"
    assert reason_target({"rule_hint": "R7"}) == "R7"
    assert reason_target({}) == "NONE"


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------

def test_calibrate_picks_precision_cut() -> None:
    # Confident rows (>=0.9) are all correct; lower ones are wrong → cut at 0.9.
    confs = [0.95, 0.92, 0.6, 0.55]
    correct = [True, True, False, False]
    cut = select_autopass_threshold(confs, correct, target_precision=0.99)
    assert cut == pytest.approx(0.92)


def test_calibrate_falls_back_when_unreachable() -> None:
    cut = select_autopass_threshold([0.6, 0.7], [False, False], target_precision=0.99, default=0.85)
    assert cut == 0.85


# ---------------------------------------------------------------------------
# Train → serialize → pure inference (synthetic separable data)
# ---------------------------------------------------------------------------

def _make_rows() -> list[dict]:
    rows: list[dict] = []
    for _ in range(60):
        rows.append({  # group A → APPROVED / AUTO_PASS
            "source": "POSTING_BASE", "claim_type": "Layover allowance",
            "cycle_month": ["AUGUST", 2025], "claimed_days": [2, 3],
            "roster_links": ["http://x"], "staff_id": "1",
            "disposition": "APPROVED", "rule_hint": "NONE",
        })
        rows.append({  # group B → REJECTED / AUTO_REJECT, reason R7
            "source": "POSTING_BASE", "claim_type": "",
            "cycle_month": ["AUGUST", 2025], "claimed_days": [5],
            "roster_links": [], "staff_id": "2",
            "disposition": "REJECTED", "rule_hint": "R7",
        })
        rows.append({  # group C → DEFER / REVIEW, reason R8
            "source": "LATE", "claim_type": "Perdiem for Posting Base",
            "cycle_month": ["JULY", 2025], "claimed_days": [7],
            "roster_links": ["http://y"], "staff_id": "3",
            "disposition": "DEFER_BACKCLAIM", "rule_hint": "R8",
        })
    return rows


@pytest.fixture(scope="module")
def model_path(tmp_path_factory) -> str:
    rows = _make_rows()
    result = train(rows, rows, dataset_version="test")
    path = str(tmp_path_factory.mktemp("triage") / "triage.json")
    save_artifact(result.artifact, path)
    return path


_LOW_ABSTAIN = TriageConfig(enabled=True, autopass_min_conf=0.5, review_band=0.02)


def test_routes_learned_classes(model_path: str) -> None:
    a = {"source": "POSTING_BASE", "claim_type": "Layover allowance",
         "cycle_month": ["AUGUST", 2025], "claimed_days": [2, 3],
         "roster_links": ["http://x"], "staff_id": "1"}
    b = {"source": "POSTING_BASE", "claim_type": "",
         "cycle_month": ["AUGUST", 2025], "claimed_days": [5], "roster_links": [], "staff_id": "2"}
    c = {"source": "LATE", "claim_type": "Perdiem for Posting Base",
         "cycle_month": ["JULY", 2025], "claimed_days": [7], "roster_links": ["http://y"],
         "staff_id": "3"}
    assert triage(build_features(a), model_path, _LOW_ABSTAIN).route == "AUTO_PASS"
    assert triage(build_features(b), model_path, _LOW_ABSTAIN).route == "AUTO_REJECT"
    assert triage(build_features(c), model_path, _LOW_ABSTAIN).route == "SEND_TO_REVIEW"


def test_abstention_demotes_unconfident_autopass(model_path: str) -> None:
    a = {"source": "POSTING_BASE", "claim_type": "Layover allowance",
         "cycle_month": ["AUGUST", 2025], "claimed_days": [2, 3],
         "roster_links": ["http://x"], "staff_id": "1"}
    strict = TriageConfig(enabled=True, autopass_min_conf=0.999, review_band=0.0)
    assert triage(build_features(a), model_path, strict).route == "SEND_TO_REVIEW"


def test_reason_hint_ranks_correct_rule(model_path: str) -> None:
    b = {"source": "POSTING_BASE", "claim_type": "",
         "cycle_month": ["AUGUST", 2025], "claimed_days": [5], "roster_links": [], "staff_id": "2"}
    ranked = predict_reason(build_features(b), model_path)
    assert ranked[0][0] == "R7"


def test_safe_triage_fallback(model_path: str) -> None:
    feats = build_features({"source": "LATE", "claim_type": "", "cycle_month": ["JULY", 2025]})
    # Disabled → None (caller keeps rule verdict).
    assert safe_triage(feats, TriageConfig(enabled=False, model_path=model_path)) is None
    # Missing artifact → None, never raises.
    assert safe_triage(feats, TriageConfig(enabled=True, model_path="/no/such/model.json")) is None
    # Enabled + present → a real result.
    assert safe_triage(feats, TriageConfig(enabled=True, model_path=model_path)) is not None
