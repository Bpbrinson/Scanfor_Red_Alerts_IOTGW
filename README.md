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

The backend serves the frontend directly, so there are no CORS issues.
`/api/*` routes are handled by FastAPI; everything else serves the static frontend files.

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/api/health` | Health check |
| GET | `/api/summary` | Summary card counts |
| GET | `/api/alert-batches/latest` | Latest batch metadata |
| GET | `/api/alerts` | All classified alert events |
| GET | `/api/known-issues` | Known issue catalog |

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

## Phase History

| Phase | Description |
|---|---|
| Phase 1 | Frontend only — static HTML/CSS/JS with hardcoded mock data |
| Phase 2 | FastAPI backend + API fetch layer; frontend connected to backend |
| Phase 3 | Real email parsing + database (planned) |
