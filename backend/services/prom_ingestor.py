import hashlib
import json
import logging
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from backend.database.models import (
    AlertBatch,
    AlertEvent,
    AlertSeries,
    KnownIssue,
    PromSnapshot,
    PromSnapshotFile,
)
from backend.services.classifier import classify_alert, classify_alert_signal
from backend.services.config import (
    ACTIONABLE_COLORS,
    PROM_FILE_PATH,
    RESOLUTION_GRACE_MIN_SECONDS,
    RESOLUTION_GRACE_MIN_SNAPSHOTS,
    SOURCE_STALE_SECONDS,
    SUPPRESS_KNOWN_ERRORS,
)
from backend.services.counter_math import compute_counter_delta, compute_interval_seconds, compute_rate_per_hour
from backend.services.fingerprint import build_fingerprint_exact, build_fingerprint_general, extract_log_epoch, extract_log_scope
from backend.services.prom_inventory import (
    PromFileRead,
    combine_file_hashes,
    compute_file_quality_status,
    read_prom_file,
    resolve_source_files,
    source_mode,
)

# A previously-active alert's source file being in one of these states means
# its absence this run can't be trusted — see _is_source_healthy().
_UNHEALTHY_FILE_STATUSES = ("stale", "parse_failure")

_LOG = logging.getLogger(__name__)

# Prevents the watcher and a manual "Process Now" click (or two manual clicks)
# from both passing the idempotency check and double-writing a batch. A plain
# threading.Lock (not asyncio.Lock) because both call sites end up running in
# worker threads — FastAPI's sync route handlers run in its thread pool, and
# the watcher calls this via asyncio.to_thread — not on a single event loop.
_process_lock = threading.Lock()


class ProcessAlreadyRunningError(Exception):
    """Raised when process_prom_file() is called while another run (watcher
    or manual trigger) already holds the lock, instead of blocking/queuing."""

COLOR_SEVERITY_HINT = {
    "red": "high",
    "yellow": "medium",
    "black": "low",
}


def _short_hash(file_hash: str) -> str:
    return file_hash[:6]


def _format_snapshot_id(processed_at: datetime, file_hash: str) -> str:
    return f"PROM-{processed_at.strftime('%Y%m%d-%H%M%S')}-{_short_hash(file_hash)}"


def _format_batch_id(received_time: datetime, file_hash: str) -> str:
    return f"PROM-{received_time.strftime('%Y%m%d-%H%M%S')}-{_short_hash(file_hash)}"


def _wait_until_stable(paths: List[Path], timeout_seconds: int = 10) -> bool:
    if not paths:
        return False
    stable_until = time.time() + timeout_seconds
    last_sizes = [p.stat().st_size for p in paths]
    while time.time() < stable_until:
        time.sleep(1)
        current_sizes = [p.stat().st_size for p in paths]
        if current_sizes == last_sizes:
            return True
        last_sizes = current_sizes
    return False


def _latest_successful_snapshot(db: Session) -> Optional[PromSnapshot]:
    return (
        db.query(PromSnapshot)
        .filter(PromSnapshot.status == "processed")
        .order_by(PromSnapshot.processed_at.desc())
        .first()
    )


def _previous_active_alerts(db: Session, previous_snapshot: Optional[PromSnapshot]) -> List[AlertEvent]:
    if not previous_snapshot:
        return []
    return (
        db.query(AlertEvent)
        .filter(
            AlertEvent.snapshot_id == previous_snapshot.snapshot_id,
            AlertEvent.category != "resolved",
        )
        .all()
    )


def _expected_filenames(db: Session, previous_snapshot: Optional[PromSnapshot]) -> set:
    """Filenames the previous processed snapshot actually read — the baseline
    "what should be here" set a missing/newly-discovered comparison needs.
    No separate table: PromSnapshotFile already records this per snapshot."""
    if not previous_snapshot:
        return set()
    rows = (
        db.query(PromSnapshotFile.filename)
        .filter(PromSnapshotFile.snapshot_id == previous_snapshot.snapshot_id)
        .all()
    )
    return {row[0] for row in rows}


