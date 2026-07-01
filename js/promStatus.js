function _formatBytes(n) {
  if (n == null) return "—";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

function _escapeHtml(value) {
  if (value == null) return "";
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function renderPromStatusCard() {
  const el = document.getElementById("prom-status-card");
  if (!el) return;
  el.innerHTML = `
    <div class="prom-status-actions">
      <button class="btn btn-secondary" onclick="processPromNow()">Process .prom Folder Now</button>
    </div>
  `;
}

function renderPromFileList() {
  const el = document.getElementById("prom-file-list");
  if (!el) return;

  const files = STORE.promFiles?.files || [];
  if (!files.length) {
    el.innerHTML = `<div class="prom-file-empty">No .prom files found in configured path.</div>`;
    return;
  }

  const rows = files.map((f) => `
    <tr>
      <td class="mono">${_escapeHtml(f.filename)}</td>
      <td class="text-right">${f.metric_count ?? 0}</td>
      <td>${_escapeHtml(f.generated_time || "—")}</td>
      <td>${_escapeHtml(f.modified_time || "—")}</td>
      <td class="text-right">${_formatBytes(f.size_bytes)}</td>
      <td class="mono text-muted small">${_escapeHtml(f.state_file || "—")}</td>
    </tr>
  `).join("");

  el.innerHTML = `
    <table class="prom-file-table">
      <thead>
        <tr>
          <th>File</th>
          <th class="text-right">Metrics</th>
          <th>Generated</th>
          <th>Modified</th>
          <th class="text-right">Size</th>
          <th>State file</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
  `;
}

function togglePromFileList() {
  const el = document.getElementById("prom-file-list");
  if (!el) return;
  el.style.display = el.style.display === "none" ? "block" : "none";
}
