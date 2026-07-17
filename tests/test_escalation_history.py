"""
Critical requirement: signal_type must never affect whether a row is stored,
matched across snapshots, or eligible for escalation/resolution detection.
"""

import pytest

from backend.database.models import AlertEvent
from backend.services import prom_ingestor

PROM_HEADER = (
    "# HELP scanfor_errors Total errors matching scanfor patterns\n"
    "# TYPE scanfor_errors gauge\n"
    "# Generated: {gen_time}\n"
    "# State file: /tmp/state.dat\n"
)


def _prom_content(gen_time, color=None, count=None, known_error="false"):
    header = PROM_HEADER.format(gen_time=gen_time)
    if color is None:
        return header  # no data lines — the metric has disappeared
    line = (
        'scanfor_errors{system_type="IotGW",system="cars",hostname="cars-cars1-plmon-scanfor",'
        'tenant="cars",filename="commandlistener-main.20260701",error_type="SQLException",'
        'error_index="1",color="%s",known_error="%s",note="",caused_by=""} %d\n'
    ) % (color, known_error, count)
    return header + line


@pytest.fixture(autouse=True)
def _no_stability_wait(monkeypatch):
    monkeypatch.setattr(prom_ingestor, "_wait_until_stable", lambda paths, timeout_seconds=10: True)


def test_noise_row_escalating_to_actionable_is_recognized_as_the_same_alert(tmp_path, db_session, monkeypatch):
    prom_path = tmp_path / "host1.prom"
    monkeypatch.setattr(prom_ingestor, "PROM_FILE_PATH", prom_path)

    prom_path.write_text(_prom_content("2026-07-01 08:00:00", "black", 2))
    result1 = prom_ingestor.process_prom_file(db_session)
    event1 = db_session.query(AlertEvent).filter(AlertEvent.snapshot_id == result1["snapshot_id"]).one()
    assert event1.signal_type == "noise"
    assert event1.count == 2

    prom_path.write_text(_prom_content("2026-07-01 08:10:00", "red", 12))
    result2 = prom_ingestor.process_prom_file(db_session)
    event2 = db_session.query(AlertEvent).filter(AlertEvent.snapshot_id == result2["snapshot_id"]).one()

    # It's the same tracked alert — not a brand-new one just because it was
    # previously noise.
    assert event2.fingerprint_exact == event1.fingerprint_exact
    assert event2.first_seen == event1.first_seen
    assert event2.previous_count == 2
    assert event2.growth == 10

    # And it correctly escalated in classification.
    assert event2.signal_type == "actionable"

    # It must NOT have been recorded as resolved — it's still present.
    resolved = db_session.query(AlertEvent).filter(AlertEvent.category == "resolved").all()
    assert resolved == []


def test_actionable_row_becoming_non_actionable_still_tracks_history_and_can_resolve(tmp_path, db_session, monkeypatch):
    prom_path = tmp_path / "host1.prom"
    monkeypatch.setattr(prom_ingestor, "PROM_FILE_PATH", prom_path)

    prom_path.write_text(_prom_content("2026-07-01 08:00:00", "red", 20))
    result1 = prom_ingestor.process_prom_file(db_session)
    event1 = db_session.query(AlertEvent).filter(AlertEvent.snapshot_id == result1["snapshot_id"]).one()
    assert event1.signal_type == "actionable"

    # Same alert, now non-actionable (black), same count.
    prom_path.write_text(_prom_content("2026-07-01 08:10:00", "black", 20))
    result2 = prom_ingestor.process_prom_file(db_session)
    event2 = db_session.query(AlertEvent).filter(AlertEvent.snapshot_id == result2["snapshot_id"]).one()

    assert event2.fingerprint_exact == event1.fingerprint_exact
    assert event2.first_seen == event1.first_seen
    assert event2.signal_type == "noise"
    assert event2.growth == 0

    # Now it disappears from the source entirely. The source file is still
    # present and fresh (a healthy, complete scan) — but a single healthy
    # absence isn't enough to call it resolved: the resolution grace period
    # (request Section 4, "prevent false resolutions") requires it to stay
    # absent across SCANFOR_RESOLUTION_GRACE_MIN_SNAPSHOTS qualifying scans
    # and SCANFOR_RESOLUTION_GRACE_MIN_SECONDS of elapsed source time first.
    prom_path.write_text(_prom_content("2026-07-01 08:20:00"))  # no data lines
    result3 = prom_ingestor.process_prom_file(db_session)
    pending = (
        db_session.query(AlertEvent)
        .filter(
            AlertEvent.snapshot_id == result3["snapshot_id"],
            AlertEvent.fingerprint_exact == event1.fingerprint_exact,
        )
        .one()
    )
    assert pending.category != "resolved"
    assert pending.data_quality_status == "pending_resolution"
    assert pending.signal_type == "noise"  # still carries its last known classification forward
    assert pending.count == 20  # last known count, not reset

    # A second qualifying absence, with the grace window's elapsed-time
    # requirement now satisfied (20 minutes after the first absence) — it
    # actually resolves, carrying its last known classification forward.
    prom_path.write_text(_prom_content("2026-07-01 08:40:00"))  # no data lines
    result4 = prom_ingestor.process_prom_file(db_session)
    resolved = (
        db_session.query(AlertEvent)
        .filter(AlertEvent.snapshot_id == result4["snapshot_id"], AlertEvent.category == "resolved")
        .one()
    )
    assert resolved.fingerprint_exact == event1.fingerprint_exact
    assert resolved.signal_type == "noise"  # reflects its last known (black) state, not deleted or hidden


def test_suppressed_alert_is_still_matched_across_snapshots(tmp_path, db_session, monkeypatch):
    prom_path = tmp_path / "host1.prom"
    monkeypatch.setattr(prom_ingestor, "PROM_FILE_PATH", prom_path)

    prom_path.write_text(_prom_content("2026-07-01 08:00:00", "red", 5, known_error="true"))
    result1 = prom_ingestor.process_prom_file(db_session)
    event1 = db_session.query(AlertEvent).filter(AlertEvent.snapshot_id == result1["snapshot_id"]).one()
    assert event1.signal_type == "suppressed"

    prom_path.write_text(_prom_content("2026-07-01 08:10:00", "red", 40, known_error="true"))
    result2 = prom_ingestor.process_prom_file(db_session)
    event2 = db_session.query(AlertEvent).filter(AlertEvent.snapshot_id == result2["snapshot_id"]).one()

    # Even though it's suppressed (not shown in the default view), growth is
    # still computed against its own history — the comparison engine doesn't
    # skip it.
    assert event2.fingerprint_exact == event1.fingerprint_exact
    assert event2.previous_count == 5
    assert event2.growth == 35