def _compute_source_health(
    file_reads: List[PromFileRead],
    reference_time: Optional[datetime],
    expected_filenames: set,
) -> Dict[str, Any]:
    """Per-file quality_status plus this run's overall completeness_status —
    see prom_inventory.compute_file_quality_status and request Section 4
    ("prevent false resolutions"). completeness_status precedence: every
    expected file unavailable -> missing_source; some (not all) expected
    files missing/stale/unreadable -> partial; otherwise complete (a lone
    parse_warning file doesn't downgrade the snapshot — it was still read
    successfully, just had some flagged rows)."""
    quality_by_filename = {
        fr.filename: compute_file_quality_status(fr, reference_time, SOURCE_STALE_SECONDS)
        for fr in file_reads
    }
    present_filenames = set(quality_by_filename)
    missing_files = sorted(expected_filenames - present_filenames)
    newly_discovered_files = sorted(present_filenames - expected_filenames) if expected_filenames else []
    unhealthy_present = any(status in _UNHEALTHY_FILE_STATUSES for status in quality_by_filename.values())

    if expected_filenames and set(missing_files) == expected_filenames:
        completeness_status = "missing_source"
    elif missing_files or unhealthy_present:
        completeness_status = "partial"
    else:
        completeness_status = "complete"

    return {
        "quality_by_filename": quality_by_filename,
        "missing_files": missing_files,
        "newly_discovered_files": newly_discovered_files,
        "completeness_status": completeness_status,
    }


def _is_source_healthy(filename: Optional[str], quality_by_filename: Dict[str, str]) -> bool:
    """Whether this run's read of `filename` is trustworthy enough to accept
    an alert's absence from it as real. False for a filename not present at
    all this run (status unknown -> missing) as well as one that's stale or
    failed to parse."""
    if not filename:
        return False
    status = quality_by_filename.get(filename)
    if status is None:
        return False
    return status not in _UNHEALTHY_FILE_STATUSES


def _find_previous_alert(
    previous_alerts: List[AlertEvent],
    fingerprint_exact: str,
    fingerprint_general: str,
) -> Optional[AlertEvent]:
    for prev in previous_alerts:
        if prev.fingerprint_exact == fingerprint_exact:
            return prev
    for prev in previous_alerts:
        if prev.fingerprint_general == fingerprint_general:
            return prev
    return None


def _apply_color_severity(color: str, current_severity: Optional[str]) -> Optional[str]:
    if current_severity:
        return current_severity
    return COLOR_SEVERITY_HINT.get((color or "").lower())


def _find_known_issue_by_id(known_issues: List[KnownIssue], known_issue_id: Optional[str]) -> Optional[KnownIssue]:
    if not known_issue_id:
        return None
    for ki in known_issues:
        if getattr(ki, "known_issue_id", None) == known_issue_id:
            return ki
    return None


def _find_or_create_series(db: Session, alert: Dict[str, Any], observed_at: Optional[datetime]) -> AlertSeries:
    """Permanent identity for this alert_key (backend/database/models.py::AlertSeries).
    Looked up once per alert per ingestion run; created on first sight. Only
    identity/lifecycle fields are touched here — operational fields (owner,
    ticket, notes, known-issue link, severity/suppression overrides) are only
    ever written by the mutation endpoints in backend/routes/alerts.py, never
    by ingestion, so a running scan can never clobber a human's edits."""
    alert_key = alert["fingerprint_exact"]
    series = db.query(AlertSeries).filter(AlertSeries.alert_key == alert_key).first()
    if series is None:
        series = AlertSeries(
            alert_key=alert_key,
            tenant=alert["tenant"],
            system=alert["system"],
            hostname=alert["hostname"],
            log_scope=extract_log_scope(alert["log_file"]),
            error_type=alert["error_type"],
            error_index=alert["error_index"],
            caused_by=alert.get("caused_by") or None,
            first_seen=observed_at,
            last_seen=observed_at,
            lifecycle_status="active",
        )
        db.add(series)
        db.flush()
    else:
        if series.first_seen is None or (observed_at and observed_at < series.first_seen):
            series.first_seen = observed_at
        if observed_at and (series.last_seen is None or observed_at > series.last_seen):
            series.last_seen = observed_at
        if series.lifecycle_status == "resolved":
            series.lifecycle_status = "active"  # seen again — no longer resolved
        # Reappeared — any in-progress resolution grace period no longer applies.
        series.pending_resolution_since = None
        series.absence_count = 0
        db.add(series)
    return series


