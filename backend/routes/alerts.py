from typing import Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from backend.database.db import get_db
from backend.database.models import (
    AlertBatch,
    AlertEvent,
    AlertSeries,
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
from backend.services.trends import get_affected_vm_counts_for_batch, get_trends_for_alert_keys

router = APIRouter()

_VALID_SIGNAL_TYPES = {"actionable", "noise", "suppressed"}
_VALID_INCLUDE_TOKENS = _VALID_SIGNAL_TYPES | {"all"}


def _parse_include(include: Optional[str]) -> Optional[List[str]]:
    """Parse the `include` query param into a list of signal_types to return.

    Defaults to actionable-only when not provided. Returns None to mean "all
    signal_types, no filter". Raises HTTPException(400) for unrecognized
    tokens so callers get a clear error instead of a silently empty result.
    """
    if not include or not include.strip():
        return ["actionable"]

    tokens = [tok.strip().lower() for tok in include.split(",") if tok.strip()]
    if not tokens:
        return ["actionable"]

    invalid = sorted(set(tok for tok in tokens if tok not in _VALID_INCLUDE_TOKENS))
    if invalid:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid include value(s): {', '.join(invalid)}. "
                "Valid values are: actionable, noise, suppressed, all."
            ),
        )

    if "all" in tokens:
        return None
    return tokens


def _event_to_dict(event: AlertEvent) -> dict:
    return {
        "alert_id": event.alert_id,
        "batch_id": event.batch_id,
        "status": event.status,
        "category": event.category,
        "signal_type": event.signal_type,
        "color": event.color,
        "raw_known_error": event.raw_known_error,
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
        # Trend-analysis identity/base fields (see backend/services/trends.py).
        # alert_key reuses the existing fingerprint_exact — the stable identity
        # already used to correlate this alert across processing runs.
        "alert_key": event.fingerprint_exact,
        "current_value": event.count,
        "previous_value": event.previous_count,
        "is_red": bool(event.is_red),
        # Data-quality (backend/services/prom_ingestor.py — Section 4 "prevent
        # false resolutions"): ok | unexpected_decrease | source_missing |
        # source_stale | source_parse_failure | pending_resolution.
        "data_quality_status": event.data_quality_status,
    }


def _enrich_with_trends(db: Session, events: List[AlertEvent], event_dicts: List[dict]) -> List[dict]:
    """Adds multi-window trend fields to each event dict in one batch pass —
    never one query per row. A single alert's trend calculation failing is
    logged and simply omitted for that alert (defaults below), never raised
    further; existing fields are always preserved either way."""
    alert_keys = [event.fingerprint_exact for event in events if event.fingerprint_exact]

    # Anchor "now" to the most recent actual observation in this result set,
    # not wall-clock time — otherwise a paused/stale deployment (or a bare
    # gap in ingestion) would make the lookback window exclude everything,
    # even though the data itself is perfectly usable relative to itself.
    observed_times = [event.processed_at for event in events if event.processed_at]
    now = max(observed_times) if observed_times else None

    # affected_vm_count is computed per (tenant, system, error_type, log_file)
    # signature for the batches actually represented in this result set — a
    # small, fixed number of extra queries (one per distinct batch_id), not
    # one per alert row. Computed *before* trend calculation (Phase 4) so it
    # can also feed the Change Score's multi_vm_spread component, not just
    # the display-only affected_vm_count field.
    vm_counts_by_batch: Dict[str, Dict[Tuple[Optional[str], Optional[str], Optional[str], Optional[str]], int]] = {}
    for event in events:
        if event.batch_id not in vm_counts_by_batch:
            vm_counts_by_batch[event.batch_id] = get_affected_vm_counts_for_batch(db, event.batch_id)

    affected_vm_count_by_event_id: Dict[int, int] = {}
    affected_vm_counts_by_key: Dict[str, int] = {}
    for event in events:
        vm_key = (event.tenant, event.system, event.error_type, event.log_file)
        count = vm_counts_by_batch.get(event.batch_id, {}).get(vm_key, 1 if event.is_red else 0)
        affected_vm_count_by_event_id[event.id] = count
        if event.fingerprint_exact:
            affected_vm_counts_by_key[event.fingerprint_exact] = count

    trends_by_key = get_trends_for_alert_keys(db, alert_keys, now=now, affected_vm_counts=affected_vm_counts_by_key)

    _DEFAULT_TREND_FIELDS = {
        "absolute_change": None, "percentage_change": None, "growth_rate_per_hour": None,
        "change_30m": None, "percentage_change_30m": None,
        "change_15m": None, "percentage_change_15m": None,
        "change_1h": None, "percentage_change_1h": None,
        "change_6h": None, "percentage_change_6h": None,
        "change_24h": None, "percentage_change_24h": None,
        "slope_1h": None, "slope_6h": None, "acceleration": None,
        "baseline_rate_per_hour": None, "baseline_mad": None,
        "threshold_excess_percentage": None,
        "red_started_at": None, "red_duration_seconds": None, "consecutive_red_snapshots": 0,
        "red_state_transition_count": 0, "is_flapping": False,
        "trend_state": "insufficient_history",
        "change_score": None,
        "change_score_confidence": None,
        "change_score_components": {
            "short_term_vs_baseline": None, "sustained_1h_vs_baseline": None, "acceleration": None,
            "persistence": None, "multi_vm_spread": None,
        },
    }

    for event, event_dict in zip(events, event_dicts):
        trend = trends_by_key.get(event.fingerprint_exact)
        event_dict.update(trend.to_dict() if trend is not None else dict(_DEFAULT_TREND_FIELDS))
        event_dict["affected_vm_count"] = affected_vm_count_by_event_id[event.id]

    return event_dicts


