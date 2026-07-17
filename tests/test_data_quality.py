"""
Phase 2 (prevent false resolutions + source/parse data quality) tests. See
backend/services/prom_parser.py (structured parsing/validation) and
backend/services/prom_ingestor.py (resolution gating, source health).
"""

import pytest

from backend.database.models import AlertEvent, PromSnapshotFile
from backend.services import prom_ingestor

PROM_HEADER = (
    "# HELP scanfor_errors Total errors matching scanfor patterns\n"
    "# TYPE scanfor_errors gauge\n"
    "# Generated: {gen_time}\n"
    "# State file: /tmp/state_{host}.dat\n"
)


def _line(hostname, count, error_index="1", color="red", caused_by=""):
    return (
        'scanfor_errors{system_type="IotGW",system="cars",hostname="%s",'
        'tenant="cars",filename="aerislistener-main.20260716",error_type="SQLException",'
        'error_index="%s",color="%s",known_error="false",note="",caused_by="%s"} %d\n'
    ) % (hostname, error_index, color, caused_by, count)


def _content(host, gen_time, lines):
    return PROM_HEADER.format(gen_time=gen_time, host=host) + "".join(lines)


@pytest.fixture(autouse=True)
def _no_stability_wait(monkeypatch):
    monkeypatch.setattr(prom_ingestor, "_wait_until_stable", lambda paths, timeout_seconds=10: True)


def _latest_event(db_session, snapshot_id, hostname):
    return (
        db_session.query(AlertEvent)
        .filter(AlertEvent.snapshot_id == snapshot_id, AlertEvent.hostname == hostname)
        .one()
    )


def test_missing_source_file_does_not_falsely_resolve_and_marks_snapshot_partial(tmp_path, db_session, monkeypatch):
    monkeypatch.setattr(prom_ingestor, "PROM_FILE_PATH", tmp_path)
    file_a = tmp_path / "hostA.prom"
    file_b = tmp_path / "hostB.prom"

    file_a.write_text(_content("hostA", "2026-07-16 08:00:00", [_line("host-a", 10)]))
    file_b.write_text(_content("hostB", "2026-07-16 08:00:00", [_line("host-b", 5)]))
    result1 = prom_ingestor.process_prom_file(db_session)
    event_b1 = _latest_event(db_session, result1["snapshot_id"], "host-b")
    assert event_b1.category != "resolved"

    # hostB.prom vanishes from the folder entirely (e.g. transient scan
    # failure) — hostA.prom is still there and freshly generated.
    file_b.unlink()
    file_a.write_text(_content("hostA", "2026-07-16 08:10:00", [_line("host-a", 12)]))
    result2 = prom_ingestor.process_prom_file(db_session)

    assert result2["completeness_status"] == "partial"
    assert result2["missing_files"] == ["hostB.prom"]

    # host-a processed completely normally.
    event_a2 = _latest_event(db_session, result2["snapshot_id"], "host-a")
    assert event_a2.count == 12
    assert event_a2.category != "resolved"

    # host-b must NOT be falsely resolved — its source simply isn't there to
    # confirm the absence against.
    event_b2 = _latest_event(db_session, result2["snapshot_id"], "host-b")
    assert event_b2.category != "resolved"
    assert event_b2.data_quality_status == "source_missing"
    assert event_b2.count == 5  # last known count carried forward, not reset


def test_stale_source_file_does_not_falsely_resolve(tmp_path, db_session, monkeypatch):
    monkeypatch.setattr(prom_ingestor, "PROM_FILE_PATH", tmp_path)
    file_a = tmp_path / "hostA.prom"
    file_b = tmp_path / "hostB.prom"

    file_a.write_text(_content("hostA", "2026-07-16 08:00:00", [_line("host-a", 10)]))
    file_b.write_text(_content("hostB", "2026-07-16 08:00:00", [_line("host-b", 5)]))
    prom_ingestor.process_prom_file(db_session)

    # hostA.prom keeps getting refreshed; hostB.prom is still present on disk
    # but the upstream system stopped regenerating it — 35 minutes stale
    # relative to this run's reference time, past the default 30-minute
    # SCANFOR_SOURCE_STALE_SECONDS tolerance.
    file_a.write_text(_content("hostA", "2026-07-16 08:35:00", [_line("host-a", 14)]))
    result2 = prom_ingestor.process_prom_file(db_session)

    assert result2["completeness_status"] == "partial"

    file_row = (
        db_session.query(PromSnapshotFile)
        .filter(PromSnapshotFile.snapshot_id == result2["snapshot_id"], PromSnapshotFile.filename == "hostB.prom")
        .one()
    )
    assert file_row.quality_status == "stale"

    event_b2 = _latest_event(db_session, result2["snapshot_id"], "host-b")
    assert event_b2.category != "resolved"
    assert event_b2.data_quality_status == "source_stale"


