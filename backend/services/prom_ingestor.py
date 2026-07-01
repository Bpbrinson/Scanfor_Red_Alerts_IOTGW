import hashlib
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from backend.database.models import AlertBatch, AlertEvent, KnownIssue, PromSnapshot
from backend.services.classifier import classify_alert
from backend.services.config import PROM_FILE_PATH
from backend.services.fingerprint import build_fingerprint_exact, build_fingerprint_general
from backend.services.prom_parser import parse_prom_file


def _compute_file_hash(path: Path) -> str:
    content = path.read_bytes()
    return hashlib.sha256(content).hexdigest()


def _format_snapshot_id(timestamp: datetime) -> str:
    return timestamp.strftime("PROM-%Y%m%d-%H%M%S")


def _parse_generated_time(path: Path) -> Optional[datetime]:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("# Generated:"):
            value = line.partition(":")[2].strip()
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                try:
                    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    return None
    return None


def _wait_until_stable(path: Path, timeout_seconds: int = 10) -> bool:
    if not path.exists():
        return False
    stable_until = time.time() + timeout_seconds
    last_size = path.stat().st_size
    while time.time() < stable_until:
        time.sleep(1)
        current_size = path.stat().st_size
        if current_size == last_size:
            return True
        last_size = current_size
    return False


def _latest_successful_snapshot(db: Session) -> Optional[PromSnapshot]:
    return (
        db.query(PromSnapshot)
        .filter(PromSnapshot.status == "processed")
        .order_by(PromSnapshot.processed_at.desc())
        .first()
    )


def _latest_snapshot_by_hash(db: Session, file_hash: str) -> Optional[PromSnapshot]:
    return (
        db.query(PromSnapshot)
        .filter(PromSnapshot.file_hash == file_hash)
        .order_by(PromSnapshot.processed_at.desc())
        .first()
    )


def _merge_previous_seen(alert: AlertEvent, previous: Optional[AlertEvent]) -> None:
    if previous:
        alert.first_seen = previous.first_seen or alert.first_seen


def _find_previous_alert(db: Session, alert: Dict[str, any], previous_snapshot: Optional[PromSnapshot]) -> Optional[AlertEvent]:
    if not previous_snapshot:
        return None

    query = db.query(AlertEvent).filter(AlertEvent.snapshot_id == previous_snapshot.snapshot_id)
    exact = query.filter(AlertEvent.fingerprint_exact == alert["fingerprint_exact"]).first()
    if exact:
        return exact
    return query.filter(AlertEvent.fingerprint_general == alert["fingerprint_general"]).first()


def _classify_alert(alert: Dict[str, any], known_issues: List[KnownIssue]) -> Dict[str, any]:
    return classify_alert(
        alert["hostname"],
        alert["log_file"],
        alert["error_type"],
        alert["count"],
        alert["growth"],
        known_issues=known_issues,
    )


def _build_alert_event(alert: Dict[str, any], batch_id: str, snapshot_id: str, previous_alert: Optional[AlertEvent], known_issues: List[KnownIssue]) -> AlertEvent:
    classification = _classify_alert(alert, known_issues)
    id_seed = "|".join(
        [
            snapshot_id,
            alert["hostname"],
            alert["raw_filename"],
            alert["error_type"],
            alert["error_index"],
            str(alert.get("caused_by", "")),
            alert["tenant"],
            alert["system"],
        ]
    )
    alert_id = hashlib.sha1(id_seed.encode("utf-8")).hexdigest()[:16]
    event = AlertEvent(
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
        severity=classification["severity"],
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
        raw_known_error=alert["raw_known_error"],
        raw_note=alert["raw_note"],
        caused_by=alert["caused_by"],
        previous_count=alert["previous_count"],
        snapshot_id=snapshot_id,
    )

    _merge_previous_seen(event, previous_alert)
    return event


