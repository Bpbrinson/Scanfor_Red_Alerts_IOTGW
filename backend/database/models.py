"""
database/models.py
─────────────────────────────────────────────────────────────────────────────
SQLAlchemy ORM models for all five tables.
"""

from datetime import datetime
from sqlalchemy import Boolean, Column, Float, Index, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship

from backend.database.db import Base


class AlertBatch(Base):
    __tablename__ = "alert_batches"

    id = Column(Integer, primary_key=True, index=True)
    batch_id = Column(String, unique=True, index=True, nullable=False)
    source = Column(String)
    environment = Column(String)
    email_subject = Column(String)
    sender = Column(String)
    received_time = Column(String)           # ISO-8601 string
    received_time_display = Column(String)   # Human-readable display value
    total_issues_detected = Column(Integer, default=0)
    processed_at = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    events = relationship("AlertEvent", back_populates="batch")


class AlertEvent(Base):
    __tablename__ = "alert_events"
    __table_args__ = (
        # Trend engine's core query (current, processed_at-based): history for
        # one alert_key ordered by ingestion time. Was created via raw SQL in
        # an earlier ad-hoc migration (backend/database/db.py::ensure_indexes)
        # and is declared here so Alembic autogenerate sees it instead of
        # trying to drop it.
        Index("ix_alert_events_fpexact_processed_at", "fingerprint_exact", "processed_at"),
        # Same query, keyed on observed_at (source-generated time) instead —
        # the field trend calculations are moving to, since processed_at is
        # wall-clock ingestion time and can't be trusted for rate math across
        # irregular scan intervals.
        Index("ix_alert_events_fpexact_observed_at", "fingerprint_exact", "observed_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    alert_id = Column(String, unique=True, index=True, nullable=False)
    batch_id = Column(String, ForeignKey("alert_batches.batch_id"), nullable=False, index=True)
    status = Column(String, default="new")
    category = Column(String, default="new")  # new | known | worsening | resolved
    signal_type = Column(String(20), nullable=False, default="noise", index=True)  # actionable | noise | suppressed
    hostname = Column(String)
    raw_filename = Column(String)
    log_file = Column(String)
    error_type = Column(String)
    count = Column(Integer)
    growth = Column(Integer)
    severity = Column(String, nullable=True)
    first_seen = Column(String)
    last_seen = Column(String)
    fingerprint = Column(String)
    fingerprint_exact = Column(String, nullable=True, index=True)  # alert identity across processing runs
    fingerprint_general = Column(String, nullable=True)
    classification_reason = Column(Text)
    suggested_action = Column(Text, nullable=True)
    known_issue_id = Column(String, nullable=True)
    owner = Column(String, nullable=True)
    runbook_link = Column(String, nullable=True)
    ticket_link = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    normal_range = Column(String, nullable=True)
    escalation_rule = Column(String, nullable=True)
    system_type = Column(String, nullable=True)
    system = Column(String, nullable=True)
    tenant = Column(String, nullable=True)
    error_index = Column(String, nullable=True)
    color = Column(String, nullable=True)
    raw_known_error = Column(String, nullable=True)
    raw_note = Column(String, nullable=True)
    caused_by = Column(String, nullable=True)
    previous_count = Column(Integer, default=0)
    snapshot_id = Column(String, nullable=True, index=True)

    # Trend-analysis fields (multi-window growth, slope, persistence — see
    # backend/services/trends.py). processed_at is the real wall-clock moment
    # of this observation, used for actual-elapsed-time calculations instead
    # of assuming a fixed interval between runs. is_red/red_threshold are
    # snapshot-time-captured so historical trend math isn't affected by a
    # Known Issue's threshold changing later.
    # Not independently indexed — every current query filters by processed_at
    # combined with fingerprint_exact (the composite index above covers it);
    # a standalone index here would just be unused write overhead.
    processed_at = Column(DateTime, nullable=True)
    is_red = Column(Boolean, nullable=True)
    red_threshold = Column(Float, nullable=True)

    # ─── Per-file source metadata + reset-aware counter fields ─────────────
    # observed_at is when the SOURCE .prom file said its metrics were
    # generated (parsed from that file's own "# Generated:" line) — this is
    # what trend/rate calculations must use, since files in the same folder
    # can have several minutes of skew and processed_at is only ever the
    # wall-clock moment this app happened to read them. ingested_at is that
    # wall-clock moment, kept as a distinctly-named field alongside the
    # existing processed_at (unchanged, for backward compatibility) rather
    # than renaming it.
    observed_at = Column(DateTime, nullable=True)
    ingested_at = Column(DateTime, nullable=True)
    source_filename = Column(String, nullable=True)        # the .prom file on disk, e.g. "cars-cars1-plmon-scanfor.prom"
    source_generated_time = Column(String, nullable=True)  # raw "# Generated:" string from that file
    source_state_file = Column(String, nullable=True)      # raw "# State file:" string from that file
    source_file_hash = Column(String, nullable=True)       # sha256 of that specific file's bytes (not folder-wide)

    # count/growth above are the raw cumulative counter and its raw signed
    # delta (kept for backward compatibility/audit — growth CAN be negative
    # across a daily counter rollover). The fields below are the reset-aware
    # equivalents ingestion also computes so trend math never mistakes a
    # rollover for an improvement — see backend/services/counter_math.py.
    raw_signed_delta = Column(Integer, nullable=True)     # == growth; named explicitly for clarity where both are read together
    interval_delta = Column(Integer, nullable=True)        # reset-aware, always >= 0
    interval_seconds = Column(Float, nullable=True)        # elapsed time (observed_at basis) since the previous observation
    rate_per_hour = Column(Float, nullable=True)
    counter_reset_detected = Column(Boolean, nullable=True, default=False)
    counter_epoch = Column(String, nullable=True)          # date suffix from the raw dated log filename, e.g. "20260717"
    data_quality_status = Column(String, nullable=True, default="ok")  # ok | unexpected_decrease (more added in a later phase)

    series_id = Column(Integer, ForeignKey("alert_series.id"), nullable=True, index=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    batch = relationship("AlertBatch", back_populates="events")
    alert_notes = relationship("AlertNote", back_populates="event", cascade="all, delete-orphan")
    status_history = relationship("IssueStatusHistory", back_populates="event", cascade="all, delete-orphan")
    series = relationship("AlertSeries", back_populates="events")


class AlertSeries(Base):
    """
    Permanent, mutable identity for one stable alert_key (== fingerprint_exact
    — tenant | system | exact hostname | normalized log scope | error_type |
    error_index | caused_by). AlertEvent stays an immutable, append-only
    observation from a single processing run; every operational field an
    engineer can edit (known-issue link, owner, ticket, notes, manual
    severity/suppression) lives here instead, so it survives every future
    snapshot of the same alert_key regardless of daily log-filename rollover.
    """
    __tablename__ = "alert_series"

    id = Column(Integer, primary_key=True, index=True)
    alert_key = Column(String, unique=True, nullable=False, index=True)

    tenant = Column(String, nullable=True)
    system = Column(String, nullable=True)
    hostname = Column(String, nullable=True)
    log_scope = Column(String, nullable=True)
    error_type = Column(String, nullable=True)
    error_index = Column(String, nullable=True)
    caused_by = Column(String, nullable=True)

    first_seen = Column(DateTime, nullable=True)
    last_seen = Column(DateTime, nullable=True)
    lifecycle_status = Column(String, nullable=False, default="active")  # active | resolved | archived

    known_issue_id = Column(String, nullable=True)
    owner = Column(String, nullable=True)
    ticket_link = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    severity_override = Column(String, nullable=True)
    suppression_override = Column(Boolean, nullable=True)  # None = no override, True/False = forced

    # Resolution grace-period tracking (backend/services/prom_ingestor.py) —
    # null/0 whenever the alert is actively observed or hasn't started a
    # qualifying (source-healthy) absence yet. Set on the first qualifying
    # absence, cleared the moment the alert reappears or once it actually
    # resolves.
    pending_resolution_since = Column(DateTime, nullable=True)
    absence_count = Column(Integer, nullable=False, default=0)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    events = relationship("AlertEvent", back_populates="series")


class KnownIssue(Base):
    __tablename__ = "known_issues"

    id = Column(Integer, primary_key=True, index=True)
    known_issue_id = Column(String, unique=True, index=True, nullable=False)
    fingerprint = Column(String)
    error_type = Column(String)
    host_scope = Column(String)
    log_scope = Column(String)
    severity = Column(String)
    owner = Column(String)
    status = Column(String, default="active")  # active | monitoring | archived
    normal_count_min = Column(Integer, default=0)
    normal_count_max = Column(Integer, default=100)
    normal_growth_min = Column(Integer, default=0)
    normal_growth_max = Column(Integer, default=50)
    cause = Column(Text, default="")
    impact = Column(Text, default="")
    resolution_steps = Column(Text, default="")
    runbook_link = Column(String, nullable=True)
    ticket_link = Column(String, nullable=True)
    last_reviewed = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AlertNote(Base):
    __tablename__ = "alert_notes"

    id = Column(Integer, primary_key=True, index=True)
    alert_event_id = Column(String, ForeignKey("alert_events.alert_id"), nullable=False, index=True)
    note = Column(Text, nullable=False)
    created_by = Column(String, default="user")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    event = relationship("AlertEvent", back_populates="alert_notes")


class PromSnapshot(Base):
    __tablename__ = "prom_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    snapshot_id = Column(String, unique=True, index=True, nullable=False)
    batch_id = Column(String, ForeignKey("alert_batches.batch_id"), nullable=False)
    file_path = Column(String)
    source_mode = Column(String, default="file")
    total_files = Column(Integer, default=1)
    file_hash = Column(String)
    file_modified_time = Column(String)
    processed_at = Column(String)
    total_lines = Column(Integer, default=0)
    total_metrics = Column(Integer, default=0)
    status = Column(String)
    error_message = Column(Text, nullable=True)

    # Data-quality (Section 4: "prevent false resolutions") — worst-wins
    # summary of this run's source-file coverage. "Expected files" are
    # derived from the previous processed snapshot's own file list, not a
    # separately-stored table — see prom_ingestor.py::_compute_source_health.
    completeness_status = Column(String, nullable=True)  # complete | partial | missing_source
    missing_files = Column(Text, nullable=True)  # JSON-encoded list of filenames expected but absent this run
    newly_discovered_files = Column(Text, nullable=True)  # JSON-encoded list of filenames not seen in the previous run

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    batch = relationship("AlertBatch")
    files = relationship("PromSnapshotFile", back_populates="snapshot", cascade="all, delete-orphan")


class PromSnapshotFile(Base):
    __tablename__ = "prom_snapshot_files"

    id = Column(Integer, primary_key=True, index=True)
    snapshot_id = Column(String, ForeignKey("prom_snapshots.snapshot_id"), nullable=False, index=True)
    filename = Column(String, nullable=False)
    file_path = Column(String)
    file_hash = Column(String)
    file_modified_time = Column(String)
    size_bytes = Column(Integer, default=0)
    metric_count = Column(Integer, default=0)
    generated_time = Column(String, nullable=True)
    state_file = Column(String, nullable=True)

    # Data-quality (backend/services/prom_inventory.py::compute_file_quality_status).
    quality_status = Column(String, nullable=True)  # ok | parse_warning | stale | parse_failure
    invalid_row_count = Column(Integer, nullable=False, default=0)
    duplicate_row_count = Column(Integer, nullable=False, default=0)
    parse_warnings = Column(Text, nullable=True)  # newline-joined detail strings

    created_at = Column(DateTime, default=datetime.utcnow)

    snapshot = relationship("PromSnapshot", back_populates="files")


class IssueStatusHistory(Base):
    __tablename__ = "issue_status_history"

    id = Column(Integer, primary_key=True, index=True)
    alert_event_id = Column(String, ForeignKey("alert_events.alert_id"), nullable=False, index=True)
    old_status = Column(String)
    new_status = Column(String)
    changed_by = Column(String, default="user")
    change_reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    event = relationship("AlertEvent", back_populates="status_history")
