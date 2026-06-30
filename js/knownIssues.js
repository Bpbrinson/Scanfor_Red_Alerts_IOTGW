/**
 * knownIssues.js
 * ─────────────────────────────────────────────────────────────────────────────
 * Renders the Known Issues catalog view.
 * Depends on: mockKnownIssues.js (must be loaded first).
 */

let kiFilters = { search: "", severity: "all", status: "all", owner: "all" };

// ─── Entry Point ──────────────────────────────────────────────────────────────
function renderKnownIssuesView() {
  renderKIToolbar();
  renderKITable();
}

// ─── Toolbar ──────────────────────────────────────────────────────────────────
function renderKIToolbar() {
  const el = document.getElementById("ki-toolbar");
  if (!el) return;
  el.innerHTML = `
    <div class="filter-row">
      <div class="filter-group">
        <input
          type="text"
          id="ki-search"
          class="filter-input"
          placeholder="Search ID, error type, host scope…"
          value="${kiFilters.search}"
          oninput="onKIFilterChange()"
        />
      </div>
      <div class="filter-group">
        <label class="filter-label">Severity</label>
        <select id="ki-severity" class="filter-select" onchange="onKIFilterChange()">
          <option value="all">All Severities</option>
          <option value="critical">Critical</option>
          <option value="high">High</option>
          <option value="medium">Medium</option>
          <option value="low">Low</option>
        </select>
      </div>
      <div class="filter-group">
        <label class="filter-label">Status</label>
        <select id="ki-status" class="filter-select" onchange="onKIFilterChange()">
          <option value="all">All Statuses</option>
          <option value="active">Active</option>
          <option value="monitoring">Monitoring</option>
          <option value="archived">Archived</option>
        </select>
      </div>
      <div class="filter-group">
        <label class="filter-label">Owner</label>
        <select id="ki-owner" class="filter-select" onchange="onKIFilterChange()">
          <option value="all">All Owners</option>
          <option value="network-team">network-team</option>
          <option value="app-team">app-team</option>
          <option value="infra-team">infra-team</option>
          <option value="integrations-team">integrations-team</option>
          <option value="security-team">security-team</option>
        </select>
      </div>
      <button class="btn btn-ghost btn-sm" onclick="clearKIFilters()">Clear</button>
      <button class="btn btn-primary btn-sm ml-auto" onclick="showToast('Add Known Issue (placeholder)')">+ Add Known Issue</button>
    </div>
  `;
}

function onKIFilterChange() {
  kiFilters.search = document.getElementById("ki-search")?.value || "";
  kiFilters.severity = document.getElementById("ki-severity")?.value || "all";
  kiFilters.status = document.getElementById("ki-status")?.value || "all";
  kiFilters.owner = document.getElementById("ki-owner")?.value || "all";
  renderKITable();
}

function clearKIFilters() {
  kiFilters = { search: "", severity: "all", status: "all", owner: "all" };
  renderKIToolbar();
  renderKITable();
}

// ─── Table ────────────────────────────────────────────────────────────────────
function renderKITable() {
  const tbody = document.getElementById("tbody-ki");
  if (!tbody) return;

  const data = STORE.knownIssuesCatalog.filter((ki) => {
    if (kiFilters.search) {
      const q = kiFilters.search.toLowerCase();
      if (
        !ki.id.toLowerCase().includes(q) &&
        !ki.errorType.toLowerCase().includes(q) &&
        !ki.hostScope.toLowerCase().includes(q) &&
        !ki.fingerprint.toLowerCase().includes(q)
      )
        return false;
    }
    if (kiFilters.severity !== "all" && ki.severity !== kiFilters.severity) return false;
    if (kiFilters.status !== "all" && ki.status !== kiFilters.status) return false;
    if (kiFilters.owner !== "all" && ki.owner !== kiFilters.owner) return false;
    return true;
  });

  if (data.length === 0) {
    tbody.innerHTML = `<tr><td colspan="14" class="no-results">No known issues match current filters.</td></tr>`;
    return;
  }

  tbody.innerHTML = data.map((ki) => kiRow(ki)).join("");
}

