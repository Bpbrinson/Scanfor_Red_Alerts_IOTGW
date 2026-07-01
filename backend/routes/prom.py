from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.database.db import get_db
from backend.database.models import PromSnapshot
from backend.services.config import PROM_FILE_PATH, PROM_POLL_SECONDS, ENABLE_PROM_WATCHER
from backend.services.prom_ingestor import process_prom_file

router = APIRouter()


def _latest_snapshot(db: Session) -> Optional[PromSnapshot]:
    return (
        db.query(PromSnapshot)
        .order_by(PromSnapshot.processed_at.desc())
        .first()
    )


@router.get("/prom/status")
def get_prom_status(db: Session = Depends(get_db)):
    latest = _latest_snapshot(db)
    return {
        "configured_file_path": str(PROM_FILE_PATH),
        "file_exists": PROM_FILE_PATH.exists(),
        "latest_snapshot_id": latest.snapshot_id if latest else None,
        "latest_batch_id": latest.batch_id if latest else None,
        "latest_file_hash": latest.file_hash if latest else None,
        "latest_processed_at": latest.processed_at if latest else None,
        "latest_total_metrics": latest.total_metrics if latest else 0,
        "watcher_enabled": ENABLE_PROM_WATCHER,
        "poll_seconds": PROM_POLL_SECONDS,
    }


@router.post("/prom/process")
def post_prom_process(db: Session = Depends(get_db)):
    try:
        result = process_prom_file(db)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return result


@router.get("/prom/snapshots")
def get_prom_snapshots(limit: int = Query(20, gt=0), db: Session = Depends(get_db)):
    snapshots = (
        db.query(PromSnapshot)
        .order_by(PromSnapshot.processed_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "snapshot_id": s.snapshot_id,
            "batch_id": s.batch_id,
            "file_path": s.file_path,
            "file_hash": s.file_hash,
            "processed_at": s.processed_at,
            "total_lines": s.total_lines,
            "total_metrics": s.total_metrics,
            "status": s.status,
            "error_message": s.error_message,
        }
        for s in snapshots
    ]


@router.get("/prom/snapshots/latest")
def get_prom_snapshot_latest(db: Session = Depends(get_db)):
    latest = _latest_snapshot(db)
    if not latest:
        raise HTTPException(status_code=404, detail="No prom snapshots found")
    return {
        "snapshot_id": latest.snapshot_id,
        "batch_id": latest.batch_id,
        "file_path": latest.file_path,
        "file_hash": latest.file_hash,
        "processed_at": latest.processed_at,
        "total_lines": latest.total_lines,
        "total_metrics": latest.total_metrics,
        "status": latest.status,
        "error_message": latest.error_message,
    }
