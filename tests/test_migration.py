"""
Migration tests for run_migrations() (backend/database/db.py), which drives
the real Alembic migration chain in backend/migrations/versions/. A "legacy"
database here means one that already has the pre-Alembic schema (signal_type,
trend columns, etc. — all from earlier work, captured in the baseline
migration) but predates Alembic itself: no alembic_version table, no
alert_series table, none of the reset-aware counter columns or Phase 2
data-quality columns added by later migrations.
"""

import sqlite3
from datetime import datetime

from backend.database.db import DB_PATH, run_migrations

_LEGACY_ROWS = [
    # alert_id, batch_id, fingerprint_exact, status, category, hostname, color,
    # raw_known_error, count, growth, known_issue_id, owner, ticket_link, notes, first_seen, last_seen
    ("a1", "b1", "KEY-A", "new", "new", "h1", "red", "false", 10, 5, None, None, None, None, "2026-01-01T00:00:00", "2026-01-02T00:00:00"),
    ("a2", "b1", "KEY-A", "new", "new", "h1", "red", "false", 30, 20, None, None, None, None, "2026-01-01T00:00:00", "2026-01-03T00:00:00"),
    ("a3", "b1", "KEY-B", "known", "known", "h2", "black", "false", 3, 1, "KI-001", "alice", "JIRA-1", "watching this", "2026-01-05T00:00:00", "2026-01-05T00:00:00"),
]


