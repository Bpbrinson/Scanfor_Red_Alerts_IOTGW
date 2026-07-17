from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

from backend.database.db import get_db
from backend.database.models import AlertBatch, AlertEvent

router = APIRouter()


@router.get("/summary")
def get_summary(db: Session = Depends(get_db)):
    # Latest batch drives the active-alert counts
    latest_batch = (
        db.query(AlertBatch)
        .order_by(AlertBatch.id.desc())
        .first()
    )

    if not latest_batch:
        return {
            "total_alerts": 0, "new_unknown_count": 0, "known_issues_count": 0,
            "worsening_count": 0, "resolved_count": 0,
            "highest_growth": {"hostname": None, "error_type": None, "growth": 0},
            "last_alert_batch_time": None, "source": None, "environment": None,
            "signal_counts": {"actionable": 0, "noise": 0, "suppressed": 0, "total": 0},
        }

    # Count active categories from the latest batch — actionable alerts only, so
    # these primary tiles represent alerts that need attention, not dashboard noise.
    rows = (
        db.query(AlertEvent.category, func.count(AlertEvent.id))
        .filter(AlertEvent.batch_id == latest_batch.batch_id, AlertEvent.signal_type == "actionable")
        .group_by(AlertEvent.category)
        .all()
    )
    cat_counts = {cat: n for cat, n in rows}

    # Resolved alerts can span batches (unaffected by signal_type — scope unchanged)
    resolved_count = (
        db.query(func.count(AlertEvent.id))
        .filter(AlertEvent.category == "resolved")
        .scalar()
    ) or 0

    # Highest-growth actionable alert from the latest batch (excluding resolved)
    highest = (
        db.query(AlertEvent)
        .filter(
            AlertEvent.batch_id == latest_batch.batch_id,
            AlertEvent.category != "resolved",
            AlertEvent.signal_type == "actionable",
        )
        .order_by(AlertEvent.growth.desc())
        .first()
    )

    total = (
        db.query(func.count(AlertEvent.id))
        .filter(AlertEvent.signal_type == "actionable")
        .scalar()
    ) or 0

    # Signal-type breakdown, scoped to the latest batch (the same scope as cat_counts
    # above) so noise/suppressed counts reflect what's currently active, not all history.
    signal_rows = (
        db.query(AlertEvent.signal_type, func.count(AlertEvent.id))
        .filter(AlertEvent.batch_id == latest_batch.batch_id)
        .group_by(AlertEvent.signal_type)
        .all()
    )
    signal_counts = {"actionable": 0, "noise": 0, "suppressed": 0}
    for signal_type, count in signal_rows:
        signal_counts[signal_type] = count
    signal_counts["total"] = sum(signal_counts.values())

    return {
        "total_alerts": total,
        "new_unknown_count": cat_counts.get("new", 0),
        "known_issues_count": cat_counts.get("known", 0),
        "worsening_count": cat_counts.get("worsening", 0),
        "resolved_count": resolved_count,
        "highest_growth": {
            "hostname": highest.hostname if highest else None,
            "error_type": highest.error_type if highest else None,
            "growth": highest.growth if highest else 0,
        },
        "last_alert_batch_time": latest_batch.received_time_display,
        "source": latest_batch.source,
        "environment": latest_batch.environment,
        "signal_counts": signal_counts,
    }