function kiRow(ki) {
  const sevClass = { critical: "sev-critical", high: "sev-high", medium: "sev-medium", low: "sev-low" }[ki.severity] || "";
  const statusClass = { active: "status-known", monitoring: "status-worsening", archived: "status-resolved" }[ki.status] || "";
  return `
    <tr class="alert-row">
      <td><span class="ki-badge">${ki.id}</span></td>
      <td><span class="fp-chip fp-chip-sm">${ki.fingerprint}</span></td>
      <td><span class="error-type">${ki.errorType}</span></td>
      <td class="mono text-muted small">${ki.hostScope}</td>
      <td class="mono text-muted small">${ki.logScope}</td>
      <td><span class="sev-badge ${sevClass}">${ki.severity.toUpperCase()}</span></td>
      <td class="text-muted">${ki.owner}</td>
      <td><span class="status-badge ${statusClass}">${ki.status.toUpperCase()}</span></td>
      <td class="text-muted">${ki.normalCountRange}</td>
      <td class="small text-muted ellipsis" title="${ki.cause}">${ki.cause}</td>
      <td class="small text-muted">${ki.lastReviewed}</td>
      <td class="action-btns">
        <button class="btn btn-xs btn-info" onclick="showKIDetail('${ki.id}')">View</button>
        <button class="btn btn-xs btn-ghost" onclick="showToast('Edit (placeholder)')">Edit</button>
        <button class="btn btn-xs btn-ghost" onclick="showToast('Review (placeholder)')">Review</button>
        ${ki.runbookLink ? `<button class="btn btn-xs btn-secondary" onclick="showToast('Runbook (placeholder)')">Runbook</button>` : ""}
        <button class="btn btn-xs btn-danger-ghost" onclick="showToast('Archive (placeholder)')">Archive</button>
      </td>
    </tr>
  `;
}

// ─── Detail Modal ─────────────────────────────────────────────────────────────
function showKIDetail(id) {
  const ki = STORE.knownIssuesCatalog.find((k) => k.id === id);
  if (!ki) return;

  const sevClass = { critical: "sev-critical", high: "sev-high", medium: "sev-medium", low: "sev-low" }[ki.severity] || "";
  const steps = ki.resolutionSteps
    .split("\n")
    .map((s) => `<li>${s.replace(/^\d+\.\s*/, "")}</li>`)
    .join("");

  document.getElementById("modal-body").innerHTML = `
    <div class="modal-ki-header">
      <span class="ki-badge ki-badge-lg">${ki.id}</span>
      <span class="sev-badge ${sevClass}">${ki.severity.toUpperCase()}</span>
      <span class="text-muted ml-4">Owner: ${ki.owner}</span>
      <span class="text-muted ml-4">Last Reviewed: ${ki.lastReviewed}</span>
    </div>
    <div class="expand-grid mt-4">
      <div class="expand-block">
        <div class="expand-section-label">Identity</div>
        <div class="kv"><span class="k">Error Type</span><span class="v">${ki.errorType}</span></div>
        <div class="kv"><span class="k">Host Scope</span><span class="v mono">${ki.hostScope}</span></div>
        <div class="kv"><span class="k">Log Scope</span><span class="v mono">${ki.logScope}</span></div>
        <div class="kv"><span class="k">Fingerprint</span><span class="v fp-chip">${ki.fingerprint}</span></div>
        <div class="kv"><span class="k">Normal Range</span><span class="v">${ki.normalCountRange}</span></div>
        <div class="kv"><span class="k">Status</span><span class="v">${ki.status}</span></div>
      </div>
      <div class="expand-block">
        <div class="expand-section-label">Cause &amp; Impact</div>
        <p class="small mt-4">${ki.cause}</p>
        <div class="expand-section-label mt-4">Impact</div>
        <p class="small mt-4">${ki.impact}</p>
      </div>
    </div>
    <div class="expand-block mt-4">
      <div class="expand-section-label">Resolution Steps</div>
      <ol class="resolution-steps">${steps}</ol>
    </div>
    <div class="modal-ki-footer mt-4">
      ${ki.runbookLink ? `<button class="btn btn-secondary" onclick="showToast('Runbook (placeholder)')">View Runbook</button>` : ""}
      ${ki.ticketLink ? `<button class="btn btn-ghost" onclick="showToast('Ticket (placeholder)')">View Ticket</button>` : ""}
      <button class="btn btn-ghost" onclick="showToast('Edit (placeholder)')">Edit</button>
      <button class="btn btn-ghost" onclick="showToast('Review (placeholder)')">Mark Reviewed</button>
    </div>
  `;
  document.getElementById("modal-overlay").style.display = "flex";
}

function closeModal() {
  document.getElementById("modal-overlay").style.display = "none";
}
