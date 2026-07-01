function renderPromStatusCard() {
  const status = STORE.promStatus;
  const el = document.getElementById("prom-status-card");
  if (!el) return;

  if (!status) {
    el.innerHTML = `
      <div class="prom-status-card empty">
        <div class="prom-status-label">Prometheus .prom source</div>
        <div class="prom-status-value">No status available</div>
      </div>
    `;
    return;
  }

  el.innerHTML = `
    <div class="prom-status-card">
      <div class="prom-status-row">
        <div><strong>Data Source</strong></div>
        <div>Prometheus .prom file</div>
      </div>
      <div class="prom-status-row">
        <div>File path</div>
        <div class="mono">${status.configured_file_path}</div>
      </div>
      <div class="prom-status-row">
        <div>Latest snapshot</div>
        <div>${status.latest_snapshot_id || "—"}</div>
      </div>
      <div class="prom-status-row">
        <div>Latest batch</div>
        <div>${status.latest_batch_id || "—"}</div>
      </div>
      <div class="prom-status-row">
        <div>Total metrics</div>
        <div>${status.latest_total_metrics}</div>
      </div>
      <div class="prom-status-row">
        <div>Last processed</div>
        <div>${status.latest_processed_at || "—"}</div>
      </div>
      <div class="prom-status-row">
        <div>Watcher</div>
        <div>${status.watcher_enabled ? `Enabled (${status.poll_seconds}s)` : "Disabled"}</div>
      </div>
      <div class="prom-status-actions">
        <button class="btn btn-secondary" onclick="processPromNow()">Process .prom Now</button>
        <button class="btn btn-secondary" onclick="refreshData()">Refresh Dashboard</button>
      </div>
    </div>
  `;
}
