from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from backend.database.db import get_db
from backend.database.models import (
    AlertBatch,
    AlertEvent,
    KnownIssue,
    AlertNote,
    IssueStatusHistory,
)
from backend.database.schemas import (
    AlertNoteCreate,
    AlertStatusUpdate,
    AlertTicketUpdate,
    MarkKnownRequest,
)
from backend.services.classifier import classify_alert

router = APIRouter()


def _event_to_dict(event: AlertEvent) -> dict:
    return {
        "alert_id": event.alert_id,
        "batch_id": event.batch_id,
        "status": event.status,
        "category": event.category,
        "hostname": event.hostname,
        "raw_filename": event.raw_filename,
        "log_file": event.log_file,
        "error_type": event.error_type,
        "count": event.count,
        "growth": event.growth,
        "severity": event.severity,
        "first_seen": event.first_seen,
        "last_seen": event.last_seen,
        "fingerprint": event.fingerprint,
        "classification_reason": event.classification_reason,
        "suggested_action": event.suggested_action,
        "known_issue_id": event.known_issue_id,
        "owner": event.owner,
        "runbook_link": event.runbook_link,
        "ticket_link": event.ticket_link,
        "notes": event.notes or "",
        "normal_range": event.normal_range,
        "escalation_rule": event.escalation_rule,
    }


def _generate_known_issue_id(db: Session) -> str:
    known_issue_ids = [row[0] for row in db.query(KnownIssue.known_issue_id).all()]
    max_number = 0
    for value in known_issue_ids:
        try:
            num = int(value.split("-")[-1])
            if num > max_number:
                max_number = num
        except ValueError:
            continue
    return f"KI-{max_number + 1:03d}"


def _latest_batch_id(db: Session) -> Optional[str]:
    latest = db.query(AlertBatch).order_by(AlertBatch.id.desc()).first()
    return latest.batch_id if latest else None


def _normalize_category(category: Optional[str]) -> Optional[str]:
    if not category:
        return None

    normalized = category.strip().lower()
    if normalized in ["new", "new / unknown", "new unknown", "new_unknown"]:
        return "new"
    if normalized in ["known", "known issue", "known issues", "known_issue"]:
        return "known"
    if normalized in ["worsening", "known but worsening", "worsening issue", "worsening issues"]:
        return "worsening"
    if normalized in ["resolved", "resolved / no longer seen", "resolved no longer seen", "resolved_issue"]:
        return "resolved"
    if normalized in ["suppressed", "archived"]:
        return normalized
    return normalized


@router.get("/alert-batches/latest")
def get_latest_batch(db: Session = Depends(get_db)):
    batch = db.query(AlertBatch).order_by(AlertBatch.id.desc()).first()
    if not batch:
        raise HTTPException(status_code=404, detail="No alert batches found")

    total = (
        db.query(func.count(AlertEvent.id))
        .filter(AlertEvent.batch_id == batch.batch_id)
        .scalar()
        or 0
    )
    return {
        "batch_id": batch.batch_id,
        "source": batch.source,
        "received_time": batch.received_time,
        "received_time_display": batch.received_time_display,
        "environment": batch.environment,
        "email_subject": batch.email_subject,
        "sender": batch.sender,
        "processed_at": batch.processed_at,
        "total_issues_detected": total,
    }


@router.get("/alerts")
def get_alerts(
    category: Optional[str] = None,
    severity: Optional[str] = None,
    hostname: Optional[str] = None,
    error_type: Optional[str] = None,
    batch_id: Optional[str] = None,
    db: Session = Depends(get_db),
):
    latest_batch_id = _latest_batch_id(db)
    if not latest_batch_id:
        return []

    query = db.query(AlertEvent)

    if batch_id:
        query = query.filter(AlertEvent.batch_id == batch_id)
    else:
        query = query.filter(
            or_(
                AlertEvent.batch_id == latest_batch_id,
                AlertEvent.category == "resolved",
            )
        )

    normalized_category = _normalize_category(category)
    if normalized_category:
        query = query.filter(AlertEvent.category == normalized_category)
    if severity:
        query = query.filter(AlertEvent.severity == severity)
    if hostname:
        query = query.filter(AlertEvent.hostname.contains(hostname))
    if error_type:
        query = query.filter(AlertEvent.error_type.contains(error_type))

    events = query.order_by(AlertEvent.last_seen.desc()).all()
    return [_event_to_dict(event) for event in events]


