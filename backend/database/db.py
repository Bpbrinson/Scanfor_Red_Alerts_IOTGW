"""
database/db.py
─────────────────────────────────────────────────────────────────────────────
SQLite engine + session factory.
All routes that need DB access use the `get_db` FastAPI dependency.
"""

import os
from pathlib import Path
from sqlalchemy import create_engine
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

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency — yields a DB session and ensures it is closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
