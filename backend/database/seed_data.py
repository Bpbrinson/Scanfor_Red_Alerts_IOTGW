"""
database/seed_data.py
─────────────────────────────────────────────────────────────────────────────
Loads realistic sample data into the database.
Uses the same alert examples as the Phase 2 mock files.
Classification runs at seed time — categories are stored in the DB.
"""

from datetime import datetime
from sqlalchemy.orm import Session

from backend.database.models import AlertBatch, AlertEvent, KnownIssue, AlertNote, IssueStatusHistory
from backend.services.fingerprint import build_fingerprint
from backend.services.classifier import classify_alert

# ─── Known Issues catalog ────────────────────────────────────────────────────
SEED_KNOWN_ISSUES = [
    {
        "known_issue_id": "KI-001",
        "fingerprint": "prod | ccgw-eastus2-prod | *server-main | javax_net_ssl",
        "error_type": "javax_net_ssl",
        "host_scope": "ccgw-eastus2-prod-*",
        "log_scope": "*server-main",
        "severity": "high",
        "owner": "network-team",
        "status": "active",
        "normal_count_min": 50,
        "normal_count_max": 600,
        "normal_growth_min": 0,
        "normal_growth_max": 200,
        "cause": "Periodic SSL/TLS handshake failures between IoTGW connectors and OEM endpoints when certs approach expiry or rotation windows.",
        "impact": "OEM data ingestion interruptions; messages queue up and replay after cert refresh.",
        "resolution_steps": "1. Verify cert expiry on affected connector VM.\n2. Renew or rotate cert per cert-mgmt runbook.\n3. Restart connector service.\n4. Confirm error count drops to baseline.",
        "runbook_link": "#runbook-ki-001",
        "ticket_link": "#ticket-net-4421",
        "last_reviewed": "2026-06-15",
    },
    {
        "known_issue_id": "KI-002",
        "fingerprint": "prod | mxcpiog | listener-main | NullPointerException",
        "error_type": "NullPointerException",
        "host_scope": "mxcpiog*",
        "log_scope": "listener-main",
        "severity": "medium",
        "owner": "app-team",
        "status": "active",
        "normal_count_min": 2,
        "normal_count_max": 15,
        "normal_growth_min": 0,
        "normal_growth_max": 10,
        "cause": "Race condition in the IoTGW listener when a vehicle session is torn down while a message batch is still being processed.",
        "impact": "Dropped message batch for affected vehicle; vehicle re-sends on next heartbeat.",
        "resolution_steps": "1. Confirm count is within normal range (< 20).\n2. Check for spike pattern matching vehicle re-auth storms.\n3. If > 20, notify app-team lead for hotfix assessment.",
        "runbook_link": "#runbook-ki-002",
        "ticket_link": "#ticket-app-8812",
        "last_reviewed": "2026-06-20",
    },
    {
        "known_issue_id": "KI-003",
        "fingerprint": "prod | ccgw-centralus-prod | *server-main | ConnectionRefusedException",
        "error_type": "ConnectionRefusedException",
        "host_scope": "ccgw-centralus-prod-*",
        "log_scope": "*server-main",
        "severity": "medium",
        "owner": "integrations-team",
        "status": "active",
        "normal_count_min": 0,
        "normal_count_max": 20,
        "normal_growth_min": 0,
        "normal_growth_max": 15,
        "cause": "Downstream OEM integration endpoint temporarily unavailable; often caused by OEM-side maintenance windows.",
        "impact": "Temporary data gap for affected OEM; auto-retry resolves within 15 min.",
        "resolution_steps": "1. Check OEM maintenance calendar.\n2. If no scheduled maintenance, escalate to OEM integration contact.\n3. Monitor retry queue; clear if stale entries exceed 1 hour.",
        "runbook_link": "#runbook-ki-003",
        "ticket_link": "#ticket-int-2209",
        "last_reviewed": "2026-06-22",
    },
    {
        "known_issue_id": "KI-004",
        "fingerprint": "prod | mxpiog | listener-main | OutOfMemoryError",
        "error_type": "OutOfMemoryError",
        "host_scope": "mxpiog*",
        "log_scope": "listener-main",
        "severity": "high",
        "owner": "infra-team",
        "status": "active",
        "normal_count_min": 0,
        "normal_count_max": 5,
        "normal_growth_min": 0,
        "normal_growth_max": 5,
        "cause": "JVM heap exhaustion on listener nodes during peak vehicle session load; heap sizing is under review.",
        "impact": "Listener process may restart; brief message processing gap on affected node.",
        "resolution_steps": "1. Verify listener process is still running (or restarted automatically).\n2. Check heap usage via JMX or node metrics.\n3. If recurring, escalate to infra-team for heap increase.\n4. Review GC logs for leak patterns.",
        "runbook_link": "#runbook-ki-004",
        "ticket_link": "#ticket-inf-3317",
        "last_reviewed": "2026-06-18",
    },
    {
        "known_issue_id": "KI-005",
        "fingerprint": "prod | mxqrpiog | listener-main | AuthenticationException",
        "error_type": "AuthenticationException",
        "host_scope": "mxqrpiog*",
        "log_scope": "listener-main",
        "severity": "low",
        "owner": "security-team",
        "status": "monitoring",
        "normal_count_min": 0,
        "normal_count_max": 10,
        "normal_growth_min": 0,
        "normal_growth_max": 5,
        "cause": "Occasional vehicle token refresh failures; tokens expire and vehicles retry with fresh tokens.",
        "impact": "Minimal — vehicles reconnect automatically within 60 seconds.",
        "resolution_steps": "1. Confirm counts stay below 10.\n2. If spike > 10, check token issuer service health.\n3. Escalate to security-team if token service shows errors.",
        "runbook_link": "#runbook-ki-005",
        "ticket_link": None,
        "last_reviewed": "2026-06-28",
    },
]

