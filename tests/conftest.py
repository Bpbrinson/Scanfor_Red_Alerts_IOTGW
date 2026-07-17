"""
tests/conftest.py
─────────────────────────────────────────────────────────────────────────────
Points the app at an isolated, throwaway SQLite file BEFORE any backend module
is imported (env vars are read at import time throughout this codebase), then
gives every test a clean schema via an autouse fixture.
"""

import os
import tempfile
from pathlib import Path

import pytest

_TEST_DIR = Path(tempfile.mkdtemp(prefix="scanfor_test_"))
os.environ["SCANFOR_DB_PATH"] = str(_TEST_DIR / "test.db")
os.environ.setdefault("SCANFOR_PROM_FILE_PATH", str(_TEST_DIR / "prom_unused"))
os.environ.setdefault("SCANFOR_ENABLE_PROM_WATCHER", "false")

from backend.database.db import SessionLocal, engine, run_migrations  # noqa: E402
from backend.database import models  # noqa: E402,F401 — register models with Base


@pytest.fixture(autouse=True)
def _fresh_db():
    """Every test starts from a clean, fully up-to-date schema, built the
    same way production does: through the real Alembic chain. Using
    Base.metadata.create_all() here instead would create tables (e.g.
    alert_series) directly from the ORM models, bypassing Alembic entirely —
    then the next run_migrations() call (e.g. triggered by a TestClient
    hitting the app's startup event) finds no alembic_version table, treats
    the db as an unstamped legacy database, and tries to create those same
    tables again."""
    with engine.connect() as conn:
        conn = conn.execution_options(isolation_level="AUTOCOMMIT")
        tables = [
            row[0]
            for row in conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'")
        ]
        for table in tables:
            conn.exec_driver_sql(f'DROP TABLE IF EXISTS "{table}"')
    run_migrations()
    yield


@pytest.fixture
def db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
