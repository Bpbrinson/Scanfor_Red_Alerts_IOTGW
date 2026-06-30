/**
 * mockKnownIssues.js
 * ─────────────────────────────────────────────────────────────────────────────
 * MOCK DATA ONLY — replace with real API calls when the backend is ready.
 * The known-issue records are the "catalog" that fingerprint-matching uses
 * to classify incoming alerts.
 */

const KNOWN_ISSUES = [
  {
    id: "KI-001",
    fingerprint: "prod | ccgw-eastus2 | *server-main | javax_net_ssl",
    errorType: "javax_net_ssl",
    hostScope: "ccgw-eastus2-prod-*",
    logScope: "*server-main",
    severity: "high",
    owner: "network-team",
    status: "active",
    normalCountRange: "50–600",
    cause:
      "Periodic SSL/TLS handshake failures between IoTGW connectors and OEM endpoints when certs approach expiry or rotation windows.",
    impact:
      "OEM data ingestion interruptions; messages queue up and replay after cert refresh.",
    resolutionSteps:
      "1. Verify cert expiry on affected connector VM.\n2. Renew or rotate cert per cert-mgmt runbook.\n3. Restart connector service.\n4. Confirm error count drops to baseline.",
    runbookLink: "#runbook-ki-001",
    ticketLink: "#ticket-net-4421",
    lastReviewed: "2026-06-15",
  },
  {
    id: "KI-002",
    fingerprint: "prod | mxcpiog | listener-main | NullPointerException",
    errorType: "NullPointerException",
    hostScope: "mxcpiog*",
    logScope: "listener-main",
    severity: "medium",
    owner: "app-team",
    status: "active",
    normalCountRange: "2–15",
    cause:
      "Race condition in the IoTGW listener when a vehicle session is torn down while a message batch is still being processed.",
    impact:
      "Dropped message batch for affected vehicle; vehicle re-sends on next heartbeat.",
    resolutionSteps:
      "1. Confirm count is within normal range (< 20).\n2. Check for spike pattern matching vehicle re-auth storms.\n3. If > 20, notify app-team lead for hotfix assessment.",
    runbookLink: "#runbook-ki-002",
    ticketLink: "#ticket-app-8812",
    lastReviewed: "2026-06-20",
  },
  {
    id: "KI-003",
    fingerprint: "prod | ccgw-centralus | *server-main | ConnectionRefusedException",
    errorType: "ConnectionRefusedException",
    hostScope: "ccgw-centralus-prod-*",
    logScope: "*server-main",
    severity: "medium",
    owner: "integrations-team",
    status: "active",
    normalCountRange: "0–20",
    cause:
      "Downstream OEM integration endpoint temporarily unavailable; often caused by OEM-side maintenance windows.",
    impact: "Temporary data gap for affected OEM; auto-retry resolves within 15 min.",
    resolutionSteps:
      "1. Check OEM maintenance calendar.\n2. If no scheduled maintenance, escalate to OEM integration contact.\n3. Monitor retry queue; clear if stale entries exceed 1 hour.",
    runbookLink: "#runbook-ki-003",
    ticketLink: "#ticket-int-2209",
    lastReviewed: "2026-06-22",
  },
  {
    id: "KI-004",
    fingerprint: "prod | mxpiog | listener-main | OutOfMemoryError",
    errorType: "OutOfMemoryError",
    hostScope: "mxpiog*",
    logScope: "listener-main",
    severity: "high",
    owner: "infra-team",
    status: "active",
    normalCountRange: "0–5",
    cause:
      "JVM heap exhaustion on listener nodes during peak vehicle session load; heap sizing is under review.",
    impact:
      "Listener process may restart; brief message processing gap on affected node.",
    resolutionSteps:
      "1. Verify listener process is still running (or restarted automatically).\n2. Check heap usage via JMX or node metrics.\n3. If recurring, escalate to infra-team for heap increase.\n4. Review GC logs for leak patterns.",
    runbookLink: "#runbook-ki-004",
    ticketLink: "#ticket-inf-3317",
    lastReviewed: "2026-06-18",
  },
  {
    id: "KI-005",
    fingerprint: "prod | mxqrpiog | listener-main | AuthenticationException",
    errorType: "AuthenticationException",
    hostScope: "mxqrpiog*",
    logScope: "listener-main",
    severity: "low",
    owner: "security-team",
    status: "monitoring",
    normalCountRange: "0–10",
    cause:
      "Occasional vehicle token refresh failures; tokens expire and vehicles retry with fresh tokens.",
    impact: "Minimal — vehicles reconnect automatically within 60 seconds.",
    resolutionSteps:
      "1. Confirm counts stay below 10.\n2. If spike > 10, check token issuer service health.\n3. Escalate to security-team if token service shows errors.",
    runbookLink: "#runbook-ki-005",
    ticketLink: null,
    lastReviewed: "2026-06-28",
  },
];
