"""
database/db.py
─────────────────────────────────────────────────────────────────────────────
SQLite engine + session factory.
All routes that need DB access use the `get_db` FastAPI dependency.
"""

import os
from pathlib import Path
from sqlalchemy import create_engine, event, MetaData
from sqlalchemy.orm import sessionmaker, DeclarativeBase

# Database file location — override with SCANFOR_DB_PATH for containers /
# custom deployments. Defaults to the file next to this module.
_default_db = Path(__file__).parent / "scanfor_red.db"
DB_PATH = Path(os.environ.get("SCANFOR_DB_PATH", str(_default_db))).expanduser()
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},  # required for SQLite + FastAPI
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:
    """Production-safe SQLite settings, applied to every new connection:
    - WAL journal mode: readers (dashboard/API/Grafana-style consumers) don't
      block writers (cron ingest/retention) and vice versa, unlike the
      default rollback-journal mode.
    - busy_timeout: a connection that hits a lock waits and retries for up
      to 5s instead of immediately raising "database is locked" — matters
      now that ingestion, the watcher, and API reads can all overlap.
    """
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


# Explicit naming convention so Alembic autogenerate always emits named
# constraints — SQLite's batch mode (table-recreation, used for anything an
# in-place ALTER TABLE can't do) requires every constraint to have a name.
_NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=_NAMING_CONVENTION)


def get_db():
    """FastAPI dependency — yields a DB session and ensures it is closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def run_migrations() -> None:
    """Bring the database up to the latest Alembic revision (backend/migrations/).

    Replaces the project's old Base.metadata.create_all() + ensure_*() ad-hoc
    ALTER TABLE startup functions entirely — all schema changes from here on
    go through a real migration.

    Legacy databases created before Alembic existed already have every table
    the baseline migration would CREATE; running the baseline's CREATE TABLE
    statements against them would fail. Detected here (app tables exist but
    no alembic_version table yet) and stamped to the baseline revision
    instead of executing it — a fresh/empty database just runs the baseline
    normally, which creates everything. Idempotent either way; safe to call
    on every startup.
    """
    from alembic import command
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from sqlalchemy import inspect

    project_root = Path(__file__).resolve().parent.parent.parent
    cfg = Config(str(project_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(project_root / "backend" / "migrations"))

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    has_alembic_version = "alembic_version" in existing_tables
    has_legacy_tables = "alert_batches" in existing_tables

    if not has_alembic_version and has_legacy_tables:
        script = ScriptDirectory.from_config(cfg)
        for base_revision in script.get_bases():
            command.stamp(cfg, base_revision)

    command.upgrade(cfg, "head")