# ─── Current alert batch ─────────────────────────────────────────────────────
SEED_BATCH = {
    "batch_id": "ALERT-20260630-1243",
    "source": "IoTGW",
    "environment": "Production",
    "email_subject": "[Scanfor Red] IoTGW Alert Report — 2026-06-30 12:43",
    "sender": "scanfor-red@internal.company.com",
    "received_time": "2026-06-30T12:43:00",
    "received_time_display": "Tuesday, June 30, 2026 at 12:43 PM",
    "processed_at": "2026-06-30T12:44:15",
}

# ─── Raw active alerts (to be classified at seed time) ───────────────────────
SEED_RAW_ALERTS = [
    # 5 that will be classified as new/unknown
    {"alert_id": "a-new-001", "hostname": "mxmcpiog02",                    "raw_filename": "listener-main.20260630",   "error_type": "SQLException",           "count": 144,  "growth": 141, "first_seen": "2026-06-30T12:01:00", "last_seen": "2026-06-30T12:43:00"},
    {"alert_id": "a-new-002", "hostname": "mxqrpiog01",                    "raw_filename": "listener-main.20260630",   "error_type": "SQLException",           "count": 156,  "growth": 153, "first_seen": "2026-06-30T12:02:00", "last_seen": "2026-06-30T12:43:00"},
    {"alert_id": "a-new-003", "hostname": "mxqrpiog02",                    "raw_filename": "listener-main.20260630",   "error_type": "SQLException",           "count": 171,  "growth": 168, "first_seen": "2026-06-30T12:02:00", "last_seen": "2026-06-30T12:43:00"},
    {"alert_id": "a-new-004", "hostname": "ccgw-eastus2-prod-cgcj-vm-01",  "raw_filename": "smlistener-main.20260630", "error_type": "invalid.*redentials",    "count": 102,  "growth": 15,  "first_seen": "2026-06-30T11:55:00", "last_seen": "2026-06-30T12:40:00"},
    {"alert_id": "a-new-005", "hostname": "ccgw-westus2-prod-dev-vm-01",   "raw_filename": "devlistener-main.20260630","error_type": "SocketTimeoutException", "count": 38,   "growth": 38,  "first_seen": "2026-06-30T12:30:00", "last_seen": "2026-06-30T12:43:00"},
    # Will be classified as known or worsening by the classifier
    {"alert_id": "a-kn-001",  "hostname": "ccgw-eastus2-prod-ford-vm-01",  "raw_filename": "fordserver-main.20260630", "error_type": "javax_net_ssl",          "count": 325,  "growth": 66,  "first_seen": "2026-06-30T10:00:00", "last_seen": "2026-06-30T12:43:00"},
    {"alert_id": "a-kn-002",  "hostname": "ccgw-eastus2-prod-maz-vm-01",   "raw_filename": "mazdaserver-main.20260630","error_type": "javax_net_ssl",          "count": 1916, "growth": 496, "first_seen": "2026-06-30T08:00:00", "last_seen": "2026-06-30T12:43:00"},
    {"alert_id": "a-kn-003",  "hostname": "mxcpiog04",                     "raw_filename": "listener-main.20260630",   "error_type": "NullPointerException",   "count": 22,   "growth": 3,   "first_seen": "2026-06-30T11:00:00", "last_seen": "2026-06-30T12:30:00"},
    {"alert_id": "a-kn-004",  "hostname": "ccgw-centralus-prod-toyota-vm-01","raw_filename": "toyotaserver-main.20260630","error_type": "ConnectionRefusedException","count": 14,"growth": 2, "first_seen": "2026-06-30T09:15:00", "last_seen": "2026-06-30T12:00:00"},
    {"alert_id": "a-kn-005",  "hostname": "mxpiog09",                      "raw_filename": "listener-main.20260630",   "error_type": "OutOfMemoryError",       "count": 5,    "growth": 1,   "first_seen": "2026-06-30T11:45:00", "last_seen": "2026-06-30T12:15:00"},
]

