from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.database.db import DB_PATH, get_db
from backend.database.models import AlertEvent

router = APIRouter()


@router.get("/health")
def health(db: Session = Depends(get_db)):
    alert_events_row_count = db.query(func.count(AlertEvent.id)).scalar() or 0
    db_size_bytes = DB_PATH.stat().st_size if DB_PATH.exists() else 0
    return {
        "status": "ok",
        "service": "scanfor-red-api",
        "db_path": str(DB_PATH),
        "db_size_bytes": db_size_bytes,
        "alert_events_row_count": alert_events_row_count,
    }
