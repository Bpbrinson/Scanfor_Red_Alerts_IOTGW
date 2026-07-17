/**
 * dashboard.js
 * ─────────────────────────────────────────────────────────────────────────────
 * Renders the main triage dashboard view.
 * Depends on: mockAlerts.js, fingerprint.js (must be loaded first).
 */

// ─── State ────────────────────────────────────────────────────────────────────
let dashFilters = {
  search: "",
  status: "all",
  severity: "all",
  owner: "all",
  sort: "none",
  trendState: "all",
  minChangeScore: 0,
  persistentOnly: false,
  flappingOnly: false,
  multiVmOnly: false,
};

// Track which rows are expanded
const expandedRows = new Set();

// ─── Trend display helpers (backend/services/trends.py) ───────────────────────
const TREND_LABELS = {
  data_unavailable: "Data unavailable",
  insufficient_history: "Insufficient history",
  new: "New",
  spike: "Spike",
  worsening_rapidly: "Rapidly worsening",
  worsening_steadily: "Steadily worsening",
  slow_growth: "Slow growth",
  accelerating: "Accelerating",
  persistent: "Persistent",
  stable: "Stable",
  cooling: "Cooling",
  improving: "Improving",
  resolving: "Resolving",
  flapping: "Flapping",
  resolved: "Resolved",
};

