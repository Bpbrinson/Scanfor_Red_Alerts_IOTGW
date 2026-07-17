# Scanfor Red — Alert Triage Dashboard

Production-monitoring dashboard for triaging Scanfor Red email alerts.

---

## Phase 2 — Backend API + Frontend Connected

### How to Run

**Step 1 — Start the backend API**

From the project root:

```bash
pip3 install -r requirements.txt          # first time only
python3 -m uvicorn backend.main:app --reload --port 9000
```

API runs at `http://localhost:9000`. Interactive docs at `http://localhost:9000/docs`.

**Step 2 — Open the dashboard**

```bash
open http://localhost:9000
```

---

## Phase 3 — SQLite Database Layer

Phase 3 adds a local SQLite database so the backend API reads and writes real data instead of relying only on mock data files.

### Database

- Database engine: SQLite
- Database file: `backend/database/scanfor_red.db`
- Database models: `backend/database/models.py`
- Initialization script: `backend/database/init_db.py`
- Seed data: `backend/database/seed_data.py`

### Initialize / reset the database

From the project root:

```bash
python3 -m backend.database.init_db
```

To reset and reseed data:

```bash
python3 -m backend.database.init_db --reset
```

### What is now database-backed

- `GET /api/summary` → reads alert batches and alert events from SQLite
- `GET /api/alert-batches/latest` → reads latest batch metadata from SQLite
- `GET /api/alerts` → reads alert events from SQLite
- `GET /api/known-issues` → reads known issue records from SQLite
- `POST /api/known-issues` → creates a new known issue in SQLite
- `PUT /api/known-issues/{known_issue_id}` → updates a known issue in SQLite
- `PATCH /api/known-issues/{known_issue_id}/archive` → archives a known issue in SQLite
- `POST /api/alerts/{alert_id}/notes` → adds a note to an alert event in SQLite
- `PATCH /api/alerts/{alert_id}/status` → updates alert status/category in SQLite
- `POST /api/alerts/{alert_id}/mark-known` → links an alert to a known issue or creates one, then updates the alert

### What is intentionally not built yet

- Gmail / Outlook email ingestion
- Real email parsing
- Ticket integration (Jira / Labtrack / similar)
- Notifications
- Authentication
- Production secrets or real customer data

---

The backend serves the frontend directly, so there are no CORS issues.
`/api/*` routes are handled by FastAPI; everything else serves the static frontend files.

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/api/health` | Health check |
| GET | `/api/summary` | Summary card counts |
| GET | `/api/alert-batches/latest` | Latest batch metadata |
| GET | `/api/alerts` | Classified alert events — defaults to `signal_type=actionable`; see `include=` below |
| GET | `/api/known-issues` | Known issue catalog |
| GET | `/api/prom/status` | Current Prometheus file status |
| POST | `/api/prom/process` | Process the configured `.prom` file immediately |
| GET | `/api/prom/snapshots` | List recorded Prometheus snapshots |
| GET | `/api/prom/snapshots/latest` | Latest Prometheus snapshot |

---

## File Structure

```
Scanfor_Red_Email_Alerts_Dashboard/
│
├── index.html              # Frontend entry point
├── requirements.txt        # Python dependencies
│
├── css/
│   └── styles.css          # Dark theme, all visual styles
│
├── js/
│   ├── api.js              # ★ API fetch functions (getSummary, getAlerts, etc.)
│   ├── dataStore.js        # ★ STORE object + populate functions (API or mock fallback)
│   ├── app.js              # Entry point: async data load, view routing, toast
│   ├── dashboard.js        # Dashboard view renderer (4 alert sections + filters)
│   ├── knownIssues.js      # Known Issues view + detail modal
│   ├── fingerprint.js      # buildFingerprint() utility (JS version)
│   ├── mockAlerts.js       # Fallback mock data (used when API is offline)
│   └── mockKnownIssues.js  # Fallback mock known issues
│
└── backend/
    ├── main.py             # FastAPI app, CORS, router registration
    ├── routes/
    │   ├── health.py
    │   ├── summary.py
    │   ├── alerts.py
    │   └── known_issues.py
    ├── data/
    │   ├── mock_alerts.py       # ★ Backend mock: RAW_ALERTS, RESOLVED_ALERTS, ALERT_BATCH
    │   └── mock_known_issues.py # ★ Backend mock: KNOWN_ISSUES catalog
    └── services/
        ├── fingerprint.py       # build_fingerprint() (Python version)
        └── classifier.py        # classify_alert() → category + classification reason