@router.patch("/alerts/{alert_id}/ticket")
def update_alert_ticket(
    alert_id: str,
    update: AlertTicketUpdate,
    db: Session = Depends(get_db),
):
    event = db.query(AlertEvent).filter_by(alert_id=alert_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Alert not found")

    event.ticket_link = update.ticket_link or None
    db.add(event)
    db.commit()
    db.refresh(event)
    return _event_to_dict(event)


@router.post("/alerts/{alert_id}/notes")
def add_alert_note(
    alert_id: str,
    note_request: AlertNoteCreate,
    db: Session = Depends(get_db),
):
    event = db.query(AlertEvent).filter_by(alert_id=alert_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Alert not found")

    note = AlertNote(
        alert_event_id=alert_id,
        note=note_request.note,
        created_by=note_request.created_by,
    )
    event.notes = note_request.note or ""
    db.add(note)
    db.add(event)
    db.commit()
    db.refresh(note)
    return {
        "id": note.id,
        "alert_event_id": note.alert_event_id,
        "note": note.note,
        "created_by": note.created_by,
        "created_at": note.created_at.isoformat(),
    }


@router.patch("/alerts/{alert_id}/status")
def update_alert_status(
    alert_id: str,
    status_update: AlertStatusUpdate,
    db: Session = Depends(get_db),
):
    event = db.query(AlertEvent).filter_by(alert_id=alert_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Alert not found")

    old_status = event.status
    old_category = event.category
    event.status = status_update.status
    event.category = status_update.category or status_update.status

    if status_update.clear_known_issue:
        event.known_issue_id = None
        event.owner = None
        event.runbook_link = None
        event.normal_range = None
        event.escalation_rule = None
        event.classification_reason = "Manually moved back to New / Unknown."
        event.suggested_action = f"Re-triage {event.error_type} on {event.hostname}"

    history = IssueStatusHistory(
        alert_event_id=alert_id,
        old_status=old_status,
        new_status=event.category,
        changed_by=status_update.changed_by,
        change_reason=status_update.change_reason,
    )
    db.add(history)
    db.add(event)
    db.commit()
    db.refresh(event)
    return _event_to_dict(event)


@router.post("/alerts/{alert_id}/mark-known")
def mark_alert_known(
    alert_id: str,
    request: MarkKnownRequest,
    db: Session = Depends(get_db),
):
    event = db.query(AlertEvent).filter_by(alert_id=alert_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Alert not found")

    known_issue = None
    if request.known_issue_id:
        known_issue = (
            db.query(KnownIssue)
            .filter_by(known_issue_id=request.known_issue_id)
            .first()
        )
        if not known_issue:
            raise HTTPException(status_code=404, detail="Known issue not found")

    if request.new_known_issue:
        known_issue = KnownIssue(
            known_issue_id=_generate_known_issue_id(db),
            status="active",
            **request.new_known_issue.dict(),
        )
        db.add(known_issue)
        db.commit()
        db.refresh(known_issue)

    if not known_issue:
        raise HTTPException(
            status_code=400,
            detail="Provide known_issue_id or new_known_issue payload",
        )

    classification = classify_alert(
        event.hostname,
        event.log_file,
        event.error_type,
        event.count,
        event.growth,
        known_issues=[known_issue],
    )

    # User explicitly linked this alert to a KI — force it out of "new".
    # Worsening requires actual growth since the last snapshot; a high count
    # with growth == 0 stays "known".
    forced_category = "worsening" if classification["category"] == "worsening" else "known"

    max_count = known_issue.normal_count_max or 0
    if (
        event.count is not None
        and max_count
        and event.count > max_count
        and (event.growth or 0) > 0
    ):
        forced_category = "worsening"

    old_status = event.status
    event.status = forced_category
    event.category = forced_category
    event.known_issue_id = known_issue.known_issue_id
    event.owner = known_issue.owner or event.owner
    event.runbook_link = known_issue.runbook_link
    event.ticket_link = known_issue.ticket_link
    event.severity = classification["severity"] or known_issue.severity
    event.classification_reason = (
        classification["classification_reason"]
        if classification["category"] != "new"
        else f"Manually linked to Known Issue {known_issue.known_issue_id}."
    )
    event.suggested_action = classification["suggested_action"] or (known_issue.resolution_steps or "").split("\n")[0]

    history = IssueStatusHistory(
        alert_event_id=alert_id,
        old_status=old_status,
        new_status=event.category,
        changed_by=request.changed_by,
        change_reason=None,
    )
    db.add(history)
    db.add(event)
    db.commit()
    db.refresh(event)
    return _event_to_dict(event)