# ─── Resolved alerts (from a prior batch) ────────────────────────────────────
SEED_RESOLVED_ALERTS = [
    {"alert_id": "a-res-001", "batch_id": "ALERT-20260629-2355", "hostname": "ccgw-westus2-prod-honda-vm-01",   "raw_filename": "hondaserver-main.20260629",  "error_type": "javax_net_ssl",          "count": 487, "growth": 120, "first_seen": "2026-06-29T20:00:00", "last_seen": "2026-06-29T23:55:00", "notes": "SSL cert renewed. Issue cleared after midnight rotation."},
    {"alert_id": "a-res-002", "batch_id": "ALERT-20260629-1830", "hostname": "mxpiog07",                       "raw_filename": "listener-main.20260629",      "error_type": "SQLException",           "count": 92,  "growth": 88,  "first_seen": "2026-06-29T15:00:00", "last_seen": "2026-06-29T18:30:00", "notes": "DB connection pool restarted by DBA team. No recurrence."},
    {"alert_id": "a-res-003", "batch_id": "ALERT-20260629-2110", "hostname": "ccgw-centralus-prod-nissan-vm-01","raw_filename": "nissanserver-main.20260629",  "error_type": "ConnectionRefusedException","count": 31, "growth": 10,  "first_seen": "2026-06-29T19:00:00", "last_seen": "2026-06-29T21:10:00", "notes": "Downstream service restarted. Connections restored."},
]

# ─── Sample notes ─────────────────────────────────────────────────────────────
SEED_NOTES = [
    {"alert_event_id": "a-kn-002", "note": "Count spiked to 1916 — monitoring cert expiry. Notified network-team.", "created_by": "Brandon"},
    {"alert_event_id": "a-new-001", "note": "No known fingerprint match. Checking listener-main logs on mxmcpiog02.", "created_by": "Brandon"},
    {"alert_event_id": "a-res-001", "note": "Confirmed resolved after cert rotation at midnight. Closed.", "created_by": "Brandon"},
]