def test_invalid_row_is_not_stored_and_does_not_resolve_the_previous_alert(tmp_path, db_session, monkeypatch):
    prom_path = tmp_path / "host1.prom"
    monkeypatch.setattr(prom_ingestor, "PROM_FILE_PATH", prom_path)

    prom_path.write_text(_content("host1", "2026-07-16 08:00:00", [_line("host-a", 10)]))
    result1 = prom_ingestor.process_prom_file(db_session)
    event1 = _latest_event(db_session, result1["snapshot_id"], "host-a")
    assert event1.count == 10

    # Same alert's row now arrives with a blank hostname — missing a
    # required-for-identity label, so it's invalid and excluded from
    # valid_rows (see prom_parser.ParseResult), not stored with a blank field.
    malformed_line = _line("", 999)
    prom_path.write_text(_content("host1", "2026-07-16 08:10:00", [malformed_line]))
    result2 = prom_ingestor.process_prom_file(db_session)

    # The malformed row was counted, not silently dropped.
    file_row = (
        db_session.query(PromSnapshotFile)
        .filter(PromSnapshotFile.snapshot_id == result2["snapshot_id"])
        .one()
    )
    assert file_row.invalid_row_count == 1
    assert file_row.quality_status == "parse_warning"

    # No row was stored for the blank hostname.
    assert db_session.query(AlertEvent).filter(AlertEvent.hostname == "").count() == 0

    # And the previous, legitimate host-a alert was not resolved just because
    # one malformed row happened to arrive this run — the file itself is
    # still healthy, so it's pending, not immediately resolved.
    pending = _latest_event(db_session, result2["snapshot_id"], "host-a")
    assert pending.category != "resolved"
    assert pending.data_quality_status == "pending_resolution"


def test_duplicate_metric_identity_within_one_file_is_detected_and_deduplicated(tmp_path, db_session, monkeypatch):
    prom_path = tmp_path / "host1.prom"
    monkeypatch.setattr(prom_ingestor, "PROM_FILE_PATH", prom_path)

    # Two lines, identical identity (same tenant/system/hostname/log_file/
    # error_type/error_index/caused_by), different counts.
    prom_path.write_text(_content("host1", "2026-07-16 08:00:00", [
        _line("host-a", 10),
        _line("host-a", 999),
    ]))
    result = prom_ingestor.process_prom_file(db_session)

    stored = db_session.query(AlertEvent).filter(AlertEvent.snapshot_id == result["snapshot_id"]).all()
    assert len(stored) == 1
    assert stored[0].count == 10  # first occurrence kept, not the duplicate

    file_row = (
        db_session.query(PromSnapshotFile)
        .filter(PromSnapshotFile.snapshot_id == result["snapshot_id"])
        .one()
    )
    assert file_row.duplicate_row_count == 1
    assert file_row.quality_status == "parse_warning"


def test_blank_color_still_stores_as_noise_not_rejected(tmp_path, db_session, monkeypatch):
    """color is deliberately exempt from required-label rejection — a blank
    color is a valid, meaningful noise classification, not a data problem."""
    prom_path = tmp_path / "host1.prom"
    monkeypatch.setattr(prom_ingestor, "PROM_FILE_PATH", prom_path)

    prom_path.write_text(_content("host1", "2026-07-16 08:00:00", [_line("host-a", 10, color="")]))
    result = prom_ingestor.process_prom_file(db_session)

    event = _latest_event(db_session, result["snapshot_id"], "host-a")
    assert event.signal_type == "noise"

    file_row = (
        db_session.query(PromSnapshotFile)
        .filter(PromSnapshotFile.snapshot_id == result["snapshot_id"])
        .one()
    )
    assert file_row.invalid_row_count == 0
    assert file_row.quality_status == "ok"
