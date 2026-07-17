"""
services/retention.py
─────────────────────────────────────────────────────────────────────────────
Offloads aged-out alert history so alert_events (and its children) don't grow
unbounded. A row is eligible for offload only if ALL of these hold:

  - older than the retention window (AlertEvent.created_at < cutoff)
  - not tied to an open ticket (ticket_link IS NULL)
  - not tied to an active known issue (known_issue_id IS NULL, or the linked
    KnownIssue.status is "archived")
  - not part of the single most recent successful PromSnapshot, which
    prom_ingestor.py always needs for the next growth comparison

Eligible rows are exported to CSV before deletion. alert_notes and
issue_status_history rows for those alerts are exported and deleted the same
way (their FK is alert_event_id, not the alert_events primary key, so ORM
cascade doesn't cover a bulk Query.delete() and is handled explicitly here).
alert_batches / prom_snapshots / prom_snapshot_files left with zero remaining
alert_events afterward are deleted too (still protecting the latest snapshot).

VACUUM is intentionally NOT run in here — SQLite can't VACUUM inside an open
transaction, so the caller runs it separately once this session is closed.
"""

import csv
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List

from sqlalchemy import inspect as sa_inspect, or_
from sqlalchemy.orm import Session

from backend.database.models import (
    AlertBatch,
    AlertEvent,
    AlertNote,
    IssueStatusHistory,
    KnownIssue,
    PromSnapshot,
    PromSnapshotFile,
)


def _rows_to_dicts(rows: List[Any]) -> List[Dict[str, Any]]:
    dicts = []
    for row in rows:
        mapper = sa_inspect(row).mapper
        dicts.append({col.key: getattr(row, col.key) for col in mapper.column_attrs})
    return dicts


def _export_csv(rows: List[Dict[str, Any]], path: Path) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _latest_successful_snapshot(db: Session) -> "PromSnapshot | None":
    return (
        db.query(PromSnapshot)
        .filter(PromSnapshot.status == "processed")
        .order_by(PromSnapshot.processed_at.desc())
        .first()
    )


def run_retention(db: Session, retention_days: int, export_dir: Path) -> Dict[str, Any]:
    cutoff = datetime.utcnow() - timedelta(days=retention_days)
    run_stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")

    latest_snapshot = _latest_successful_snapshot(db)
    protected_snapshot_id = latest_snapshot.snapshot_id if latest_snapshot else None
    protected_batch_id = latest_snapshot.batch_id if latest_snapshot else None

    candidates_query = (
        db.query(AlertEvent)
        .outerjoin(KnownIssue, AlertEvent.known_issue_id == KnownIssue.known_issue_id)
        .filter(AlertEvent.created_at < cutoff)
        .filter(AlertEvent.ticket_link.is_(None))
        .filter(or_(AlertEvent.known_issue_id.is_(None), KnownIssue.status == "archived"))
    )
    if protected_snapshot_id:
        candidates_query = candidates_query.filter(AlertEvent.snapshot_id != protected_snapshot_id)

    candidates = candidates_query.all()

    empty_result = {
        "status": "no-op",
        "cutoff": cutoff.isoformat(),
        "retention_days": retention_days,
        "deleted_alert_events": 0,
        "deleted_alert_notes": 0,
        "deleted_status_history": 0,
        "deleted_batches": 0,
        "deleted_snapshots": 0,
        "deleted_snapshot_files": 0,
        "export_dir": None,
    }
    if not candidates:
        return empty_result

    alert_ids = [c.alert_id for c in candidates]
    notes = db.query(AlertNote).filter(AlertNote.alert_event_id.in_(alert_ids)).all()
    history = db.query(IssueStatusHistory).filter(IssueStatusHistory.alert_event_id.in_(alert_ids)).all()

    export_prefix = export_dir / f"retention_{run_stamp}"
    _export_csv(_rows_to_dicts(candidates), Path(f"{export_prefix}_alert_events.csv"))
    _export_csv(_rows_to_dicts(notes), Path(f"{export_prefix}_alert_notes.csv"))
    _export_csv(_rows_to_dicts(history), Path(f"{export_prefix}_issue_status_history.csv"))

    deleted_notes = (
        db.query(AlertNote)
        .filter(AlertNote.alert_event_id.in_(alert_ids))
        .delete(synchronize_session=False)
    )
    deleted_history = (
        db.query(IssueStatusHistory)
        .filter(IssueStatusHistory.alert_event_id.in_(alert_ids))
        .delete(synchronize_session=False)
    )
    deleted_events = (
        db.query(AlertEvent)
        .filter(AlertEvent.alert_id.in_(alert_ids))
        .delete(synchronize_session=False)
    )
    db.commit()

    # Orphan cleanup: batches/snapshots with zero remaining alert_events, excluding the
    # single most recent successful snapshot (still needed for the next comparison pass).
    remaining_batch_ids = {row[0] for row in db.query(AlertEvent.batch_id).distinct().all()}

    orphaned_batches_q = db.query(AlertBatch)
    orphaned_snapshots_q = db.query(PromSnapshot)
    if remaining_batch_ids:
        orphaned_batches_q = orphaned_batches_q.filter(~AlertBatch.batch_id.in_(remaining_batch_ids))
        orphaned_snapshots_q = orphaned_snapshots_q.filter(~PromSnapshot.batch_id.in_(remaining_batch_ids))
    if protected_batch_id:
        orphaned_batches_q = orphaned_batches_q.filter(AlertBatch.batch_id != protected_batch_id)
    if protected_snapshot_id:
        orphaned_snapshots_q = orphaned_snapshots_q.filter(PromSnapshot.snapshot_id != protected_snapshot_id)

    orphaned_batches = orphaned_batches_q.all()
    orphaned_snapshots = orphaned_snapshots_q.all()

    deleted_snapshot_files = 0
    for snap in orphaned_snapshots:
        deleted_snapshot_files += (
            db.query(PromSnapshotFile)
            .filter(PromSnapshotFile.snapshot_id == snap.snapshot_id)
            .delete(synchronize_session=False)
        )
        db.delete(snap)
    for batch in orphaned_batches:
        db.delete(batch)
    db.commit()

    return {
        "status": "completed",
        "cutoff": cutoff.isoformat(),
        "retention_days": retention_days,
        "deleted_alert_events": deleted_events,
        "deleted_alert_notes": deleted_notes,
        "deleted_status_history": deleted_history,
        "deleted_batches": len(orphaned_batches),
        "deleted_snapshots": len(orphaned_snapshots),
        "deleted_snapshot_files": deleted_snapshot_files,
        "export_dir": str(export_dir),
    }