def _apply_series_overrides(
    classification: Dict[str, Any],
    series: AlertSeries,
    known_issues: List[KnownIssue],
    alert: Dict[str, Any],
) -> Dict[str, Any]:
    """Layers a series' manually-set operational state on top of the
    automatic classify_alert() result, so a human's mark-known/severity/
    suppression choice stays consistent (category included) even if the
    automatic wildcard/fingerprint matching wouldn't have re-found the same
    Known Issue on its own. Mirrors the forced-category logic already used
    by POST /api/alerts/{id}/mark-known (backend/routes/alerts.py)."""
    result = dict(classification)

    if series.known_issue_id and series.known_issue_id != classification.get("known_issue_id"):
        linked_ki = _find_known_issue_by_id(known_issues, series.known_issue_id)
        if linked_ki is not None and getattr(linked_ki, "status", None) != "archived":
            max_count = linked_ki.normal_count_max or 0
            is_worsening = bool(max_count) and alert["growth"] > 0 and (
                alert["count"] > max_count or alert["growth"] > max_count
            )
            result["category"] = "worsening" if is_worsening else "known"
            result["known_issue_id"] = linked_ki.known_issue_id
            result["owner"] = linked_ki.owner or result.get("owner")
            result["classification_reason"] = f"Manually linked to Known Issue {linked_ki.known_issue_id}."
            result["suggested_action"] = (linked_ki.resolution_steps or "").split("\n")[0] or result.get("suggested_action")

    if series.owner:
        result["owner"] = series.owner
    if series.severity_override:
        result["severity"] = series.severity_override

    return result


