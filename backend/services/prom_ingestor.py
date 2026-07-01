import hashlib
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from backend.database.models import (
    AlertBatch,
    AlertEvent,
    KnownIssue,
    PromSnapshot,
    PromSnapshotFile,
)
from backend.services.classifier import classify_alert
from backend.services.config import PROM_FILE_PATH
from backend.services.fingerprint import build_fingerprint_exact, build_fingerprint_general
from backend.services.prom_inventory import (
    describe_file,
    folder_hash,
    resolve_source_files,
    source_mode,
)
from backend.services.prom_parser import parse_prom_file


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


def _parse_generated_time(paths: List[Path]) -> Optional[datetime]:
    latest: Optional[datetime] = None
    for path in paths:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                if not line.startswith("#"):
                    break
                if line.startswith("# Generated:"):
                    value = line.partition(":")[2].strip()
                    try:
                        parsed = datetime.fromisoformat(value)
                    except ValueError:
                        try:
                            parsed = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
                        except ValueError:
                            parsed = None
                    if parsed and (latest is None or parsed > latest):
                        latest = parsed
                    break
    return latest


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


def _build_alert_event(
    alert: Dict[str, Any],
    batch_id: str,
    snapshot_id: str,
    known_issues: List[KnownIssue],
    index: int,
) -> AlertEvent:
    classification = classify_alert(
        alert["hostname"],
        alert["log_file"],
        alert["error_type"],
        alert["count"],
        alert["growth"],
        known_issues=known_issues,
    )
    severity = _apply_color_severity(alert["color"], classification["severity"])

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
        runbook_link=None,
        ticket_link=None,
        notes="",
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
    )


def _build_resolved_event(
    prev: AlertEvent,
    batch_id: str,
    snapshot_id: str,
    index: int,
) -> AlertEvent:
    id_seed = "|".join([snapshot_id, "resolved", str(index), prev.fingerprint_exact or "", prev.fingerprint_general or ""])
    alert_id = hashlib.sha1(id_seed.encode("utf-8")).hexdigest()[:16]
    return AlertEvent(
        alert_id=f"{snapshot_id}-res-{alert_id}",
        batch_id=batch_id,
        status="resolved",
        category="resolved",
        hostname=prev.hostname,
        raw_filename=prev.raw_filename,
        log_file=prev.log_file,
        error_type=prev.error_type,
        count=0,
        growth=-1 * (prev.count or 0),
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
    )


def _persist_snapshot_files(db: Session, snapshot_id: str, source_files: List[Path], per_file_metrics: List[int]) -> List[Dict[str, Any]]:
    processed_files: List[Dict[str, Any]] = []
    for path, metric_count in zip(source_files, per_file_metrics):
        info = describe_file(path)
        info["metric_count"] = metric_count
        db.add(PromSnapshotFile(
            snapshot_id=snapshot_id,
            filename=info["filename"],
            file_path=info["full_path"],
            file_hash=hashlib.sha256(path.read_bytes()).hexdigest(),
            file_modified_time=info["modified_time"],
            size_bytes=info["size_bytes"],
            metric_count=metric_count,
            generated_time=info["generated_time"],
            state_file=info["state_file"],
        ))
        processed_files.append({
            "filename": info["filename"],
            "metric_count": metric_count,
            "size_bytes": info["size_bytes"],
            "generated_time": info["generated_time"],
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
    root_path = PROM_FILE_PATH
    mode = source_mode(root_path)
    if mode == "missing":
        raise FileNotFoundError(f"Configured .prom path not found: {root_path}")

    source_files = resolve_source_files(root_path)
    if not source_files:
        raise FileNotFoundError(f"No .prom files found in {root_path}")

    if not _wait_until_stable(source_files):
        raise RuntimeError("Prom source files did not stabilize before reading.")

    file_hash = folder_hash(source_files)
    previous_snapshot = _latest_successful_snapshot(db)
    if previous_snapshot and previous_snapshot.file_hash == file_hash:
        return _skipped_response(previous_snapshot, source_files, mode, file_hash)

    raw_alerts: List[Dict[str, Any]] = []
    per_file_metrics: List[int] = []
    total_lines = 0
    for src in source_files:
        parsed = parse_prom_file(src)
        raw_alerts.extend(parsed)
        per_file_metrics.append(len(parsed))
        total_lines += sum(1 for _ in src.open("r", encoding="utf-8"))

    generated_time = _parse_generated_time(source_files) or datetime.utcnow()
    processed_at = datetime.utcnow()
    snapshot_id = _format_snapshot_id(processed_at, file_hash)
    batch_id = _format_batch_id(generated_time, file_hash)

    batch = AlertBatch(
        batch_id=batch_id,
        source="IotGW",
        environment="Production",
        email_subject="Prometheus scanfor_errors snapshot",
        sender="local-prom-folder" if mode == "folder" else "local-prom-file",
        received_time=generated_time.isoformat(),
        received_time_display=generated_time.strftime("%Y-%m-%d %H:%M:%S"),
        processed_at=processed_at.isoformat(),
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
        processed_at=processed_at.isoformat(),
        total_lines=total_lines,
        total_metrics=len(raw_alerts),
        status="processed",
        error_message="",
    )
    db.add(snapshot)
    db.flush()

    processed_files = _persist_snapshot_files(db, snapshot_id, source_files, per_file_metrics)

    known_issues = db.query(KnownIssue).filter(KnownIssue.status != "archived").all()
    previous_active_alerts = _previous_active_alerts(db, previous_snapshot)

    current_general_fingerprints: set = set()
    matched_previous_ids: set = set()
    now_iso = processed_at.isoformat()

    for index, raw in enumerate(raw_alerts):
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

        event = _build_alert_event(raw, batch_id, snapshot_id, known_issues, index)
        db.add(event)
        current_general_fingerprints.add(event.fingerprint_general)

    resolved_events: List[AlertEvent] = []
    for prev in previous_active_alerts:
        if prev.id in matched_previous_ids:
            continue
        if prev.fingerprint_general in current_general_fingerprints:
            continue
        resolved_events.append(_build_resolved_event(prev, batch_id, snapshot_id, len(resolved_events)))
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
        "snapshot_id": snapshot_id,
        "batch_id": batch_id,
        "file_hash": file_hash,
        "processed_files": processed_files,
    }
