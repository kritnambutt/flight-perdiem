"""Background pipeline worker.

Picks up PENDING runs from the database and executes the full pipeline:
  parsing → downloading → ocr → validating → aggregating → done

Run with:
  python -m perdiem.worker.runner

One concurrent run at a time (Pi constraint).
"""
from __future__ import annotations

import datetime as dt
import logging
import time
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from perdiem.config import settings
from perdiem.db import repository as repo
from perdiem.db.models import Run
from perdiem.db.session import SessionLocal
from perdiem.engine.config import RulesConfig
from perdiem.engine.ingest import ingest_cycle
from perdiem.engine.models import Claim, ExtractedRoster, RedAnnotation, RosterRef

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

_POLL_INTERVAL = 5  # seconds between DB polls when idle


# ---------------------------------------------------------------------------
# OCR snapshot serialisation (PD-ML-001)
# ---------------------------------------------------------------------------


def _iso(value: object) -> str | None:
    """ISO-format a date/datetime, or None."""
    if value is None:
        return None
    iso = getattr(value, "isoformat", None)
    return iso() if callable(iso) else str(value)


def _serialise_extracted(r: ExtractedRoster, *, backend: str = "tesseract") -> dict:
    """Flatten an ExtractedRoster into JSON for the verdict's `extracted` column.

    Lets the Exceptions panel show what the OCR actually read (with confidence)
    so a low-confidence / mislocated read is self-evident to a reviewer (N1).
    The `backend` field records which extractor produced the fields (PD-ML-007).
    """
    return {
        "backend": backend,
        "staff_id": {"value": r.staff_id.value, "conf": r.staff_id.confidence},
        "name": {"value": r.name.value, "conf": r.name.confidence},
        "start_date": _iso(r.start_date.value),
        "end_date": _iso(r.end_date.value),
        "generated_at": _iso(r.generated_at.value),
        "grid_days": len(r.grid),
        "needs_review": r.needs_review,
    }


# ---------------------------------------------------------------------------
# Crash safety
# ---------------------------------------------------------------------------


def _recover_stale_runs(session: Session) -> None:
    """Mark any RUNNING run as FAILED on startup (worker restarted mid-run)."""
    stale = list(session.scalars(select(Run).where(Run.status == "RUNNING")))
    for run in stale:
        logger.warning("Recovering stale run %s", run.id)
        repo.update_run_status(
            session, run.id, "FAILED",
            stage="crashed",
            finished_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        )
        repo.write_audit(
            session, "worker_restarted", run_id=run.id,
            detail={"reason": "worker process restarted mid-run"},
        )
    if stale:
        session.commit()


# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------


def _load_rules_cfg(session: Session) -> RulesConfig:
    cfg_map = repo.get_all_config(session)
    cfg = RulesConfig()
    if "outbound_flights" in cfg_map:
        cfg.outbound_flights = set(cfg_map["outbound_flights"])
    if "return_flights" in cfg_map:
        cfg.return_flights = set(cfg_map["return_flights"])
    if "rate_thb_per_day" in cfg_map:
        cfg.rate_thb_per_day = int(cfg_map["rate_thb_per_day"])
    if "name_match_threshold" in cfg_map:
        cfg.name_match_threshold = float(cfg_map["name_match_threshold"])
    if "staff_id_reject_min_confidence" in cfg_map:
        cfg.staff_id_reject_min_confidence = float(cfg_map["staff_id_reject_min_confidence"])
    return cfg


# ---------------------------------------------------------------------------
# Pipeline execution
# ---------------------------------------------------------------------------


