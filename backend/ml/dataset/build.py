"""Dataset build orchestrator (PD-ML-002).

Joins the three workbooks across all monthly sheets into two labelled splits — a
**text/decision** dataset (all history) and a **vision** dataset (rows whose roster
image is cached) — assigns crew-grouped train/val/test splits, and produces a
manifest + data-quality report.
"""
from __future__ import annotations

import hashlib
import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from ml.dataset.join import apply_blank_remark_rule, build_master_index
from ml.dataset.models import Split, TextRow, VisionRow
from ml.dataset.normalise import classify_disposition, normalize_claim_month
from ml.dataset.readers import (
    RawFormRow,
    form_sheet_names,
    read_form_sheet,
    read_identity_registry,
    read_master_sheet,
)
from perdiem.engine.drive import extract_file_id

logger = logging.getLogger(__name__)

# Bump when the labelling rules (blank-Remark rule, remark→rule map) change, so a
# dataset's manifest pins exactly how its labels were derived.
LABELLING_RULE_VERSION = "1.0"

# Crew-grouped split ratios (by staff_id / name — never random by day, to avoid the
# same crew leaking across train and test).
_SPLIT_TRAIN_PCT = 70
_SPLIT_VAL_PCT = 15  # remainder → test

_CANONICAL_MONTHS = {
    "JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE",
    "JULY", "AUGUST", "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER",
}


@dataclass
class BuildStats:
    """Counters surfaced in the data-quality report."""

    rows_per_sheet: dict[str, int] = field(default_factory=dict)
    unparsed_sheets: list[str] = field(default_factory=list)
    empty_master_sheets: list[str] = field(default_factory=list)
    disposition_counts: Counter = field(default_factory=Counter)
    rule_hint_counts: Counter = field(default_factory=Counter)
    label_source_counts: Counter = field(default_factory=Counter)
    split_counts: Counter = field(default_factory=Counter)
    blank_remark_approved: int = 0
    unmatched_master: int = 0
    text_rows: int = 0
    vision_rows: int = 0
    vision_links_seen: int = 0
    vision_links_missing: int = 0
    identity_registry_size: int = 0


@dataclass
class BuildResult:
    text_rows: list[TextRow]
    vision_rows: list[VisionRow]
    stats: BuildStats
    manifest: dict


def _split_for(group_key: str) -> Split:
    """Deterministically assign a crew group to train/val/test (stable across runs)."""
    h = int(hashlib.sha1(group_key.encode("utf-8")).hexdigest(), 16) % 100
    if h < _SPLIT_TRAIN_PCT:
        return "train"
    if h < _SPLIT_TRAIN_PCT + _SPLIT_VAL_PCT:
        return "val"
    return "test"


