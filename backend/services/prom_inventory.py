import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.services.config import PROM_FILE_PATH
from backend.services.prom_parser import parse_prom_file


def resolve_source_files(path: Path) -> List[Path]:
    if path.is_dir():
        return sorted(p for p in path.glob("*.prom") if p.is_file())
    if path.is_file():
        return [path]
    return []


def source_mode(path: Path) -> str:
    if path.is_dir():
        return "folder"
    if path.is_file():
        return "file"
    return "missing"


def _parse_prom_header(path: Path) -> Dict[str, Optional[str]]:
    generated: Optional[str] = None
    state_file: Optional[str] = None
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            if not line.startswith("#"):
                break
            if line.startswith("# Generated:"):
                generated = line.partition(":")[2].strip()
            elif line.startswith("# State file:"):
                state_file = line.partition(":")[2].strip()
    return {"generated_time": generated, "state_file": state_file}


def describe_file(path: Path) -> Dict[str, Any]:
    stat = path.stat()
    metrics = parse_prom_file(path)
    header = _parse_prom_header(path)
    return {
        "filename": path.name,
        "path": str(path),
        "full_path": str(path.resolve()),
        "size_bytes": stat.st_size,
        "modified_time": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        "metric_count": len(metrics),
        "generated_time": header["generated_time"],
        "state_file": header["state_file"],
    }


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def folder_hash(paths: List[Path]) -> str:
    hasher = hashlib.sha256()
    for p in paths:
        hasher.update(p.name.encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(p.read_bytes())
        hasher.update(b"\0")
    return hasher.hexdigest()


def list_configured_files() -> List[Dict[str, Any]]:
    files = resolve_source_files(PROM_FILE_PATH)
    return [describe_file(p) for p in files]
