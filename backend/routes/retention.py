from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.database.db import get_db
from backend.services.config import EXPORT_DIR, RETENTION_DAYS
from backend.services.retention import run_retention

router = APIRouter()


@router.get("/retention/status")
def get_retention_config():
    return {
        "retention_days": RETENTION_DAYS,
        "export_dir": str(EXPORT_DIR),
    }


@router.post("/retention/run")
def post_retention_run(db: Session = Depends(get_db)):
    return run_retention(db, retention_days=RETENTION_DAYS, export_dir=EXPORT_DIR)
