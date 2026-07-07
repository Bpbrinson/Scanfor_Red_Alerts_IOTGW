"""
backend/cron_ingest.py
─────────────────────────────────────────────────────────────────────────────
Standalone ingestion script designed to run from an OS cron job.

Reads .prom files from SCANFOR_PROM_FILE_PATH, computes growth vs the
previous snapshot in the DB, classifies each alert, and writes a new
AlertBatch + AlertEvents to the database.  Runs are idempotent: if the
folder hash hasn't changed since the last successful snapshot, the run
exits without writing anything.

Usage (project root):
    python3 -m backend.cron_ingest

Environment variables:
    SCANFOR_PROM_FILE_PATH   Path to the .prom folder
                             Local default: /Users/bpb/Documents/Test_Data
                             Server: /home/plmon/status/scanfor

Cron entry (every 10 minutes):
    */10 * * * * cd /path/to/Scanfor_Red_Email_Alerts_Dashboard && \\
        SCANFOR_PROM_FILE_PATH=/home/plmon/status/scanfor \\
        python3 -m backend.cron_ingest >> /var/log/scanfor_cron.log 2>&1
"""

import logging
import sys

from backend.database.db import Base, SessionLocal, engine
from backend.services.prom_ingestor import process_prom_file

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
_LOG = logging.getLogger(__name__)


def main() -> int:
    # Ensure tables exist (safe to call repeatedly; a no-op if already created)
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        result = process_prom_file(db)
        status = result["status"]
        if status == "skipped":
            _LOG.info("skipped — folder unchanged (hash=%s)", result.get("file_hash", "")[:12])
        else:
            _LOG.info(
                "processed — files=%d metrics=%d new_events=%d resolved=%d batch=%s",
                result["total_files"],
                result["total_metrics"],
                result["created_alert_events"],
                result["resolved_alert_events"],
                result["batch_id"],
            )
        return 0
    except FileNotFoundError as exc:
        _LOG.error("prom path not found: %s", exc)
        return 2
    except Exception as exc:
        _LOG.error("ingest failed: %s", exc, exc_info=True)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
