"""
Phase 1 (reset-aware identity + per-file timestamps + AlertSeries) tests.
See backend/services/counter_math.py and backend/services/prom_ingestor.py.
"""

import threading

import pytest

from backend.database.models import AlertEvent, AlertSeries, KnownIssue
from backend.database.schemas import AlertNoteCreate, AlertTicketUpdate, MarkKnownRequest
from backend.routes.alerts import add_alert_note, mark_alert_known, update_alert_ticket
from backend.services import prom_ingestor
from backend.services.counter_math import compute_counter_delta

PROM_HEADER = (
    "# HELP scanfor_errors Total errors matching scanfor patterns\n"
    "# TYPE scanfor_errors gauge\n"
    "# Generated: {gen_time}\n"
    "# State file: {state_file}\n"
)


def _line(hostname, raw_filename, count, error_type="SQLException", error_index="1",
          tenant="cars", system="cars", color="red", known_error="false", caused_by=""):
    return (
        'scanfor_errors{system_type="IotGW",system="%s",hostname="%s",'
        'tenant="%s",filename="%s",error_type="%s",'
        'error_index="%s",color="%s",known_error="%s",note="",caused_by="%s"} %d\n'
    ) % (system, hostname, tenant, raw_filename, error_type, error_index, color, known_error, caused_by, count)


def _content(gen_time, lines, state_file="/tmp/state.dat"):
    return PROM_HEADER.format(gen_time=gen_time, state_file=state_file) + "".join(lines)


@pytest.fixture(autouse=True)
def _no_stability_wait(monkeypatch):
    monkeypatch.setattr(prom_ingestor, "_wait_until_stable", lambda paths, timeout_seconds=10: True)


def _latest_event_for_host(db_session, snapshot_id, hostname):
    return (
        db_session.query(AlertEvent)
        .filter(AlertEvent.snapshot_id == snapshot_id, AlertEvent.hostname == hostname)
        .one()
    )


# ─── Pure counter math (backend/services/counter_math.py) ───────────────────

def test_counter_math_midnight_reset_acceptance_case():
    """The spec's own acceptance case: 120 (...20260716) -> 5 (...20260717)."""
    result = compute_counter_delta(
        current_count=5,
        previous_count=120,
        current_epoch="20260717",
        previous_epoch="20260716",
        current_raw_filename="aerislistener-main.20260717",
        previous_raw_filename="aerislistener-main.20260716",
        current_state_file="/tmp/state.dat",
        previous_state_file="/tmp/state.dat",
    )
    assert result.raw_signed_delta == -115
    assert result.interval_delta == 5
    assert result.counter_reset_detected is True
    assert result.data_quality_status == "ok"


def test_counter_math_unexpected_decrease_without_reset_signal_is_flagged_not_negative():
    result = compute_counter_delta(
        current_count=30,
        previous_count=50,
        current_epoch="20260716",
        previous_epoch="20260716",
        current_raw_filename="aerislistener-main.20260716",
        previous_raw_filename="aerislistener-main.20260716",
        current_state_file="/tmp/state.dat",
        previous_state_file="/tmp/state.dat",
    )
    assert result.raw_signed_delta == -20
    assert result.interval_delta == 0  # never negative, never read as improvement
    assert result.counter_reset_detected is False
    assert result.data_quality_status == "unexpected_decrease"


# ─── End-to-end ingestion ────────────────────────────────────────────────────

