"""
database/init_db.py
─────────────────────────────────────────────────────────────────────────────
Creates database tables and seeds sample data.

Usage (from project root):
    python3 -m backend.database.init_db            # create + seed
    python3 -m backend.database.init_db --reset    # drop all tables, recreate, re-seed
"""

import sys
from backend.database.db import engine, SessionLocal, DB_PATH
from backend.database.models import Base
from backend.database.seed_data import seed


def init(reset: bool = False) -> None:
    print(f"Database: {DB_PATH}")

    if reset:
        print("Dropping all tables...")
        Base.metadata.drop_all(bind=engine)
        print("  ✓ Tables dropped")

    print("Creating tables...")
    Base.metadata.create_all(bind=engine)
    print("  ✓ Tables created")

    print("Seeding data...")
    db = SessionLocal()
    try:
        seed(db)
    finally:
        db.close()

    print(f"\nDatabase ready at: {DB_PATH}")


if __name__ == "__main__":
    reset_flag = "--reset" in sys.argv
    init(reset=reset_flag)