def _build_alert_event(
    alert: Dict[str, Any],
    batch_id: str,
    snapshot_id: str,
    known_issues: List[KnownIssue],
    index: int,
    ingested_at: datetime,
    series: AlertSeries,
) -> AlertEvent:
    classification = classify_alert(
        alert["hostname"],
        alert["log_file"],
        alert["error_type"],
        alert["count"],
        alert["growth"],
        known_issues=known_issues,
    )
    classification = _apply_series_overrides(classification, series, known_issues, alert)

    severity = _apply_color_severity(alert["color"], classification["severity"])
    signal_type = classify_alert_signal(
        alert["color"],
        bool(alert["raw_known_error"]),
        ACTIONABLE_COLORS,
        SUPPRESS_KNOWN_ERRORS,
    )
    if series.suppression_override is True:
        signal_type = "suppressed"
    elif series.suppression_override is False and signal_type == "suppressed":
        # Manual override: never auto-suppress this alert_key even though
        # it's flagged as a known error — recompute as if it weren't.
        signal_type = classify_alert_signal(alert["color"], False, ACTIONABLE_COLORS, SUPPRESS_KNOWN_ERRORS)

    is_red = (alert["color"] or "").strip().lower() == "red"
    # Snapshot-time capture: a Known Issue's threshold can change later, but
    # historical trend math (threshold_excess_percentage) must reflect what
    # the threshold actually was at the moment of this observation.
    matched_known_issue = _find_known_issue_by_id(known_issues, classification["known_issue_id"])
    red_threshold = float(matched_known_issue.normal_count_max) if (
        matched_known_issue is not None and matched_known_issue.normal_count_max
    ) else None
    runbook_link = matched_known_issue.runbook_link if matched_known_issue is not None else None

    id_seed = "|".join([
        snapshot_id,
        str(index),
        alert["hostname"],
        alert["raw_filename"],
        alert["error_type"],
        alert["error_index"],
        str(alert.get("caused_by", "")),
        alert["tenant"],
        alert["system"],
    ])
    alert_id = hashlib.sha1(id_seed.encode("utf-8")).hexdigest()[:16]

    return AlertEvent(
        alert_id=f"{snapshot_id}-{alert_id}",
        batch_id=batch_id,
        status=classification["category"],
        category=classification["category"],
        signal_type=signal_type,
        hostname=alert["hostname"],
        raw_filename=alert["raw_filename"],
        log_file=alert["log_file"],
        error_type=alert["error_type"],
        count=alert["count"],
        growth=alert["growth"],
        severity=severity,
        first_seen=alert["first_seen"],
        last_seen=alert["last_seen"],
        fingerprint=alert["fingerprint_general"],
        fingerprint_exact=alert["fingerprint_exact"],
        fingerprint_general=alert["fingerprint_general"],
        classification_reason=classification["classification_reason"],
        suggested_action=classification["suggested_action"],
        known_issue_id=classification["known_issue_id"],
        owner=classification["owner"],
        # Operational fields sourced from the series so they survive every
        # future snapshot regardless of daily log-filename rollover — never
        # hardcoded/reset here (that was the previous behavior and silently
        # wiped ticket/notes on every single ingestion run).
        runbook_link=runbook_link,
        ticket_link=series.ticket_link,
        notes=series.notes or "",
        system_type=alert["system_type"],
        system=alert["system"],
        tenant=alert["tenant"],
        error_index=alert["error_index"],
        color=alert["color"],
        raw_known_error="true" if alert["raw_known_error"] else "false",
        raw_note=alert["raw_note"],
        caused_by=alert["caused_by"],
        previous_count=alert["previous_count"],
        snapshot_id=snapshot_id,
        processed_at=ingested_at,
        is_red=is_red,
        red_threshold=red_threshold,
        observed_at=alert["observed_at"],
        ingested_at=ingested_at,
        source_filename=alert["source_filename"],
        source_generated_time=alert["source_generated_time"],
        source_state_file=alert["source_state_file"],
        source_file_hash=alert["source_file_hash"],
        raw_signed_delta=alert["raw_signed_delta"],
        interval_delta=alert["interval_delta"],
        interval_seconds=alert["interval_seconds"],
        rate_per_hour=alert["rate_per_hour"],
        counter_reset_detected=alert["counter_reset_detected"],
        counter_epoch=alert["counter_epoch"],
        data_quality_status=alert["data_quality_status"],
        series_id=series.id,
    )


def _build_resolved_event(
    prev: AlertEvent,
    batch_id: str,
    snapshot_id: str,
    index: int,
    ingested_at: datetime,
) -> AlertEvent:
    id_seed = "|".join([snapshot_id, "resolved", str(index), prev.fingerprint_exact or "", prev.fingerprint_general or ""])
    alert_id = hashlib.sha1(id_seed.encode("utf-8")).hexdigest()[:16]
    known_error = (prev.raw_known_error or "").strip().lower() == "true"
    signal_type = classify_alert_signal(prev.color, known_error, ACTIONABLE_COLORS, SUPPRESS_KNOWN_ERRORS)
    return AlertEvent(
        alert_id=f"{snapshot_id}-res-{alert_id}",
        batch_id=batch_id,
        status="resolved",
        category="resolved",
        signal_type=signal_type,
        # A resolved row explicitly means "confirmed absent this run" — never
        # counted as red for trend/persistence purposes, regardless of the
        # color it last had (see backend/services/trends.py::compute_red_persistence).
        processed_at=ingested_at,
        ingested_at=ingested_at,
        observed_at=prev.observed_at,
        is_red=False,
        red_threshold=prev.red_threshold,
        hostname=prev.hostname,
        raw_filename=prev.raw_filename,
        log_file=prev.log_file,
        error_type=prev.error_type,
        count=0,
        growth=-1 * (prev.count or 0),
        raw_signed_delta=-1 * (prev.count or 0),
        interval_delta=0,
        counter_reset_detected=False,
        data_quality_status="ok",
        severity=prev.severity,
        first_seen=prev.first_seen,
        last_seen=prev.last_seen,
        fingerprint=prev.fingerprint,
        fingerprint_exact=prev.fingerprint_exact,
        fingerprint_general=prev.fingerprint_general,
        classification_reason="Previously active issue not seen in current .prom folder snapshot.",
        suggested_action="Verify resolution and archive if stable.",
        known_issue_id=prev.known_issue_id,
        owner=prev.owner,
        runbook_link=prev.runbook_link,
        ticket_link=prev.ticket_link,
        notes=prev.notes,
        system_type=prev.system_type,
        system=prev.system,
        tenant=prev.tenant,
        error_index=prev.error_index,
        color=prev.color,
        raw_known_error=prev.raw_known_error,
        raw_note=prev.raw_note,
        caused_by=prev.caused_by,
        previous_count=prev.count,
        snapshot_id=snapshot_id,
        series_id=prev.series_id,
    )


