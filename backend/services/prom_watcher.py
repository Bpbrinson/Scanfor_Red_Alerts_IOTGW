import asyncio
import logging

from backend.database.db import SessionLocal
from backend.services.config import ENABLE_PROM_WATCHER, PROM_POLL_SECONDS
from backend.services.prom_ingestor import process_prom_file

_LOG = logging.getLogger(__name__)

watcher_task: asyncio.Task | None = None


def _run_prom_process() -> None:
    db = SessionLocal()
    try:
        result = process_prom_file(db)
        _LOG.info("Prom watcher processed file: %s", result)
    except Exception as exc:
        _LOG.error("Prom watcher error: %s", exc, exc_info=True)
    finally:
        db.close()


async def _watcher_loop() -> None:
    while True:
        await asyncio.sleep(PROM_POLL_SECONDS)
        _run_prom_process()


async def start_prom_watcher() -> None:
    global watcher_task
    if not ENABLE_PROM_WATCHER:
        return
    if watcher_task is None or watcher_task.done():
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