def _get_or_create_series(db: Session, event: AlertEvent) -> AlertSeries:
    """The permanent identity this event belongs to (backend/database/models.py
    ::AlertSeries) — operational edits (ticket, notes, owner, known-issue
    link) are written here so they survive every future ingestion run for
    the same alert_key, not just the current batch's row. Falls back to a
    lookup-or-create by fingerprint_exact for any event that somehow lacks
    a series link (shouldn't happen once the backfill migration has run)."""
    if event.series_id:
        series = db.query(AlertSeries).filter(AlertSeries.id == event.series_id).first()
        if series is not None:
            return series

    series = db.query(AlertSeries).filter(AlertSeries.alert_key == event.fingerprint_exact).first()
    if series is None:
        series = AlertSeries(
            alert_key=event.fingerprint_exact,
            tenant=event.tenant,
            system=event.system,
            hostname=event.hostname,
            log_scope=event.log_file,
            error_type=event.error_type,
            error_index=event.error_index,
            caused_by=event.caused_by,
            lifecycle_status="active",
        )
        db.add(series)
        db.flush()
    event.series_id = series.id
    return series


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
    include: Optional[str] = None,
    db: Session = Depends(get_db),
):
    latest_batch_id = _latest_batch_id(db)
    if not latest_batch_id:
        return []

    signal_types = _parse_include(include)

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

    if signal_types is not None:
        query = query.filter(AlertEvent.signal_type.in_(signal_types))

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
    event_dicts = [_event_to_dict(event) for event in events]
    return _enrich_with_trends(db, events, event_dicts)


@router.patch("/alerts/{alert_id}/ticket")
def update_alert_ticket(
    alert_id: str,
    update: AlertTicketUpdate,
    db: Session = Depends(get_db),
):
    event = db.query(AlertEvent).filter_by(alert_id=alert_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Alert not found")

    series = _get_or_create_series(db, event)
    series.ticket_link = update.ticket_link or None
    event.ticket_link = series.ticket_link
    db.add(series)
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

    series = _get_or_create_series(db, event)
    note = AlertNote(
        alert_event_id=alert_id,
        note=note_request.note,
        created_by=note_request.created_by,
    )
    series.notes = note_request.note or ""
    event.notes = series.notes
    db.add(note)
    db.add(series)
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

    series = _get_or_create_series(db, event)
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
        # Clear the series' link too — otherwise the next ingestion run would
        # re-apply it via _apply_series_overrides() and undo this unmark.
        series.known_issue_id = None
        series.owner = None
        db.add(series)

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

    series = _get_or_create_series(db, event)

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
    event.ticket_link = event.ticket_link or known_issue.ticket_link
    event.severity = classification["severity"] or known_issue.severity
    event.classification_reason = (
        classification["classification_reason"]
        if classification["category"] != "new"
        else f"Manually linked to Known Issue {known_issue.known_issue_id}."
    )
    event.suggested_action = classification["suggested_action"] or (known_issue.resolution_steps or "").split("\n")[0]

    # Persist the link on the series too, so it survives the next ingestion
    # run even if automatic wildcard/fingerprint matching wouldn't have
    # re-found this Known Issue on its own — see
    # backend/services/prom_ingestor.py::_apply_series_overrides.
    series.known_issue_id = known_issue.known_issue_id
    if known_issue.owner:
        series.owner = known_issue.owner
    if not series.ticket_link and known_issue.ticket_link:
        series.ticket_link = known_issue.ticket_link

    history = IssueStatusHistory(
        alert_event_id=alert_id,
        old_status=old_status,
        new_status=event.category,
        changed_by=request.changed_by,
        change_reason=None,
    )
    db.add(series)
    db.add(history)
    db.add(event)
    db.commit()
    db.refresh(event)
    return _event_to_dict(event)