def _build_carried_forward_event(
    prev: AlertEvent,
    batch_id: str,
    snapshot_id: str,
    index: int,
    ingested_at: datetime,
    data_quality_status: str,
    classification_reason: str,
) -> AlertEvent:
    """A previously-active alert not seen this run, where the source data
    isn't trustworthy enough to call it resolved yet (or ever, if the source
    itself is unhealthy) — see request Section 4 ("prevent false
    resolutions"). Carries the previous observation's classification, count,
    and identity forward unchanged; interval/rate fields are None (not 0)
    since no new reading actually happened this run — claiming zero change
    would be as false as claiming resolution."""
    id_seed = "|".join([snapshot_id, "carried", str(index), prev.fingerprint_exact or "", prev.fingerprint_general or ""])
    alert_id = hashlib.sha1(id_seed.encode("utf-8")).hexdigest()[:16]
    return AlertEvent(
        alert_id=f"{snapshot_id}-cf-{alert_id}",
        batch_id=batch_id,
        status=prev.status,
        category=prev.category,
        signal_type=prev.signal_type,
        processed_at=ingested_at,
        ingested_at=ingested_at,
        observed_at=prev.observed_at,
        is_red=prev.is_red,
        red_threshold=prev.red_threshold,
        hostname=prev.hostname,
        raw_filename=prev.raw_filename,
        log_file=prev.log_file,
        error_type=prev.error_type,
        count=prev.count,
        growth=prev.growth,
        raw_signed_delta=None,
        interval_delta=None,
        interval_seconds=None,
        rate_per_hour=None,
        counter_reset_detected=False,
        counter_epoch=prev.counter_epoch,
        data_quality_status=data_quality_status,
        severity=prev.severity,
        first_seen=prev.first_seen,
        last_seen=prev.last_seen,
        fingerprint=prev.fingerprint,
        fingerprint_exact=prev.fingerprint_exact,
        fingerprint_general=prev.fingerprint_general,
        classification_reason=classification_reason,
        suggested_action=prev.suggested_action,
        known_issue_id=prev.known_issue_id,
        owner=prev.owner,
        runbook_link=prev.runbook_link,
        ticket_link=prev.ticket_link,
        notes=prev.notes,
        system_type=prev.system_type,
        system=prev.system,
        tenant=prev.tenant,
        error_index=prev.error_index,
        color=prev.color,
        raw_known_error=prev.raw_known_error,
        raw_note=prev.raw_note,
        caused_by=prev.caused_by,
        previous_count=prev.previous_count,
        snapshot_id=snapshot_id,
        series_id=prev.series_id,
        source_filename=prev.source_filename,
        source_generated_time=prev.source_generated_time,
        source_state_file=prev.source_state_file,
        source_file_hash=prev.source_file_hash,
    )


def _persist_snapshot_files(
    db: Session,
    snapshot_id: str,
    file_reads: List[PromFileRead],
    quality_by_filename: Dict[str, str],
) -> List[Dict[str, Any]]:
    processed_files: List[Dict[str, Any]] = []
    for fr in file_reads:
        quality_status = quality_by_filename.get(fr.filename, "ok")
        db.add(PromSnapshotFile(
            snapshot_id=snapshot_id,
            filename=fr.filename,
            file_path=fr.full_path,
            file_hash=fr.file_hash,
            file_modified_time=fr.modified_time,
            size_bytes=fr.size_bytes,
            metric_count=fr.metric_count,
            generated_time=fr.generated_time,
            state_file=fr.state_file,
            quality_status=quality_status,
            invalid_row_count=fr.invalid_row_count,
            duplicate_row_count=fr.duplicate_row_count,
            parse_warnings="\n".join(fr.parse_warnings) if fr.parse_warnings else None,
        ))
        processed_files.append({
            "filename": fr.filename,
            "metric_count": fr.metric_count,
            "size_bytes": fr.size_bytes,
            "generated_time": fr.generated_time,
            "quality_status": quality_status,
        })
    return processed_files


