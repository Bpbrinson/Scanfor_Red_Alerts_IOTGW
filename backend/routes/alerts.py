from fastapi import APIRouter
from backend.data.mock_alerts import RAW_ALERTS, RESOLVED_ALERTS, ALERT_BATCH
from backend.services.classifier import classify_alert
from backend.services.fingerprint import build_fingerprint

router = APIRouter()


@router.get("/alert-batches/latest")
def get_latest_batch():
    total = len(RAW_ALERTS) + len(RESOLVED_ALERTS)
    return {**ALERT_BATCH, "total_issues_detected": total}


@router.get("/alerts")
def get_alerts():
    results = []

    for a in RAW_ALERTS:
        fp = build_fingerprint(a["hostname"], a["raw_filename"], a["error_type"])
        cl = classify_alert(
            a["hostname"], a["raw_filename"], a["error_type"], a["count"], a["growth"]
        )
        results.append({
            "alert_id": a["alert_id"],
            "batch_id": a["batch_id"],
            "status": cl["category"],
            "category": cl["category"],
            "hostname": a["hostname"],
            "raw_filename": a["raw_filename"],
            "log_file": a["raw_filename"],
            "error_type": a["error_type"],
            "count": a["count"],
            "growth": a["growth"],
            "severity": cl["severity"],
            "first_seen": a["first_seen"],
            "last_seen": a["last_seen"],
            "fingerprint": fp,
            "classification_reason": cl["classification_reason"],
            "suggested_action": cl["suggested_action"],
            "known_issue_id": cl["known_issue_id"],
            "owner": cl["owner"],
            "runbook_link": None,
            "ticket_link": None,
            "notes": a.get("notes", ""),
            # Worsening extras — populated only when category == worsening
            "normal_range": None,
            "escalation_rule": None,
        })

    # Enrich worsening entries with normal range and escalation rule
    from backend.data.mock_known_issues import KNOWN_ISSUES
    ki_map = {ki["known_issue_id"]: ki for ki in KNOWN_ISSUES}
    for r in results:
        if r["known_issue_id"]:
            ki = ki_map.get(r["known_issue_id"])
            if ki:
                r["runbook_link"] = ki["runbook_link"]
                r["ticket_link"] = ki["ticket_link"]
                if r["category"] == "worsening":
                    r["normal_range"] = f"{ki['normal_count_min']}–{ki['normal_count_max']}"
                    r["escalation_rule"] = (
                        f"Count > {ki['normal_count_max']} — notify {ki['owner']}"
                    )

    # Append resolved alerts
    for a in RESOLVED_ALERTS:
        fp = build_fingerprint(a["hostname"], a["raw_filename"], a["error_type"])
        cl = classify_alert(
            a["hostname"], a["raw_filename"], a["error_type"], a["count"], a["growth"]
        )
        ki = ki_map.get(cl.get("known_issue_id", "")) if cl.get("known_issue_id") else None
        results.append({
            "alert_id": a["alert_id"],
            "batch_id": a["batch_id"],
            "status": "resolved",
            "category": "resolved",
            "hostname": a["hostname"],
            "raw_filename": a["raw_filename"],
            "log_file": a["raw_filename"],
            "error_type": a["error_type"],
            "count": a["count"],
            "growth": a["growth"],
            "severity": None,
            "first_seen": a["first_seen"],
            "last_seen": a["last_seen"],
            "fingerprint": fp,
            "classification_reason": "Previously active issue not seen in current batch.",
            "suggested_action": None,
            "known_issue_id": cl.get("known_issue_id"),
            "owner": cl.get("owner"),
            "runbook_link": ki["runbook_link"] if ki else None,
            "ticket_link": ki["ticket_link"] if ki else None,
            "notes": a.get("notes", ""),
            "normal_range": None,
            "escalation_rule": None,
        })

    return results
