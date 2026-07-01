import argparse
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

PROMETHEUS_PREFIX = "scanfor_errors"
LABELS_RE = re.compile(r"([a-zA-Z_][a-zA-Z0-9_]*)=\"([^\"]*)\"")
FILENAME_DATE_SUFFIX_RE = re.compile(r"\.(\d{8})$")


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


def parse_prom_file(path: Path) -> List[Dict[str, Any]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    records: List[Dict[str, Any]] = []
    for line in lines:
        parsed = parse_prom_line(line)
        if parsed is not None:
            records.append(parsed)
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse a Prometheus .prom file into Scanfor alert records.")
    parser.add_argument("path", nargs="?", default="sample.prom", help="Path to the .prom file")
    args = parser.parse_args()

    path = Path(args.path)
    if not path.exists():
        print(f"File not found: {path}")
        return 1

    records = parse_prom_file(path)
    print(f"Parsed {len(records)} scanfor_errors records from {path}")
    for record in records[:5]:
        print(record)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
