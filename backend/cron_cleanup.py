"""
backend/cron_cleanup.py
─────────────────────────────────────────────────────────────────────────────
Standalone retention/offload job, designed to run from an OS cron job ONCE A
DAY — not every 10 minutes like cron_ingest.py.

Exports alert_events (and their notes/status history) older than
SCANFOR_RETENTION_DAYS to CSV, then deletes them, along with any
alert_batches / prom_snapshots left with zero remaining alert_events. Rows
tied to an open ticket or an active (non-archived) known issue are always
kept regardless of age. The single most recent successful snapshot is never
touched, since backend/services/prom_ingestor.py depends on it for the next
growth comparison.

Usage (project root):
    python3 -m backend.cron_cleanup

Environment variables:
    SCANFOR_RETENTION_DAYS   Age cutoff in days (default: 90)
    SCANFOR_EXPORT_DIR       Where CSV exports land before deletion
                             (default: an "exports" folder next to the DB file)

Cron entry (daily at 03:00):
    0 3 * * * cd /path/to/Scanfor_Red_Email_Alerts_Dashboard && \\
        python3 -m backend.cron_cleanup >> /var/log/scanfor_cleanup.log 2>&1
"""

import logging
import sys

from backend.database.db import SessionLocal, engine, run_migrations
from backend.services.config import EXPORT_DIR, RETENTION_DAYS
from backend.services.retention import run_retention

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
_LOG = logging.getLogger(__name__)


def main() -> int:
    # Idempotent — brings the DB to the latest Alembic revision.
    run_migrations()

    db = SessionLocal()
    try:
        result = run_retention(db, retention_days=RETENTION_DAYS, export_dir=EXPORT_DIR)
    except Exception as exc:
        _LOG.error("retention run failed: %s", exc, exc_info=True)
        return 1
    finally:
        db.close()

    if result["status"] == "no-op":
        _LOG.info("no-op — nothing older than %d days (cutoff=%s)", RETENTION_DAYS, result["cutoff"])
        return 0

    _LOG.info(
        "completed — events=%d notes=%d history=%d batches=%d snapshots=%d snapshot_files=%d exported_to=%s",
        result["deleted_alert_events"],
        result["deleted_alert_notes"],
        result["deleted_status_history"],
        result["deleted_batches"],
        result["deleted_snapshots"],
        result["deleted_snapshot_files"],
        result["export_dir"],
    )

    # SQLite can't VACUUM inside an open transaction, so this runs on its own
    # connection after the retention session above has already committed and closed.
    with engine.connect() as conn:
        conn = conn.execution_options(isolation_level="AUTOCOMMIT")
        conn.exec_driver_sql("VACUUM")
    _LOG.info("VACUUM complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
