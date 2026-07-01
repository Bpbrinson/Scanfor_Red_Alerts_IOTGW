/**
 * dataStore.js
 * ─────────────────────────────────────────────────────────────────────────────
 * Central data store for the dashboard.
 *
 * All render functions read from STORE instead of directly from the mock-data
 * globals. This means:
 *   - When the API is available: STORE is populated by api.js fetch calls
 *   - When the API is unavailable: STORE falls back to the JS mock globals
 *
 * Replace the mock-fallback path with a proper error state in Phase 3 once
 * the backend is always expected to be running.
 */

const STORE = {
  batch:               null,  // current alert batch metadata
  allAlerts:           [],    // all categories combined
  newAlerts:           [],
  knownAlerts:         [],
  worseningAlerts:     [],
  resolvedAlerts:      [],
  knownIssuesCatalog:  [],
  loaded:              false,
  usingFallback:       false,
  promStatus:         null,
};

/**
 * Store Prometheus .prom status information.
 */
function populatePromStatus(promStatus) {
  STORE.promStatus = promStatus;
}

/**
 * Populate STORE from API-fetched data (already transformed to camelCase).
 */
function populateStoreFromApi(batch, alerts, knownIssues) {
  STORE.batch              = batch;
  STORE.allAlerts          = alerts;
  STORE.newAlerts          = alerts.filter((a) => a.category === "new");
  STORE.knownAlerts        = alerts.filter((a) => a.category === "known");
  STORE.worseningAlerts    = alerts.filter((a) => a.category === "worsening");
  STORE.resolvedAlerts     = alerts.filter((a) => a.category === "resolved");
  STORE.knownIssuesCatalog = knownIssues;
  STORE.loaded             = true;
  STORE.usingFallback      = false;
}

/**
 * Populate STORE from the JS mock-data globals when the API is unreachable.
 * The mock globals (NEW_ALERTS, etc.) are loaded via mockAlerts.js and
 * mockKnownIssues.js which are still included in index.html.
 */
function populateStoreFromMock() {
  // Add `category` field so the filter logic in render functions works
  const tag = (arr, cat) => arr.map((a) => ({ ...a, category: cat }));

  const newA  = tag(NEW_ALERTS,       "new");
  const knA   = tag(KNOWN_ALERTS,     "known");
  const wsA   = tag(WORSENING_ALERTS, "worsening");
  const resA  = tag(RESOLVED_ALERTS,  "resolved");

  STORE.batch              = ALERT_BATCH;
  STORE.newAlerts          = newA;
  STORE.knownAlerts        = knA;
  STORE.worseningAlerts    = wsA;
  STORE.resolvedAlerts     = resA;
  STORE.allAlerts          = [...newA, ...knA, ...wsA, ...resA];
  STORE.knownIssuesCatalog = KNOWN_ISSUES;
  STORE.promStatus         = null;
  STORE.loaded             = true;
  STORE.usingFallback      = true;
}
