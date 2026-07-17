from dataclasses import dataclass, field
from os import environ
from pathlib import Path
from typing import Dict

from backend.database.db import DB_PATH


def _get_bool(name: str, default: bool) -> bool:
    value = environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "y", "on")


# Default to the external metrics folder so local runs match the production-like
# dashboard flow and do not depend on repository sample data.
_DEFAULT_PROM_PATH = "/Users/bpb/Documents/Test_Data"

PROM_FILE_PATH = Path(environ.get("SCANFOR_PROM_FILE_PATH", _DEFAULT_PROM_PATH)).expanduser()
PROM_POLL_SECONDS = int(environ.get("SCANFOR_PROM_POLL_SECONDS", "60") or 60)
ENABLE_PROM_WATCHER = _get_bool("SCANFOR_ENABLE_PROM_WATCHER", False)

# How many days of alert_events (and their notes/status history) to keep before the
# retention job exports and deletes them. Rows tied to an open ticket or an active
# (non-archived) known issue are always kept regardless of age.
RETENTION_DAYS = int(environ.get("SCANFOR_RETENTION_DAYS", "90") or 90)

# Where CSV exports land before deletion. Defaults next to the database file so a
# Docker deployment's exports live on the same persisted volume as the DB.
EXPORT_DIR = Path(environ.get("SCANFOR_EXPORT_DIR", str(DB_PATH.parent / "exports"))).expanduser()


def _parse_color_set(name: str, default: str) -> set:
    """Case-insensitive, comma-separated color list. Blank/invalid falls back to default."""
    raw = environ.get(name, default) or ""
    colors = {part.strip().lower() for part in raw.split(",") if part.strip()}
    if not colors:
        colors = {part.strip().lower() for part in default.split(",") if part.strip()}
    return colors


# Colors treated as candidates for the "actionable" signal_type classification.
# A row whose color isn't in this set (and isn't suppressed as a known error) is noise.
ACTIONABLE_COLORS = _parse_color_set("SCANFOR_ACTIONABLE_COLORS", "red,yellow")

# When true, rows Scanfor already flagged as known errors are classified as
# "suppressed" rather than actionable, regardless of color.
SUPPRESS_KNOWN_ERRORS = _get_bool("SCANFOR_SUPPRESS_KNOWN_ERRORS", True)