def test_stable_identity_and_reset_math_across_a_filename_rollover(tmp_path, db_session, monkeypatch):
    prom_path = tmp_path / "host1.prom"
    monkeypatch.setattr(prom_ingestor, "PROM_FILE_PATH", prom_path)

    prom_path.write_text(_content("2026-07-16 08:00:00", [
        _line("aerislistener-vm-01", "aerislistener-main.20260716", 120),
    ]))
    result1 = prom_ingestor.process_prom_file(db_session)
    event1 = _latest_event_for_host(db_session, result1["snapshot_id"], "aerislistener-vm-01")
    assert event1.count == 120
    assert event1.series_id is not None

    # Midnight rollover: new dated filename, counter restarts near zero.
    prom_path.write_text(_content("2026-07-17 08:00:00", [
        _line("aerislistener-vm-01", "aerislistener-main.20260717", 5),
    ]))
    result2 = prom_ingestor.process_prom_file(db_session)
    event2 = _latest_event_for_host(db_session, result2["snapshot_id"], "aerislistener-vm-01")

    # Same stable identity — not treated as a brand-new alert.
    assert event2.fingerprint_exact == event1.fingerprint_exact
    assert event2.series_id == event1.series_id

    # Reset-aware counter math, matching the spec's acceptance case exactly.
    assert event2.raw_signed_delta == -115
    assert event2.interval_delta == 5
    assert event2.counter_reset_detected is True
    assert event2.counter_epoch == "20260717"

    # Exactly one AlertSeries backs both observations.
    series_count = db_session.query(AlertSeries).filter(AlertSeries.alert_key == event1.fingerprint_exact).count()
    assert series_count == 1


def test_unexpected_decrease_with_no_reset_signal_flags_data_quality(tmp_path, db_session, monkeypatch):
    prom_path = tmp_path / "host1.prom"
    monkeypatch.setattr(prom_ingestor, "PROM_FILE_PATH", prom_path)

    prom_path.write_text(_content("2026-07-16 08:00:00", [
        _line("host-a", "aerislistener-main.20260716", 50),
    ]))
    prom_ingestor.process_prom_file(db_session)

    # Same day, same file, same state file — count just went down. Not a
    # rollover; must be flagged, never read as -20 worth of improvement.
    prom_path.write_text(_content("2026-07-16 09:00:00", [
        _line("host-a", "aerislistener-main.20260716", 30),
    ]))
    result2 = prom_ingestor.process_prom_file(db_session)
    event2 = _latest_event_for_host(db_session, result2["snapshot_id"], "host-a")

    assert event2.raw_signed_delta == -20
    assert event2.interval_delta == 0
    assert event2.counter_reset_detected is False
    assert event2.data_quality_status == "unexpected_decrease"


def test_irregular_interval_rate_per_hour(tmp_path, db_session, monkeypatch):
    prom_path = tmp_path / "host1.prom"
    monkeypatch.setattr(prom_ingestor, "PROM_FILE_PATH", prom_path)

    prom_path.write_text(_content("2026-07-16 08:00:00", [
        _line("host-a", "aerislistener-main.20260716", 10),
    ]))
    prom_ingestor.process_prom_file(db_session)

    # 90 minutes later, same epoch — a normal (non-reset) update.
    prom_path.write_text(_content("2026-07-16 09:30:00", [
        _line("host-a", "aerislistener-main.20260716", 25),
    ]))
    result2 = prom_ingestor.process_prom_file(db_session)
    event2 = _latest_event_for_host(db_session, result2["snapshot_id"], "host-a")

    assert event2.interval_delta == 15
    assert event2.interval_seconds == pytest.approx(5400.0)
    assert event2.rate_per_hour == pytest.approx(10.0)


def test_per_file_observed_at_not_a_shared_folder_wide_timestamp(tmp_path, db_session, monkeypatch):
    monkeypatch.setattr(prom_ingestor, "PROM_FILE_PATH", tmp_path)

    (tmp_path / "filea.prom").write_text(_content("2026-07-16 08:00:00", [
        _line("host-a", "aerislistener-main.20260716", 10),
    ]))
    (tmp_path / "fileb.prom").write_text(_content("2026-07-16 08:20:00", [
        _line("host-b", "aerislistener-main.20260716", 20),
    ]))

    result = prom_ingestor.process_prom_file(db_session)
    event_a = _latest_event_for_host(db_session, result["snapshot_id"], "host-a")
    event_b = _latest_event_for_host(db_session, result["snapshot_id"], "host-b")

    assert event_a.observed_at.isoformat(sep=" ") == "2026-07-16 08:00:00"
    assert event_b.observed_at.isoformat(sep=" ") == "2026-07-16 08:20:00"
    assert event_a.observed_at != event_b.observed_at


