import asyncio
import logging
from typing import Optional

from backend.database.db import SessionLocal
from backend.services.config import ENABLE_PROM_WATCHER, PROM_POLL_SECONDS
from backend.services.prom_ingestor import ProcessAlreadyRunningError, process_prom_file

_LOG = logging.getLogger(__name__)

watcher_task: Optional[asyncio.Task] = None


def _run_prom_process() -> None:
    """Runs on a worker thread (see asyncio.to_thread below) — this function
    itself must stay synchronous since SessionLocal()/process_prom_file()
    are both blocking DB/file calls."""
    db = SessionLocal()
    try:
        result = process_prom_file(db)
        if result["status"] == "skipped":
            _LOG.info("watcher: skipped — folder unchanged (hash=%s)", result.get("file_hash", "")[:12])
        else:
            _LOG.info(
                "watcher: processed — files=%d metrics=%d new_events=%d resolved=%d batch=%s",
                result["total_files"], result["total_metrics"],
                result["created_alert_events"], result["resolved_alert_events"], result["batch_id"],
            )
    except ProcessAlreadyRunningError:
        # A manual "Process Now" click is already running — expected/benign,
        # not a failure. Next poll will pick up whatever it leaves behind.
        _LOG.info("watcher: skipped this cycle — a manual process run is already in progress")
    except FileNotFoundError as exc:
        _LOG.warning("watcher: prom path not found: %s", exc)
    except Exception as exc:
        _LOG.error("watcher: ingest failed: %s", exc, exc_info=True)
    finally:
        db.close()


async def _watcher_loop() -> None:
    while True:
        await asyncio.sleep(PROM_POLL_SECONDS)
        # Blocking file/DB work must not run on the event loop thread.
        await asyncio.to_thread(_run_prom_process)


async def start_prom_watcher() -> None:
    global watcher_task
    if not ENABLE_PROM_WATCHER:
        return
    if watcher_task is None or watcher_task.done():
        # Run once immediately so the dashboard has data right after startup
        # instead of waiting a full PROM_POLL_SECONDS for the first ingest.
        await asyncio.to_thread(_run_prom_process)
        watcher_task = asyncio.create_task(_watcher_loop())


async def stop_prom_watcher() -> None:
    global watcher_task
    if watcher_task and not watcher_task.done():
        watcher_task.cancel()
        try:
            await watcher_task
        except asyncio.CancelledError:
            pass
        watcher_task = None
