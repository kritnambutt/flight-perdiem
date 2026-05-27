"""Data-quality report for the ML dataset builder (PD-ML-002).

Renders a human-readable markdown report from a build's ``BuildStats`` so the
labelling assumptions are auditable: rows per sheet, label coverage, unmatched
joins, blank-Remark approvals, and any sheets that couldn't be parsed.
"""
from __future__ import annotations

from ml.dataset.build import BuildResult, BuildStats


def _table(header: tuple[str, str], rows: list[tuple[str, object]]) -> str:
    lines = [f"| {header[0]} | {header[1]} |", "| --- | ---: |"]
    lines += [f"| {k} | {v} |" for k, v in rows]
    return "\n".join(lines)


def render_quality_report(result: BuildResult) -> str:
    """Return the markdown data-quality report for a completed build."""
    s: BuildStats = result.stats
    m = result.manifest

    out: list[str] = []
    out.append(f"# ML Dataset Quality Report — `{m['version']}`")
    out.append("")
    out.append(f"- Built: `{m['built_at']}`")
    out.append(f"- Labelling-rule version: `{m['labelling_rule_version']}`")
    out.append(f"- Rate: **{m['rate_thb_per_day']} THB/day**")
    out.append("")

    out.append("## Totals")
    out.append("")
    out.append(
        _table(
            ("Metric", "Count"),
            [
                ("Text rows", s.text_rows),
                ("Vision rows", s.vision_rows),
                ("Identity registry (staff IDs)", s.identity_registry_size),
                ("Blank-Remark → APPROVED (master-reconciled)", s.blank_remark_approved),
                ("Unmatched master (approved/defer, no paid row)", s.unmatched_master),
                ("Roster links seen", s.vision_links_seen),
                ("Roster links missing from cache", s.vision_links_missing),
                ("Unparsed sheets", len(s.unparsed_sheets)),
                ("Master sheets with no rows", len(s.empty_master_sheets)),
            ],
        )
    )
    out.append("")

    out.append("## Disposition distribution (gold WS-3 label)")
    out.append("")
    out.append(
        _table(
            ("Disposition", "Count"),
            sorted(s.disposition_counts.items(), key=lambda kv: -kv[1]),
        )
    )
    out.append("")

    out.append("## rule_hint distribution")
    out.append("")
    out.append(
        _table(
            ("rule_hint", "Count"),
            sorted(s.rule_hint_counts.items(), key=lambda kv: -kv[1]),
        )
    )
    out.append("")

    out.append("## Label source")
    out.append("")
    out.append(
        _table(("label_source", "Count"), sorted(s.label_source_counts.items()))
    )
    out.append("")

    out.append("## Split (crew-grouped)")
    out.append("")
    out.append(_table(("split", "Rows"), sorted(s.split_counts.items())))
    out.append("")

    if s.unparsed_sheets:
        out.append("## Unparsed sheets (reported, not dropped)")
        out.append("")
        out += [f"- `{name}`" for name in s.unparsed_sheets]
        out.append("")

    out.append("## Rows per sheet")
    out.append("")
    out.append(
        _table(
            ("workbook!sheet", "Rows"),
            sorted(s.rows_per_sheet.items()),
        )
    )
    out.append("")

    return "\n".join(out)
