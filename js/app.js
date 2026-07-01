/**
 * app.js
 * ─────────────────────────────────────────────────────────────────────────────
 * Entry point. Loads data from the backend API on startup, then renders.
 * Falls back to the JS mock data if the API is unreachable.
 */

let currentView = "dashboard";

// ─── View routing ─────────────────────────────────────────────────────────────
function switchView(view) {
  currentView = view;

  document.getElementById("view-dashboard").style.display =
    view === "dashboard" ? "" : "none";
  document.getElementById("view-known-issues").style.display =
    view === "known-issues" ? "" : "none";

  document.querySelectorAll(".nav-tab").forEach((t) => t.classList.remove("active"));
  document.getElementById(`tab-${view}`)?.classList.add("active");

  if (view === "dashboard") renderDashboard();
  if (view === "known-issues") renderKnownIssuesView();
}

// ─── Toast ────────────────────────────────────────────────────────────────────
function showToast(msg) {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.classList.add("show");
  setTimeout(() => t.classList.remove("show"), 2600);
}

// ─── Loading / error UI ───────────────────────────────────────────────────────
function setLoading(on) {
  document.getElementById("loading-overlay").style.display = on ? "flex" : "none";
}

function setApiBanner(type, msg) {
  const el = document.getElementById("api-banner");
  if (!msg) {
    el.style.display = "none";
    return;
  }
  el.className = `api-banner api-banner-${type}`;
  el.innerHTML = msg;
  el.style.display = "block";
}

// ─── Data loading ─────────────────────────────────────────────────────────────
async function loadData() {
  setLoading(true);
  setApiBanner(null, null);

  try {
    // Fetch in parallel — all the dashboard data plus prom status + inventory.
    const [batch, alerts, knownIssues, promStatus, promFiles] = await Promise.all([
      getLatestBatch(),
      getAlerts(),
      getKnownIssues(),
      getPromStatus(),
      getPromFiles().catch(() => null),
    ]);

    populateStoreFromApi(batch, alerts, knownIssues);
    populatePromStatus(promStatus);
    populatePromFiles(promFiles);
    setApiBanner(null, null);

  } catch (err) {
    // API unreachable — fall back to the bundled JS mock data so the page
    // remains functional while the backend is starting up or not yet deployed.
    populateStoreFromMock();
    setApiBanner(
      "warn",
      `<strong>⚠ API unavailable</strong> — showing mock data. ` +
      `Start the backend with: <code>python3 -m uvicorn backend.main:app --reload --port 9000</code> ` +
      `then <a href="javascript:location.reload()">reload this page</a>.`
    );
    console.warn("Scanfor API unreachable, using mock fallback.", err);

  } finally {
    setLoading(false);
    switchView("dashboard");
  }
}

// ─── Refresh handler (wired to "Refresh Data" button) ─────────────────────────
async function refreshData() {
  await loadData();
  showToast("Data refreshed.");
}

// ─── Prom processing ─────────────────────────────────────────────────────────
async function processPromNow() {
  setLoading(true);
  setApiBanner(null, null);
  try {
    const result = await processPromFile();
    if (result.status === "skipped") {
      setApiBanner("info", "No new .prom folder changes detected.");
    } else {
      setApiBanner(
        "success",
        `Processed ${result.total_files ?? 0} .prom file(s) — ${result.created_alert_events ?? 0} alerts, ${result.resolved_alert_events ?? 0} resolved.`,
      );
    }
  } catch (err) {
    setApiBanner("error", `Unable to process .prom folder. ${err.message}`);
  } finally {
    await loadData();
    setLoading(false);
  }
}

// ─── Init ─────────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  initTheme();
  loadData();
});