def _create_legacy_database():
    """Build a pre-Alembic database: the modern (pre-Phase-1) alert_events
    shape, populated, with no alembic_version table — simulating a database
    that already went through the project's earlier ad-hoc migrations (the
    old ensure_indexes()/ensure_signal_type_column()/ensure_trend_columns()
    startup functions, which ran on every boot before Alembic existed) but
    has never run an Alembic migration. That means it already has every
    column the baseline migration would create (signal_type, processed_at,
    is_red, red_threshold, updated_at, ...) — just not alert_series or any
    of the Phase-1 reset-aware columns."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("DROP TABLE IF EXISTS alembic_version")
    conn.execute("DROP TABLE IF EXISTS alert_events")
    conn.execute("DROP TABLE IF EXISTS alert_series")
    conn.execute("DROP TABLE IF EXISTS known_issues")
    conn.execute("DROP TABLE IF EXISTS alert_batches")
    conn.execute("DROP TABLE IF EXISTS prom_snapshot_files")
    conn.execute("DROP TABLE IF EXISTS prom_snapshots")
    conn.execute(
        """
        CREATE TABLE alert_batches (
            id INTEGER PRIMARY KEY,
            batch_id TEXT UNIQUE NOT NULL,
            source TEXT,
            environment TEXT,
            email_subject TEXT,
            sender TEXT,
            received_time TEXT,
            received_time_display TEXT,
            total_issues_detected INTEGER,
            processed_at TEXT,
            created_at DATETIME,
            updated_at DATETIME
        )
        """
    )
    conn.execute("INSERT INTO alert_batches (batch_id) VALUES ('b1')")
    conn.execute(
        """
        CREATE TABLE known_issues (
            id INTEGER PRIMARY KEY,
            known_issue_id TEXT UNIQUE NOT NULL,
            fingerprint TEXT,
            error_type TEXT,
            host_scope TEXT,
            log_scope TEXT,
            severity TEXT,
            owner TEXT,
            status TEXT,
            normal_count_min INTEGER,
            normal_count_max INTEGER,
            normal_growth_min INTEGER,
            normal_growth_max INTEGER,
            cause TEXT,
            impact TEXT,
            resolution_steps TEXT,
            runbook_link TEXT,
            ticket_link TEXT,
            last_reviewed TEXT,
            created_at DATETIME,
            updated_at DATETIME
        )
        """
    )
    conn.execute("INSERT INTO known_issues (known_issue_id, normal_count_max) VALUES ('KI-001', 5)")
    conn.execute(
        """
        CREATE TABLE alert_events (
            id INTEGER PRIMARY KEY,
            alert_id TEXT UNIQUE NOT NULL,
            batch_id TEXT NOT NULL,
            status TEXT,
            category TEXT,
            signal_type TEXT(20) NOT NULL DEFAULT 'actionable',
            hostname TEXT,
            raw_filename TEXT,
            log_file TEXT,
            error_type TEXT,
            count INTEGER,
            growth INTEGER,
            severity TEXT,
            first_seen TEXT,
            last_seen TEXT,
            fingerprint TEXT,
            fingerprint_exact TEXT,
            fingerprint_general TEXT,
            classification_reason TEXT,
            suggested_action TEXT,
            known_issue_id TEXT,
            owner TEXT,
            runbook_link TEXT,
            ticket_link TEXT,
            notes TEXT,
            normal_range TEXT,
            escalation_rule TEXT,
            system_type TEXT,
            system TEXT,
            tenant TEXT,
            error_index TEXT,
            color TEXT,
            raw_known_error TEXT,
            raw_note TEXT,
            caused_by TEXT,
            previous_count INTEGER,
            snapshot_id TEXT,
            processed_at DATETIME,
            is_red BOOLEAN,
            red_threshold REAL,
            created_at DATETIME,
            updated_at DATETIME
        )
        """
    )
    created_at = datetime(2026, 1, 1, 0, 0, 0).isoformat(sep=" ")
    conn.executemany(
        "INSERT INTO alert_events "
        "(alert_id, batch_id, fingerprint_exact, status, category, hostname, color, raw_known_error, "
        " count, growth, known_issue_id, owner, ticket_link, notes, first_seen, last_seen, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [row + (created_at,) for row in _LEGACY_ROWS],
    )

    # Also pre-Phase-2 shape: no quality_status/completeness_status/etc. —
    # those are new in the data_quality_and_resolution_grace migration, never
    # part of any pre-Alembic ad-hoc function.
    conn.execute(
        """
        CREATE TABLE prom_snapshots (
            id INTEGER PRIMARY KEY,
            snapshot_id TEXT UNIQUE NOT NULL,
            batch_id TEXT NOT NULL,
            file_path TEXT,
            source_mode TEXT,
            total_files INTEGER,
            file_hash TEXT,
            file_modified_time TEXT,
            processed_at TEXT,
            total_lines INTEGER,
            total_metrics INTEGER,
            status TEXT,
            error_message TEXT,
            created_at DATETIME,
            updated_at DATETIME
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE prom_snapshot_files (
            id INTEGER PRIMARY KEY,
            snapshot_id TEXT NOT NULL,
            filename TEXT NOT NULL,
            file_path TEXT,
            file_hash TEXT,
            file_modified_time TEXT,
            size_bytes INTEGER,
            metric_count INTEGER,
            generated_time TEXT,
            state_file TEXT,
            created_at DATETIME
        )
        """
    )

    conn.commit()
    conn.close()


def test_run_migrations_stamps_legacy_db_and_upgrades_without_data_loss():
    _create_legacy_database()

    run_migrations()

    conn = sqlite3.connect(str(DB_PATH))
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "alembic_version" in tables
    assert "alert_series" in tables

    # No rows lost.
    assert conn.execute("SELECT COUNT(*) FROM alert_events").fetchone()[0] == len(_LEGACY_ROWS)

    # New columns exist.
    columns = {row[1] for row in conn.execute("PRAGMA table_info(alert_events)")}
    assert {"observed_at", "series_id", "interval_delta", "counter_reset_detected", "data_quality_status"} <= columns

    conn.close()


def test_run_migrations_backfills_one_series_per_alert_key():
    _create_legacy_database()
    run_migrations()

    conn = sqlite3.connect(str(DB_PATH))
    # KEY-A has two rows (a1, a2); KEY-B has one (a3) -> 2 distinct series.
    series_count = conn.execute("SELECT COUNT(*) FROM alert_series").fetchone()[0]
    assert series_count == 2

    # Every event points at a series.
    null_series = conn.execute("SELECT COUNT(*) FROM alert_events WHERE series_id IS NULL").fetchone()[0]
    assert null_series == 0

    # The series for KEY-B carries forward its most-recent row's operational fields.
    owner, ticket_link, notes, known_issue_id = conn.execute(
        "SELECT owner, ticket_link, notes, known_issue_id FROM alert_series WHERE alert_key = 'KEY-B'"
    ).fetchone()
    assert (owner, ticket_link, notes, known_issue_id) == ("alice", "JIRA-1", "watching this", "KI-001")

    # KEY-A's series spans both its rows' first_seen/last_seen. Compared as
    # parsed datetimes (not raw strings) since SQLite round-trips a DATETIME
    # column with an explicit ".000000" microsecond suffix.
    first_seen, last_seen = conn.execute(
        "SELECT first_seen, last_seen FROM alert_series WHERE alert_key = 'KEY-A'"
    ).fetchone()
    assert datetime.fromisoformat(first_seen) == datetime(2026, 1, 1, 0, 0, 0)
    assert datetime.fromisoformat(last_seen) == datetime(2026, 1, 3, 0, 0, 0)

    conn.close()


def test_run_migrations_is_idempotent():
    _create_legacy_database()
    run_migrations()

    conn = sqlite3.connect(str(DB_PATH))
    series_after_first = conn.execute("SELECT COUNT(*) FROM alert_series").fetchone()[0]
    conn.close()

    run_migrations()  # must not error or duplicate the backfill

    conn = sqlite3.connect(str(DB_PATH))
    series_after_second = conn.execute("SELECT COUNT(*) FROM alert_series").fetchone()[0]
    assert series_after_second == series_after_first
    conn.close()


def test_run_migrations_bootstraps_a_completely_fresh_database():
    """A brand-new deployment (no tables at all) must come up cleanly through
    run_migrations() alone — no separate Base.metadata.create_all() step."""
    conn = sqlite3.connect(str(DB_PATH))
    tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    for table in tables:
        conn.execute(f"DROP TABLE IF EXISTS {table}")
    conn.commit()
    conn.close()

    run_migrations()

    conn = sqlite3.connect(str(DB_PATH))
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"alert_batches", "alert_events", "alert_series", "known_issues", "alembic_version"} <= tables
    conn.close()