def _get_float(name: str, default: float) -> float:
    value = environ.get(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _get_int(name: str, default: int) -> int:
    value = environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


# Resolution grace period (Section 4: "prevent false resolutions"): an alert
# genuinely absent from a healthy scan only actually resolves once it has
# been absent for at least this many *qualifying* consecutive snapshots AND
# this much elapsed source (not wall-clock) time — both starting defaults,
# not tuned against real operational history. A scan whose relevant source
# file is missing/stale/unreadable never counts toward or against this.
RESOLUTION_GRACE_MIN_SNAPSHOTS = _get_int("SCANFOR_RESOLUTION_GRACE_MIN_SNAPSHOTS", 2)
RESOLUTION_GRACE_MIN_SECONDS = _get_int("SCANFOR_RESOLUTION_GRACE_MIN_SECONDS", 1200)

# A source file is "stale" if its own "# Generated:" time is older than this
# run's reference time by more than this many seconds — i.e. the upstream
# system stopped regenerating it even though the file is still on disk.
SOURCE_STALE_SECONDS = _get_int("SCANFOR_SOURCE_STALE_SECONDS", 1800)


@dataclass(frozen=True)
class TrendConfig:
    """Tunable thresholds for backend/services/trends.py.

    All values are env-overridable (SCANFOR_TREND_*) with defaults chosen to
    be reasonable starting points, not tuned against real operational data —
    see the "recommended configuration to tune" note in project docs.
    """

    # Multi-window lookback targets, in minutes. 30m added for Phase 3's
    # rolling 30-minute rate (request Section 6).
    window_minutes: Dict[str, int] = field(default_factory=lambda: {
        "30m": _get_int("SCANFOR_TREND_WINDOW_30M_MIN", 30),
        "15m": _get_int("SCANFOR_TREND_WINDOW_15M_MIN", 15),
        "1h": _get_int("SCANFOR_TREND_WINDOW_1H_MIN", 60),
        "6h": _get_int("SCANFOR_TREND_WINDOW_6H_MIN", 360),
        "24h": _get_int("SCANFOR_TREND_WINDOW_24H_MIN", 1440),
    })

    # Regression / acceleration
    min_regression_points: int = _get_int("SCANFOR_TREND_MIN_REGRESSION_POINTS", 3)
    min_acceleration_points: int = _get_int("SCANFOR_TREND_MIN_ACCELERATION_POINTS", 3)

    # Classification thresholds
    rapid_growth_percentage: float = _get_float("SCANFOR_TREND_RAPID_GROWTH_PCT", 50.0)
    rapid_growth_absolute: float = _get_float("SCANFOR_TREND_RAPID_GROWTH_ABS", 10.0)
    minimum_slope_for_worsening: float = _get_float("SCANFOR_TREND_MIN_SLOPE_WORSENING", 1.0)
    minimum_acceleration: float = _get_float("SCANFOR_TREND_MIN_ACCELERATION", 5.0)
    persistent_red_hours: float = _get_float("SCANFOR_TREND_PERSISTENT_RED_HOURS", 2.0)
    spike_recovery_window_minutes: float = _get_float("SCANFOR_TREND_SPIKE_RECOVERY_MIN", 60.0)
    recently_red_lookback_hours: float = _get_float("SCANFOR_TREND_RECENTLY_RED_LOOKBACK_HOURS", 24.0)

    # Flapping
    flapping_window_hours: float = _get_float("SCANFOR_TREND_FLAPPING_WINDOW_HOURS", 1.0)
    flapping_transition_threshold: int = _get_int("SCANFOR_TREND_FLAPPING_TRANSITIONS", 3)

    # Rolling median/MAD baseline (Phase 3 — request Section 6: "robust
    # baseline such as rolling median and median absolute deviation... a
    # single large spike must not permanently inflate the baseline"). Built
    # from each observation's own interval_delta, never re-derived from raw
    # values (that would reintroduce the counter-reset bug this whole rewrite
    # exists to fix).
    baseline_window_hours: float = _get_float("SCANFOR_TREND_BASELINE_WINDOW_HOURS", 6.0)
    min_baseline_points: int = _get_int("SCANFOR_TREND_MIN_BASELINE_POINTS", 3)
    baseline_worsening_multiplier: float = _get_float("SCANFOR_TREND_BASELINE_WORSENING_MULTIPLIER", 2.0)
    baseline_mild_multiplier: float = _get_float("SCANFOR_TREND_BASELINE_MILD_MULTIPLIER", 1.0)
    steady_worsening_min_consecutive: int = _get_int("SCANFOR_TREND_STEADY_WORSENING_MIN_CONSECUTIVE", 3)
    # A rate change below this (errors/hour) never triggers a worsening/spike/
    # accelerating classification regardless of percentage — request Section
    # 6: "minimum absolute floors so tiny changes do not create alarming
    # percentages."
    minimum_absolute_rate_floor: float = _get_float("SCANFOR_TREND_MIN_ABSOLUTE_RATE_FLOOR", 1.0)

    # Change Score weights (Phase 4 — request Section 7's suggested model;
    # sum to 1.0). Rebalanced at runtime over whichever components are
    # available — see trends.py::compute_change_score, which also returns a
    # separate score_confidence so a rebalanced-but-thin score is never
    # mistaken for a fully-backed one.
    change_score_weights: Dict[str, float] = field(default_factory=lambda: {
        "short_term_vs_baseline": _get_float("SCANFOR_CHANGE_SCORE_WEIGHT_SHORT_TERM", 0.30),
        "sustained_1h_vs_baseline": _get_float("SCANFOR_CHANGE_SCORE_WEIGHT_SUSTAINED_1H", 0.25),
        "acceleration": _get_float("SCANFOR_CHANGE_SCORE_WEIGHT_ACCELERATION", 0.20),
        "persistence": _get_float("SCANFOR_CHANGE_SCORE_WEIGHT_PERSISTENCE", 0.15),
        "multi_vm_spread": _get_float("SCANFOR_CHANGE_SCORE_WEIGHT_MULTI_VM", 0.10),
    })
    # affected_vm_count normalization: 1 VM (just itself) scores 0, this many
    # *additional* VMs affected scores 100 — "broadly spreading" per Section 7's
    # interpretation bands.
    multi_vm_spread_reference_count: int = _get_int("SCANFOR_CHANGE_SCORE_MULTI_VM_REFERENCE", 4)

    # How far back to fetch raw history for one alert_key's trend computation.
    # Must cover the largest window above (24h) with margin for irregular
    # processing intervals.
    history_lookback_hours: float = _get_float("SCANFOR_TREND_HISTORY_LOOKBACK_HOURS", 48.0)


TREND_CONFIG = TrendConfig()