def test_prom_bak_files_are_still_ignored(tmp_path, db_session, monkeypatch):
    monkeypatch.setattr(prom_ingestor, "PROM_FILE_PATH", tmp_path)

    (tmp_path / "real.prom").write_text(_content("2026-07-16 08:00:00", [
        _line("host-a", "aerislistener-main.20260716", 10),
    ]))
    # A stale backup copy sitting in the same folder — must not be read.
    (tmp_path / "real.prom.bak").write_text(_content("2026-07-15 08:00:00", [
        _line("host-a", "aerislistener-main.20260715", 999),
    ]))

    result = prom_ingestor.process_prom_file(db_session)
    assert result["total_files"] == 1
    assert result["total_metrics"] == 1


def test_multi_vm_grouping_does_not_merge_exact_hosts(tmp_path, db_session, monkeypatch):
    prom_path = tmp_path / "host1.prom"
    monkeypatch.setattr(prom_ingestor, "PROM_FILE_PATH", prom_path)

    prom_path.write_text(_content("2026-07-16 08:00:00", [
        _line("mxqrpiog01", "aerislistener-main.20260716", 10),
        _line("mxqrpiog02", "aerislistener-main.20260716", 10),
    ]))
    result = prom_ingestor.process_prom_file(db_session)
    event1 = _latest_event_for_host(db_session, result["snapshot_id"], "mxqrpiog01")
    event2 = _latest_event_for_host(db_session, result["snapshot_id"], "mxqrpiog02")

    # Same everything except the exact hostname — exact identity (and the
    # series/backfill it drives) must not merge them into one alert_key.
    assert event1.fingerprint_exact != event2.fingerprint_exact
    assert event1.series_id != event2.series_id


def test_known_issue_owner_ticket_and_notes_survive_a_rollover_via_series(tmp_path, db_session, monkeypatch):
    prom_path = tmp_path / "host1.prom"
    monkeypatch.setattr(prom_ingestor, "PROM_FILE_PATH", prom_path)

    prom_path.write_text(_content("2026-07-16 08:00:00", [
        _line("host-a", "aerislistener-main.20260716", 10),
    ]))
    result1 = prom_ingestor.process_prom_file(db_session)
    event1 = _latest_event_for_host(db_session, result1["snapshot_id"], "host-a")

    known_issue = KnownIssue(known_issue_id="KI-900", status="active", owner="alice", normal_count_max=1000)
    db_session.add(known_issue)
    db_session.commit()

    mark_alert_known(event1.alert_id, MarkKnownRequest(known_issue_id="KI-900"), db_session)
    add_alert_note(event1.alert_id, AlertNoteCreate(note="watching this", created_by="bob"), db_session)
    update_alert_ticket(event1.alert_id, AlertTicketUpdate(ticket_link="JIRA-99"), db_session)

    # Rollover to a new day's log file — a brand-new AlertEvent row.
    prom_path.write_text(_content("2026-07-17 08:00:00", [
        _line("host-a", "aerislistener-main.20260717", 3),
    ]))
    result2 = prom_ingestor.process_prom_file(db_session)
    event2 = _latest_event_for_host(db_session, result2["snapshot_id"], "host-a")

    assert event2.known_issue_id == "KI-900"
    assert event2.owner == "alice"
    assert event2.ticket_link == "JIRA-99"
    assert event2.notes == "watching this"


def test_concurrent_processing_is_rejected_not_queued(db_session):
    assert prom_ingestor._process_lock.acquire(blocking=False)
    try:
        with pytest.raises(prom_ingestor.ProcessAlreadyRunningError):
            prom_ingestor.process_prom_file(db_session)
    finally:
        prom_ingestor._process_lock.release()