def _form_cycle_month(row: RawFormRow) -> tuple[str, int]:
    """Resolve the claimed (cycle) month for a form row.

    Posting Base carries a canonical "AUGUST 2025"; Late Submission is messy
    ("July", "กรกฎาคม", 11.0…) and arrears-dated, so we normalise with the submission
    sheet's year as a hint and fall back to the sheet month if no month is found.
    """
    norm = normalize_claim_month(row.claim_month_raw, year_hint=row.sheet_month[1])
    parts = norm.split()
    if parts and parts[0] in _CANONICAL_MONTHS:
        month = parts[0]
        year = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else row.sheet_month[1]
        return month, year
    return row.sheet_month


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_dataset(
    pb_path: str,
    late_path: str,
    ccd_path: str,
    *,
    version: str,
    rate_thb_per_day: int = 400,
    roster_cache_dir: str | None = None,
) -> BuildResult:
    """Build the text + vision datasets from the three workbooks.

    Args:
        pb_path / late_path: the two form response workbooks.
        ccd_path: the CCD payroll master workbook (outcomes + identity).
        version: dataset version tag (recorded in the manifest).
        rate_thb_per_day: THB per approved day (config-driven; never hard-coded).
        roster_cache_dir: where ``<file_id>.<ext>`` roster images are cached. When
            absent, the vision split is empty (most history has no cached image).
    """
    stats = BuildStats()

    # 1. Master index + identity registry.
    master_rows = []
    for sheet in form_sheet_names(ccd_path):
        rows = read_master_sheet(ccd_path, sheet)
        if rows:
            master_rows.extend(rows)
        else:
            stats.empty_master_sheets.append(sheet)
    master_index = build_master_index(master_rows)
    identity = read_identity_registry(ccd_path)
    stats.identity_registry_size = len(identity)

    # 2. Form rows from both workbooks (every monthly sheet).
    raw_rows: list[RawFormRow] = []
    for path, source in ((pb_path, "POSTING_BASE"), (late_path, "LATE")):
        if not path:
            continue
        for sheet in form_sheet_names(path):
            rows, month = read_form_sheet(path, sheet, source)  # type: ignore[arg-type]
            if month is None:
                stats.unparsed_sheets.append(f"{Path(path).name}!{sheet}")
                continue
            stats.rows_per_sheet[f"{Path(path).name}!{sheet}"] = len(rows)
            raw_rows.extend(rows)

    cache_dir = Path(roster_cache_dir) if roster_cache_dir else None

    # 3. Join + label each row → TextRow (+ VisionRow when a roster image is cached).
    text_rows: list[TextRow] = []
    vision_rows: list[VisionRow] = []
    for row in raw_rows:
        cycle_month = _form_cycle_month(row)
        classified = classify_disposition(row.admin_remark)

        match = None
        if row.staff_id is not None:
            match = master_index.get((row.staff_id, cycle_month[0], cycle_month[1]))
        matched = match is not None

        disposition, rule_hint, label_source = apply_blank_remark_rule(classified, matched)
        if label_source == "master_reconciled":
            stats.blank_remark_approved += 1

        approved = matched
        approved_periods = list(match.periods) if match else []
        approved_days = match.days if match else 0
        total_thb = approved_days * rate_thb_per_day

        unmatched = (not matched) and disposition in ("APPROVED", "DEFER_BACKCLAIM")
        if unmatched:
            stats.unmatched_master += 1

        # Backfill the name from the identity registry when the form left it blank.
        name = row.name or identity.get(row.staff_id or "", {}).get("name_en", "")

        group_key = row.staff_id or row.name or row.provenance
        split = _split_for(group_key)

        text_rows.append(
            TextRow(
                provenance=row.provenance,
                source=row.source,
                staff_id=row.staff_id,
                name=name,
                cycle_month=cycle_month,
                claimed_days=_parse_days(row.claimed_days_raw),
                claim_type=row.claim_type,
                crew_remark=row.crew_remark,
                disposition=disposition,
                reason_text=row.admin_remark,
                rule_hint=rule_hint,
                approved=approved,
                approved_periods=approved_periods,
                approved_days=approved_days,
                total_thb=total_thb,
                split=split,
                label_source=label_source,  # type: ignore[arg-type]
                unmatched_master=unmatched,
                roster_links=row.roster_links,
            )
        )
        stats.disposition_counts[disposition] += 1
        stats.rule_hint_counts[rule_hint] += 1
        stats.label_source_counts[label_source] += 1
        stats.split_counts[split] += 1

        # Vision split: keep only rows whose roster Drive link resolves to a cached image.
        if cache_dir is not None:
            for link in row.roster_links:
                stats.vision_links_seen += 1
                image_path = _resolve_cached_image(link, cache_dir)
                if image_path is None:
                    stats.vision_links_missing += 1
                    continue
                vision_rows.append(
                    VisionRow(
                        provenance=row.provenance,
                        image_path=image_path,
                        fields={
                            "staff_id": row.staff_id,
                            "name": name,
                            "cycle_month": list(cycle_month),
                            "claimed_days": _parse_days(row.claimed_days_raw),
                            "approved_periods": [
                                [s.isoformat(), e.isoformat()] for s, e in approved_periods
                            ],
                        },
                        label_source="master_reconciled" if matched else "regex_bootstrap",
                        split=split,
                    )
                )

    stats.text_rows = len(text_rows)
    stats.vision_rows = len(vision_rows)

    manifest = {
        "version": version,
        "built_at": datetime.now(UTC).isoformat(),
        "labelling_rule_version": LABELLING_RULE_VERSION,
        "rate_thb_per_day": rate_thb_per_day,
        "sources": {
            "posting_base": _source_meta(pb_path),
            "late_submission": _source_meta(late_path),
            "ccd_master": _source_meta(ccd_path),
        },
        "counts": {
            "text_rows": stats.text_rows,
            "vision_rows": stats.vision_rows,
            "identity_registry": stats.identity_registry_size,
            "unparsed_sheets": len(stats.unparsed_sheets),
            "splits": dict(stats.split_counts),
            "dispositions": dict(stats.disposition_counts),
        },
    }
    return BuildResult(text_rows, vision_rows, stats, manifest)


def _source_meta(path: str) -> dict:
    if not path or not Path(path).exists():
        return {"path": path, "sha256": None}
    return {"path": path, "sha256": _sha256(path)}


def _parse_days(raw: object) -> list[int]:
    from ml.dataset.normalise import parse_thai_day_list

    return parse_thai_day_list(raw)


def _resolve_cached_image(link: str, cache_dir: Path) -> str | None:
    """Map a Drive link to a cached ``<file_id>.<ext>`` path, or None if not cached."""
    file_id = extract_file_id(link)
    if file_id is None:
        return None
    for cached in cache_dir.glob(f"{file_id}.*"):
        if cached.suffix != ".tmp":
            return str(cached)
    return None
