from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.database.db import get_db
from backend.database.models import PromSnapshot, PromSnapshotFile
from backend.services.config import ENABLE_PROM_WATCHER, PROM_FILE_PATH, PROM_POLL_SECONDS
from backend.services.prom_ingestor import process_prom_file
from backend.services.prom_inventory import (
    list_configured_files,
    resolve_source_files,
    source_mode,
)

router = APIRouter()


def _latest_snapshot(db: Session) -> Optional[PromSnapshot]:
    return (
        db.query(PromSnapshot)
        .order_by(PromSnapshot.processed_at.desc())
        .first()
    )


def _snapshot_files_dict(db: Session, snapshot_id: str) -> list:
    files = (
        db.query(PromSnapshotFile)
        .filter(PromSnapshotFile.snapshot_id == snapshot_id)
        .order_by(PromSnapshotFile.filename)
        .all()
    )
    return [
        {
            "filename": f.filename,
            "file_path": f.file_path,
            "file_hash": f.file_hash,
            "modified_time": f.file_modified_time,
            "size_bytes": f.size_bytes,
            "metric_count": f.metric_count,
            "generated_time": f.generated_time,
            "state_file": f.state_file,
        }
        for f in files
    ]


@router.get("/prom/status")
def get_prom_status(db: Session = Depends(get_db)):
    root_path = PROM_FILE_PATH
    mode = source_mode(root_path)
    source_files = resolve_source_files(root_path) if mode != "missing" else []
    latest = _latest_snapshot(db)

    files_payload: list = []
    latest_error: Optional[str] = None
    if latest:
        files_payload = _snapshot_files_dict(db, latest.snapshot_id)
        latest_error = latest.error_message or None

    return {
        "configured_path": str(root_path),
        "configured_path_type": mode,
        "file_exists": root_path.is_file(),
        "folder_exists": root_path.is_dir(),
        "total_prom_files": len(source_files),
        "total_prom_metrics_latest": latest.total_metrics if latest else 0,
        "latest_snapshot_id": latest.snapshot_id if latest else None,
        "latest_batch_id": latest.batch_id if latest else None,
        "latest_file_hash": latest.file_hash if latest else None,
        "latest_processed_at": latest.processed_at if latest else None,
        "watcher_enabled": ENABLE_PROM_WATCHER,
        "poll_seconds": PROM_POLL_SECONDS,
        "recent_error_message": latest_error,
        "files": files_payload,
    }


@router.get("/prom/files")
def get_prom_files():
    root_path = PROM_FILE_PATH
    mode = source_mode(root_path)
    if mode == "missing":
        raise HTTPException(status_code=404, detail=f"Configured .prom path not found: {root_path}")
    return {
        "configured_path": str(root_path),
        "source_mode": mode,
        "files": list_configured_files(),
    }


@router.post("/prom/process")
def post_prom_process(db: Session = Depends(get_db)):
    try:
        return process_prom_file(db)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


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
            "source_mode": s.source_mode,
            "total_files": s.total_files,
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
        "source_mode": latest.source_mode,
        "total_files": latest.total_files,
        "file_hash": latest.file_hash,
        "processed_at": latest.processed_at,
        "total_lines": latest.total_lines,
        "total_metrics": latest.total_metrics,
        "status": latest.status,
        "error_message": latest.error_message,
        "files": _snapshot_files_dict(db, latest.snapshot_id),
    }