function formatDuration(seconds) {
  if (seconds == null) return "—";
  const s = Math.max(0, Math.round(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (h === 0 && m === 0) return "<1m";
  if (h === 0) return `${m}m`;
  return `${h}h ${m}m`;
}

function fmtSigned(n, digits = 0) {
  if (n == null) return "—";
  const v = Number(n);
  const sign = v > 0 ? "+" : "";
  return `${sign}${digits ? v.toFixed(digits) : Math.round(v)}`;
}

function fmtPct(n, digits = 1) {
  if (n == null) return "—";
  const v = Number(n);
  const sign = v > 0 ? "+" : "";
  return `${sign}${v.toFixed(digits)}%`;
}

function trendBadge(a) {
  const state = a.trendState || "insufficient_history";
  const label = TREND_LABELS[state] || state;
  return `<span class="trend-badge trend-${state}">${label}</span>`;
}

/**
 * Trend detail block — appended to each section's existing expand panel
 * (behind the "▼ Details" toggle), not shown as an always-visible row. The
 * quick-glance numbers live in the "Scan Δ" table column instead; this panel
 * holds the rest (1h/6h/24h changes, slopes, acceleration, threshold excess,
 * red duration/start, flapping transitions, score breakdown).
 */
function trendDetailBlock(a) {
  const comp = a.changeScoreComponents || {};
  const fmtComp = (v) => (v == null ? "—" : Math.round(v));
  const vmNote = (a.affectedVmCount || 0) > 1 ? ` (${a.affectedVmCount} VMs affected)` : "";
  return `
    <div class="expand-block">
      <div class="expand-section-label">Trend Detail</div>
      <div class="kv"><span class="k">Trend</span><span class="v">${trendBadge(a)}${vmNote}</span></div>
      <div class="kv"><span class="k">1h change / Rate</span><span class="v">${fmtSigned(a.change1h)} / ${fmtSigned(a.growthRatePerHour, 1)}/hr</span></div>
      <div class="kv"><span class="k">15m / 6h / 24h</span><span class="v">${fmtSigned(a.change15m)} / ${fmtSigned(a.change6h)} / ${fmtSigned(a.change24h)}</span></div>
      <div class="kv"><span class="k">Slope 1h / 6h</span><span class="v">${fmtSigned(a.slope1h, 1)}/hr / ${fmtSigned(a.slope6h, 1)}/hr</span></div>
      <div class="kv"><span class="k">Acceleration</span><span class="v">${fmtSigned(a.acceleration, 1)}</span></div>
      <div class="kv"><span class="k">Threshold excess</span><span class="v">${fmtPct(a.thresholdExcessPercentage, 0)}</span></div>
      <div class="kv"><span class="k">Red duration</span><span class="v">${formatDuration(a.redDurationSeconds)}${a.redStartedAt ? ` (since ${new Date(a.redStartedAt).toLocaleString()})` : ""}</span></div>
      <div class="kv"><span class="k">Flapping transitions</span><span class="v">${a.redStateTransitionCount ?? 0}${a.isFlapping ? " (flapping)" : ""}</span></div>
      ${a.changeScore != null ? `<div class="kv"><span class="k">Change score</span><span class="v font-bold">${a.changeScore}${a.changeScoreConfidence != null ? ` <span class="text-muted">(confidence ${Math.round(a.changeScoreConfidence)})</span>` : ""}</span></div>` : ""}
      ${a.changeScore != null ? `<div class="kv"><span class="k">Score components</span><span class="v text-muted">short-term ${fmtComp(comp.short_term_vs_baseline)} · sustained 1h ${fmtComp(comp.sustained_1h_vs_baseline)} · accel ${fmtComp(comp.acceleration)} · persistence ${fmtComp(comp.persistence)} · multi-VM ${fmtComp(comp.multi_vm_spread)}</span></div>` : ""}
    </div>
  `;
}

// ─── Mark Known handler ───────────────────────────────────────────────────────
async function markKnownFromRow(alertId) {
  const alert = STORE.allAlerts.find((x) => x.id === alertId);
  if (!alert) {
    showToast("Alert not found.");
    return;
  }

  const payload = {
    changed_by: "user",
    new_known_issue: {
      fingerprint: alert.fingerprint,
      error_type: alert.errorType,
      host_scope: alert.hostname,
      log_scope: alert.logFile,
      severity: alert.severity || "medium",
      owner: alert.owner || "",
      normal_count_min: 0,
      normal_count_max: Math.max(Number(alert.count) || 0, 100),
      normal_growth_min: 0,
      normal_growth_max: Math.max(Number(alert.growth) || 0, 50),
      cause: "",
      impact: "",
      resolution_steps: alert.suggestedAction || "",
      runbook_link: null,
      ticket_link: null,
      last_reviewed: new Date().toISOString().slice(0, 10),
    },
  };

  setLoading(true);
  try {
    const updated = await markAlertKnown(alertId, payload);
    showToast("Marked known.");
    await loadData();
  } catch (err) {
    console.error(err);
    showToast(`Failed to mark known: ${err.message}`);
  } finally {
    setLoading(false);
  }
}

// ─── Ticket linker ────────────────────────────────────────────────────────────
async function linkTicketToRow(alertId) {
  const alert = STORE.allAlerts.find((x) => x.id === alertId);
  if (!alert) {
    showToast("Alert not found.");
    return;
  }

  const current = alert.ticketLink || "";
  const input = prompt("Ticket number or link (leave blank to clear):", current);
  if (input === null) return;
  const value = input.trim();

  setLoading(true);
  try {
    await updateAlertTicket(alertId, value || null);
    showToast(value ? `Ticket ${value} linked.` : "Ticket cleared.");
    await loadData();
  } catch (err) {
    console.error(err);
    showToast(`Failed to update ticket: ${err.message}`);
  } finally {
    setLoading(false);
  }
}

// ─── Unmark Known handler ─────────────────────────────────────────────────────
async function unmarkKnownFromRow(alertId) {
  const alert = STORE.allAlerts.find((x) => x.id === alertId);
  if (!alert) {
    showToast("Alert not found.");
    return;
  }

  const msg =
    `Move "${alert.errorType}" on ${alert.hostname} back to New / Unknown?\n\n` +
    `This clears its link to ${alert.knownIssueId || "the known issue"}.`;
  if (!confirm(msg)) return;

  setLoading(true);
  try {
    await updateAlertStatus(alertId, {
      status: "new",
      category: "new",
      changed_by: "user",
      change_reason: "Unmarked from known — returned to New / Unknown",
      clear_known_issue: true,
    });
    showToast("Alert moved back to New / Unknown.");
    await loadData();
  } catch (err) {
    console.error(err);
    showToast(`Failed to unmark: ${err.message}`);
  } finally {
    setLoading(false);
  }
}

// ─── Reopen handler ───────────────────────────────────────────────────────────
async function reopenAlert(alertId) {
  const alert = STORE.allAlerts.find((x) => x.id === alertId);
  if (!alert) {
    showToast("Alert not found.");
    return;
  }

  const msg = `Reopen "${alert.errorType}" on ${alert.hostname}?\n\nIt will move back to New / Unknown.`;
  if (!confirm(msg)) return;

  setLoading(true);
  try {
    await updateAlertStatus(alertId, {
      status: "new",
      category: "new",
      changed_by: "user",
      change_reason: "Reopened from Resolved section",
    });
    showToast("Alert reopened.");
    await loadData();
  } catch (err) {
    console.error(err);
    showToast(`Failed to reopen: ${err.message}`);
  } finally {
    setLoading(false);
  }
}

// ─── Save Note ────────────────────────────────────────────────────────────────
async function saveNoteFromRow(alertId) {
  const textarea = document.getElementById(`notes-${alertId}`);
  if (!textarea) {
    showToast("Note field not found.");
    return;
  }
  const value = textarea.value;

  try {
    await saveAlertNote(alertId, value);
    // Keep the row expanded — update STORE in place so future renders show the value.
    const alert = STORE.allAlerts.find((x) => x.id === alertId);
    if (alert) alert.notes = value;
    for (const bucket of [STORE.newAlerts, STORE.knownAlerts, STORE.worseningAlerts, STORE.resolvedAlerts]) {
      const hit = bucket.find((x) => x.id === alertId);
      if (hit) hit.notes = value;
    }
    showToast("Note saved.");
  } catch (err) {
    console.error(err);
    showToast(`Failed to save note: ${err.message}`);
  }
}

// ─── Ticket cell renderer ─────────────────────────────────────────────────────
function renderTicketField(a) {
  if (a.ticketLink) {
    return `<a href="${a.ticketLink}" class="link" onclick="linkTicketToRow('${a.id}');return false;">${a.ticketLink.replace("#ticket-", "")}</a>`;
  }
  return `<a href="#" class="link text-muted" onclick="linkTicketToRow('${a.id}');return false;">Add ticket</a>`;
}

// ─── Theme toggle ─────────────────────────────────────────────────────────────
function initTheme() {
  const saved = localStorage.getItem("scanfor-theme") || "dark";
  document.body.classList.toggle("light-mode", saved === "light");
  updateThemeButton(saved);
}

function toggleTheme() {
  const isLight = document.body.classList.toggle("light-mode");
  const theme = isLight ? "light" : "dark";
  localStorage.setItem("scanfor-theme", theme);
  updateThemeButton(theme);
}

function updateThemeButton(theme) {
  const btn = document.getElementById("theme-toggle");
  if (btn) btn.textContent = theme === "light" ? "Dark mode" : "Light mode";
}

// ─── Entry Point ──────────────────────────────────────────────────────────────
function renderDashboard() {
  renderHeaderMeta();
  renderSummaryCards();
  renderFilterBar();
  renderAllSections();
}

// ─── Header date ──────────────────────────────────────────────────────────────
function renderHeaderMeta() {
  const el = document.getElementById("header-meta");
  if (!el) return;
  const now = new Date();
  const dateStr = now.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
  const env = STORE.batch?.environment || "Production";
  const source = STORE.batch?.source || "IoTGW";
  el.innerHTML = `${env} &nbsp;·&nbsp; ${source} &nbsp;·&nbsp; ${dateStr}`;
}

// ─── Batch Header ─────────────────────────────────────────────────────────────
function renderBatchHeader() {
  const el = document.getElementById("batch-header");
  el.innerHTML = `
    <div class="batch-header-grid">
      <div class="batch-meta">
        <div class="batch-title-row">
          <span class="batch-id-badge">${STORE.batch.id}</span>
          <span class="batch-env-badge">${STORE.batch.environment}</span>
        </div>
        <div class="batch-fields">
          <div class="batch-field"><span class="bf-label">Source</span><span class="bf-val">${STORE.batch.source}</span></div>
          <div class="batch-field"><span class="bf-label">Received</span><span class="bf-val">${STORE.batch.receivedTime}</span></div>
          <div class="batch-field"><span class="bf-label">Total Issues</span><span class="bf-val alert-count">${STORE.allAlerts.filter((a) => a.category !== "resolved").length}</span></div>
        </div>
      </div>
      <div class="batch-actions">
        <button class="btn btn-secondary" onclick="refreshData()">&#8635; Refresh Data</button>
        <button class="btn btn-secondary" onclick="showToast('Export triggered (placeholder)')">&#8595; Export Report</button>
      </div>
    </div>
    <div id="prom-status-card" class="prom-status-container"></div>
  `;
}

// ─── Summary Cards ────────────────────────────────────────────────────────────
function renderSummaryCards() {
  // newAlerts/knownAlerts/worseningAlerts are already actionable-only (dataStore.js),
  // so these tiles naturally reflect actionable alerts by default.
  const activeActionable = [...STORE.newAlerts, ...STORE.knownAlerts, ...STORE.worseningAlerts];
  const total = activeActionable.length;
  const newCount = STORE.newAlerts.length;
  const knownCount = STORE.knownAlerts.length;
  const worseningCount = STORE.worseningAlerts.length;
  const resolvedCount = STORE.resolvedAlerts.length;

  const highestGrowth = activeActionable.length > 0
    ? activeActionable.reduce((max, a) => (a.growth > max.growth ? a : max), activeActionable[0])
    : null;

  const el = document.getElementById("summary-cards");
  el.innerHTML = `
    <div class="card card-total">
      <div class="card-value">${total}</div>
      <div class="card-label">Total Alerts</div>
    </div>
    <div class="card card-new" onclick="scrollToSection('section-new')">
      <div class="card-value">${newCount}</div>
      <div class="card-label">New / Unknown</div>
    </div>
    <div class="card card-known" onclick="scrollToSection('section-known')">
      <div class="card-value">${knownCount}</div>
      <div class="card-label">Known Issues</div>
    </div>
    <div class="card card-worsening" onclick="scrollToSection('section-worsening')">
      <div class="card-value">${worseningCount}</div>
      <div class="card-label">Worsening</div>
    </div>
    <div class="card card-growth">
      <div class="card-value text-red">${highestGrowth ? '+' + highestGrowth.growth : '—'}</div>
      <div class="card-label">Highest Growth</div>
      <div class="card-sub">${highestGrowth ? highestGrowth.hostname : ''}</div>
    </div>
  `;
}

function scrollToSection(id) {
  document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
}

// ─── Filter Bar ───────────────────────────────────────────────────────────────
function renderFilterBar() {
  const el = document.getElementById("filter-bar");
  el.innerHTML = `
    <div class="filter-row">
      <div class="filter-group">
        <input
          type="text"
          id="filter-search"
          class="filter-input"
          placeholder="Search hostname or error type…"
          value="${dashFilters.search}"
          oninput="onFilterChange()"
        />
      </div>
      <div class="filter-group">
        <label class="filter-label">Category</label>
        <select id="filter-status" class="filter-select" onchange="onFilterChange()">
          <option value="all" ${dashFilters.status === "all" ? "selected" : ""}>All Categories</option>
          <option value="new" ${dashFilters.status === "new" ? "selected" : ""}>New / Unknown</option>
          <option value="known" ${dashFilters.status === "known" ? "selected" : ""}>Known</option>
          <option value="worsening" ${dashFilters.status === "worsening" ? "selected" : ""}>Worsening</option>
        </select>
      </div>
      <div class="filter-group">
        <label class="filter-label">Severity</label>
        <select id="filter-severity" class="filter-select" onchange="onFilterChange()">
          <option value="all">All Severities</option>
          <option value="critical">Critical</option>
          <option value="high">High</option>
          <option value="medium">Medium</option>
          <option value="low">Low</option>
        </select>
      </div>
      <div class="filter-group">
        <label class="filter-label">Sort</label>
        <select id="filter-sort" class="filter-select" onchange="onFilterChange()">
          <option value="none">Default Order</option>
          <option value="count-desc">Highest Count</option>
          <option value="growth-desc">Highest Growth</option>
          <option value="change-score-desc">Highest Change Score</option>
          <option value="prev-scan-desc">Largest Previous-Scan Increase</option>
          <option value="1h-desc">Largest 1-Hour Increase</option>
          <option value="rate-desc">Fastest Growth Rate</option>
          <option value="red-duration-desc">Longest Red Duration</option>
          <option value="vms-desc">Most Affected VMs</option>
          <option value="newest-desc">Newest Alert</option>
        </select>
      </div>
      <div class="filter-group">
        <label class="filter-label">Trend</label>
        <select id="filter-trend" class="filter-select" onchange="onFilterChange()">
          <option value="all">All Trends</option>
          ${Object.entries(TREND_LABELS).map(([val, label]) => `<option value="${val}" ${dashFilters.trendState === val ? "selected" : ""}>${label}</option>`).join("")}
        </select>
      </div>
      <div class="filter-group">
        <label class="filter-label">Min Score</label>
        <input
          type="number" id="filter-min-score" class="filter-input" style="width:70px"
          min="0" max="100" value="${dashFilters.minChangeScore}"
          oninput="onFilterChange()"
        />
      </div>
      <div class="filter-group filter-group-checks">
        <label class="filter-check"><input type="checkbox" id="filter-persistent" onchange="onFilterChange()" ${dashFilters.persistentOnly ? "checked" : ""}/> Persistent</label>
        <label class="filter-check"><input type="checkbox" id="filter-flapping" onchange="onFilterChange()" ${dashFilters.flappingOnly ? "checked" : ""}/> Flapping</label>
        <label class="filter-check"><input type="checkbox" id="filter-multivm" onchange="onFilterChange()" ${dashFilters.multiVmOnly ? "checked" : ""}/> Multi-VM</label>
      </div>
      <button class="btn btn-ghost btn-sm" onclick="clearFilters()">Clear Filters</button>
    </div>
  `;
}

function onFilterChange() {
  dashFilters.search = document.getElementById("filter-search")?.value || "";
  dashFilters.status = document.getElementById("filter-status")?.value || "all";
  dashFilters.severity = document.getElementById("filter-severity")?.value || "all";
  dashFilters.owner = document.getElementById("filter-owner")?.value || "all";
  dashFilters.sort = document.getElementById("filter-sort")?.value || "none";
  dashFilters.trendState = document.getElementById("filter-trend")?.value || "all";
  dashFilters.minChangeScore = Number(document.getElementById("filter-min-score")?.value) || 0;
  dashFilters.persistentOnly = !!document.getElementById("filter-persistent")?.checked;
  dashFilters.flappingOnly = !!document.getElementById("filter-flapping")?.checked;
  dashFilters.multiVmOnly = !!document.getElementById("filter-multivm")?.checked;
  renderAllSections();
}

function clearFilters() {
  dashFilters = {
    search: "", status: "all", severity: "all", owner: "all", sort: "none",
    trendState: "all", minChangeScore: 0, persistentOnly: false, flappingOnly: false, multiVmOnly: false,
  };
  renderFilterBar();
  renderAllSections();
}

// ─── Filter / Sort helpers ────────────────────────────────────────────────────
function matchesSearch(alert) {
  if (!dashFilters.search) return true;
  const q = dashFilters.search.toLowerCase();
  return (
    alert.hostname?.toLowerCase().includes(q) ||
    alert.errorType?.toLowerCase().includes(q) ||
    alert.logFile?.toLowerCase().includes(q)
  );
}

function matchesOwner(alert) {
  if (dashFilters.owner === "all") return true;
  return alert.owner === dashFilters.owner;
}

function matchesSeverity(alert) {
  if (dashFilters.severity === "all") return true;
  return alert.severity === dashFilters.severity;
}

function matchesTrendState(alert) {
  if (dashFilters.trendState === "all") return true;
  return alert.trendState === dashFilters.trendState;
}

function matchesMinChangeScore(alert) {
  if (!dashFilters.minChangeScore) return true;
  return (alert.changeScore ?? -1) >= dashFilters.minChangeScore;
}

function matchesPersistentOnly(alert) {
  if (!dashFilters.persistentOnly) return true;
  return alert.trendState === "persistent";
}

function matchesFlappingOnly(alert) {
  if (!dashFilters.flappingOnly) return true;
  return !!alert.isFlapping;
}

function matchesMultiVmOnly(alert) {
  if (!dashFilters.multiVmOnly) return true;
  return (alert.affectedVmCount || 0) > 1;
}

function applySortAndFilter(list) {
  let result = list.filter((a) =>
    matchesSearch(a) && matchesOwner(a) && matchesSeverity(a) &&
    matchesTrendState(a) && matchesMinChangeScore(a) &&
    matchesPersistentOnly(a) && matchesFlappingOnly(a) && matchesMultiVmOnly(a)
  );
  if (dashFilters.sort === "count-desc") result.sort((a, b) => (b.currentCount ?? b.count ?? 0) - (a.currentCount ?? a.count ?? 0));
  if (dashFilters.sort === "growth-desc") result.sort((a, b) => (b.growth ?? 0) - (a.growth ?? 0));
  if (dashFilters.sort === "change-score-desc") result.sort((a, b) => (b.changeScore ?? -1) - (a.changeScore ?? -1));
  if (dashFilters.sort === "prev-scan-desc") result.sort((a, b) => (b.absoluteChange ?? -Infinity) - (a.absoluteChange ?? -Infinity));
  if (dashFilters.sort === "1h-desc") result.sort((a, b) => (b.change1h ?? -Infinity) - (a.change1h ?? -Infinity));
  if (dashFilters.sort === "rate-desc") result.sort((a, b) => (b.growthRatePerHour ?? -Infinity) - (a.growthRatePerHour ?? -Infinity));
  if (dashFilters.sort === "red-duration-desc") result.sort((a, b) => (b.redDurationSeconds ?? -1) - (a.redDurationSeconds ?? -1));
  if (dashFilters.sort === "vms-desc") result.sort((a, b) => (b.affectedVmCount ?? 0) - (a.affectedVmCount ?? 0));
  if (dashFilters.sort === "newest-desc") result.sort((a, b) => new Date(b.firstSeen || 0) - new Date(a.firstSeen || 0));
  return result;
}

// ─── All Sections ─────────────────────────────────────────────────────────────
function renderAllSections() {
  const showAll = dashFilters.status === "all";
  const setDisplay = (id, visible) => {
    const el = document.getElementById(id);
    if (el) el.style.display = visible ? "" : "none";
  };

  setDisplay("section-new", showAll || dashFilters.status === "new");
  setDisplay("section-known", showAll || dashFilters.status === "known");
  setDisplay("section-worsening", showAll || dashFilters.status === "worsening");
  setDisplay("section-resolved", showAll || dashFilters.status === "resolved");

  renderNewSection();
  renderKnownSection();
  renderWorseningSection();
  renderResolvedSection();
  renderSuppressedSection();
  renderNoiseSection();

  // Update section count badges after each render
  const el = (id) => document.getElementById(id);
  if (el("count-new")) el("count-new").textContent = applySortAndFilter(STORE.newAlerts).length;
  if (el("count-known")) el("count-known").textContent = applySortAndFilter(STORE.knownAlerts).length;
  if (el("count-worsening")) el("count-worsening").textContent = applySortAndFilter(STORE.worseningAlerts).length;
  if (el("count-resolved")) el("count-resolved").textContent = applySortAndFilter(STORE.resolvedAlerts).length;
}

// ─── Section: New / Unknown ───────────────────────────────────────────────────
function renderNewSection() {
  const data = applySortAndFilter(STORE.newAlerts);
  const tbody = document.getElementById("tbody-new");
  if (!tbody) return;

  tbody.innerHTML = data.length === 0
    ? `<tr><td colspan="9" class="no-results">No new issues match current filters.</td></tr>`
    : data.map((a) => newAlertRow(a)).join("");
}

function newAlertRow(a) {
  const fp = buildFingerprint(a);
  const isExpanded = expandedRows.has(a.id);
  return `
    <tr class="alert-row alert-row-new" id="row-${a.id}">
      <td><span class="status-badge status-new">NEW</span></td>
      <td class="mono">${a.hostname}</td>
      <td class="mono text-muted">${a.rawFilename || a.logFile}</td>
      <td><span class="error-type">${a.errorType}</span></td>
      <td class="text-red font-bold">${a.count}</td>
      <td class="text-red font-bold">+${a.growth}</td>
      <td class="${(a.percentageChange ?? 0) > 0 ? "text-red" : "text-muted"} font-bold">${fmtPct(a.percentageChange)}</td>
      <td class="suggested-action">${a.suggestedAction}</td>
      <td><div class="action-btns">
        <button class="btn btn-xs btn-info" onclick="markKnownFromRow('${a.id}')">Mark Known</button>
        <button class="btn btn-xs btn-warning" onclick="linkTicketToRow('${a.id}')">Ticket</button>
        <button class="btn btn-xs btn-expand" onclick="toggleRow('${a.id}')">${isExpanded ? "▲ Less" : "▼ Details"}</button>
      </div></td>
    </tr>
    ${isExpanded ? expandedRowNew(a, fp) : ""}
  `;
}

function expandedRowNew(a, fp) {
  return `
    <tr class="expand-row">
      <td colspan="9">
        <div class="expand-panel">
          <div class="expand-grid">
            <div class="expand-block">
              <div class="expand-section-label">Alert Details</div>
              <div class="kv"><span class="k">Hostname</span><span class="v mono">${a.hostname}</span></div>
              <div class="kv"><span class="k">Log File</span><span class="v mono">${a.rawFilename || a.logFile}</span></div>
              <div class="kv"><span class="k">Error Type</span><span class="v">${a.errorType}</span></div>
              <div class="kv"><span class="k">Count</span><span class="v text-red">${a.count}</span></div>
              <div class="kv"><span class="k">Growth</span><span class="v text-red">+${a.growth}</span></div>
            </div>
            <div class="expand-block">
              <div class="expand-section-label">Classification</div>
              <div class="kv"><span class="k">Fingerprint</span><span class="v fp-chip">${fp}</span></div>
              <div class="kv"><span class="k">Suggested Action</span><span class="v">${a.suggestedAction}</span></div>
              <div class="kv"><span class="k">Ticket</span><span class="v">${renderTicketField(a)}</span></div>
            </div>
            ${trendDetailBlock(a)}
            <div class="expand-block expand-block-notes">
              <div class="expand-section-label">Notes</div>
              <textarea id="notes-${a.id}" class="notes-input" placeholder="Add investigation notes…">${a.notes || ""}</textarea>
              <button class="btn btn-xs btn-ghost mt-4" onclick="saveNoteFromRow('${a.id}')">Save Note</button>
            </div>
          </div>
        </div>
      </td>
    </tr>
  `;
}

// ─── Section: Known Issues ────────────────────────────────────────────────────
function renderKnownSection() {
  const data = applySortAndFilter(STORE.knownAlerts);
  const tbody = document.getElementById("tbody-known");
  if (!tbody) return;

  tbody.innerHTML = data.length === 0
    ? `<tr><td colspan="9" class="no-results">No known issues match current filters.</td></tr>`
    : data.map((a) => knownAlertRow(a)).join("");
}

function knownAlertRow(a) {
  const fp = buildFingerprint(a);
  const isExpanded = expandedRows.has(a.id);
  return `
    <tr class="alert-row alert-row-known" id="row-${a.id}">
      <td><span class="status-badge status-known">KNOWN</span></td>
      <td class="mono">${a.hostname}</td>
      <td class="mono text-muted">${a.rawFilename || a.logFile}</td>
      <td><span class="error-type">${a.errorType}</span></td>
      <td class="font-bold">${a.count}</td>
      <td class="${a.growth > 100 ? "text-orange" : "text-muted"}">+${a.growth}</td>
      <td class="${(a.percentageChange ?? 0) > 0 ? "text-orange" : "text-muted"}">${fmtPct(a.percentageChange)}</td>
      <td>${a.ticketLink ? `<a href="${a.ticketLink}" class="link" onclick="linkTicketToRow('${a.id}');return false;">${a.ticketLink.replace("#ticket-", "")}</a>` : `<a href="#" class="link text-muted" onclick="linkTicketToRow('${a.id}');return false;">Add</a>`}</td>
      <td><div class="action-btns">
        <button class="btn btn-xs btn-ghost" onclick="linkTicketToRow('${a.id}')">Ticket</button>
        <button class="btn btn-xs btn-ghost" onclick="showToast('Add Note (placeholder)')">Note</button>
        <button class="btn btn-xs btn-danger-ghost" onclick="unmarkKnownFromRow('${a.id}')">Unmark</button>
        <button class="btn btn-xs btn-expand" onclick="toggleRow('${a.id}')">${isExpanded ? "▲ Less" : "▼ Details"}</button>
      </div></td>
    </tr>
    ${isExpanded ? expandedRowKnown(a, fp) : ""}
  `;
}

function expandedRowKnown(a, fp) {
  const ki = STORE.knownIssuesCatalog.find((k) => k.id === a.knownIssueId);
  return `
    <tr class="expand-row">
      <td colspan="9">
        <div class="expand-panel">
          <div class="expand-grid">
            <div class="expand-block">
              <div class="expand-section-label">Alert Details</div>
              <div class="kv"><span class="k">Hostname</span><span class="v mono">${a.hostname}</span></div>
              <div class="kv"><span class="k">Log File</span><span class="v mono">${a.rawFilename || a.logFile}</span></div>
              <div class="kv"><span class="k">Error Type</span><span class="v">${a.errorType}</span></div>
              <div class="kv"><span class="k">Count</span><span class="v">${a.count}</span></div>
              <div class="kv"><span class="k">Growth</span><span class="v ${a.growth > 100 ? "text-orange" : "text-muted"}">+${a.growth}</span></div>
            </div>
            <div class="expand-block">
              <div class="expand-section-label">Classification</div>
              <div class="kv"><span class="k">ID</span><span class="v"><span class="ki-badge">${a.knownIssueId}</span></span></div>
              <div class="kv"><span class="k">Fingerprint</span><span class="v fp-chip">${fp}</span></div>
              ${ki ? `<div class="kv"><span class="k">Cause</span><span class="v">${ki.cause}</span></div>` : ""}
              ${ki ? `<div class="kv"><span class="k">Next Step</span><span class="v">${ki.resolutionSteps.split("\n")[0]}</span></div>` : ""}
              <div class="kv"><span class="k">Ticket</span><span class="v">${renderTicketField(a)}</span></div>
            </div>
            ${trendDetailBlock(a)}
            <div class="expand-block expand-block-notes">
              <div class="expand-section-label">Notes</div>
              <textarea id="notes-${a.id}" class="notes-input" placeholder="Add notes…">${a.notes || ""}</textarea>
              <button class="btn btn-xs btn-ghost mt-4" onclick="saveNoteFromRow('${a.id}')">Save Note</button>
            </div>
          </div>
        </div>
      </td>
    </tr>
  `;
}

// ─── Section: Worsening ───────────────────────────────────────────────────────
function renderWorseningSection() {
  const data = applySortAndFilter(STORE.worseningAlerts);
  const tbody = document.getElementById("tbody-worsening");
  if (!tbody) return;

  tbody.innerHTML = data.length === 0
    ? `<tr><td colspan="9" class="no-results">No worsening issues match current filters.</td></tr>`
    : data.map((a) => worseningAlertRow(a)).join("");
}

function worseningAlertRow(a) {
  const fp = buildFingerprint(a);
  const isExpanded = expandedRows.has(a.id);
  const severity = (a.severity || "medium").toLowerCase();
  const sevClass = { critical: "sev-critical", high: "sev-high", medium: "sev-medium", low: "sev-low" }[severity] || "sev-medium";
  return `
    <tr class="alert-row alert-row-worsening" id="row-${a.id}">
      <td><span class="status-badge status-worsening">WORSENING</span></td>
      <td class="mono">${a.hostname}</td>
      <td class="mono text-muted">${a.rawFilename || a.logFile}</td>
      <td><span class="error-type">${a.errorType}</span></td>
      <td class="text-muted">${a.normalRange ?? "—"}</td>
      <td class="text-red font-bold">${a.currentCount}</td>
      <td class="text-red font-bold">+${a.growth}</td>
      <td class="${(a.percentageChange ?? 0) > 0 ? "text-red" : "text-muted"} font-bold">${fmtPct(a.percentageChange)}</td>
      <td><div class="action-btns">
        <button class="btn btn-xs btn-warning" onclick="linkTicketToRow('${a.id}')">Ticket</button>
        <button class="btn btn-xs btn-ghost" onclick="showToast('Add Note (placeholder)')">Note</button>
        <button class="btn btn-xs btn-danger-ghost" onclick="unmarkKnownFromRow('${a.id}')">Unmark</button>
        <button class="btn btn-xs btn-expand" onclick="toggleRow('${a.id}')">${isExpanded ? "▲ Less" : "▼ Details"}</button>
      </div></td>
    </tr>
    ${isExpanded ? expandedRowWorsening(a, fp) : ""}
  `;
}

function expandedRowWorsening(a, fp) {
  return `
    <tr class="expand-row">
      <td colspan="9">
        <div class="expand-panel">
          <div class="expand-grid">
            <div class="expand-block">
              <div class="expand-section-label">Alert Details</div>
              <div class="kv"><span class="k">Hostname</span><span class="v mono">${a.hostname}</span></div>
              <div class="kv"><span class="k">Log File</span><span class="v mono">${a.rawFilename || a.logFile}</span></div>
              <div class="kv"><span class="k">Error Type</span><span class="v">${a.errorType}</span></div>
              <div class="kv"><span class="k">Normal Range</span><span class="v">${a.normalRange}</span></div>
              <div class="kv"><span class="k">Current Count</span><span class="v text-red font-bold">${a.currentCount}</span></div>
              <div class="kv"><span class="k">Growth</span><span class="v text-red font-bold">+${a.growth}</span></div>
              <div class="kv"><span class="k">Severity</span><span class="v">${a.severity}</span></div>
            </div>
            <div class="expand-block">
              <div class="expand-section-label">Classification</div>
              <div class="kv"><span class="k">Fingerprint</span><span class="v fp-chip">${fp}</span></div>
              <div class="kv"><span class="k">Escalation Rule</span><span class="v text-orange">${a.escalationRule}</span></div>
              <div class="kv"><span class="k">Ticket</span><span class="v">${renderTicketField(a)}</span></div>
            </div>
            ${trendDetailBlock(a)}
            <div class="expand-block expand-block-notes">
              <div class="expand-section-label">Notes</div>
              <textarea id="notes-${a.id}" class="notes-input" placeholder="Add incident notes…">${a.notes || ""}</textarea>
              <button class="btn btn-xs btn-ghost mt-4" onclick="saveNoteFromRow('${a.id}')">Save Note</button>
            </div>
          </div>
        </div>
      </td>
    </tr>
  `;
}

// ─── Section: Resolved ────────────────────────────────────────────────────────
function renderResolvedSection() {
  const data = applySortAndFilter(STORE.resolvedAlerts);
  const tbody = document.getElementById("tbody-resolved");
  if (!tbody) return;

  tbody.innerHTML = data.length === 0
    ? `<tr><td colspan="9" class="no-results">No resolved issues match current filters.</td></tr>`
    : data.map((a) => resolvedAlertRow(a)).join("");
}

function resolvedAlertRow(a) {
  const fp = buildFingerprint(a);
  const isExpanded = expandedRows.has(a.id);
  return `
    <tr class="alert-row alert-row-resolved" id="row-${a.id}">
      <td><span class="status-badge status-resolved">RESOLVED</span></td>
      <td><span class="error-type">${a.errorType}</span></td>
      <td class="mono">${a.hostname}</td>
      <td class="mono text-muted">${a.rawFilename || a.logFile}</td>
      <td class="text-muted">${a.previousCount}</td>
      <td class="text-muted">${a.lastSeen}</td>
      <td>${a.resolutionNotes}</td>
      <td class="text-muted">${a.knownIssueId ? `<span class="ki-badge">${a.knownIssueId}</span>` : "—"}</td>
      <td><div class="action-btns">
        <button class="btn btn-xs btn-warning" onclick="reopenAlert('${a.id}')">Reopen</button>
        <button class="btn btn-xs btn-ghost" onclick="showToast('Archive (placeholder)')">Archive</button>
        <button class="btn btn-xs btn-expand" onclick="toggleRow('${a.id}')">${isExpanded ? "▲ Less" : "▼ Details"}</button>
      </div></td>
    </tr>
    ${isExpanded ? expandedRowResolved(a, fp) : ""}
  `;
}

function expandedRowResolved(a, fp) {
  return `
    <tr class="expand-row">
      <td colspan="9">
        <div class="expand-panel">
          <div class="expand-grid">
            <div class="expand-block">
              <div class="expand-section-label">Alert Details</div>
              <div class="kv"><span class="k">Hostname</span><span class="v mono">${a.hostname}</span></div>
              <div class="kv"><span class="k">Log File</span><span class="v mono">${a.rawFilename || a.logFile}</span></div>
              <div class="kv"><span class="k">Error Type</span><span class="v">${a.errorType}</span></div>
              <div class="kv"><span class="k">Previous Count</span><span class="v">${a.previousCount}</span></div>
            </div>
            <div class="expand-block">
              <div class="expand-section-label">Classification</div>
              <div class="kv"><span class="k">Fingerprint</span><span class="v fp-chip">${fp}</span></div>
              <div class="kv"><span class="k">Resolution Notes</span><span class="v">${a.resolutionNotes}</span></div>
              <div class="kv"><span class="k">Ticket</span><span class="v">${renderTicketField(a)}</span></div>
            </div>
            <div class="expand-block expand-block-notes">
              <div class="expand-section-label">Notes</div>
              <textarea class="notes-input" placeholder="Additional notes…"></textarea>
              <button class="btn btn-xs btn-ghost mt-4" onclick="showToast('Note saved (placeholder)')">Save Note</button>
            </div>
          </div>
        </div>
      </td>
    </tr>
  `;
}

// ─── Sections: Suppressed / Noise (muted audit view) ──────────────────────────
// These rows are retained, never deleted — signal_type only controls where they
// show up in the UI. Collapsed by default since they're a secondary/audit view,
// not the primary triage workflow.
const auditSectionsExpanded = { suppressed: false, noise: false };

function toggleAuditSection(key) {
  auditSectionsExpanded[key] = !auditSectionsExpanded[key];
  const body = document.getElementById(`body-${key}`);
  if (body) body.style.display = auditSectionsExpanded[key] ? "" : "none";
  const caret = document.getElementById(`caret-${key}`);
  if (caret) caret.textContent = auditSectionsExpanded[key] ? "▲" : "▼";
}

function auditAlertRow(a, signalLabel) {
  const fp = buildFingerprint(a);
  const isExpanded = expandedRows.has(a.id);
  return `
    <tr class="alert-row alert-row-muted" id="row-${a.id}">
      <td><span class="status-badge status-${a.signalType}">${signalLabel}</span></td>
      <td class="mono text-muted">${a.hostname}</td>
      <td class="mono text-muted">${a.rawFilename || a.logFile}</td>
      <td class="text-muted">${a.errorType}</td>
      <td class="text-muted">${a.color ?? "—"}</td>
      <td class="text-muted">${a.knownError ? "Yes" : "No"}</td>
      <td class="text-muted">${a.count}</td>
      <td class="text-muted">${a.growth >= 0 ? "+" + a.growth : a.growth}</td>
      <td><div class="action-btns">
        <button class="btn btn-xs btn-ghost" onclick="linkTicketToRow('${a.id}')">Ticket</button>
        <button class="btn btn-xs btn-expand" onclick="toggleRow('${a.id}')">${isExpanded ? "▲ Less" : "▼ Details"}</button>
      </div></td>
    </tr>
    ${isExpanded ? expandedRowAudit(a, fp) : ""}
  `;
}

function expandedRowAudit(a, fp) {
  return `
    <tr class="expand-row">
      <td colspan="9">
        <div class="expand-panel">
          <div class="expand-grid">
            <div class="expand-block">
              <div class="expand-section-label">Alert Details</div>
              <div class="kv"><span class="k">Hostname</span><span class="v mono">${a.hostname}</span></div>
              <div class="kv"><span class="k">Log File</span><span class="v mono">${a.rawFilename || a.logFile}</span></div>
              <div class="kv"><span class="k">Error Type</span><span class="v">${a.errorType}</span></div>
              <div class="kv"><span class="k">Count</span><span class="v">${a.count}</span></div>
              <div class="kv"><span class="k">Growth</span><span class="v">${a.growth}</span></div>
            </div>
            <div class="expand-block">
              <div class="expand-section-label">Classification</div>
              <div class="kv"><span class="k">Signal Type</span><span class="v">${a.signalType}</span></div>
              <div class="kv"><span class="k">Color</span><span class="v">${a.color ?? "—"}</span></div>
              <div class="kv"><span class="k">Known Error</span><span class="v">${a.knownError ? "Yes" : "No"}</span></div>
              <div class="kv"><span class="k">Fingerprint</span><span class="v fp-chip">${fp}</span></div>
              <div class="kv"><span class="k">Ticket</span><span class="v">${renderTicketField(a)}</span></div>
            </div>
            <div class="expand-block expand-block-notes">
              <div class="expand-section-label">Notes</div>
              <textarea id="notes-${a.id}" class="notes-input" placeholder="Add notes…">${a.notes || ""}</textarea>
              <button class="btn btn-xs btn-ghost mt-4" onclick="saveNoteFromRow('${a.id}')">Save Note</button>
            </div>
          </div>
        </div>
      </td>
    </tr>
  `;
}

function renderSuppressedSection() {
  const tbody = document.getElementById("tbody-suppressed");
  if (!tbody) return;
  const data = STORE.suppressedAlerts || [];
  tbody.innerHTML = data.length === 0
    ? `<tr><td colspan="9" class="no-results">No suppressed rows.</td></tr>`
    : data.map((a) => auditAlertRow(a, "SUPPRESSED")).join("");
  const countEl = document.getElementById("count-suppressed");
  if (countEl) countEl.textContent = data.length;
}

function renderNoiseSection() {
  const tbody = document.getElementById("tbody-noise");
  if (!tbody) return;
  const data = STORE.noiseAlerts || [];
  tbody.innerHTML = data.length === 0
    ? `<tr><td colspan="9" class="no-results">No noise rows.</td></tr>`
    : data.map((a) => auditAlertRow(a, "NOISE")).join("");
  const countEl = document.getElementById("count-noise");
  if (countEl) countEl.textContent = data.length;
}

// ─── Row Toggle ───────────────────────────────────────────────────────────────
function toggleRow(id) {
  if (expandedRows.has(id)) {
    expandedRows.delete(id);
  } else {
    expandedRows.add(id);
  }
  renderAllSections();
  // Scroll the row into view after re-render
  setTimeout(() => {
    document.getElementById(`row-${id}`)?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, 50);
}
