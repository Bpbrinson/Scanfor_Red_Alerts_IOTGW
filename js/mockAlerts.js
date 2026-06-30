/**
 * mockAlerts.js
 * ─────────────────────────────────────────────────────────────────────────────
 * MOCK DATA ONLY — replace this file's exports with real API calls when the
 * backend is ready. The shape of each object should stay the same so the UI
 * components don't need to change.
 *
 * Categories:
 *   new       – no matching known-issue fingerprint
 *   known     – matched a known-issue record
 *   worsening – matched, but growth exceeds the issue's normal threshold
 *   resolved  – was active in a previous batch, absent from the current one
 */

const ALERT_BATCH = {
  id: "ALERT-20260630-1243",
  source: "IoTGW",
  receivedTime: "Tuesday, June 30, 2026 at 12:43 PM",
  environment: "Production",
};

// ─── New / Unknown Issues ────────────────────────────────────────────────────
const NEW_ALERTS = [
  {
    id: "a-new-001",
    status: "new",
    hostname: "mxmcpiog02",
    logFile: "listener-main.20260630",
    errorType: "SQLException",
    count: 144,
    growth: 141,
    firstSeen: "2026-06-30 12:01",
    lastSeen: "2026-06-30 12:43",
    suggestedAction: "Investigate DB connection pool on mxmcpiog02",
    classificationReason: "No matching known issue fingerprint found.",
    notes: "",
  },
  {
    id: "a-new-002",
    status: "new",
    hostname: "mxqrpiog01",
    logFile: "listener-main.20260630",
    errorType: "SQLException",
    count: 156,
    growth: 153,
    firstSeen: "2026-06-30 12:02",
    lastSeen: "2026-06-30 12:43",
    suggestedAction: "Check DB health on mxqrpiog01 listener cluster",
    classificationReason: "No matching known issue fingerprint found.",
    notes: "",
  },
  {
    id: "a-new-003",
    status: "new",
    hostname: "mxqrpiog02",
    logFile: "listener-main.20260630",
    errorType: "SQLException",
    count: 171,
    growth: 168,
    firstSeen: "2026-06-30 12:02",
    lastSeen: "2026-06-30 12:43",
    suggestedAction: "Coordinate with mxqrpiog01 investigation — same error type",
    classificationReason: "No matching known issue fingerprint found.",
    notes: "",
  },
  {
    id: "a-new-004",
    status: "new",
    hostname: "ccgw-eastus2-prod-cgcj-vm-01",
    logFile: "smlistener-main.20260630",
    errorType: "invalid.*redentials",
    count: 102,
    growth: 15,
    firstSeen: "2026-06-30 11:55",
    lastSeen: "2026-06-30 12:40",
    suggestedAction: "Verify service account credentials for cgcj connector",
    classificationReason: "No matching known issue fingerprint found.",
    notes: "",
  },
  {
    id: "a-new-005",
    status: "new",
    hostname: "ccgw-westus2-prod-dev-vm-01",
    logFile: "devlistener-main.20260630",
    errorType: "SocketTimeoutException",
    count: 38,
    growth: 38,
    firstSeen: "2026-06-30 12:30",
    lastSeen: "2026-06-30 12:43",
    suggestedAction: "Check downstream service availability from westus2",
    classificationReason: "No matching known issue fingerprint found.",
    notes: "",
  },
];

