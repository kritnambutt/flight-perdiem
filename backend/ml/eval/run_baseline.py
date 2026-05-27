"""Baseline run + report writer for the eval harness (PD-ML-003).

Produces the frozen reference numbers every later model reports against: the
end-to-end decision KPIs for the status-quo "review everything" backend (and any
extra backend passed in), plus an optional per-field extraction pass over the vision
split. Writes a markdown + JSON report under `ML_REPORT_DIR`.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from ml.eval.e2e import RouteFn, assert_no_leakage, evaluate_e2e, load_text_rows, review_all
from ml.eval.metrics import E2EMetrics, FieldMetrics
from ml.eval.scorers import aggregate_field_metrics, score_dates, score_name, score_staff_id
from perdiem.engine.config import RulesConfig
from perdiem.engine.models import RosterRef

logger = logging.getLogger(__name__)


@dataclass
class BaselineReport:
    dataset_version: str
    split: str
    backends: dict[str, E2EMetrics] = field(default_factory=dict)
    field_metrics: FieldMetrics | None = None
    reason: dict | None = None          # {top1, top2, n, per_class}
    n_rows: int = 0
    built_at: str = ""


def score_reason_hint(model_path: str, rows: list[dict]) -> dict:
    """Top-1/top-2 rule_hint accuracy on non-APPROVED rows (PD-ML-004 AC-2).

    The reason hint is advisory — measured here so the queue reviewer knows how often
    the suggested rule is right; it never drives a verdict.
    """
    from collections import Counter

    from perdiem.engine.triage import build_features, predict_reason

    targets = [r for r in rows if r.get("disposition") != "APPROVED"]
    if not targets:
        return {"top1": 0.0, "top2": 0.0, "n": 0, "per_class_top1": {}}

    top1 = top2 = 0
    per_class_total: Counter = Counter()
    per_class_hit: Counter = Counter()
    for row in targets:
        gold = row.get("rule_hint") or "NONE"
        ranked = predict_reason(build_features(row), model_path)
        names = [c for c, _ in ranked]
        per_class_total[gold] += 1
        if names[:1] == [gold]:
            top1 += 1
            per_class_hit[gold] += 1
        if gold in names[:2]:
            top2 += 1
    n = len(targets)
    return {
        "top1": top1 / n,
        "top2": top2 / n,
        "n": n,
        "per_class_top1": {
            c: per_class_hit[c] / per_class_total[c] for c in per_class_total
        },
    }


def run_e2e(
    dataset_dir: str | Path,
    *,
    split: str = "test",
    extra_backends: dict[str, RouteFn] | None = None,
) -> BaselineReport:
    """Score the status-quo baseline (+ any extra routing backends) on the split."""
    rows = load_text_rows(dataset_dir, split=split)
    assert_no_leakage(rows, expected_split=split)

    backends: dict[str, RouteFn] = {"review_all": review_all}
    if extra_backends:
        backends.update(extra_backends)

    results = {name: evaluate_e2e(fn, rows) for name, fn in backends.items()}
    return BaselineReport(
        dataset_version=Path(dataset_dir).name,
        split=split,
        backends=results,
        n_rows=len(rows),
        built_at=datetime.now(UTC).isoformat(),
    )


def evaluate_fields(extractor, vision_rows: list[dict]) -> FieldMetrics:
    """Run an extractor over cached vision rows and score per-field vs weak labels.

    Rows whose image is missing/unreadable are excluded from every denominator (a
    coverage line, not a silent miss). The vision labels are weak/derived (PD-ML-002),
    so this measures relative extraction quality, not absolute truth.
    """
    pred_ids: list[str | None] = []
    gold_ids: list[str | None] = []
    pred_names: list[str | None] = []
    gold_names: list[str | None] = []
    pred_starts: list[object] = []
    gold_starts: list[object] = []

    for row in vision_rows:
        image_path = row.get("image_path")
        if not image_path or not Path(image_path).exists():
            continue
        ref = RosterRef(
            source_url="",
            file_id=None,
            local_path=image_path,
            content_type=None,
            status="OK",
        )
        try:
            roster = extractor.extract(ref)
        except Exception as exc:  # noqa: BLE001 — one bad image must not abort the eval
            logger.warning("extract failed for %s: %s", image_path, exc)
            continue
        fields = row.get("fields", {})
        pred_ids.append(roster.staff_id.value)
        gold_ids.append(fields.get("staff_id"))
        pred_names.append(roster.name.value)
        gold_names.append(fields.get("name"))
        pred_starts.append(roster.start_date.value)
        periods = fields.get("approved_periods") or []
        gold_starts.append(periods[0][0] if periods else None)

    return aggregate_field_metrics(
        staff_id=score_staff_id(pred_ids, gold_ids),
        name=score_name(pred_names, gold_names, RulesConfig().name_match_threshold),
        date_range=score_dates(pred_starts, gold_starts),
        generated_date=(0.0, 0),   # no gold generated-date in the weak vision labels
        grid_counts=(0, 0, 0),     # no gold grid legs in the weak vision labels
    )


def render_report(report: BaselineReport) -> str:
    """Markdown rendering of a baseline report."""
    out = [
        f"# ML Eval Baseline — `{report.dataset_version}` / split `{report.split}`",
        "",
        f"- Built: `{report.built_at}`",
        f"- Rows scored: **{report.n_rows}**",
        "",
        "## End-to-end decision KPIs",
        "",
        "| Backend | auto-pass match | auto-pass % | auto-reject % | review % | disagree |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, m in report.backends.items():
        out.append(
            f"| `{name}` | {m.auto_pass_match_master:.3f} | {m.auto_pass_frac:.3f} | "
            f"{m.auto_reject_frac:.3f} | {m.review_queue_frac:.3f} | {m.disagreement_rate:.3f} |"
        )
    out.append("")
    out.append(
        "> Baseline `review_all` = the manual status quo (auto-pass nothing). A triage "
        "backend's value is a lower **review queue %** at a high **auto-pass match** and "
        "low **disagreement**."
    )
    if report.reason is not None:
        r = report.reason
        out += [
            "",
            "## Reason-hint accuracy (advisory; non-APPROVED rows)",
            "",
            f"- Top-1: **{r['top1']:.3f}**, Top-2: **{r['top2']:.3f}** over {r['n']} rows",
            "",
            "| rule_hint | top-1 acc |",
            "| --- | ---: |",
            *[f"| {c} | {acc:.3f} |" for c, acc in sorted(r["per_class_top1"].items())],
        ]
    if report.field_metrics is not None:
        fm = report.field_metrics
        out += [
            "",
            "## Per-field extraction (vision split)",
            "",
            "| Field | Metric | Coverage (gold rows) |",
            "| --- | ---: | ---: |",
            f"| staff_id | {fm.staff_id_acc:.3f} | {fm.coverage.get('staff_id', 0)} |",
            f"| name | {fm.name_match_rate:.3f} | {fm.coverage.get('name', 0)} |",
            f"| date_range (start) | {fm.date_range_acc:.3f} | "
            f"{fm.coverage.get('date_range', 0)} |",
            f"| generated_date | {fm.generated_date_acc:.3f} | "
            f"{fm.coverage.get('generated_date', 0)} |",
            f"| grid legs P/R | {fm.grid_leg_precision:.3f} / {fm.grid_leg_recall:.3f} | "
            f"{fm.coverage.get('grid_legs_gold', 0)} |",
        ]
        if all(v == 0 for v in fm.coverage.values()):
            out.append("")
            out.append(
                "> No vision ground-truth rows available (empty/uncached vision split). "
                "Per-field numbers populate once rosters are cached (PD-ING-002)."
            )
    return "\n".join(out)


def write_report(report: BaselineReport, report_dir: str | Path) -> Path:
    """Write `<report_dir>/<version>_<split>_baseline.{md,json}`; return the md path."""
    out_dir = Path(report_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{report.dataset_version}_{report.split}_baseline"
    (out_dir / f"{stem}.json").write_text(
        json.dumps(
            {
                "dataset_version": report.dataset_version,
                "split": report.split,
                "n_rows": report.n_rows,
                "built_at": report.built_at,
                "backends": {k: v.to_dict() for k, v in report.backends.items()},
                "field_metrics": report.field_metrics.to_dict() if report.field_metrics else None,
                "reason": report.reason,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    md_path = out_dir / f"{stem}.md"
    md_path.write_text(render_report(report), encoding="utf-8")
    return md_path
