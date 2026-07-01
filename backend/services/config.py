from os import environ
from pathlib import Path


def _get_bool(name: str, default: bool) -> bool:
    value = environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "y", "on")


PROM_FILE_PATH = Path(environ.get("SCANFOR_PROM_FILE_PATH", "/prom")).expanduser()
PROM_POLL_SECONDS = int(environ.get("SCANFOR_PROM_POLL_SECONDS", "60") or 60)
ENABLE_PROM_WATCHER = _get_bool("SCANFOR_ENABLE_PROM_WATCHER", False)
