"""
database/schemas.py
─────────────────────────────────────────────────────────────────────────────
Pydantic schemas used for validating POST / PUT / PATCH request bodies.
Response shapes are returned as plain dicts from routes.
"""

from typing import Optional
from pydantic import BaseModel


# ─── Known Issue ──────────────────────────────────────────────────────────────

class KnownIssueCreate(BaseModel):
    fingerprint: str
    error_type: str
    host_scope: str
    log_scope: str
    severity: str = "medium"
    owner: str = ""
    normal_count_min: int = 0
    normal_count_max: int = 100
    normal_growth_min: int = 0
    normal_growth_max: int = 50
    cause: str = ""
    impact: str = ""
    resolution_steps: str = ""
    runbook_link: Optional[str] = None
    ticket_link: Optional[str] = None
    last_reviewed: Optional[str] = None


class KnownIssueUpdate(BaseModel):
    fingerprint: Optional[str] = None
    error_type: Optional[str] = None
    host_scope: Optional[str] = None
    log_scope: Optional[str] = None
    severity: Optional[str] = None
    owner: Optional[str] = None
    normal_count_min: Optional[int] = None
    normal_count_max: Optional[int] = None
    normal_growth_min: Optional[int] = None
    normal_growth_max: Optional[int] = None
    cause: Optional[str] = None
    impact: Optional[str] = None
    resolution_steps: Optional[str] = None
    runbook_link: Optional[str] = None
    ticket_link: Optional[str] = None
    last_reviewed: Optional[str] = None


# ─── Alert Note ───────────────────────────────────────────────────────────────

class AlertNoteCreate(BaseModel):
    note: str
    created_by: str = "user"


# ─── Alert Status Update ──────────────────────────────────────────────────────

class AlertStatusUpdate(BaseModel):
    status: str       # new | known | worsening | resolved | suppressed | archived
    category: Optional[str] = None  # defaults to status if not provided
    changed_by: str = "user"
    change_reason: Optional[str] = None
    clear_known_issue: bool = False  # unlink KI + related fields when true


# ─── Mark Known ───────────────────────────────────────────────────────────────

class MarkKnownRequest(BaseModel):
    known_issue_id: Optional[str] = None          # link to existing KI
    new_known_issue: Optional[KnownIssueCreate] = None  # or create a new one
    changed_by: str = "user"


class AlertTicketUpdate(BaseModel):
    ticket_link: Optional[str] = None
    changed_by: str = "user"
