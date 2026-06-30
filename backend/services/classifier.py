"""
services/classifier.py
─────────────────────────────────────────────────────────────────────────────
Alert classification logic.

`classify_alert` now accepts the known-issue catalog as a parameter so it
can be called with either DB-fetched records or the in-memory mock list.
This keeps the classifier decoupled from the data source.

Each known_issue dict/object must expose these attributes (dict-key or attr):
  known_issue_id, host_scope, log_scope, error_type,
  normal_count_max, severity, owner, resolution_steps
"""

from __future__ import annotations
from typing import Optional, List, Any
import re

from backend.services.fingerprint import extract_host_prefix, extract_log_scope


def _get(obj: Any, key: str):
    """Access dict key or object attribute transparently."""
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def _host_matches_scope(hostname: str, scope: str) -> bool:
    prefix = extract_host_prefix(hostname)
    pattern = scope.rstrip("*").rstrip("-")
    return prefix.startswith(pattern)


def _log_matches_scope(log_file: str, scope: str) -> bool:
    log_scope = extract_log_scope(log_file)
    if scope.startswith("*"):
        return log_scope.endswith(scope.lstrip("*"))
    if scope.endswith("*"):
        return log_scope.startswith(scope.rstrip("*"))
    return log_scope == scope


def _error_matches(error_type: str, ki_error_type: str) -> bool:
    try:
        return bool(re.search(ki_error_type, error_type, re.I))
    except re.error:
        return error_type == ki_error_type


def find_matching_known_issue(
    hostname: str,
    log_file: str,
    error_type: str,
    known_issues: List[Any],
) -> Optional[Any]:
    """Return the first known issue that matches all three dimensions, or None."""
    for ki in known_issues:
        if ki is None:
            continue
        if _get(ki, "status") == "archived":
            continue
        if (
            _error_matches(error_type, _get(ki, "error_type") or "")
            and _host_matches_scope(hostname, _get(ki, "host_scope") or "")
            and _log_matches_scope(log_file, _get(ki, "log_scope") or "")
        ):
            return ki
    return None


def classify_alert(
    hostname: str,
    log_file: str,
    error_type: str,
    count: int,
    growth: int,
    known_issues: Optional[List[Any]] = None,
) -> dict:
    """
    Classify a single alert against the known-issue catalog.

    known_issues: list of KnownIssue ORM objects or dicts.
                  If None, falls back to the mock data (backward compat).
    """
    if known_issues is None:
        from backend.data.mock_known_issues import KNOWN_ISSUES
        known_issues = KNOWN_ISSUES

    ki = find_matching_known_issue(hostname, log_file, error_type, known_issues)

    if ki is None:
        return {
            "category": "new",
            "classification_reason": "No matching known issue fingerprint found.",
            "known_issue_id": None,
            "severity": _infer_severity(count, growth),
            "suggested_action": f"Investigate {error_type} on {hostname}",
            "owner": None,
        }

    max_count = _get(ki, "normal_count_max") or 100
    is_worsening = count > max_count or growth > max_count

    if is_worsening:
        return {
            "category": "worsening",
            "classification_reason": (
                f"Known issue matched ({_get(ki, 'known_issue_id')}), but count or growth "
                f"exceeded normal threshold (max {max_count})."
            ),
            "known_issue_id": _get(ki, "known_issue_id"),
            "severity": _escalate_severity(_get(ki, "severity") or "medium"),
            "suggested_action": (_get(ki, "resolution_steps") or "").split("\n")[0],
            "owner": _get(ki, "owner"),
        }

    return {
        "category": "known",
        "classification_reason": (
            f"Matched Known Issue {_get(ki, 'known_issue_id')} by error type and scope."
        ),
        "known_issue_id": _get(ki, "known_issue_id"),
        "severity": _get(ki, "severity"),
        "suggested_action": (_get(ki, "resolution_steps") or "").split("\n")[0],
        "owner": _get(ki, "owner"),
    }


def _infer_severity(count: int, growth: int) -> str:
    if count > 1000 or growth > 400:
        return "critical"
    if count > 300 or growth > 100:
        return "high"
    if count > 50 or growth > 20:
        return "medium"
    return "low"


def _escalate_severity(base: str) -> str:
    order = ["low", "medium", "high", "critical"]
    idx = order.index(base) if base in order else 1
    return order[min(idx + 1, len(order) - 1)]
