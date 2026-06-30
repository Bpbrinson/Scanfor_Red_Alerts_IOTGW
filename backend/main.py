"""
main.py — Scanfor Red API
─────────────────────────────────────────────────────────────────────────────
Run from the project root (Scanfor_Red_Email_Alerts_Dashboard/):

    python3 -m uvicorn backend.main:app --reload --port 9000

Then open http://localhost:9000 — the backend serves the frontend too,
so there are no CORS issues.
"""

from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.routes import health, summary, alerts, known_issues

app = FastAPI(
    title="Scanfor Red API",
    description="Backend API for the Scanfor Red Alert Triage Dashboard",
    version="0.2.0",
)

# allow_origin_regex=".*" reflects the actual Origin header back (including
# "null" from file:// pages) instead of returning a literal "*", which
# browsers reject for null origins.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=".*",
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api")
app.include_router(summary.router, prefix="/api")
app.include_router(alerts.router, prefix="/api")
app.include_router(known_issues.router, prefix="/api")

# Serve the frontend from the project root at http://localhost:9000
# API routes registered above take priority; everything else falls through to
# static files. html=True makes / serve index.html automatically.
_FRONTEND_DIR = Path(__file__).parent.parent
app.mount("/", StaticFiles(directory=_FRONTEND_DIR, html=True), name="frontend")
