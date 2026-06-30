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
        .order_by(AlertBatch.received_time.desc())
        .first()
    )

    if not latest_batch:
        return {
            "total_alerts": 0, "new_unknown_count": 0, "known_issues_count": 0,
            "worsening_count": 0, "resolved_count": 0,
            "highest_growth": {"hostname": None, "error_type": None, "growth": 0},
            "last_alert_batch_time": None, "source": None, "environment": None,
        }

    # Count active categories from the latest batch
    rows = (
        db.query(AlertEvent.category, func.count(AlertEvent.id))
        .filter(AlertEvent.batch_id == latest_batch.batch_id)
        .group_by(AlertEvent.category)
        .all()
    )
    cat_counts = {cat: n for cat, n in rows}

    # Resolved alerts can span batches
    resolved_count = (
        db.query(func.count(AlertEvent.id))
        .filter(AlertEvent.category == "resolved")
        .scalar()
    ) or 0

    # Highest-growth alert from the latest batch (excluding resolved)
    highest = (
        db.query(AlertEvent)
        .filter(
            AlertEvent.batch_id == latest_batch.batch_id,
            AlertEvent.category != "resolved",
        )
        .order_by(AlertEvent.growth.desc())
        .first()
    )

    total = (
        db.query(func.count(AlertEvent.id)).scalar()
    ) or 0

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
    }