// ─── Known Issues (matched a known-issue record) ─────────────────────────────
const KNOWN_ALERTS = [
  {
    id: "a-kn-001",
    status: "known",
    hostname: "ccgw-eastus2-prod-ford-vm-01",
    logFile: "fordserver-main.20260630",
    errorType: "javax_net_ssl",
    count: 325,
    growth: 66,
    knownIssueId: "KI-001",
    owner: "network-team",
    runbookLink: "#runbook-ki-001",
    ticketLink: "#ticket-net-4421",
    classificationReason: "Matched Known Issue KI-001 by error type and log scope.",
    notes: "",
  },
  {
    id: "a-kn-002",
    status: "known",
    hostname: "ccgw-eastus2-prod-maz-vm-01",
    logFile: "mazdaserver-main.20260630",
    errorType: "javax_net_ssl",
    count: 1916,
    growth: 496,
    knownIssueId: "KI-001",
    owner: "network-team",
    runbookLink: "#runbook-ki-001",
    ticketLink: "#ticket-net-4421",
    classificationReason: "Matched Known Issue KI-001 by error type and log scope.",
    notes: "",
  },
  {
    id: "a-kn-003",
    status: "known",
    hostname: "mxcpiog04",
    logFile: "listener-main.20260630",
    errorType: "NullPointerException",
    count: 22,
    growth: 3,
    knownIssueId: "KI-002",
    owner: "app-team",
    runbookLink: "#runbook-ki-002",
    ticketLink: "#ticket-app-8812",
    classificationReason: "Matched Known Issue KI-002 by error type and log scope.",
    notes: "",
  },
  {
    id: "a-kn-004",
    status: "known",
    hostname: "ccgw-centralus-prod-toyota-vm-01",
    logFile: "toyotaserver-main.20260630",
    errorType: "ConnectionRefusedException",
    count: 14,
    growth: 2,
    knownIssueId: "KI-003",
    owner: "integrations-team",
    runbookLink: "#runbook-ki-003",
    ticketLink: "#ticket-int-2209",
    classificationReason: "Matched Known Issue KI-003 by error type and host scope.",
    notes: "",
  },
  {
    id: "a-kn-005",
    status: "known",
    hostname: "mxpiog09",
    logFile: "listener-main.20260630",
    errorType: "OutOfMemoryError",
    count: 5,
    growth: 1,
    knownIssueId: "KI-004",
    owner: "infra-team",
    runbookLink: "#runbook-ki-004",
    ticketLink: "#ticket-inf-3317",
    classificationReason: "Matched Known Issue KI-004 by error type and host scope.",
    notes: "",
  },
];

// ─── Known but Worsening ─────────────────────────────────────────────────────
const WORSENING_ALERTS = [
  {
    id: "a-ws-001",
    status: "worsening",
    hostname: "ccgw-eastus2-prod-maz-vm-01",
    logFile: "mazdaserver-main.20260630",
    errorType: "javax_net_ssl",
    normalRange: "200–600",
    currentCount: 1916,
    growth: 496,
    severity: "critical",
    escalationRule: "Count > 1000 — auto-escalate to network-team lead",
    knownIssueId: "KI-001",
    classificationReason:
      "Known issue matched, but growth exceeded normal threshold (496 > 200 max growth).",
    notes: "",
  },
  {
    id: "a-ws-002",
    status: "worsening",
    hostname: "ccgw-eastus2-prod-ford-vm-01",
    logFile: "fordserver-main.20260630",
    errorType: "javax_net_ssl",
    normalRange: "50–250",
    currentCount: 325,
    growth: 66,
    severity: "high",
    escalationRule: "Count > 300 — notify network-team",
    knownIssueId: "KI-001",
    classificationReason:
      "Known issue matched, but count exceeded normal high threshold (325 > 250).",
    notes: "",
  },
  {
    id: "a-ws-003",
    status: "worsening",
    hostname: "mxcpiog04",
    logFile: "listener-main.20260630",
    errorType: "NullPointerException",
    normalRange: "5–15",
    currentCount: 22,
    growth: 3,
    severity: "medium",
    escalationRule: "Count > 20 — notify app-team",
    knownIssueId: "KI-002",
    classificationReason:
      "Known issue matched, but count exceeded normal high threshold (22 > 15).",
    notes: "",
  },
];

// ─── Resolved / No Longer Seen ───────────────────────────────────────────────
const RESOLVED_ALERTS = [
  {
    id: "a-res-001",
    status: "resolved",
    hostname: "ccgw-westus2-prod-honda-vm-01",
    logFile: "hondaserver-main.20260629",
    errorType: "javax_net_ssl",
    previousCount: 487,
    lastSeen: "2026-06-29 23:55",
    resolutionNotes: "SSL cert renewed. Issue cleared after midnight rotation.",
    knownIssueId: "KI-001",
  },
  {
    id: "a-res-002",
    status: "resolved",
    hostname: "mxpiog07",
    logFile: "listener-main.20260629",
    errorType: "SQLException",
    previousCount: 92,
    lastSeen: "2026-06-29 18:30",
    resolutionNotes: "DB connection pool restarted by DBA team. No recurrence.",
    knownIssueId: null,
  },
  {
    id: "a-res-003",
    status: "resolved",
    hostname: "ccgw-centralus-prod-nissan-vm-01",
    logFile: "nissanserver-main.20260629",
    errorType: "ConnectionRefusedException",
    previousCount: 31,
    lastSeen: "2026-06-29 21:10",
    resolutionNotes: "Downstream service restarted. Connections restored.",
    knownIssueId: "KI-003",
  },
];

// ─── Aggregated export ────────────────────────────────────────────────────────
const ALL_ALERTS = [
  ...NEW_ALERTS,
  ...KNOWN_ALERTS,
  ...WORSENING_ALERTS,
  ...RESOLVED_ALERTS,
];