def _resolve_missing_alerts(db: Session, batch_id: str, snapshot_id: str, previous_snapshot: Optional[PromSnapshot], current_fingerprints: List[str], known_issues: List[KnownIssue]) -> List[AlertEvent]:
    if not previous_snapshot:
        return []

    previous_alerts = db.query(AlertEvent).filter(AlertEvent.snapshot_id == previous_snapshot.snapshot_id).all()
    resolved_events: List[AlertEvent] = []

    for prev in previous_alerts:
        if prev.fingerprint_general in current_fingerprints:
            continue
        resolved = AlertEvent(
            alert_id=f"{snapshot_id}-resolved-{prev.alert_id}",
            batch_id=batch_id,
            status="resolved",
            category="resolved",
            hostname=prev.hostname,
            raw_filename=prev.raw_filename,
            log_file=prev.log_file,
            error_type=prev.error_type,
            count=0,
            growth=-1 * (prev.previous_count or prev.count or 0),
            severity=prev.severity,
            first_seen=prev.first_seen,
            last_seen=prev.last_seen,
            fingerprint=prev.fingerprint,
            fingerprint_exact=prev.fingerprint_exact,
            fingerprint_general=prev.fingerprint_general,
            classification_reason="Previously active issue not seen in current .prom snapshot.",
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
        resolved_events.append(resolved)

    return resolved_events


def _create_batch(db: Session, source: str, received_time: datetime, total_metrics: int) -> AlertBatch:
    batch_id = _format_snapshot_id(received_time)
    batch = AlertBatch(
        batch_id=batch_id,
        source=source,
        environment="Production",
        email_subject="Prometheus scanfor_errors snapshot",
        sender="local-prom-file",
        received_time=received_time.isoformat(),
        received_time_display=received_time.strftime("%Y-%m-%d %H:%M:%S"),
        processed_at=datetime.utcnow().isoformat(),
        total_issues_detected=total_metrics,
    )
    db.add(batch)
    db.flush()
    return batch


def _create_snapshot(db: Session, file_path: Path, file_hash: str, processed_at: datetime, total_lines: int, total_metrics: int, batch_id: str, status: str, error_message: Optional[str] = None) -> PromSnapshot:
    snapshot_id = _format_snapshot_id(processed_at)
    snapshot = PromSnapshot(
        snapshot_id=snapshot_id,
        batch_id=batch_id,
        file_path=str(file_path.resolve()),
        file_hash=file_hash,
        file_modified_time=file_path.stat().st_mtime,
        processed_at=processed_at.isoformat(),
        total_lines=total_lines,
        total_metrics=total_metrics,
        status=status,
        error_message=error_message or "",
    )
    db.add(snapshot)
    db.flush()
    return snapshot


def process_prom_file(db: Session) -> Dict[str, any]:
    file_path = PROM_FILE_PATH
    if not file_path.exists():
        raise FileNotFoundError(f"Configured .prom file not found: {file_path}")

    if not _wait_until_stable(file_path):
        raise RuntimeError("Prom file did not stabilize before reading.")

    file_hash = _compute_file_hash(file_path)
    previous_snapshot = _latest_successful_snapshot(db)
    if previous_snapshot and previous_snapshot.file_hash == file_hash:
        return {
            "status": "skipped",
            "message": "No new .prom changes detected.",
            "snapshot_id": previous_snapshot.snapshot_id,
            "batch_id": previous_snapshot.batch_id,
            "total_metrics": previous_snapshot.total_metrics,
            "created_alert_events": 0,
            "resolved_alert_events": 0,
            "file_hash": file_hash,
        }

    raw_alerts = parse_prom_file(file_path)
    generated_time = _parse_generated_time(file_path) or datetime.utcnow()
    batch = _create_batch(db, source="IotGW", received_time=generated_time, total_metrics=len(raw_alerts))
    snapshot = _create_snapshot(
        db,
        file_path=file_path,
        file_hash=file_hash,
        processed_at=datetime.utcnow(),
        total_lines=len(file_path.read_text(encoding="utf-8").splitlines()),
        total_metrics=len(raw_alerts),
        batch_id=batch.batch_id,
        status="processed",
    )

    known_issues = db.query(KnownIssue).filter(KnownIssue.status != "archived").all()
    current_fingerprints: List[str] = []
    created_alerts = []

    for raw in raw_alerts:
        raw["fingerprint_exact"] = build_fingerprint_exact(
            raw["tenant"], raw["system"], raw["hostname"], raw["log_file"], raw["error_type"], raw["error_index"], raw["caused_by"],
        )
        raw["fingerprint_general"] = build_fingerprint_general(
            raw["tenant"], raw["system"], raw["hostname"], raw["log_file"], raw["error_type"], raw["error_index"], raw["caused_by"],
        )

        previous_alert = _find_previous_alert(db, raw, previous_snapshot)
        raw["previous_count"] = previous_alert.count if previous_alert else 0
        raw["growth"] = raw["count"] - raw["previous_count"]
        raw["first_seen"] = previous_alert.first_seen if previous_alert else datetime.utcnow().isoformat()
        raw["last_seen"] = datetime.utcnow().isoformat()

        event = _build_alert_event(raw, batch.batch_id, snapshot.snapshot_id, previous_alert, known_issues)
        db.add(event)
        created_alerts.append(event)
        current_fingerprints.append(event.fingerprint_general)

    resolved_events = _resolve_missing_alerts(db, batch.batch_id, snapshot.snapshot_id, previous_snapshot, current_fingerprints, known_issues)
    for resolved in resolved_events:
        db.add(resolved)

    db.commit()

    return {
        "status": "processed",
        "message": "Prom file processed successfully.",
        "snapshot_id": snapshot.snapshot_id,
        "batch_id": batch.batch_id,
        "total_metrics": len(raw_alerts),
        "created_alert_events": len(created_alerts),
        "resolved_alert_events": len(resolved_events),
        "file_hash": file_hash,
    }
