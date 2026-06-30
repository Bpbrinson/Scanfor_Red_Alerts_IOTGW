from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.database.db import get_db
from backend.database.models import KnownIssue
from backend.database.schemas import KnownIssueCreate, KnownIssueUpdate

router = APIRouter()


def _ki_to_dict(ki: KnownIssue) -> dict:
    return {
        "known_issue_id": ki.known_issue_id,
        "fingerprint": ki.fingerprint,
        "error_type": ki.error_type,
        "host_scope": ki.host_scope,
        "log_scope": ki.log_scope,
        "severity": ki.severity,
        "owner": ki.owner,
        "status": ki.status,
        "normal_count_min": ki.normal_count_min,
        "normal_count_max": ki.normal_count_max,
        "normal_growth_min": ki.normal_growth_min,
        "normal_growth_max": ki.normal_growth_max,
        "cause": ki.cause,
        "impact": ki.impact,
        "resolution_steps": ki.resolution_steps,
        "runbook_link": ki.runbook_link,
        "ticket_link": ki.ticket_link,
        "last_reviewed": ki.last_reviewed,
        "created_at": ki.created_at.isoformat() if ki.created_at else None,
        "updated_at": ki.updated_at.isoformat() if ki.updated_at else None,
    }


def _generate_known_issue_id(db: Session) -> str:
    all_ids = db.query(KnownIssue.known_issue_id).scalars().all()
    max_value = 0
    for value in all_ids:
        try:
            num = int(value.split("-")[-1])
            if num > max_value:
                max_value = num
        except ValueError:
            continue
    return f"KI-{max_value + 1:03d}"


@router.get("/known-issues")
def get_known_issues(db: Session = Depends(get_db)):
    known_issues = db.query(KnownIssue).order_by(KnownIssue.known_issue_id).all()
    return [_ki_to_dict(ki) for ki in known_issues]


@router.post("/known-issues")
def create_known_issue(payload: KnownIssueCreate, db: Session = Depends(get_db)):
    known_issue = KnownIssue(
        known_issue_id=_generate_known_issue_id(db),
        **payload.dict(),
    )
    db.add(known_issue)
    db.commit()
    db.refresh(known_issue)
    return _ki_to_dict(known_issue)


@router.put("/known-issues/{known_issue_id}")
def update_known_issue(
    known_issue_id: str,
    payload: KnownIssueUpdate,
    db: Session = Depends(get_db),
):
    known_issue = db.query(KnownIssue).filter_by(known_issue_id=known_issue_id).first()
    if not known_issue:
        raise HTTPException(status_code=404, detail="Known issue not found")

    for field, value in payload.dict(exclude_unset=True).items():
        setattr(known_issue, field, value)

    db.add(known_issue)
    db.commit()
    db.refresh(known_issue)
    return _ki_to_dict(known_issue)


@router.patch("/known-issues/{known_issue_id}/archive")
def archive_known_issue(known_issue_id: str, db: Session = Depends(get_db)):
    known_issue = db.query(KnownIssue).filter_by(known_issue_id=known_issue_id).first()
    if not known_issue:
        raise HTTPException(status_code=404, detail="Known issue not found")

    known_issue.status = "archived"
    db.add(known_issue)
    db.commit()
    db.refresh(known_issue)
    return _ki_to_dict(known_issue)