def seed(db: Session) -> None:
    """Insert all seed data into the database. Skips records that already exist."""

    # 1 — Known Issues
    for ki_data in SEED_KNOWN_ISSUES:
        existing = db.query(KnownIssue).filter_by(known_issue_id=ki_data["known_issue_id"]).first()
        if not existing:
            db.add(KnownIssue(**ki_data))
    db.flush()

    # Build in-memory list for classifier at seed time
    all_ki = db.query(KnownIssue).all()

    # 2 — Current batch
    batch = db.query(AlertBatch).filter_by(batch_id=SEED_BATCH["batch_id"]).first()
    if not batch:
        batch = AlertBatch(**SEED_BATCH, total_issues_detected=len(SEED_RAW_ALERTS))
        db.add(batch)
        db.flush()

    # 3 — Active alerts (classified at seed time)
    ki_map = {ki.known_issue_id: ki for ki in all_ki}

    for raw in SEED_RAW_ALERTS:
        existing = db.query(AlertEvent).filter_by(alert_id=raw["alert_id"]).first()
        if existing:
            continue

        fp = build_fingerprint(raw["hostname"], raw["raw_filename"], raw["error_type"])
        cl = classify_alert(
            raw["hostname"], raw["raw_filename"], raw["error_type"],
            raw["count"], raw["growth"],
            known_issues=all_ki,
        )

        ki = ki_map.get(cl["known_issue_id"]) if cl["known_issue_id"] else None
        normal_range = None
        escalation_rule = None
        if ki and cl["category"] == "worsening":
            normal_range = f"{ki.normal_count_min}–{ki.normal_count_max}"
            escalation_rule = f"Count > {ki.normal_count_max} — notify {ki.owner}"

        db.add(AlertEvent(
            alert_id=raw["alert_id"],
            batch_id=SEED_BATCH["batch_id"],
            status=cl["category"],
            category=cl["category"],
            hostname=raw["hostname"],
            raw_filename=raw["raw_filename"],
            log_file=raw["raw_filename"].split(".")[0] if "." in raw["raw_filename"] else raw["raw_filename"],
            error_type=raw["error_type"],
            count=raw["count"],
            growth=raw["growth"],
            severity=cl["severity"],
            first_seen=raw["first_seen"],
            last_seen=raw["last_seen"],
            fingerprint=fp,
            classification_reason=cl["classification_reason"],
            suggested_action=cl["suggested_action"],
            known_issue_id=cl["known_issue_id"],
            owner=cl["owner"],
            runbook_link=ki.runbook_link if ki else None,
            ticket_link=ki.ticket_link if ki else None,
            notes="",
            normal_range=normal_range,
            escalation_rule=escalation_rule,
        ))

    db.flush()

    # 4 — Prior batch record (parent for resolved alerts)
    for res in SEED_RESOLVED_ALERTS:
        prior_batch = db.query(AlertBatch).filter_by(batch_id=res["batch_id"]).first()
        if not prior_batch:
            db.add(AlertBatch(
                batch_id=res["batch_id"],
                source="IoTGW",
                environment="Production",
                email_subject="[Scanfor Red] Prior Batch",
                sender="scanfor-red@internal.company.com",
                received_time=res["batch_id"].replace("ALERT-", "").replace("-", "T", 1)[:16] + ":00",
                received_time_display="Prior batch",
                processed_at=res["batch_id"].replace("ALERT-", "")[:10] + "T00:00:00",
                total_issues_detected=0,
            ))
    db.flush()

    # 5 — Resolved alerts
    for res in SEED_RESOLVED_ALERTS:
        existing = db.query(AlertEvent).filter_by(alert_id=res["alert_id"]).first()
        if existing:
            continue

        fp = build_fingerprint(res["hostname"], res["raw_filename"], res["error_type"])
        cl = classify_alert(
            res["hostname"], res["raw_filename"], res["error_type"],
            res["count"], res["growth"],
            known_issues=all_ki,
        )
        ki = ki_map.get(cl["known_issue_id"]) if cl["known_issue_id"] else None

        db.add(AlertEvent(
            alert_id=res["alert_id"],
            batch_id=res["batch_id"],
            status="resolved",
            category="resolved",
            hostname=res["hostname"],
            raw_filename=res["raw_filename"],
            log_file=res["raw_filename"].split(".")[0] if "." in res["raw_filename"] else res["raw_filename"],
            error_type=res["error_type"],
            count=res["count"],
            growth=res["growth"],
            severity=None,
            first_seen=res["first_seen"],
            last_seen=res["last_seen"],
            fingerprint=fp,
            classification_reason="Previously active issue not seen in current batch.",
            suggested_action=None,
            known_issue_id=cl["known_issue_id"],
            owner=cl["owner"],
            runbook_link=ki.runbook_link if ki else None,
            ticket_link=ki.ticket_link if ki else None,
            notes=res.get("notes", ""),
        ))

    db.flush()

    # 6 — Sample notes
    for note_data in SEED_NOTES:
        event = db.query(AlertEvent).filter_by(alert_id=note_data["alert_event_id"]).first()
        if event:
            existing_note = db.query(AlertNote).filter_by(
                alert_event_id=note_data["alert_event_id"],
                note=note_data["note"]
            ).first()
            if not existing_note:
                db.add(AlertNote(
                    alert_event_id=note_data["alert_event_id"],
                    note=note_data["note"],
                    created_by=note_data["created_by"],
                ))

    db.commit()
    print(f"  ✓ Seeded {len(SEED_KNOWN_ISSUES)} known issues")
    print(f"  ✓ Seeded {len(SEED_RAW_ALERTS)} active alerts")
    print(f"  ✓ Seeded {len(SEED_RESOLVED_ALERTS)} resolved alerts")
    print(f"  ✓ Seeded {len(SEED_NOTES)} sample notes")
