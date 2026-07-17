"""
Ingestion tests: every parsed row must be stored regardless of classification,
and signal_type must be computed correctly at write time.
"""

import pytest

from backend.database.models import AlertEvent
from backend.services import prom_ingestor

PROM_HEADER = (
    "# HELP scanfor_errors Total errors matching scanfor patterns\n"
    "# TYPE scanfor_errors gauge\n"
    "# Generated: 2026-07-01 08:00:00\n"
    "# State file: /tmp/state.dat\n"
)


def _line(hostname, error_index, color, count, known_error="false"):
    return (
        'scanfor_errors{system_type="IotGW",system="cars",hostname="%s",'
        'tenant="cars",filename="commandlistener-main.20260701",error_type="SQLException",'
        'error_index="%s",color="%s",known_error="%s",note="",caused_by=""} %d\n'
    ) % (hostname, error_index, color, known_error, count)


@pytest.fixture(autouse=True)
def _no_stability_wait(monkeypatch):
    # _wait_until_stable polls file size for up to 10s; not needed when the
    # test writes the file once and never touches it mid-run.
    monkeypatch.setattr(prom_ingestor, "_wait_until_stable", lambda paths, timeout_seconds=10: True)


def test_all_parsed_rows_are_stored_regardless_of_classification(tmp_path, db_session, monkeypatch):
    content = PROM_HEADER + "".join([
        _line("host-actionable", "1", "red", 50, "false"),
        _line("host-noise", "2", "black", 5, "false"),
        _line("host-suppressed", "3", "red", 30, "true"),
        _line("host-noise-2", "4", "green", 1, "false"),
    ])
    prom_path = tmp_path / "host1.prom"
    prom_path.write_text(content)
    monkeypatch.setattr(prom_ingestor, "PROM_FILE_PATH", prom_path)

    result = prom_ingestor.process_prom_file(db_session)

    assert result["status"] == "processed"
    assert result["total_metrics"] == 4
    assert result["created_alert_events"] == 4

    stored = db_session.query(AlertEvent).filter(AlertEvent.snapshot_id == result["snapshot_id"]).all()
    assert len(stored) == 4  # storage count matches parsed count — nothing filtered out

    by_host = {e.hostname: e for e in stored}
    assert by_host["host-actionable"].signal_type == "actionable"
    assert by_host["host-noise"].signal_type == "noise"
    assert by_host["host-suppressed"].signal_type == "suppressed"
    assert by_host["host-noise-2"].signal_type == "noise"


def test_noise_and_suppressed_rows_keep_full_existing_fields(tmp_path, db_session, monkeypatch):
    content = PROM_HEADER + _line("host-1", "1", "black", 7, "false")
    prom_path = tmp_path / "host1.prom"
    prom_path.write_text(content)
    monkeypatch.setattr(prom_ingestor, "PROM_FILE_PATH", prom_path)

    result = prom_ingestor.process_prom_file(db_session)
    event = db_session.query(AlertEvent).filter(AlertEvent.snapshot_id == result["snapshot_id"]).one()

    # Existing ingestion behavior is unchanged apart from the added field.
    assert event.hostname == "host-1"
    assert event.error_type == "SQLException"
    assert event.count == 7
    assert event.category == "new"  # unaffected by signal_type
    assert event.color == "black"
    assert event.signal_type == "noise"


def test_custom_actionable_colors_and_suppression_disabled(tmp_path, db_session, monkeypatch):
    monkeypatch.setattr(prom_ingestor, "ACTIONABLE_COLORS", {"orange"})
    monkeypatch.setattr(prom_ingestor, "SUPPRESS_KNOWN_ERRORS", False)

    content = PROM_HEADER + "".join([
        _line("host-orange", "1", "orange", 9, "false"),
        _line("host-red-known", "2", "red", 9, "true"),  # known error, but suppression is off
    ])
    prom_path = tmp_path / "host1.prom"
    prom_path.write_text(content)
    monkeypatch.setattr(prom_ingestor, "PROM_FILE_PATH", prom_path)

    result = prom_ingestor.process_prom_file(db_session)
    stored = {
        e.hostname: e
        for e in db_session.query(AlertEvent).filter(AlertEvent.snapshot_id == result["snapshot_id"]).all()
    }

    assert stored["host-orange"].signal_type == "actionable"
    assert stored["host-red-known"].signal_type == "noise"  # red isn't in the custom actionable set
