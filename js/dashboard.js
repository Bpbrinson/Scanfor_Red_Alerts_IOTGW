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
};

// Track which rows are expanded
const expandedRows = new Set();

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
    showToast(`Marked known as ${updated.known_issue_id}.`);
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
  const total = STORE.allAlerts.filter((a) => a.category !== "resolved").length;
  const newCount = STORE.newAlerts.length;
  const knownCount = STORE.knownAlerts.length;
  const worseningCount = STORE.worseningAlerts.length;
  const resolvedCount = STORE.resolvedAlerts.length;

  const allActive = STORE.allAlerts.filter((a) => a.category !== "resolved");
  const highestGrowth = allActive.length > 0
    ? allActive.reduce((max, a) => (a.growth > max.growth ? a : max), allActive[0])
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
        </select>
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
  renderAllSections();
}

function clearFilters() {
  dashFilters = { search: "", status: "all", severity: "all", owner: "all", sort: "none" };
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

function applySortAndFilter(list) {
  let result = list.filter((a) => matchesSearch(a) && matchesOwner(a) && matchesSeverity(a));
  if (dashFilters.sort === "count-desc") result.sort((a, b) => (b.currentCount ?? b.count ?? 0) - (a.currentCount ?? a.count ?? 0));
  if (dashFilters.sort === "growth-desc") result.sort((a, b) => (b.growth ?? 0) - (a.growth ?? 0));
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
    ? `<tr><td colspan="8" class="no-results">No new issues match current filters.</td></tr>`
    : data.map((a) => newAlertRow(a)).join("");
}

function newAlertRow(a) {
  const fp = buildFingerprint(a);
  const isExpanded = expandedRows.has(a.id);
  return `
    <tr class="alert-row alert-row-new" id="row-${a.id}">
      <td><span class="status-badge status-new">NEW</span></td>
      <td class="mono">${a.hostname}</td>
      <td class="mono text-muted">${a.logFile}</td>
      <td><span class="error-type">${a.errorType}</span></td>
      <td class="text-red font-bold">${a.count}</td>
      <td class="text-red font-bold">+${a.growth}</td>
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
      <td colspan="8">
        <div class="expand-panel">
          <div class="expand-grid">
            <div class="expand-block">
              <div class="expand-section-label">Alert Details</div>
              <div class="kv"><span class="k">Hostname</span><span class="v mono">${a.hostname}</span></div>
              <div class="kv"><span class="k">Log File</span><span class="v mono">${a.logFile}</span></div>
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
      <td class="mono text-muted">${a.logFile}</td>
      <td><span class="error-type">${a.errorType}</span></td>
      <td class="font-bold">${a.count}</td>
      <td class="${a.growth > 100 ? "text-orange" : "text-muted"}">+${a.growth}</td>
      <td><span class="ki-badge">${a.knownIssueId}</span></td>
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
              <div class="kv"><span class="k">Log File</span><span class="v mono">${a.logFile}</span></div>
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
    ? `<tr><td colspan="8" class="no-results">No worsening issues match current filters.</td></tr>`
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
      <td class="mono text-muted">${a.logFile}</td>
      <td><span class="error-type">${a.errorType}</span></td>
      <td class="text-muted">${a.normalRange ?? "—"}</td>
      <td class="text-red font-bold">${a.currentCount}</td>
      <td class="text-red font-bold">+${a.growth}</td>
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
      <td colspan="8">
        <div class="expand-panel">
          <div class="expand-grid">
            <div class="expand-block">
              <div class="expand-section-label">Alert Details</div>
              <div class="kv"><span class="k">Hostname</span><span class="v mono">${a.hostname}</span></div>
              <div class="kv"><span class="k">Log File</span><span class="v mono">${a.logFile}</span></div>
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
      <td class="mono text-muted">${a.logFile}</td>
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
              <div class="kv"><span class="k">Log File</span><span class="v mono">${a.logFile}</span></div>
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
