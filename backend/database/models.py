"""
database/models.py
─────────────────────────────────────────────────────────────────────────────
SQLAlchemy ORM models for all five tables.
"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
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

    id = Column(Integer, primary_key=True, index=True)
    alert_id = Column(String, unique=True, index=True, nullable=False)
    batch_id = Column(String, ForeignKey("alert_batches.batch_id"), nullable=False)
    status = Column(String, default="new")
    category = Column(String, default="new")  # new | known | worsening | resolved
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
    classification_reason = Column(Text)
    suggested_action = Column(Text, nullable=True)
    known_issue_id = Column(String, nullable=True)
    owner = Column(String, nullable=True)
    runbook_link = Column(String, nullable=True)
    ticket_link = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    normal_range = Column(String, nullable=True)
    escalation_rule = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    batch = relationship("AlertBatch", back_populates="events")
    alert_notes = relationship("AlertNote", back_populates="event", cascade="all, delete-orphan")
    status_history = relationship("IssueStatusHistory", back_populates="event", cascade="all, delete-orphan")


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
    alert_event_id = Column(String, ForeignKey("alert_events.alert_id"), nullable=False)
    note = Column(Text, nullable=False)
    created_by = Column(String, default="user")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    event = relationship("AlertEvent", back_populates="alert_notes")


class IssueStatusHistory(Base):
    __tablename__ = "issue_status_history"

    id = Column(Integer, primary_key=True, index=True)
    alert_event_id = Column(String, ForeignKey("alert_events.alert_id"), nullable=False)
    old_status = Column(String)
    new_status = Column(String)
    changed_by = Column(String, default="user")
    change_reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    event = relationship("AlertEvent", back_populates="status_history")
