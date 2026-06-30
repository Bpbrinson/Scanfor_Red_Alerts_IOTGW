"""
data/mock_alerts.py
─────────────────────────────────────────────────────────────────────────────
Mock alert batch and alert event data.
Replace with real email parsing + DB queries in Phase 3.

Alerts are stored as raw input (hostname, log_file, error_type, count, growth).
The classifier and fingerprint services derive category/fingerprint at runtime,
mirroring what will happen with real data later.
"""

ALERT_BATCH = {
    "batch_id": "ALERT-20260630-1243",
    "source": "IoTGW",
    "received_time": "2026-06-30T12:43:00",
    "received_time_display": "Tuesday, June 30, 2026 at 12:43 PM",
    "environment": "Production",
    "email_subject": "[Scanfor Red] IoTGW Alert Report — 2026-06-30 12:43",
    "sender": "scanfor-red@internal.company.com",
    "processed_at": "2026-06-30T12:44:15",
}

# ─── Raw alert events ─────────────────────────────────────────────────────────
# These are the records as they would come from the email parser.
# The API layer classifies them and adds fingerprint/category before returning.

RAW_ALERTS = [
    # ── New / Unknown ──────────────────────────────────────────────────────────
    {
        "alert_id": "a-new-001",
        "batch_id": "ALERT-20260630-1243",
        "hostname": "mxmcpiog02",
        "raw_filename": "listener-main.20260630",
        "error_type": "SQLException",
        "count": 144,
        "growth": 141,
        "first_seen": "2026-06-30T12:01:00",
        "last_seen": "2026-06-30T12:43:00",
        "notes": "",
    },
    {
        "alert_id": "a-new-002",
        "batch_id": "ALERT-20260630-1243",
        "hostname": "mxqrpiog01",
        "raw_filename": "listener-main.20260630",
        "error_type": "SQLException",
        "count": 156,
        "growth": 153,
        "first_seen": "2026-06-30T12:02:00",
        "last_seen": "2026-06-30T12:43:00",
        "notes": "",
    },
    {
        "alert_id": "a-new-003",
        "batch_id": "ALERT-20260630-1243",
        "hostname": "mxqrpiog02",
        "raw_filename": "listener-main.20260630",
        "error_type": "SQLException",
        "count": 171,
        "growth": 168,
        "first_seen": "2026-06-30T12:02:00",
        "last_seen": "2026-06-30T12:43:00",
        "notes": "",
    },
    {
        "alert_id": "a-new-004",
        "batch_id": "ALERT-20260630-1243",
        "hostname": "ccgw-eastus2-prod-cgcj-vm-01",
        "raw_filename": "smlistener-main.20260630",
        "error_type": "invalid.*redentials",
        "count": 102,
        "growth": 15,
        "first_seen": "2026-06-30T11:55:00",
        "last_seen": "2026-06-30T12:40:00",
        "notes": "",
    },
    {
        "alert_id": "a-new-005",
        "batch_id": "ALERT-20260630-1243",
        "hostname": "ccgw-westus2-prod-dev-vm-01",
        "raw_filename": "devlistener-main.20260630",
        "error_type": "SocketTimeoutException",
        "count": 38,
        "growth": 38,
        "first_seen": "2026-06-30T12:30:00",
        "last_seen": "2026-06-30T12:43:00",
        "notes": "",
    },
    # ── Known (matched, within normal range) ───────────────────────────────────
    {
        "alert_id": "a-kn-001",
        "batch_id": "ALERT-20260630-1243",
        "hostname": "ccgw-eastus2-prod-ford-vm-01",
        "raw_filename": "fordserver-main.20260630",
        "error_type": "javax_net_ssl",
        "count": 325,
        "growth": 66,
        "first_seen": "2026-06-30T10:00:00",
        "last_seen": "2026-06-30T12:43:00",
        "notes": "",
    },
    {
        "alert_id": "a-kn-002",
        "batch_id": "ALERT-20260630-1243",
        "hostname": "ccgw-eastus2-prod-maz-vm-01",
        "raw_filename": "mazdaserver-main.20260630",
        "error_type": "javax_net_ssl",
        "count": 1916,
        "growth": 496,
        "first_seen": "2026-06-30T08:00:00",
        "last_seen": "2026-06-30T12:43:00",
        "notes": "",
    },
    {
        "alert_id": "a-kn-003",
        "batch_id": "ALERT-20260630-1243",
        "hostname": "mxcpiog04",
        "raw_filename": "listener-main.20260630",
        "error_type": "NullPointerException",
        "count": 22,
        "growth": 3,
        "first_seen": "2026-06-30T11:00:00",
        "last_seen": "2026-06-30T12:30:00",
        "notes": "",
    },
    {
        "alert_id": "a-kn-004",
        "batch_id": "ALERT-20260630-1243",
        "hostname": "ccgw-centralus-prod-toyota-vm-01",
        "raw_filename": "toyotaserver-main.20260630",
        "error_type": "ConnectionRefusedException",
        "count": 14,
        "growth": 2,
        "first_seen": "2026-06-30T09:15:00",
        "last_seen": "2026-06-30T12:00:00",
        "notes": "",
    },
    {
        "alert_id": "a-kn-005",
        "batch_id": "ALERT-20260630-1243",
        "hostname": "mxpiog09",
        "raw_filename": "listener-main.20260630",
        "error_type": "OutOfMemoryError",
        "count": 5,
        "growth": 1,
        "first_seen": "2026-06-30T11:45:00",
        "last_seen": "2026-06-30T12:15:00",
        "notes": "",
    },
    # ── Resolved (prior batch, absent from current) ────────────────────────────
    # These are stored separately since they have no current batch entry.
]

RESOLVED_ALERTS = [
    {
        "alert_id": "a-res-001",
        "batch_id": "ALERT-20260629-2355",
        "hostname": "ccgw-westus2-prod-honda-vm-01",
        "raw_filename": "hondaserver-main.20260629",
        "error_type": "javax_net_ssl",
        "count": 487,
        "growth": 120,
        "first_seen": "2026-06-29T20:00:00",
        "last_seen": "2026-06-29T23:55:00",
        "notes": "SSL cert renewed. Issue cleared after midnight rotation.",
    },
    {
        "alert_id": "a-res-002",
        "batch_id": "ALERT-20260629-1830",
        "hostname": "mxpiog07",
        "raw_filename": "listener-main.20260629",
        "error_type": "SQLException",
        "count": 92,
        "growth": 88,
        "first_seen": "2026-06-29T15:00:00",
        "last_seen": "2026-06-29T18:30:00",
        "notes": "DB connection pool restarted by DBA team. No recurrence.",
    },
    {
        "alert_id": "a-res-003",
        "batch_id": "ALERT-20260629-2110",
        "hostname": "ccgw-centralus-prod-nissan-vm-01",
        "raw_filename": "nissanserver-main.20260629",
        "error_type": "ConnectionRefusedException",
        "count": 31,
        "growth": 10,
        "first_seen": "2026-06-29T19:00:00",
        "last_seen": "2026-06-29T21:10:00",
        "notes": "Downstream service restarted. Connections restored.",
    },
]
