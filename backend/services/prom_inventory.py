import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.services.config import PROM_FILE_PATH
from backend.services.prom_parser import parse_prom_lines


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


def parse_generated_time_string(value: Optional[str]) -> Optional[datetime]:
    """Parses a "# Generated:" header value in either of the two formats
    seen in practice (ISO-8601, or "YYYY-MM-DD HH:MM:SS"). None if missing
    or unparseable — never raises."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        pass
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


@dataclass
class PromFileRead:
    """Everything ingestion, inventory, and snapshot-persistence need about
    one .prom file, produced from exactly one file read (see read_prom_file).
    generated_time is the raw header string (for audit/display);
    generated_time_parsed is the datetime trend calculations should use as
    that file's observed_at."""

    filename: str
    path: str
    full_path: str
    size_bytes: int
    modified_time: str  # isoformat
    file_hash: str
    generated_time: Optional[str]
    generated_time_parsed: Optional[datetime]
    state_file: Optional[str]
    line_count: int
    metrics: List[Dict[str, Any]]
    parse_warnings: List[str] = field(default_factory=list)
    invalid_row_count: int = 0
    duplicate_row_count: int = 0
    # None = the file itself was opened/read successfully (individual rows
    # may still be invalid/duplicate — see parse_warnings for those). Set to
    # the exception text when the file couldn't be opened/read at all, so one
    # unreadable file can't abort the whole run, the same guarantee already
    # given to a single malformed row.
    read_error: Optional[str] = None

    @property
    def metric_count(self) -> int:
        return len(self.metrics)


def read_prom_file(path: Path) -> PromFileRead:
    """The one place a .prom file is actually opened and read. Produces hash,
    size, mtime, generated time, state file, line count, and parsed metrics
    together — replaces what used to be separate reads/parses spread across
    describe_file(), folder_hash(), and process_prom_file()'s own loop."""
    try:
        stat = path.stat()
        raw_bytes = path.read_bytes()
    except OSError as exc:
        return PromFileRead(
            filename=path.name,
            path=str(path),
            full_path=str(path),
            size_bytes=0,
            modified_time=datetime.utcnow().isoformat(),
            file_hash="",
            generated_time=None,
            generated_time_parsed=None,
            state_file=None,
            line_count=0,
            metrics=[],
            parse_warnings=[f"failed to read file: {exc}"],
            read_error=str(exc),
        )

    file_hash = hashlib.sha256(raw_bytes).hexdigest()
    lines = raw_bytes.decode("utf-8", errors="replace").splitlines()

    generated_time: Optional[str] = None
    state_file: Optional[str] = None
    for line in lines:
        if not line.startswith("#"):
            break
        if line.startswith("# Generated:"):
            generated_time = line.partition(":")[2].strip()
        elif line.startswith("# State file:"):
            state_file = line.partition(":")[2].strip()

    parse_result = parse_prom_lines(lines)
    warnings = list(parse_result.invalid_row_details) + list(parse_result.duplicate_row_details)

    return PromFileRead(
        filename=path.name,
        path=str(path),
        full_path=str(path.resolve()),
        size_bytes=stat.st_size,
        modified_time=datetime.fromtimestamp(stat.st_mtime).isoformat(),
        file_hash=file_hash,
        generated_time=generated_time,
        generated_time_parsed=parse_generated_time_string(generated_time),
        state_file=state_file,
        line_count=len(lines),
        metrics=parse_result.valid_rows,
        parse_warnings=warnings,
        invalid_row_count=parse_result.invalid_row_count,
        duplicate_row_count=parse_result.duplicate_row_count,
    )


def compute_file_quality_status(fr: PromFileRead, reference_time: Optional[datetime], stale_seconds: float) -> str:
    """Worst-applicable state for one file this run: parse_failure (couldn't
    read it at all) > stale (its own Generated time is too far behind this
    run's reference time to trust an absence against it) > parse_warning
    (readable, but some rows were invalid/duplicate) > ok."""
    if fr.read_error:
        return "parse_failure"
    if reference_time is not None and fr.generated_time_parsed is not None:
        age_seconds = (reference_time - fr.generated_time_parsed).total_seconds()
        if age_seconds > stale_seconds:
            return "stale"
    if fr.invalid_row_count or fr.duplicate_row_count:
        return "parse_warning"
    return "ok"


def combine_file_hashes(file_reads: List[PromFileRead]) -> str:
    """Folder-wide idempotency hash, derived from each file's own already-
    computed hash (not a second raw-bytes read) — equivalent in effect to
    hashing the whole folder's content, since any file's content change
    changes its own hash first."""
    hasher = hashlib.sha256()
    for fr in sorted(file_reads, key=lambda f: f.filename):
        hasher.update(fr.filename.encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(fr.file_hash.encode("utf-8"))
        hasher.update(b"\0")
    return hasher.hexdigest()


def describe_file(path: Path) -> Dict[str, Any]:
    """Kept for the /api/prom/files inventory endpoint's existing response
    shape — now just formats a single read_prom_file() call instead of
    re-parsing/re-reading the file itself."""
    fr = read_prom_file(path)
    return {
        "filename": fr.filename,
        "path": fr.path,
        "full_path": fr.full_path,
        "size_bytes": fr.size_bytes,
        "modified_time": fr.modified_time,
        "metric_count": fr.metric_count,
        "generated_time": fr.generated_time,
        "state_file": fr.state_file,
    }


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def list_configured_files() -> List[Dict[str, Any]]:
    files = resolve_source_files(PROM_FILE_PATH)
    return [describe_file(p) for p in files]
