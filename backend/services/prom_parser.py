import argparse
from dataclasses import dataclass, field
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROMETHEUS_PREFIX = "scanfor_errors"
LABELS_RE = re.compile(r"([a-zA-Z_][a-zA-Z0-9_]*)=\"([^\"]*)\"")
FILENAME_DATE_SUFFIX_RE = re.compile(r"\.(\d{8})$")

# Row dict keys that must be non-blank for a row to be trustworthy enough to
# identify/track. Maps to the required labels system/hostname/tenant/filename/
# error_type/error_index (filename -> raw_filename here). `color` is
# deliberately excluded: a blank color is a valid, meaningful "noise"
# classification (see classifier.py::classify_alert_signal), not a data
# problem, and rejecting it would silently drop rows that are stored today.
_REQUIRED_ROW_KEYS = ("system", "hostname", "tenant", "raw_filename", "error_type", "error_index")


@dataclass
class ParseResult:
    """Structured outcome of parsing one file's lines. Never silently drops a
    row without recording why — invalid/duplicate rows are counted and
    detailed, not just omitted."""

    valid_rows: List[Dict[str, Any]] = field(default_factory=list)
    invalid_row_count: int = 0
    invalid_row_details: List[str] = field(default_factory=list)
    duplicate_row_count: int = 0
    duplicate_row_details: List[str] = field(default_factory=list)


def _parse_labels(label_text: str) -> Dict[str, str]:
    labels: Dict[str, str] = {}
    for match in LABELS_RE.finditer(label_text):
        labels[match.group(1)] = match.group(2)
    return labels


def _normalize_log_file(filename: Optional[str]) -> str:
    if not filename:
        return ""
    return FILENAME_DATE_SUFFIX_RE.sub("", filename)


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in ("1", "true", "yes", "y", "on")


def parse_prom_line(line: str) -> Optional[Dict[str, Any]]:
    """Turns one text line into a row dict, or None if the line isn't a
    scanfor_errors metric line at all (blank, comment, header, unparseable
    value). Does not validate required labels or duplicates — parse_prom_lines
    handles that, since only it can attach a line number to the problem."""
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None

    if not stripped.startswith(f"{PROMETHEUS_PREFIX}"):
        return None

    if "{" not in stripped or "}" not in stripped:
        return None

    metric, _, tail = stripped.partition("}")
    label_part = metric.partition("{")[2]
    labels = _parse_labels(label_part)
    value_part = tail.strip()
    if not value_part:
        return None

    try:
        count = int(float(value_part.split()[0]))
    except ValueError:
        return None

    return {
        "system_type": labels.get("system_type", ""),
        "system": labels.get("system", ""),
        "hostname": labels.get("hostname", ""),
        "tenant": labels.get("tenant", ""),
        "raw_filename": labels.get("filename", ""),
        "log_file": _normalize_log_file(labels.get("filename", "")),
        "error_type": labels.get("error_type", ""),
        "error_index": labels.get("error_index", ""),
        "color": labels.get("color", ""),
        "raw_known_error": _parse_bool(labels.get("known_error", "false")),
        "raw_note": labels.get("note", ""),
        "caused_by": labels.get("caused_by", ""),
        "count": count,
    }


def _missing_required_keys(row: Dict[str, Any]) -> List[str]:
    return [key for key in _REQUIRED_ROW_KEYS if not row.get(key)]


def _duplicate_identity_key(row: Dict[str, Any]) -> Tuple[Any, ...]:
    """Same identity tuple build_fingerprint_exact() uses — two rows that
    collide here would resolve to the same stable alert key."""
    return (
        row.get("tenant"), row.get("system"), row.get("hostname"), row.get("log_file"),
        row.get("error_type"), row.get("error_index"), row.get("caused_by"),
    )


def parse_prom_lines(lines: List[str]) -> ParseResult:
    """Parse already-read lines — used by prom_inventory.read_prom_file() so a
    file is never opened twice just to parse it after already reading it once
    for hashing/header/line-count purposes."""
    result = ParseResult()
    seen_at_line: Dict[Tuple[Any, ...], int] = {}

    for line_number, line in enumerate(lines, start=1):
        row = parse_prom_line(line)
        if row is None:
            continue

        missing = _missing_required_keys(row)
        if missing:
            result.invalid_row_count += 1
            result.invalid_row_details.append(
                f"line {line_number}: missing required field(s): {', '.join(missing)}"
            )
            continue

        key = _duplicate_identity_key(row)
        if key in seen_at_line:
            result.duplicate_row_count += 1
            result.duplicate_row_details.append(
                f"line {line_number}: duplicate of line {seen_at_line[key]} for "
                f"{row['tenant']} | {row['system']} | {row['hostname']} | {row['log_file']} | "
                f"{row['error_type']} | {row['error_index']}"
            )
            continue

        seen_at_line[key] = line_number
        result.valid_rows.append(row)

    return result


def parse_prom_file(path: Path) -> ParseResult:
    return parse_prom_lines(path.read_text(encoding="utf-8").splitlines())


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse a Prometheus .prom file into Scanfor alert records.")
    parser.add_argument("path", nargs="?", default="sample.prom", help="Path to the .prom file")
    args = parser.parse_args()

    path = Path(args.path)
    if not path.exists():
        print(f"File not found: {path}")
        return 1

    result = parse_prom_file(path)
    print(
        f"Parsed {len(result.valid_rows)} scanfor_errors records from {path} "
        f"({result.invalid_row_count} invalid, {result.duplicate_row_count} duplicate)"
    )
    for record in result.valid_rows[:5]:
        print(record)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
