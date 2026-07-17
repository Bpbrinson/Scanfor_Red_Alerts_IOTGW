/**
 * api.js
 * ─────────────────────────────────────────────────────────────────────────────
 * All API calls to the Scanfor Red backend.
 *
 * To switch from mock backend to real data in Phase 3, only this file and
 * the Python backend need to change — the rest of the frontend stays the same.
 *
 * API base URL: change this if the backend runs on a different port.
 */

// Relative URL works when the frontend is served by the backend (http://localhost:9000).
// Falls back gracefully to mock data if the backend is not running.
const API_BASE = "/api";

// ─── Transform helpers ────────────────────────────────────────────────────────
// The API returns snake_case; the frontend render functions expect camelCase.
// All normalization is done here so render code stays unchanged.

function _transformAlert(a) {
  return {
    id:                   a.alert_id,
    status:               a.status,
    category:             a.category,
    signalType:           a.signal_type,
    color:                a.color,
    knownError:           a.raw_known_error === "true" || a.raw_known_error === true,
    hostname:             a.hostname,
    logFile:              a.log_file,       // normalized (date stripped) — used for fingerprint/search/mark-known
    rawFilename:          a.raw_filename,   // full filename including date, for display only
    errorType:            a.error_type,
    count:                a.count,
    currentCount:         a.count,   // worsening rows use currentCount
    growth:               a.growth,
    severity:             a.severity,
    firstSeen:            a.first_seen,
    lastSeen:             a.last_seen,
    fingerprint:          a.fingerprint,
    classificationReason: a.classification_reason,
    suggestedAction:      a.suggested_action,
    knownIssueId:         a.known_issue_id,
    owner:                a.owner,
    runbookLink:          a.runbook_link,
    ticketLink:           a.ticket_link,
    notes:                a.notes || "",
    normalRange:          a.normal_range,
    escalationRule:       a.escalation_rule,

    // ─── Trend analysis (backend/services/trends.py) ─────────────────────
    alertKey:                 a.alert_key,
    currentValue:             a.current_value,
    previousValue:            a.previous_value,
    isRed:                    !!a.is_red,
    absoluteChange:           a.absolute_change,
    percentageChange:         a.percentage_change,
    growthRatePerHour:        a.growth_rate_per_hour,
    change15m:                a.change_15m,
    percentageChange15m:      a.percentage_change_15m,
    change1h:                 a.change_1h,
    percentageChange1h:       a.percentage_change_1h,
    change6h:                 a.change_6h,
    percentageChange6h:       a.percentage_change_6h,
    change24h:                a.change_24h,
    percentageChange24h:      a.percentage_change_24h,
    slope1h:                  a.slope_1h,
    slope6h:                  a.slope_6h,
    acceleration:             a.acceleration,
    thresholdExcessPercentage: a.threshold_excess_percentage,
    redStartedAt:             a.red_started_at,
    redDurationSeconds:       a.red_duration_seconds,
    consecutiveRedSnapshots:  a.consecutive_red_snapshots,
    redStateTransitionCount:  a.red_state_transition_count,
    isFlapping:               !!a.is_flapping,
    trendState:               a.trend_state,
    changeScore:              a.change_score,
    changeScoreConfidence:    a.change_score_confidence,
    changeScoreComponents:    a.change_score_components,
    affectedVmCount:          a.affected_vm_count,
  };
}

function _transformKnownIssue(ki) {
  return {
    id:               ki.known_issue_id,
    fingerprint:      ki.fingerprint,
    errorType:        ki.error_type,
    hostScope:        ki.host_scope,
    logScope:         ki.log_scope,
    severity:         ki.severity,
    owner:            ki.owner,
    status:           ki.status,
    normalCountRange: `${ki.normal_count_min}–${ki.normal_count_max}`,
    cause:            ki.cause,
    impact:           ki.impact,
    resolutionSteps:  ki.resolution_steps,
    runbookLink:      ki.runbook_link,
    ticketLink:       ki.ticket_link,
    lastReviewed:     ki.last_reviewed,
  };
}

function _transformBatch(b) {
  return {
    id:          b.batch_id,
    source:      b.source,
    receivedTime: b.received_time_display,
    environment: b.environment,
    totalIssues: b.total_issues_detected,
    emailSubject: b.email_subject,
    sender:      b.sender,
    processedAt: b.processed_at,
  };
}

// ─── API fetch functions ───────────────────────────────────────────────────────

async function getSummary() {
  const res = await fetch(`${API_BASE}/summary`);
  if (!res.ok) throw new Error(`/api/summary returned ${res.status}`);
  return res.json();
}

async function getLatestBatch() {
  const res = await fetch(`${API_BASE}/alert-batches/latest`);
  if (!res.ok) throw new Error(`/api/alert-batches/latest returned ${res.status}`);
  const data = await res.json();
  return _transformBatch(data);
}

async function getAlerts(include = "all") {
  // include=all fetches actionable + noise + suppressed in one call; dataStore.js
  // does the actionable/noise/suppressed split client-side, the same way it
  // already splits by category (new/known/worsening/resolved).
  const res = await fetch(`${API_BASE}/alerts?include=${encodeURIComponent(include)}`);
  if (!res.ok) throw new Error(`/api/alerts returned ${res.status}`);
  const data = await res.json();
  return data.map(_transformAlert);
}

async function getPromStatus() {
  const res = await fetch(`${API_BASE}/prom/status`);
  if (!res.ok) throw new Error(`/api/prom/status returned ${res.status}`);
  return res.json();
}

async function getPromFiles() {
  const res = await fetch(`${API_BASE}/prom/files`);
  if (!res.ok) throw new Error(`/api/prom/files returned ${res.status}`);
  return res.json();
}

async function processPromFile() {
  const res = await fetch(`${API_BASE}/prom/process`, { method: "POST" });
  if (!res.ok) {
    const error = await res.json().catch(() => null);
    throw new Error(error?.detail || `/api/prom/process returned ${res.status}`);
  }
  return res.json();
}

async function getKnownIssues() {
  const res = await fetch(`${API_BASE}/known-issues`);
  if (!res.ok) throw new Error(`/api/known-issues returned ${res.status}`);
  const data = await res.json();
  return data.map(_transformKnownIssue);
}

async function markAlertKnown(alertId, payload) {
  const res = await fetch(`${API_BASE}/alerts/${encodeURIComponent(alertId)}/mark-known`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const error = await res.json().catch(() => null);
    throw new Error(error?.detail || `mark-known returned ${res.status}`);
  }
  return res.json();
}

async function saveAlertNote(alertId, note) {
  const res = await fetch(`${API_BASE}/alerts/${encodeURIComponent(alertId)}/notes`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ note, created_by: "user" }),
  });
  if (!res.ok) {
    const error = await res.json().catch(() => null);
    throw new Error(error?.detail || `note save returned ${res.status}`);
  }
  return res.json();
}

async function updateAlertTicket(alertId, ticketLink) {
  const res = await fetch(`${API_BASE}/alerts/${encodeURIComponent(alertId)}/ticket`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ticket_link: ticketLink, changed_by: "user" }),
  });
  if (!res.ok) {
    const error = await res.json().catch(() => null);
    throw new Error(error?.detail || `ticket update returned ${res.status}`);
  }
  return res.json();
}

async function updateAlertStatus(alertId, payload) {
  const res = await fetch(`${API_BASE}/alerts/${encodeURIComponent(alertId)}/status`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const error = await res.json().catch(() => null);
    throw new Error(error?.detail || `status update returned ${res.status}`);
  }
  return res.json();
}