```

---

## Where Mock Data Lives

### Backend (authoritative data source)

| File | Contents |
|---|---|
| `backend/data/mock_alerts.py` | `ALERT_BATCH`, `RAW_ALERTS`, `RESOLVED_ALERTS` |
| `backend/data/mock_known_issues.py` | `KNOWN_ISSUES` (5 catalog records) |

Edit these to change what the API returns. Classification runs at request time.

### Frontend (fallback only)

| File | Contents |
|---|---|
| `js/mockAlerts.js` | Used only when backend is unreachable |
| `js/mockKnownIssues.js` | Used only when backend is unreachable |

---

## How the Frontend Gets Its Data

1. `app.js` calls `loadData()` on page load
2. `loadData()` calls `getLatestBatch()`, `getAlerts()`, and `getKnownIssues()` from `api.js` in parallel
3. `api.js` transforms API responses from snake_case → camelCase to match the render functions
4. Results are stored in `STORE` (defined in `dataStore.js`)
5. Render functions in `dashboard.js` and `knownIssues.js` read from `STORE`
6. If the API is unreachable, `populateStoreFromMock()` loads the JS mock globals into `STORE` and a warning banner is shown

---

## Fingerprint Logic

Each alert is normalized into a stable daily-safe key:

```
Raw:        ccgw-eastus2-prod-maz-vm-01 | mazdaserver-main.20260630 | javax_net_ssl
Normalized: prod | ccgw-eastus2-prod-maz | mazdaserver-main | javax_net_ssl
```

- Date suffix stripped from log filename
- Trailing node index stripped from hostname
- Environment inferred from hostname prefix

Same logic in both `js/fingerprint.js` and `backend/services/fingerprint.py`.

---

## Not Yet Built (Phase 3+)

- Gmail / Outlook email connection
- Real email parser
- Database (PostgreSQL / SQLite)
- Authentication
- Ticket integration (Jira / Labtrack)
- Notifications
- POST endpoints for alert ingestion

---

## Docker

The whole app (FastAPI backend + static frontend) runs in a single container.

### Quick start with docker compose

```bash
docker compose up --build
```

Then open `http://localhost:9000`.

By default:
- `${SCANFOR_PROM_SOURCE:-/Users/bpb/Documents/Test_Data}` is bind-mounted **read-only** at `/prom` inside the container as the `.prom` source folder.
- The SQLite database lives on a named Docker volume `scanfor-db` mounted at `/data`, so it persists across restarts and rebuilds.
- Tables are auto-created on startup (idempotent) — no separate `init_db` step is needed inside the container.

### Environment variables

| Variable | Default (container) | Meaning |
|---|---|---|
| `SCANFOR_PROM_FILE_PATH` | `/prom` | File **or** directory of `*.prom` files |
| `SCANFOR_DB_PATH` | `/data/scanfor_red.db` | SQLite database file location |
| `SCANFOR_PROM_POLL_SECONDS` | `60` | Watcher poll interval |
| `SCANFOR_ENABLE_PROM_WATCHER` | `false` | `true` to auto-poll every N seconds |

### Pointing at the real server folder

Edit `docker-compose.yml` and change the bind mount:

```yaml
volumes:
  - /Users/bpb/Documents/Test_Data:/prom:ro
  - scanfor-db:/data
```

Or override at runtime:

```bash
docker run --rm -p 9000:9000 \
  -v /Users/bpb/Documents/Test_Data:/prom:ro \
  -v scanfor-db:/data \
  scanfor-red-alerts:latest
```

### Reset the database

```bash
docker compose down -v          # -v removes the scanfor-db volume
docker compose up --build
```

### Alternative: bind-mount the DB dir to the host

If you prefer the DB file on your host filesystem instead of a named volume,
replace `- scanfor-db:/data` in `docker-compose.yml` with a bind mount, e.g.:

```yaml
- ./docker_data:/data
```

Note: on Windows/OneDrive paths, named volumes are more reliable than bind
mounts for SQLite due to file-locking quirks.

---

## Phase 4 — Folder-based `.prom` Ingestion

The dashboard reads Prometheus `scanfor_errors` metric files from a folder
(or a single file), snapshots each read into SQLite, and compares snapshots
to compute growth and resolved alerts. `.prom` files are never modified.

### Configuration

| Env var | Default | Meaning |
|---|---|---|
| `SCANFOR_PROM_FILE_PATH` | `/prom` | File **or** directory containing `*.prom` |
| `SCANFOR_PROM_POLL_SECONDS` | `60` | Watcher poll interval |
| `SCANFOR_ENABLE_PROM_WATCHER` | `false` | Set `true` to auto-poll on startup |

If the configured path is a directory, every `*.prom` file inside is loaded
and combined into one snapshot per processing pass.

### Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/api/prom/status` | Configured path, path type, file counts, latest snapshot, recent error, and file inventory summary |
| GET | `/api/prom/files` | Full file inventory (filename, size, mtime, metric count, generated time, state file) |
| POST | `/api/prom/process` | Process the folder now — returns `processed` or `skipped` plus per-file counts |
| GET | `/api/prom/snapshots` | Snapshot history (`limit` query) |
| GET | `/api/prom/snapshots/latest` | Latest snapshot with per-file rows |