def _skipped_response(previous_snapshot: PromSnapshot, source_files: List[Path], mode: str, file_hash: str) -> Dict[str, Any]:
    return {
        "status": "skipped",
        "message": "No new .prom folder changes detected.",
        "source_mode": mode,
        "configured_path": str(PROM_FILE_PATH),
        "total_files": len(source_files),
        "total_metrics": previous_snapshot.total_metrics,
        "created_alert_events": 0,
        "resolved_alert_events": 0,
        "snapshot_id": previous_snapshot.snapshot_id,
        "batch_id": previous_snapshot.batch_id,
        "file_hash": file_hash,
        "processed_files": [],
    }


def process_prom_file(db: Session) -> Dict[str, Any]:
    if not _process_lock.acquire(blocking=False):
        raise ProcessAlreadyRunningError(
            "Another .prom processing run is already in progress (watcher or manual trigger)."
        )
    try:
        return _process_prom_file_locked(db)
    finally:
        _process_lock.release()


def _process_prom_file_locked(db: Session) -> Dict[str, Any]:
    root_path = PROM_FILE_PATH
    mode = source_mode(root_path)
    if mode == "missing":
        raise FileNotFoundError(f"Configured .prom path not found: {root_path}")

    source_files = resolve_source_files(root_path)
    if not source_files:
        raise FileNotFoundError(f"No .prom files found in {root_path}")

    if not _wait_until_stable(source_files):
        raise RuntimeError("Prom source files did not stabilize before reading.")

    # One read per file — hash, size, mtime, generated time, state file, line
    # count, and parsed metrics all come from this single pass (see
    # backend/services/prom_inventory.py::read_prom_file).
    file_reads = [read_prom_file(src) for src in source_files]

    file_hash = combine_file_hashes(file_reads)
    previous_snapshot = _latest_successful_snapshot(db)
    if previous_snapshot and previous_snapshot.file_hash == file_hash:
        return _skipped_response(previous_snapshot, source_files, mode, file_hash)

    raw_alerts: List[Dict[str, Any]] = []
    total_lines = 0
    fallback_generated_time = max(
        (fr.generated_time_parsed for fr in file_reads if fr.generated_time_parsed),
        default=None,
    ) or datetime.utcnow()

    # Source/data-quality (Section 4: "prevent false resolutions") — computed
    # once per run against the previous snapshot's own file list, before any
    # resolution decisions are made below.
    expected_filenames = _expected_filenames(db, previous_snapshot)
    source_health = _compute_source_health(file_reads, fallback_generated_time, expected_filenames)
    quality_by_filename = source_health["quality_by_filename"]

    for fr in file_reads:
        # Each file's rows are tagged with THAT file's own observed_at — a
        # single folder-wide timestamp would silently ignore real skew
        # between files (the test-data folder alone has ~20 minutes of it).
        file_observed_at = fr.generated_time_parsed or fallback_generated_time
        for metric in fr.metrics:
            metric["observed_at"] = file_observed_at
            metric["source_filename"] = fr.filename
            metric["source_generated_time"] = fr.generated_time
            metric["source_state_file"] = fr.state_file
            metric["source_file_hash"] = fr.file_hash
            raw_alerts.append(metric)
        total_lines += fr.line_count

    generated_time = fallback_generated_time
    ingested_at = datetime.utcnow()
    snapshot_id = _format_snapshot_id(ingested_at, file_hash)
    batch_id = _format_batch_id(generated_time, file_hash)

    batch = AlertBatch(
        batch_id=batch_id,
        source="IotGW",
        environment="Production",
        email_subject="Prometheus scanfor_errors snapshot",
        sender="local-prom-folder" if mode == "folder" else "local-prom-file",
        received_time=generated_time.isoformat(),
        received_time_display=generated_time.strftime("%Y-%m-%d %H:%M:%S"),
        processed_at=ingested_at.isoformat(),
        total_issues_detected=len(raw_alerts),
    )
    db.add(batch)
    db.flush()

    latest_mtime = max((p.stat().st_mtime for p in source_files), default=0)
    snapshot = PromSnapshot(
        snapshot_id=snapshot_id,
        batch_id=batch_id,
        file_path=str(root_path.resolve()),
        source_mode=mode,
        total_files=len(source_files),
        file_hash=file_hash,
        file_modified_time=str(latest_mtime),
        processed_at=ingested_at.isoformat(),
        total_lines=total_lines,
        total_metrics=len(raw_alerts),
        status="processed",
        error_message="",
        completeness_status=source_health["completeness_status"],
        missing_files=json.dumps(source_health["missing_files"]),
        newly_discovered_files=json.dumps(source_health["newly_discovered_files"]),
    )
    db.add(snapshot)
    db.flush()

    processed_files = _persist_snapshot_files(db, snapshot_id, file_reads, quality_by_filename)

    known_issues = db.query(KnownIssue).filter(KnownIssue.status != "archived").all()
    previous_active_alerts = _previous_active_alerts(db, previous_snapshot)

    current_general_fingerprints: set = set()
    matched_previous_ids: set = set()
    now_iso = ingested_at.isoformat()

    skipped_malformed = 0
    for index, raw in enumerate(raw_alerts):
        try:
            raw["fingerprint_exact"] = build_fingerprint_exact(
                raw["tenant"], raw["system"], raw["hostname"], raw["log_file"],
                raw["error_type"], raw["error_index"], raw["caused_by"],
            )
            raw["fingerprint_general"] = build_fingerprint_general(
                raw["tenant"], raw["system"], raw["hostname"], raw["log_file"],
                raw["error_type"], raw["error_index"], raw["caused_by"],
            )

            previous = _find_previous_alert(previous_active_alerts, raw["fingerprint_exact"], raw["fingerprint_general"])
            if previous:
                matched_previous_ids.add(previous.id)
            raw["previous_count"] = previous.count if previous else 0
            raw["growth"] = raw["count"] - raw["previous_count"]
            raw["first_seen"] = previous.first_seen if previous else now_iso
            raw["last_seen"] = now_iso

            raw["counter_epoch"] = extract_log_epoch(raw["raw_filename"])
            previous_epoch = extract_log_epoch(previous.raw_filename) if previous else None
            counter_result = compute_counter_delta(
                current_count=raw["count"],
                previous_count=previous.count if previous else None,
                current_epoch=raw["counter_epoch"],
                previous_epoch=previous_epoch,
                current_raw_filename=raw["raw_filename"],
                previous_raw_filename=previous.raw_filename if previous else None,
                current_state_file=raw["source_state_file"],
                previous_state_file=previous.source_state_file if previous else None,
            )
            raw["raw_signed_delta"] = counter_result.raw_signed_delta
            raw["interval_delta"] = counter_result.interval_delta
            raw["counter_reset_detected"] = counter_result.counter_reset_detected
            raw["data_quality_status"] = counter_result.data_quality_status
            # A stale source file makes every row it produced suspect,
            # regardless of what the counter math itself concluded — a
            # frozen file can "match" an alert every run without ever
            # reflecting a real new reading.
            if quality_by_filename.get(raw["source_filename"]) == "stale":
                raw["data_quality_status"] = "source_stale"
            raw["interval_seconds"] = compute_interval_seconds(
                raw["observed_at"], previous.observed_at if previous else None
            )
            raw["rate_per_hour"] = compute_rate_per_hour(raw["interval_delta"], raw["interval_seconds"])

            series = _find_or_create_series(db, raw, raw["observed_at"])

            event = _build_alert_event(raw, batch_id, snapshot_id, known_issues, index, ingested_at, series)
            db.add(event)
            current_general_fingerprints.add(event.fingerprint_general)
        except Exception:
            # A single malformed .prom row must not fail the whole ingestion run.
            # Log and skip it — every other row in this batch still gets stored.
            skipped_malformed += 1
            _LOG.exception(
                "skipping malformed alert row batch=%s index=%d hostname=%r",
                batch_id, index, raw.get("hostname"),
            )
    if skipped_malformed:
        _LOG.warning("batch=%s skipped %d malformed row(s) out of %d parsed", batch_id, skipped_malformed, len(raw_alerts))

    # Resolution gating (Section 4: "prevent false resolutions"). A
    # previously-active alert absent from this run is only a candidate for
    # resolution if its own source file was actually healthy this run —
    # otherwise we can't trust the absence at all, and it's carried forward
    # unchanged with a data_quality_status explaining why. Even when the
    # source is healthy, a genuine absence must persist through a configured
    # grace period (RESOLUTION_GRACE_MIN_SNAPSHOTS *and*
    # RESOLUTION_GRACE_MIN_SECONDS of elapsed *source* time) before it's
    # actually marked resolved.
    resolved_events: List[AlertEvent] = []
    carried_forward_events: List[AlertEvent] = []
    for prev in previous_active_alerts:
        if prev.id in matched_previous_ids:
            continue
        if prev.fingerprint_general in current_general_fingerprints:
            continue

        if not _is_source_healthy(prev.source_filename, quality_by_filename):
            file_status = quality_by_filename.get(prev.source_filename)
            if file_status == "stale":
                data_quality_status = "source_stale"
                reason = f"Source file {prev.source_filename} has not refreshed recently enough to confirm resolution."
            elif file_status == "parse_failure":
                data_quality_status = "source_parse_failure"
                reason = f"Source file {prev.source_filename} could not be read/parsed this run."
            else:
                data_quality_status = "source_missing"
                reason = f"Source file {prev.source_filename} was not present in this run's scan."
            carried_forward_events.append(_build_carried_forward_event(
                prev, batch_id, snapshot_id, len(carried_forward_events), ingested_at, data_quality_status, reason,
            ))
            continue

        series = db.query(AlertSeries).filter(AlertSeries.id == prev.series_id).first() if prev.series_id else None
        if series is None:
            # No series link (shouldn't happen once the Phase 1 backfill has
            # run) — nowhere to track grace state, so fall back to the
            # previous (immediate) behavior rather than tracking it nowhere.
            grace_met = True
        else:
            if series.pending_resolution_since is None:
                series.pending_resolution_since = fallback_generated_time
                series.absence_count = 1
            else:
                series.absence_count += 1
            db.add(series)
            elapsed_seconds = (fallback_generated_time - series.pending_resolution_since).total_seconds()
            grace_met = (
                series.absence_count >= RESOLUTION_GRACE_MIN_SNAPSHOTS
                and elapsed_seconds >= RESOLUTION_GRACE_MIN_SECONDS
            )

        if grace_met:
            resolved_events.append(_build_resolved_event(prev, batch_id, snapshot_id, len(resolved_events), ingested_at))
            if series is not None:
                series.pending_resolution_since = None
                series.absence_count = 0
                series.lifecycle_status = "resolved"
                db.add(series)
        else:
            carried_forward_events.append(_build_carried_forward_event(
                prev, batch_id, snapshot_id, len(carried_forward_events), ingested_at,
                "pending_resolution",
                "Alert not seen this run; awaiting the resolution grace period before confirming resolved.",
            ))

    for event in carried_forward_events:
        db.add(event)
    for resolved in resolved_events:
        db.add(resolved)

    db.commit()

    return {
        "status": "processed",
        "message": "Prom folder processed successfully.",
        "source_mode": mode,
        "configured_path": str(root_path),
        "total_files": len(source_files),
        "total_metrics": len(raw_alerts),
        "created_alert_events": len(raw_alerts),
        "resolved_alert_events": len(resolved_events),
        "carried_forward_alert_events": len(carried_forward_events),
        "completeness_status": source_health["completeness_status"],
        "missing_files": source_health["missing_files"],
        "snapshot_id": snapshot_id,
        "batch_id": batch_id,
        "file_hash": file_hash,
        "processed_files": processed_files,
    }
