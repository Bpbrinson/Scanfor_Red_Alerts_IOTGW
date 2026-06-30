from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func

from backend.database.db import get_db
from backend.database.models import AlertBatch, AlertEvent

router = APIRouter()


def _batch_to_dict(batch: AlertBatch, total_issues: int) -> dict:
    return {
        "batch_id": batch.batch_id,
        "source": batch.source,
        "received_time": batch.received_time,
        "received_time_display": batch.received_time_display,
        "environment": batch.environment,
        "email_subject": batch.email_subject,
        "sender": batch.sender,
        "processed_at": batch.processed_at,
        "total_issues_detected": total_issues,
    }


@router.get("/alert-batches/latest")
def get_latest_batch(db: Session = Depends(get_db)):
    batch = (
        db.query(AlertBatch)
        .order_by(AlertBatch.received_time.desc())
        .first()
    )
    if not batch:
        raise HTTPException(status_code=404, detail="No alert batches found")

    total = (
        db.query(func.count(AlertEvent.id))
        .filter(AlertEvent.batch_id == batch.batch_id)
        .scalar()
    )
    return _batch_to_dict(batch, total or 0)