### Batch / snapshot IDs

Batch and snapshot IDs include a 6-char slice of the folder hash so runs with
identical `# Generated:` timestamps can't collide:

```
PROM-20260630-194501-068cbe
```

### Change detection

- Fingerprint match priority: `fingerprint_exact` first, then `fingerprint_general`.
- `previous_count` and `growth` are computed against the previous successful snapshot.
- `first_seen` is preserved from the earlier matching alert.
- Resolved alerts are only emitted when the previous snapshot had the fingerprint as *active*. This prevents duplicate resolved rows on every subsequent pass.

### Testing Folder Ingestion

Using an external `.prom` source folder:

1. Reset the local DB: `python -m backend.database.init_db --reset`
2. Set `SCANFOR_PROM_FILE_PATH` to the folder or file that contains your dashboard source metrics.
3. Start the backend: `python -m uvicorn backend.main:app --reload --port 9000`
4. Open `http://localhost:9000`
5. Click **Process .prom Folder Now** to process the configured source.
6. Refresh or update the source metrics, then click **Process .prom Folder Now** again to compare snapshots.
7. Remove or omit a metric line from the source, process again, and that fingerprint appears in the Resolved section.
8. In **Known Issues** view, add a known issue whose `fingerprint` matches one of the alerts.
9. Click **Process .prom Folder Now**; the matching alert moves from *New* to *Known* (or *Worsening* if its count exceeds `normal_count_max`).


### What is stored where

| Data | Source of truth |
|---|---|
| Live metric counts | `.prom` files (read-only) |
| Known issues, notes, tickets, owners, statuses, history | SQLite database |

---

## Phase 5 — Actionable vs. Noise Classification

Every parsed `.prom` row is still stored, always — this feature only changes how rows are
**displayed and queried**, never what's ingested. Alongside the existing `category` field
(new/known/worsening/resolved), each `AlertEvent` now also carries a `signal_type`:

| `signal_type` | Meaning |
|---|---|
| `actionable` | Color is in `SCANFOR_ACTIONABLE_COLORS` and it isn't a suppressed known error |
| `noise` | Color isn't actionable (e.g. black/green), or missing/unrecognized |
| `suppressed` | A known error, and `SCANFOR_SUPPRESS_KNOWN_ERRORS=true` |

Classification rule (`backend/services/classifier.py::classify_alert_signal`):

```python
if known_error and suppress_known_errors:
    signal_type = "suppressed"
elif normalized_color in actionable_colors:
    signal_type = "actionable"
else:
    signal_type = "noise"
```

### Configuration

```env
SCANFOR_ACTIONABLE_COLORS=red,yellow
SCANFOR_SUPPRESS_KNOWN_ERRORS=true
```

| Env var | Default | Meaning |
|---|---|---|
| `SCANFOR_ACTIONABLE_COLORS` | `red,yellow` | Case-insensitive, comma-separated. Blank/invalid falls back to the default. |
| `SCANFOR_SUPPRESS_KNOWN_ERRORS` | `true` | Accepts `true`/`1`/`yes`/`on` (case-insensitive) as true. |

### API examples

```bash
curl http://localhost:9000/api/alerts                          # actionable only (default)
curl http://localhost:9000/api/alerts?include=noise            # noise rows
curl http://localhost:9000/api/alerts?include=suppressed        # suppressed rows
curl http://localhost:9000/api/alerts?include=noise,suppressed  # both
curl http://localhost:9000/api/alerts?include=all               # everything, all signal_types
```

`GET /api/summary` gained a `signal_counts` breakdown (`{actionable, noise, suppressed, total}`)
scoped to the latest batch, alongside its existing (now actionable-only) primary tiles.

### Dashboard

The main New/Known/Worsening/Resolved tables show actionable alerts only, by default.
Two muted, collapsed-by-default sections below them — **Suppressed** and **Noise** — show
everything else for auditing. Nothing is deleted; a row can move between sections on the
next `.prom` ingestion if its color or known-error flag changes, or if you change the env
vars above and restart.

### Migration

No migration framework (Alembic) exists in this project. `backend/database/db.py::ensure_signal_type_column()`
runs at startup (idempotent): it adds the column via `ALTER TABLE ... ADD COLUMN ... DEFAULT 'noise'`
if missing, then backfills every existing row's real classification from its stored `color`/`known_error`
using the same rule ingestion uses. No rows are ever dropped.

---

## Phase History

| Phase | Description |
|---|---|
| Phase 1 | Frontend only — static HTML/CSS/JS with hardcoded mock data |
| Phase 2 | FastAPI backend + API fetch layer; frontend connected to backend |
| Phase 3 | SQLite database layer + database-backed API |
| Phase 4 | Folder-based `.prom` ingestion, snapshot tracking, change detection |
| Phase 5 | `signal_type` classification (actionable/noise/suppressed) + dashboard filtering |
