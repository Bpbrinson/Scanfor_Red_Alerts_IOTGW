"""API tests for /api/alerts include= filtering and /api/summary signal counts."""

import pytest
from fastapi.testclient import TestClient

from backend.database.models import AlertBatch, AlertEvent
from backend.main import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _make_event(alert_id, signal_type, category="new", **overrides):
    defaults = dict(
        alert_id=alert_id,
        batch_id="BATCH-1",
        status=category,
        category=category,
        signal_type=signal_type,
        hostname="host-1",
        raw_filename="f.log.20260701",
        log_file="f.log",
        error_type="SQLException",
        count=10,
        growth=5,
        first_seen="2026-07-01T00:00:00",
        last_seen="2026-07-01T00:00:00",
        fingerprint="fp",
        fingerprint_exact="fpe-" + alert_id,
        fingerprint_general="fpg-" + alert_id,
        classification_reason="test",
        color="red",
        raw_known_error="false",
    )
    defaults.update(overrides)
    return AlertEvent(**defaults)


def _seed(db_session):
    db_session.add(AlertBatch(batch_id="BATCH-1", source="s", environment="e", total_issues_detected=3))
    db_session.flush()
    db_session.add(_make_event("a1", "actionable"))
    db_session.add(_make_event("a2", "noise", color="black"))
    db_session.add(_make_event("a3", "suppressed", color="red", raw_known_error="true"))
    db_session.commit()


def test_get_alerts_defaults_to_actionable_only(client, db_session):
    _seed(db_session)
    res = client.get("/api/alerts")
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 1
    assert data[0]["signal_type"] == "actionable"


def test_get_alerts_include_noise(client, db_session):
    _seed(db_session)
    res = client.get("/api/alerts", params={"include": "noise"})
    data = res.json()
    assert len(data) == 1
    assert data[0]["signal_type"] == "noise"


def test_get_alerts_include_suppressed(client, db_session):
    _seed(db_session)
    res = client.get("/api/alerts", params={"include": "suppressed"})
    data = res.json()
    assert len(data) == 1
    assert data[0]["signal_type"] == "suppressed"


def test_get_alerts_include_multiple_values(client, db_session):
    _seed(db_session)
    res = client.get("/api/alerts", params={"include": "noise,suppressed"})
    data = res.json()
    assert {row["signal_type"] for row in data} == {"noise", "suppressed"}


def test_get_alerts_include_all(client, db_session):
    _seed(db_session)
    res = client.get("/api/alerts", params={"include": "all"})
    data = res.json()
    assert len(data) == 3


def test_get_alerts_invalid_include_returns_400(client, db_session):
    _seed(db_session)
    res = client.get("/api/alerts", params={"include": "bogus"})
    assert res.status_code == 400
    assert "bogus" in res.json()["detail"]


def test_existing_filters_still_work_combined_with_include(client, db_session):
    _seed(db_session)
    res = client.get("/api/alerts", params={"include": "all", "category": "new"})
    data = res.json()
    assert len(data) == 3  # all three seeded rows are category="new"

    res2 = client.get("/api/alerts", params={"include": "all", "hostname": "nonexistent"})
    assert res2.json() == []


def test_summary_counts_distinguish_actionable_noise_suppressed(client, db_session):
    _seed(db_session)
    res = client.get("/api/summary")
    data = res.json()
    assert data["signal_counts"] == {"actionable": 1, "noise": 1, "suppressed": 1, "total": 3}
    assert data["total_alerts"] == 1  # primary tiles are actionable-only
    assert data["new_unknown_count"] == 1