def _run_pipeline(run_id: uuid.UUID) -> None:
    """Execute the full pipeline for one run, updating stage as it progresses."""
    with SessionLocal() as session:
        run = repo.get_run(session, run_id)
        if run is None:
            logger.error("Run %s not found", run_id)
            return

        cfg = _load_rules_cfg(session)
        upload_dir = Path(settings.uploads_dir) / str(run_id)
        posting_path = upload_dir / "posting_base.xlsx"
        late_path = upload_dir / "late_submission.xlsx"

        try:
            # ── Stage: parsing ──────────────────────────────────────────────
            repo.update_run_status(
                session, run_id, "RUNNING", stage="parsing", progress=5,
                started_at=dt.datetime.now(dt.timezone.utc),
            )
            repo.write_audit(session, "run_started", run_id=run_id)
            session.commit()

            claims = ingest_cycle(
                cycle_month=run.cycle_month,
                pb_path=str(posting_path),
                late_path=str(late_path),
                pb_sheet=run.posting_sheet,
                late_sheet=run.late_sheet,
            )
            logger.info("Run %s: ingested %d claims", run_id, len(claims))

            # Persist claims
            claim_id_map: dict[int, uuid.UUID] = {}
            for i, claim in enumerate(claims):
                db_claim = repo.create_claim(session, run_id, claim)
                claim_id_map[i] = db_claim.id
            session.commit()

            # ── Stage: downloading ──────────────────────────────────────────
            repo.update_run_status(session, run_id, "RUNNING", stage="downloading", progress=15)
            session.commit()

            from perdiem.engine.drive import fetch_rosters
            cache_path = Path(settings.roster_cache_dir)
            logger.info("Run %s: downloading rosters for %d claims (cached files reused)", run_id, len(claims))
            t_dl = time.perf_counter()
            roster_map: dict[int, list[RosterRef]] = {
                i: fetch_rosters(claim, cache_dir=cache_path)
                for i, claim in enumerate(claims)
            }
            logger.info(
                "Run %s: download stage took %.1fs (%d claims)",
                run_id, time.perf_counter() - t_dl, len(claims),
            )
            n_with_roster = sum(
                1 for refs in roster_map.values()
                if any(r.status == "OK" and r.local_path for r in refs)
            )
            logger.info("Run %s: %d/%d claims have a usable roster", run_id, n_with_roster, len(claims))

            # Roster file-type tally (per claim's primary usable roster) for the UI stats.
            roster_stats = {"pdf": 0, "image": 0, "no_roster": 0}
            for refs in roster_map.values():
                ok = next((r for r in refs if r.status == "OK" and r.local_path), None)
                if ok is None:
                    roster_stats["no_roster"] += 1
                elif ok.content_type == "application/pdf":
                    roster_stats["pdf"] += 1
                else:
                    roster_stats["image"] += 1

            # Persist the resolved refs back onto each claim so the tally is
            # re-derivable from the DB and per-claim roster type is inspectable
            # (create_claim only stored the bare URL).
            for i, refs in roster_map.items():
                repo.update_claim_roster_refs(
                    session,
                    claim_id_map[i],
                    [
                        {
                            "url": r.source_url,
                            "file_id": r.file_id,
                            "content_type": r.content_type,
                            "status": r.status,
                        }
                        for r in refs
                    ],
                )
            session.commit()

            # ── Stage: ocr ─────────────────────────────────────────────────
            repo.update_run_status(session, run_id, "RUNNING", stage="ocr", progress=30)
            session.commit()

            from perdiem.engine.ocr.cache import load_cached, store_cached
            from perdiem.engine.ocr.doctype import DocTypeConfig
            from perdiem.engine.ocr.extract import extract_roster
            from perdiem.worker.extractor import get_extractor, model_version_for

            _doctype_cfg = DocTypeConfig(
                enabled=settings.doctype_enabled,
                model_path=settings.doctype_model_path,
                min_conf=settings.doctype_min_conf,
            )
            _extractor = get_extractor(settings.ocr_backend, settings)
            _model_ver = model_version_for(_extractor)
            _ocr_backend = _extractor.name
            logger.info("Run %s: OCR backend=%s model_version=%s", run_id, _ocr_backend, _model_ver)

            extracted_map: dict[int, ExtractedRoster] = {}
            total = len(claims)
            t_ocr = time.perf_counter()
            for i, claim in enumerate(claims):
                refs: list[RosterRef] = roster_map.get(i, [])
                ok_refs = [r for r in refs if r.status == "OK" and r.local_path]
                if ok_refs:
                    ref = ok_refs[0]
                    file_id = ref.file_id or ""

                    # Cache hit — skip re-extraction (N2 idempotency).
                    cached = load_cached(
                        settings.ocr_cache_dir, file_id, _ocr_backend, _model_ver
                    )
                    if cached is not None:
                        extracted_map[i] = cached
                        logger.debug("Run %s: OCR cache hit claim %d", run_id, i)
                        continue

                    t_item = time.perf_counter()
                    try:
                        # Doc-type gate runs first (PD-ML-005); if the backend is
                        # Tesseract, pass the doctype config so it gates at source.
                        if _ocr_backend == "tesseract":
                            result = extract_roster(ref, doctype_cfg=_doctype_cfg)
                        else:
                            result = _extractor.extract(ref)
                        extracted_map[i] = result
                        store_cached(
                            settings.ocr_cache_dir, file_id, _ocr_backend, _model_ver, result
                        )
                    except Exception as exc:
                        logger.warning("OCR failed for claim %d: %s", i, exc)
                    else:
                        logger.debug(
                            "Run %s: OCR claim %d took %.2fs",
                            run_id, i, time.perf_counter() - t_item,
                        )
                # OCR is the slow stage (Tesseract per image); emit progress so it
                # is visibly advancing in the log and the UI (OCR spans 30→55%).
                if (i + 1) % 10 == 0 or (i + 1) == total:
                    logger.info("Run %s: OCR progress %d/%d", run_id, i + 1, total)
                    repo.update_run_status(
                        session, run_id, "RUNNING", stage="ocr",
                        progress=30 + int(25 * (i + 1) / total),
                    )
                    session.commit()
            logger.info(
                "Run %s: OCR stage took %.1fs — extracted %d/%d rosters",
                run_id, time.perf_counter() - t_ocr, len(extracted_map), total,
            )

            # ── Stage: validating ───────────────────────────────────────────
            repo.update_run_status(session, run_id, "RUNNING", stage="validating", progress=55)
            session.commit()

            from perdiem.engine.rules import validate_claim
            # validate_claim requires a non-None roster + red annotation. Claims
            # without a usable roster fall back to the engine's empty result, and
            # red-box detection is not yet wired (empty RedAnnotation), so the
            # form's claimed-day list is used. See docs/analysis.
            empty_ref = RosterRef(
                source_url="", file_id=None, local_path=None,
                content_type=None, status="UNREACHABLE",
            )
            empty_extracted = extract_roster(empty_ref)
            empty_red = RedAnnotation(claimed_days=set(), confidence=0.0, bbox=None)
            pair_data: list[tuple[Claim, list]] = []
            counts = {"total": len(claims), "valid": 0, "review": 0, "invalid": 0}
            counts.update(roster_stats)
            t_val = time.perf_counter()

            for i, claim in enumerate(claims):
                extracted = extracted_map.get(i) or empty_extracted
                verdicts = validate_claim(claim, extracted, empty_red, cfg)
                pair_data.append((claim, verdicts))

                db_claim_id = claim_id_map[i]
                # PD-ML-001: persist the OCR read alongside the verdicts so the
                # Exceptions panel can show what was extracted (and why a claim
                # was reviewed/rejected) instead of a blank panel.
                repo.write_verdicts(
                    session, db_claim_id, claim.staff_id, verdicts,
                    extracted=_serialise_extracted(extracted, backend=_ocr_backend),
                    confidence=extracted.staff_id.confidence,
                )

                for v in verdicts:
                    if v.verdict in ("VALID", "VALID_BACKCLAIM"):
                        counts["valid"] += 1
                    elif v.verdict == "NEEDS_REVIEW":
                        counts["review"] += 1
                    else:
                        counts["invalid"] += 1

            session.commit()
            logger.info(
                "Run %s: validate stage took %.1fs (%d claims)",
                run_id, time.perf_counter() - t_val, len(claims),
            )

            # ── Stage: aggregating ──────────────────────────────────────────
            repo.update_run_status(
                session, run_id, "RUNNING", stage="aggregating",
                progress=85, counts=counts,
            )
            session.commit()

            # Aggregation is computed on-demand by the results endpoint; no
            # separate storage needed. Mark as done.
            repo.update_run_status(
                session, run_id, "DONE", stage="done",
                progress=100, counts=counts,
                finished_at=dt.datetime.now(dt.timezone.utc),
            )
            repo.write_audit(session, "run_finished", run_id=run_id, detail={"counts": counts})
            session.commit()
            logger.info("Run %s finished: %s", run_id, counts)

        except Exception as exc:
            logger.exception("Run %s failed: %s", run_id, exc)
            try:
                repo.update_run_status(
                    session, run_id, "FAILED", stage="error",
                    finished_at=dt.datetime.now(dt.timezone.utc),
                )
                repo.write_audit(session, "run_failed", run_id=run_id, detail={"error": str(exc)})
                session.commit()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def main() -> None:
    logger.info("Worker starting")
    with SessionLocal() as session:
        _recover_stale_runs(session)

    while True:
        with SessionLocal() as session:
            pending = session.scalars(
                select(Run).where(Run.status == "PENDING").order_by(Run.started_at.asc().nulls_first()).limit(1)
            ).first()

        if pending is not None:
            logger.info("Picked up run %s (%s)", pending.id, pending.cycle_month)
            _run_pipeline(pending.id)
        else:
            time.sleep(_POLL_INTERVAL)


if __name__ == "__main__":
    main()
