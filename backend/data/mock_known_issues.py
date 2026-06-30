"""
data/mock_known_issues.py
─────────────────────────────────────────────────────────────────────────────
Mock known-issue catalog.
Replace with database queries when a real DB is added in Phase 3.
"""

KNOWN_ISSUES = [
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
        "cause": (
            "Periodic SSL/TLS handshake failures between IoTGW connectors and OEM endpoints "
            "when certs approach expiry or rotation windows."
        ),
        "impact": (
            "OEM data ingestion interruptions; messages queue up and replay after cert refresh."
        ),
        "resolution_steps": (
            "1. Verify cert expiry on affected connector VM.\n"
            "2. Renew or rotate cert per cert-mgmt runbook.\n"
            "3. Restart connector service.\n"
            "4. Confirm error count drops to baseline."
        ),
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
        "cause": (
            "Race condition in the IoTGW listener when a vehicle session is torn down "
            "while a message batch is still being processed."
        ),
        "impact": (
            "Dropped message batch for affected vehicle; vehicle re-sends on next heartbeat."
        ),
        "resolution_steps": (
            "1. Confirm count is within normal range (< 20).\n"
            "2. Check for spike pattern matching vehicle re-auth storms.\n"
            "3. If > 20, notify app-team lead for hotfix assessment."
        ),
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
        "cause": (
            "Downstream OEM integration endpoint temporarily unavailable; often caused by "
            "OEM-side maintenance windows."
        ),
        "impact": "Temporary data gap for affected OEM; auto-retry resolves within 15 min.",
        "resolution_steps": (
            "1. Check OEM maintenance calendar.\n"
            "2. If no scheduled maintenance, escalate to OEM integration contact.\n"
            "3. Monitor retry queue; clear if stale entries exceed 1 hour."
        ),
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
        "cause": (
            "JVM heap exhaustion on listener nodes during peak vehicle session load; "
            "heap sizing is under review."
        ),
        "impact": (
            "Listener process may restart; brief message processing gap on affected node."
        ),
        "resolution_steps": (
            "1. Verify listener process is still running (or restarted automatically).\n"
            "2. Check heap usage via JMX or node metrics.\n"
            "3. If recurring, escalate to infra-team for heap increase.\n"
            "4. Review GC logs for leak patterns."
        ),
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
        "cause": (
            "Occasional vehicle token refresh failures; tokens expire and vehicles retry "
            "with fresh tokens."
        ),
        "impact": "Minimal — vehicles reconnect automatically within 60 seconds.",
        "resolution_steps": (
            "1. Confirm counts stay below 10.\n"
            "2. If spike > 10, check token issuer service health.\n"
            "3. Escalate to security-team if token service shows errors."
        ),
        "runbook_link": "#runbook-ki-005",
        "ticket_link": None,
        "last_reviewed": "2026-06-28",
    },
]
