"""
services/fingerprint.py
─────────────────────────────────────────────────────────────────────────────
Fingerprint utilities — Python equivalent of js/fingerprint.js.

Format:  env | hostPrefix | logScope | errorType
Example: prod | mxqrpiog  | listener-main | SQLException

The fingerprint strips daily date suffixes from log filenames so the same
recurring issue maps to the same key every day.
"""

import re
from typing import Optional


def extract_env(hostname: str) -> str:
    if re.search(r"staging|stg", hostname, re.I):
        return "staging"
    if re.search(r"\bdev\b|\btest\b", hostname, re.I):
        return "dev"
    return "prod"


def extract_host_prefix(hostname: str) -> str:
    """
    Strips trailing node index to produce a stable host prefix.
    mxqrpiog02              → mxqrpiog
    ccgw-eastus2-prod-ford-vm-01 → ccgw-eastus2-prod-ford
    """
    # Remove -vm-NN suffix (e.g. -vm-01)
    h = re.sub(r"-vm-\d+$", "", hostname)
    # Remove trailing digit run (e.g. mxqrpiog02 → mxqrpiog)
    h = re.sub(r"\d+$", "", h)
    return h


def extract_log_scope(log_file: str) -> str:
    """listener-main.20260630 → listener-main"""
    return re.sub(r"\.\d{8}$", "", log_file)


def extract_log_epoch(log_file: str) -> Optional[str]:
    """listener-main.20260630 → "20260630" — the counter epoch this raw
    filename belongs to. None if there's no trailing date suffix at all."""
    match = re.search(r"\.(\d{8})$", log_file or "")
    return match.group(1) if match else None


def build_fingerprint(hostname: str, log_file: str, error_type: str) -> str:
    env = extract_env(hostname)
    host_prefix = extract_host_prefix(hostname)
    log_scope = extract_log_scope(log_file)
    return f"{env} | {host_prefix} | {log_scope} | {error_type}"


def build_fingerprint_exact(
    tenant: str,
    system: str,
    hostname: str,
    log_file: str,
    error_type: str,
    error_index: str,
    caused_by: str,
) -> str:
    log_scope = extract_log_scope(log_file)
    parts = [tenant, system, hostname, log_scope, error_type, error_index]
    if caused_by:
        parts.append(caused_by)
    return " | ".join(str(p) for p in parts if p is not None)


def build_fingerprint_general(
    tenant: str,
    system: str,
    hostname: str,
    log_file: str,
    error_type: str,
    error_index: str,
    caused_by: str,
) -> str:
    host_prefix = extract_host_prefix(hostname)
    log_scope = extract_log_scope(log_file)
    parts = [tenant, system, host_prefix, log_scope, error_type, error_index]
    if caused_by:
        parts.append(caused_by)
    return " | ".join(str(p) for p in parts if p is not None)
