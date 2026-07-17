"""
services/trends.py
─────────────────────────────────────────────────────────────────────────────
Multi-window alert-growth and trend-analysis engine.

Rate-based (Phase 3): every change/slope/acceleration signal here is built
from each AlertEvent's already reset-aware `interval_delta`/`rate_per_hour`
(computed once, correctly, at ingestion time — see
backend/services/counter_math.py) instead of re-deriving deltas from the raw
cumulative `count`. A daily counter rollover corrupts a raw-value diff; it
cannot corrupt a sum/regression built from interval_delta, because
interval_delta already accounts for the reset. Nothing here ever recomputes a
delta from two raw `value`s — that would silently reintroduce the exact bug
this rewrite exists to close. `value`/`red_threshold` are kept only for
threshold-excess and "current daily total" display, which are legitimately
count-based.

Design: pure calculation functions operate on an ordered list of Observation
objects (one per historical AlertEvent row for a single alert_key) and never
touch the database — this keeps them trivially unit-testable with fixed
timestamps (see tests/test_trends.py). A thin DB-facing layer at the bottom
batch-fetches history for many alert_keys in ONE query (avoiding an N+1 query
per displayed alert) and adapts AlertEvent rows into Observations.

Nothing here filters, deletes, or mutates AlertEvent rows — this module only
*reads* the history that ingestion (backend/services/prom_ingestor.py)
already preserves for every alert, including noise/suppressed/resolved rows.
Trend metrics are calculated on demand (at API-read time), not precomputed
and stored — raw AlertEvent rows remain the only source of truth; derived
values here can always be recalculated from them.

Alert identity: alert_key = AlertEvent.fingerprint_exact (see
backend/services/fingerprint.py) — reused as-is, not duplicated.
"""

from __future__ import annotations

import logging
from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from backend.database.models import AlertEvent
from backend.services.config import TREND_CONFIG, TrendConfig

_LOG = logging.getLogger(__name__)

# data_quality_status values (backend/services/prom_ingestor.py) meaning the
# source itself can't be trusted this run — these force trend_state to
# data_unavailable regardless of what the (stale/frozen) numbers say.
# "pending_resolution" is deliberately excluded: that state still reflects a
# *healthy* source and a real (if unconfirmed) absence, so it's left to
# classify normally.
_UNHEALTHY_DATA_QUALITY_STATUSES = ("source_missing", "source_stale", "source_parse_failure")

# Median absolute deviation scaling factor so it approximates a standard
# deviation for a normal distribution — the conventional constant.
_MAD_SCALE = 1.4826


# ─── Data shapes ────────────────────────────────────────────────────────────

@dataclass
class Observation:
    """One historical data point for a single alert_key. Lists of these must
    be sorted ascending by observed_at, with the current/latest one last.

    observed_at is the *source*-generated time (AlertEvent.observed_at, with a
    fallback chain for pre-Phase-1 history that predates the column) — trend
    calculations must use this, not wall-clock ingestion time.
    """
    observed_at: datetime
    value: float
    interval_delta: Optional[float] = None
    interval_seconds: Optional[float] = None
    rate_per_hour: Optional[float] = None
    data_quality_status: Optional[str] = None
    color: Optional[str] = None
    is_red: bool = False
    known_error: bool = False
    signal_type: Optional[str] = None
    red_threshold: Optional[float] = None
    category: Optional[str] = None  # "resolved" marks an explicit disappearance


@dataclass
class RateBaseline:
    """Robust (outlier-resistant) summary of interval_delta over a trailing
    window: median and MAD (median absolute deviation, scaled). A single
    large spike can only ever be one of several points the median considers
    — by construction it can't drag the baseline the way a mean would.
    median/mad are None when fewer than the configured minimum number of
    qualifying observations exist in the window (insufficient, never a
    fabricated zero baseline)."""
    median: Optional[float]
    mad: Optional[float]
    sample_count: int


@dataclass
class RedPersistence:
    red_started_at: Optional[datetime]
    red_duration_seconds: Optional[float]
    consecutive_red_snapshots: int


@dataclass
class TrendResult:
    current_value: float
    previous_value: Optional[float]
    absolute_change: Optional[float]
    percentage_change: Optional[float]
    growth_rate_per_hour: Optional[float]
    change_30m: Optional[float]
    percentage_change_30m: Optional[float]
    change_15m: Optional[float]
    percentage_change_15m: Optional[float]
    change_1h: Optional[float]
    percentage_change_1h: Optional[float]
    change_6h: Optional[float]
    percentage_change_6h: Optional[float]
    change_24h: Optional[float]
    percentage_change_24h: Optional[float]
    slope_1h: Optional[float]
    slope_6h: Optional[float]
    acceleration: Optional[float]
    baseline_rate_per_hour: Optional[float]
    baseline_mad: Optional[float]
    threshold_excess_percentage: Optional[float]
    red_started_at: Optional[datetime]
    red_duration_seconds: Optional[float]
    consecutive_red_snapshots: int
    red_state_transition_count: int
    is_flapping: bool
    trend_state: str
    change_score: Optional[float]
    change_score_confidence: Optional[float]
    change_score_components: Dict[str, Optional[float]]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "current_value": self.current_value,
            "previous_value": self.previous_value,
            "absolute_change": self.absolute_change,
            "percentage_change": self.percentage_change,
            "growth_rate_per_hour": self.growth_rate_per_hour,
            "change_30m": self.change_30m,
            "percentage_change_30m": self.percentage_change_30m,
            "change_15m": self.change_15m,
            "percentage_change_15m": self.percentage_change_15m,
            "change_1h": self.change_1h,
            "percentage_change_1h": self.percentage_change_1h,
            "change_6h": self.change_6h,
            "percentage_change_6h": self.percentage_change_6h,
            "change_24h": self.change_24h,
            "percentage_change_24h": self.percentage_change_24h,
            "slope_1h": self.slope_1h,
            "slope_6h": self.slope_6h,
            "acceleration": self.acceleration,
            "baseline_rate_per_hour": self.baseline_rate_per_hour,
            "baseline_mad": self.baseline_mad,
            "threshold_excess_percentage": self.threshold_excess_percentage,
            "red_started_at": self.red_started_at.isoformat() if self.red_started_at else None,
            "red_duration_seconds": self.red_duration_seconds,
            "consecutive_red_snapshots": self.consecutive_red_snapshots,
            "red_state_transition_count": self.red_state_transition_count,
            "is_flapping": self.is_flapping,
            "trend_state": self.trend_state,
            "change_score": self.change_score,
            "change_score_confidence": self.change_score_confidence,
            "change_score_components": self.change_score_components,
        }


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def _safe_hours(later: Optional[datetime], earlier: Optional[datetime]) -> Optional[float]:
    """Elapsed hours between two timestamps, or None if not strictly positive."""
    if later is None or earlier is None:
        return None
    delta = (later - earlier).total_seconds() / 3600.0
    return delta if delta > 0 else None


def _median(values: Sequence[float]) -> float:
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2 == 1:
        return float(ordered[mid])
    return (ordered[mid - 1] + ordered[mid]) / 2.0


# ─── A/B: generic diff helpers (unchanged — just called with different args) ─

def compute_absolute_change(current: float, previous: Optional[float]) -> Optional[float]:
    if previous is None:
        return None
    return current - previous


def compute_percentage_change(current: float, previous: Optional[float]) -> Optional[float]:
    """None means "insufficient history" (no previous/baseline at all) or
    "new occurrence" (previous was zero and current is greater than zero —
    percentage is mathematically undefined, never returned as infinity)."""
    if previous is None:
        return None
    if previous == 0:
        if current > 0:
            return None  # new occurrence
        return 0.0  # both zero
    return ((current - previous) / previous) * 100.0


# ─── Robust rolling baseline (median/MAD) ───────────────────────────────────

def compute_rate_baseline(
    history: Sequence[Observation],
    now: datetime,
    window_hours: float,
    min_points: int,
) -> RateBaseline:
    """Median and MAD of interval_delta over the trailing window_hours,
    built only from observations with a real (non-None) interval_delta — a
    carried-forward/data_unavailable observation contributes nothing here,
    it doesn't fabricate a zero data point."""
    window_start = now - timedelta(hours=window_hours)
    values = [
        obs.interval_delta for obs in history
        if obs.interval_delta is not None and window_start <= obs.observed_at <= now
    ]
    if len(values) < min_points:
        return RateBaseline(None, None, len(values))
    med = _median(values)
    mad = _median([abs(v - med) for v in values]) * _MAD_SCALE
    return RateBaseline(med, mad, len(values))


# ─── C: multi-window change (reset-safe: sums interval_delta, never diffs value) ─

def _observation_at_or_before(history: Sequence[Observation], target_time: datetime) -> Optional[Observation]:
    """Most recent observation at or before target_time. `history` must be
    sorted ascending by observed_at. None if no observation reaches that far
    back (insufficient history for this window — not fabricated)."""
    if not history:
        return None
    times = [obs.observed_at for obs in history]
    idx = bisect_right(times, target_time)
    if idx == 0:
        return None
    return history[idx - 1]


def compute_window_changes(
    history: Sequence[Observation],
    now: datetime,
    config: TrendConfig = TREND_CONFIG,
) -> Dict[str, Dict[str, Optional[float]]]:
    """{"30m": {"change": .., "percentage_change": ..}, "1h": {...}, ...}.
    `change` is the sum of interval_delta for every observation strictly
    after the window's baseline point through `now` — reset-safe, and equal
    to today's "value now minus value N ago" whenever no reset occurred in
    the window. A window with no qualifying baseline point (history doesn't
    reach that far back) returns None for both fields, never a fabricated
    partial sum. `percentage_change` is that sum as a percentage of what the
    window's own robust baseline rate would predict for its duration — a
    reset-safe replacement for comparing against a single raw prior value."""
    current = history[-1] if history else None
    prior = history[:-1] if history else []
    results: Dict[str, Dict[str, Optional[float]]] = {}
    for label, minutes in config.window_minutes.items():
        window_hours = minutes / 60.0
        target_time = now - timedelta(minutes=minutes)
        baseline_point = _observation_at_or_before(prior, target_time) if current else None
        if current is None or baseline_point is None:
            results[label] = {"change": None, "percentage_change": None}
            continue

        change = sum(
            obs.interval_delta for obs in history
            if obs.interval_delta is not None and baseline_point.observed_at < obs.observed_at <= now
        )
        rate_baseline = compute_rate_baseline(prior, target_time, config.baseline_window_hours, config.min_baseline_points)
        expected_total = rate_baseline.median * window_hours if rate_baseline.median is not None else None
        results[label] = {
            "change": change,
            "percentage_change": compute_percentage_change(change, expected_total),
        }
    return results


# ─── D: trend slope (regression on reset-safe cumulative delta) ─────────────

def compute_slope(
    history: Sequence[Observation],
    now: datetime,
    window_hours: float,
    config: TrendConfig = TREND_CONFIG,
) -> Optional[float]:
    """Least-squares slope of cumulative interval_delta vs. hours-elapsed
    within the window, in errors per hour — equivalent to regressing the
    error rate against time, but reset-safe by construction since it's built
    from already reset-aware deltas rather than the raw counter. Requires
    config.min_regression_points qualifying observations within
    [now - window_hours, now]; None otherwise, and None if every point
    shares the same timestamp (zero x-variance — can't fit a line)."""
    window_start = now - timedelta(hours=window_hours)
    points = [
        obs for obs in history
        if obs.interval_delta is not None and window_start <= obs.observed_at <= now
    ]
    if len(points) < config.min_regression_points:
        return None

    points = sorted(points, key=lambda o: o.observed_at)
    t0 = points[0].observed_at
    xs: List[float] = []
    ys: List[float] = []
    cumulative = 0.0
    for obs in points:
        cumulative += obs.interval_delta
        xs.append((obs.observed_at - t0).total_seconds() / 3600.0)
        ys.append(cumulative)

    n = len(xs)
    x_mean = sum(xs) / n
    y_mean = sum(ys) / n
    denom = sum((x - x_mean) ** 2 for x in xs)
    if denom == 0:
        return None
    numer = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
    return numer / denom


# ─── E: acceleration (regression over multiple rate observations) ──────────

def compute_acceleration(
    history: Sequence[Observation],
    config: TrendConfig = TREND_CONFIG,
) -> Optional[float]:
    """Regression slope of rate_per_hour vs. elapsed time over the most
    recent config.min_acceleration_points observations with a valid rate —
    requires a *consistent* multi-point trend, never just the two most
    recent intervals. The request explicitly warns against classifying
    acceleration from a single large delta; today's two-point diff was
    exactly that, so this is a real methodology change, not a relabeling."""
    points = [obs for obs in history if obs.rate_per_hour is not None]
    if len(points) < config.min_acceleration_points:
        return None
    recent = points[-config.min_acceleration_points:]

    t0 = recent[0].observed_at
    xs = [(obs.observed_at - t0).total_seconds() / 3600.0 for obs in recent]
    ys = [obs.rate_per_hour for obs in recent]
    n = len(xs)
    x_mean = sum(xs) / n
    y_mean = sum(ys) / n
    denom = sum((x - x_mean) ** 2 for x in xs)
    if denom == 0:
        return None
    numer = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
    return numer / denom


# ─── F: threshold excess (unchanged — count vs. threshold, not rate-based) ──

def compute_threshold_excess_percentage(current_value: float, red_threshold: Optional[float]) -> Optional[float]:
    if red_threshold is None or red_threshold <= 0:
        return None
    return ((current_value - red_threshold) / red_threshold) * 100.0


# ─── G: red duration / persistence ───────────────────────────────────────────

def compute_red_persistence(history: Sequence[Observation]) -> RedPersistence:
    """Walks backward from the latest observation.

    Because ingestion always writes a row for a tracked alert_key on every
    run it's still relevant to — either a normal observation (red or not), a
    carried-forward observation, or an explicit "resolved" row the moment a
    healthy scan confirms it's gone — every row in this table is a genuine,
    explicit observation. A gap in *time* between two stored rows just means
    no ingestion ran in between; it is never treated as a silent "was it
    red?" guess. A resolved row (or any non-red row) always and immediately
    ends the current red streak.
    """
    if not history:
        return RedPersistence(None, None, 0)

    current = history[-1]
    if not current.is_red or current.category == "resolved":
        return RedPersistence(None, None, 0)

    consecutive = 0
    red_started_at = current.observed_at
    for obs in reversed(history):
        if obs.is_red and obs.category != "resolved":
            consecutive += 1
            red_started_at = obs.observed_at
        else:
            break

    duration = (current.observed_at - red_started_at).total_seconds()
    return RedPersistence(red_started_at, duration, consecutive)


def _consecutive_above_threshold(history: Sequence[Observation], threshold: float) -> int:
    """Trailing count of observations (walking back from the latest) whose
    own rate_per_hour is *strictly* above `threshold` — the multi-scan
    confirmation worsening_steadily requires, mirroring how
    compute_red_persistence counts a consecutive red streak. Strict, not
    `>=`: when a baseline has zero variance (MAD=0), the threshold equals
    the median exactly, and a perfectly flat, unchanging rate must not count
    as "above" its own unchanging baseline."""
    count = 0
    for obs in reversed(history):
        if obs.rate_per_hour is not None and obs.rate_per_hour > threshold:
            count += 1
        else:
            break
    return count


# ─── H: flapping ─────────────────────────────────────────────────────────────

def compute_flapping(
    history: Sequence[Observation],
    now: datetime,
    config: TrendConfig = TREND_CONFIG,
) -> Tuple[int, bool]:
    """Counts red↔non-red transitions within config.flapping_window_hours.
    is_flapping is true once the count reaches config.flapping_transition_threshold."""
    window_start = now - timedelta(hours=config.flapping_window_hours)
    points = [obs for obs in history if window_start <= obs.observed_at <= now]
    transitions = 0
    for prev_obs, next_obs in zip(points, points[1:]):
        if prev_obs.is_red != next_obs.is_red:
            transitions += 1
    return transitions, transitions >= config.flapping_transition_threshold


# ─── Step 5: trend classification (14 states + kept `improving`) ───────────

def classify_trend(
    *,
    current: Observation,
    previous: Optional[Observation],
    baseline: RateBaseline,
    change_1h: Optional[float],
    slope_1h: Optional[float],
    slope_6h: Optional[float],
    acceleration: Optional[float],
    threshold_excess_percentage: Optional[float],
    persistence: RedPersistence,
    is_flapping: bool,
    history: Sequence[Observation],
    now: datetime,
    config: TrendConfig,
) -> str:
    """Deterministic precedence chain (checked in this exact order):

        data_unavailable > resolved > flapping > new > insufficient_history >
        accelerating > worsening_rapidly > spike > cooling > resolving >
        worsening_steadily > slow_growth > persistent > stable

    `improving` is kept as an additional, non-required 15th state (see
    project docs) for "was red recently, already transitioned back on an
    earlier scan" — request Section 6's list is framed as "such as"
    (illustrative), and there's no clean replacement for this exact case
    among the 14 named states without conflating it with `cooling` (whose
    own wording implies the error is still *present*).

    Judgment calls made explicit here since the spec leaves them interpretive:

      - "data_unavailable" fires before everything else — an untrustworthy
        source makes every other signal untrustworthy too.
      - "resolved" now checks category == "resolved" directly (Phase 2's
        authoritative marker) instead of a fragile color-transition guess.
      - "cooling" = still meaningfully above the robust baseline, but the
        rate's own recent slope (acceleration) is negative — "remains
        present, but arrival rate is decreasing," per the request's literal
        wording.
      - "resolving" = at-or-below the baseline's "mild" threshold *and* still
        on a confirmed declining trend — no more meaningful new errors
        arriving, just hasn't flipped state yet. Checked before slow_growth
        so a declining-but-still-positive rate isn't mistaken for ongoing
        growth.
      - "slow_growth" = positive, above the noise floor, *not* declining, not
        yet a confirmed steady multi-scan pattern.
      - "worsening_steadily" requires config.steady_worsening_min_consecutive
        scans each above the baseline's mild threshold — a genuine multi-scan
        confirmation, not just "currently above baseline once."
      - "persistent" is reachable for a red alert whose rate is quiet (below
        the absolute floor) but has stayed red beyond the configured
        duration — neither growing nor declining, just stuck.
      - A rate below config.minimum_absolute_rate_floor never triggers
        accelerating/worsening_rapidly/worsening_steadily/slow_growth
        regardless of how large a percentage it represents.
    """
    if current.data_quality_status in _UNHEALTHY_DATA_QUALITY_STATUSES:
        return "data_unavailable"

    if current.category == "resolved":
        return "resolved"

    if is_flapping:
        return "flapping"

    if previous is None:
        return "new"

    # insufficient_history only gates the red/rate-based ladder below — the
    # non-red path (improving/stable) doesn't depend on the baseline at all,
    # so a thin history must not block it from classifying correctly.
    if current.is_red and baseline.median is None:
        return "insufficient_history"

    current_rate = current.rate_per_hour if current.rate_per_hour is not None else 0.0
    above_floor = current_rate >= config.minimum_absolute_rate_floor
    mild_threshold = (baseline.median or 0.0) + config.baseline_mild_multiplier * (baseline.mad or 0.0)
    worsening_threshold = (baseline.median or 0.0) + config.baseline_worsening_multiplier * (baseline.mad or 0.0)

    if current.is_red:
        # accelerating — rate itself confirmed rising across multiple scans.
        if above_floor and acceleration is not None and acceleration >= config.minimum_acceleration:
            return "accelerating"

        # worsening_rapidly — substantially above baseline (strictly, not
        # just at-or-equal: when a baseline has zero variance, its threshold
        # equals the median exactly, and an unchanging rate must not count
        # as "substantially above" its own flat history) for at least two
        # consecutive scans (a *confirmed* jump), or above a known-issue
        # operational threshold when one is configured. The one-or-two-scan,
        # not-yet-confirmed case is "spike" instead, checked next.
        substantially_above_known_threshold = (
            threshold_excess_percentage is not None and threshold_excess_percentage >= config.rapid_growth_percentage
        )
        if above_floor and _consecutive_above_threshold(history, worsening_threshold) >= 2:
            return "worsening_rapidly"
        if substantially_above_known_threshold:
            return "worsening_rapidly"

        # spike — this scan (or the short-term 1h window) is far above
        # baseline, but not yet confirmed by either a second consecutive
        # scan (above) or the 6h slope — "one or two short intervals... but
        # sustained growth is not yet confirmed," per the request.
        current_scan_spike = above_floor and current_rate > worsening_threshold
        short_term_spike = above_floor and change_1h is not None and change_1h >= config.rapid_growth_absolute
        if current_scan_spike or (short_term_spike and (slope_6h is None or slope_6h < config.minimum_slope_for_worsening)):
            return "spike"

        # cooling/resolving both require a *meaningfully* confirmed decline
        # — the same magnitude bar as config.minimum_acceleration, not just
        # any negative number (a hair below zero is noise, not a confirmed
        # decline). Checked before worsening_steadily/slow_growth: a
        # declining-but-still-elevated run must never read as "worsening"
        # just because it's technically stayed above the mild threshold for
        # a few scans on its way down.
        declining = acceleration is not None and acceleration <= -config.minimum_acceleration

        # cooling — still meaningfully above baseline, but decelerating:
        # "remains present, but arrival rate is decreasing" (request's literal
        # wording).
        if current_rate > mild_threshold and declining:
            return "cooling"

        # resolving — back at/below baseline *and* still on a declining
        # trend — not just quietly low all along (that's persistent/stable).
        if current_rate <= mild_threshold and declining:
            return "resolving"

        # worsening_steadily — confirmed multi-scan pattern above baseline
        # (and, per the declining check above, not on its way back down).
        if _consecutive_above_threshold(history, mild_threshold) >= config.steady_worsening_min_consecutive:
            return "worsening_steadily"

        # slow_growth — positive, above the noise floor, not declining, not
        # yet a confirmed steady pattern (could be the start of one, or just
        # low-level noise).
        if above_floor and current_rate > 0:
            return "slow_growth"

        # persistent — continuously red for the configured duration, at a
        # low/quiet (not above-floor) rate that's neither growing nor
        # declining.
        if (
            persistence.red_duration_seconds is not None
            and persistence.red_duration_seconds >= config.persistent_red_hours * 3600
        ):
            return "persistent"

        return "stable"

    # Not currently red.
    lookback_start = now - timedelta(hours=config.recently_red_lookback_hours)
    was_recently_red = any(obs.is_red and obs.observed_at >= lookback_start for obs in history[:-1])
    if was_recently_red:
        return "improving"

    return "stable"


# ─── Step 6: explainable Change Score (request Section 7) ──────────────────

def _normalize_ratio(value: Optional[float], reference: float, cap_multiplier: float = 2.0) -> Optional[float]:
    """value=0 -> 0, value=reference*cap_multiplier -> 100, clamped, linear
    between (and clamped for negatives/overshoot too). None if the input is
    missing or the reference is invalid — never crashes."""
    if value is None or reference is None or reference <= 0:
        return None
    return _clamp((value / (reference * cap_multiplier)) * 100.0)


def _normalize_vs_baseline(rate: Optional[float], baseline: "RateBaseline", config: TrendConfig) -> Optional[float]:
    """0 at the baseline median, 100 at baseline_worsening_multiplier MADs
    above it — the same "substantially above baseline" line Section 6's
    classify_trend uses for worsening_rapidly, so there's one documented
    threshold instead of two. Falls back to minimum_absolute_rate_floor as
    the comparison scale when the baseline has zero variance (MAD=0) — a
    perfectly flat history shouldn't uniformly zero out this component."""
    if rate is None or baseline.median is None:
        return None
    reference = (baseline.mad or 0.0) * config.baseline_worsening_multiplier
    if reference <= 0:
        reference = config.minimum_absolute_rate_floor
    return _clamp(((rate - baseline.median) / reference) * 100.0)


def compute_change_score(
    *,
    short_term_rate: Optional[float],
    sustained_1h_rate: Optional[float],
    baseline: "RateBaseline",
    acceleration: Optional[float],
    red_duration_seconds: Optional[float],
    affected_vm_count: Optional[int],
    config: TrendConfig = TREND_CONFIG,
) -> Tuple[Optional[float], Optional[float], Dict[str, Optional[float]]]:
    """Fixed 0-100 Change Score ranking how urgently this alert's behavior is
    changing (request Section 7) — not a replacement for trend_state or the
    raw measurements, and not a triage-priority/business-impact score either.
    Returns (change_score, score_confidence, components).

    Five components, weighted per config.change_score_weights (defaults match
    Section 7's suggested model — 30/25/20/15/10, summing to 1.0):

      - short_term_vs_baseline: the latest single scan's own rate, compared
        against the robust baseline (see _normalize_vs_baseline above).
      - sustained_1h_vs_baseline: same comparison, using the trailing hour's
        total (numerically an hourly rate) instead of one scan — "sustained"
        vs. "short-term."
      - acceleration: _normalize_ratio(acceleration, minimum_acceleration) —
        unchanged from the prior formula.
      - persistence: _normalize_ratio(red_duration_seconds,
        persistent_red_hours * 3600, cap_multiplier=1.0) — unchanged.
      - multi_vm_spread: _normalize_ratio(affected_vm_count - 1,
        multi_vm_spread_reference_count, cap_multiplier=1.0) — 1 VM (just
        itself) scores 0, reference_count+1 VMs scores 100.

    change_score itself is rebalanced over whichever components are actually
    available (proportionally, same behavior as before) so a new-ish alert
    still gets an actionable number rather than None. score_confidence is
    the part of Section 7 that behavior alone doesn't satisfy — it's the
    *un-rebalanced* fraction of total weight actually backed by real data
    (sum of available components' weights, as a 0-100 percentage). An alert
    scored entirely off `persistence` alone gets whatever that one component
    says (rebalanced to look like a full 0-100 score, as before) but
    `score_confidence == 15.0` — honest that 85% of the model had nothing to
    say, exactly what Section 7 asks for ("do not rebalance... in a way that
    makes a low-history score appear comparable to a full-history score").

    Suggested interpretation (Section 7, guidance only — not enforced against
    trend_state, which is computed independently from the same data):
    0-19 stable/little change, 20-39 slow growth, 40-59 sustained growth,
    60-79 rapid growth/significant spike, 80-100 strongly accelerating or
    broadly spreading.
    """
    short_term_score = _normalize_vs_baseline(short_term_rate, baseline, config)
    sustained_score = _normalize_vs_baseline(sustained_1h_rate, baseline, config)
    accel_score = _normalize_ratio(acceleration, config.minimum_acceleration) if acceleration is not None else None
    persistence_score = (
        _normalize_ratio(red_duration_seconds, config.persistent_red_hours * 3600, cap_multiplier=1.0)
        if red_duration_seconds is not None
        else None
    )
    multi_vm_score = (
        _normalize_ratio(affected_vm_count - 1, config.multi_vm_spread_reference_count, cap_multiplier=1.0)
        if affected_vm_count is not None
        else None
    )

    components: Dict[str, Optional[float]] = {
        "short_term_vs_baseline": short_term_score,
        "sustained_1h_vs_baseline": sustained_score,
        "acceleration": accel_score,
        "persistence": persistence_score,
        "multi_vm_spread": multi_vm_score,
    }

    available = {k: v for k, v in components.items() if v is not None}
    if not available:
        return None, None, components

    total_weight = sum(config.change_score_weights.get(k, 0.0) for k in available)
    if total_weight <= 0:
        return None, None, components

    score = sum(available[k] * config.change_score_weights.get(k, 0.0) for k in available) / total_weight
    score_confidence = round(total_weight * 100.0, 1)
    return round(_clamp(score), 1), score_confidence, components


# ─── Main entry point: compute everything for one alert_key's history ──────

def compute_trends(
    history: Sequence[Observation],
    now: Optional[datetime] = None,
    affected_vm_count: Optional[int] = None,
    config: TrendConfig = TREND_CONFIG,
) -> TrendResult:
    """`history` must be sorted ascending by observed_at, current/latest
    last. Never raises for missing data — everything degrades to None fields,
    not exceptions, so one malformed/thin alert can't break a batch. `now`
    defaults to the latest observation's own timestamp (not wall-clock), so
    window/slope calculations are anchored to when the alert was actually
    last observed, giving deterministic, reproducible results regardless of
    when the API happens to be called. `affected_vm_count` feeds the Change
    Score's multi_vm_spread component (see compute_change_score) — it's a
    per-batch signal computed outside this module (backend/routes/alerts.py),
    passed in rather than queried here to keep this module DB-free."""
    if not history:
        raise ValueError("compute_trends requires at least one observation")

    current = history[-1]
    previous = history[-2] if len(history) >= 2 else None
    now = now or current.observed_at

    # Baseline is built from *prior* observations only — it represents "what
    # was normal before this observation," the reference the current one is
    # judged against. Including the current point would let a spike partly
    # inflate its own baseline.
    baseline = compute_rate_baseline(history[:-1], now, config.baseline_window_hours, config.min_baseline_points)

    # Latest interval delta / latest error rate — already computed correctly
    # at ingestion time, just surfaced here. None (not the raw interval_delta)
    # for a genuinely first-ever observation: there's no prior state for
    # anything to have "changed" from yet, even though ingestion's own
    # interval_delta for a first sighting equals the count itself.
    if previous is None or current.interval_delta is None:
        absolute_change = None
        percentage_change = None
    else:
        absolute_change = current.interval_delta
        percentage_change = compute_percentage_change(current.interval_delta, baseline.median)
    growth_rate_per_hour = current.rate_per_hour

    windows = compute_window_changes(history, now, config)
    slope_1h = compute_slope(history, now, 1.0, config)
    slope_6h = compute_slope(history, now, 6.0, config)
    acceleration = compute_acceleration(history, config)
    threshold_excess = compute_threshold_excess_percentage(current.value, current.red_threshold)
    persistence = compute_red_persistence(history)
    transitions, is_flapping = compute_flapping(history, now, config)

    trend_state = classify_trend(
        current=current,
        previous=previous,
        baseline=baseline,
        change_1h=windows["1h"]["change"],
        slope_1h=slope_1h,
        slope_6h=slope_6h,
        acceleration=acceleration,
        threshold_excess_percentage=threshold_excess,
        persistence=persistence,
        is_flapping=is_flapping,
        history=history,
        now=now,
        config=config,
    )

    change_score, score_confidence, components = compute_change_score(
        short_term_rate=current.rate_per_hour,
        sustained_1h_rate=windows["1h"]["change"],
        baseline=baseline,
        acceleration=acceleration,
        red_duration_seconds=persistence.red_duration_seconds,
        affected_vm_count=affected_vm_count,
        config=config,
    )

    return TrendResult(
        current_value=current.value,
        previous_value=previous.value if previous else None,
        absolute_change=absolute_change,
        percentage_change=percentage_change,
        growth_rate_per_hour=growth_rate_per_hour,
        change_30m=windows["30m"]["change"],
        percentage_change_30m=windows["30m"]["percentage_change"],
        change_15m=windows["15m"]["change"],
        percentage_change_15m=windows["15m"]["percentage_change"],
        change_1h=windows["1h"]["change"],
        percentage_change_1h=windows["1h"]["percentage_change"],
        change_6h=windows["6h"]["change"],
        percentage_change_6h=windows["6h"]["percentage_change"],
        change_24h=windows["24h"]["change"],
        percentage_change_24h=windows["24h"]["percentage_change"],
        slope_1h=slope_1h,
        slope_6h=slope_6h,
        acceleration=acceleration,
        baseline_rate_per_hour=baseline.median,
        baseline_mad=baseline.mad,
        threshold_excess_percentage=threshold_excess,
        red_started_at=persistence.red_started_at,
        red_duration_seconds=persistence.red_duration_seconds,
        consecutive_red_snapshots=persistence.consecutive_red_snapshots,
        red_state_transition_count=transitions,
        is_flapping=is_flapping,
        trend_state=trend_state,
        change_score=change_score,
        change_score_confidence=score_confidence,
        change_score_components=components,
    )


# ─── DB-facing layer: batch fetch (avoids N+1) ──────────────────────────────

def _observation_from_event(event: AlertEvent) -> Observation:
    return Observation(
        observed_at=event.observed_at or event.processed_at or event.created_at,
        value=float(event.count or 0),
        interval_delta=event.interval_delta,
        interval_seconds=event.interval_seconds,
        rate_per_hour=event.rate_per_hour,
        data_quality_status=event.data_quality_status,
        color=event.color,
        is_red=bool(event.is_red),
        known_error=(event.raw_known_error or "").strip().lower() == "true",
        signal_type=event.signal_type,
        red_threshold=event.red_threshold,
        category=event.category,
    )


def get_trends_for_alert_keys(
    db: Session,
    alert_keys: Sequence[str],
    now: Optional[datetime] = None,
    affected_vm_counts: Optional[Dict[str, int]] = None,
    config: TrendConfig = TREND_CONFIG,
) -> Dict[str, TrendResult]:
    """Batch-computes trends for many alert_keys in ONE query — avoids an N+1
    query per displayed alert. Bounded to config.history_lookback_hours of
    history per key. A single alert's history failing to compute (logged,
    never raised further) is simply omitted from the result rather than
    failing the whole batch. `affected_vm_counts` (alert_key -> count) feeds
    the Change Score's multi_vm_spread component — computed by the caller
    (backend/routes/alerts.py already batches this per-batch_id for display;
    Phase 4 just also hands it to the score) since it isn't part of one
    alert_key's own AlertEvent history."""
    unique_keys = [key for key in dict.fromkeys(alert_keys) if key]
    if not unique_keys:
        return {}

    affected_vm_counts = affected_vm_counts or {}

    now = now or datetime.utcnow()
    cutoff = now - timedelta(hours=config.history_lookback_hours)

    rows = (
        db.query(AlertEvent)
        .filter(
            AlertEvent.fingerprint_exact.in_(unique_keys),
            AlertEvent.processed_at.isnot(None),
            AlertEvent.processed_at >= cutoff,
        )
        .order_by(AlertEvent.fingerprint_exact.asc(), AlertEvent.processed_at.asc())
        .all()
    )

    by_key: Dict[str, List[Observation]] = {}
    for row in rows:
        by_key.setdefault(row.fingerprint_exact, []).append(_observation_from_event(row))
    for key, observations in by_key.items():
        observations.sort(key=lambda o: o.observed_at)

    results: Dict[str, TrendResult] = {}
    for key in unique_keys:
        history = by_key.get(key)
        if not history:
            continue
        try:
            results[key] = compute_trends(
                history, now=history[-1].observed_at,
                affected_vm_count=affected_vm_counts.get(key), config=config,
            )
        except Exception:
            _LOG.exception("trend calculation failed for alert_key=%s", key)
            continue
    return results


# ─── Step 7: multi-VM pattern detection ─────────────────────────────────────

@dataclass
class MultiVMPattern:
    affected_vm_count: int
    affected_vms: List[str]
    aggregate_current_value: float
    aggregate_change_1h: Optional[float]
    aggregate_slope_1h: Optional[float]
    first_seen_at: Optional[datetime]
    last_seen_at: Optional[datetime]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "affected_vm_count": self.affected_vm_count,
            "affected_vms": self.affected_vms,
            "aggregate_current_value": self.aggregate_current_value,
            "aggregate_change_1h": self.aggregate_change_1h,
            "aggregate_slope_1h": self.aggregate_slope_1h,
            "first_seen_at": self.first_seen_at.isoformat() if self.first_seen_at else None,
            "last_seen_at": self.last_seen_at.isoformat() if self.last_seen_at else None,
        }


def get_multi_vm_pattern(
    db: Session,
    tenant: Optional[str],
    system: Optional[str],
    error_type: Optional[str],
    log_file: Optional[str],
    now: Optional[datetime] = None,
    config: TrendConfig = TREND_CONFIG,
) -> MultiVMPattern:
    """Detects the same error/metric signature (tenant + system + error_type
    + log_file, deliberately excluding hostname) currently red across
    multiple VMs. Does NOT duplicate raw rows — it aggregates the existing
    per-hostname history into a synthetic summed series and reuses the same
    change/slope math already defined above.

    Note: fingerprint_general still embeds the hostname (only trailing digits
    or "-vm-NN" suffixes are stripped — see fingerprint.py), so it does not
    collapse hostnames like "cars-cars1-..." vs "cars-cars2-..." into one
    key in this project's naming convention. Grouping by the raw stored
    columns instead is what actually finds "same error, multiple VMs" here.
    """
    now = now or datetime.utcnow()
    cutoff = now - timedelta(hours=config.history_lookback_hours)

    rows = (
        db.query(AlertEvent)
        .filter(
            AlertEvent.tenant == tenant,
            AlertEvent.system == system,
            AlertEvent.error_type == error_type,
            AlertEvent.log_file == log_file,
            AlertEvent.processed_at.isnot(None),
            AlertEvent.processed_at >= cutoff,
        )
        .order_by(AlertEvent.processed_at.asc())
        .all()
    )
    if not rows:
        return MultiVMPattern(0, [], 0.0, None, None, None, None)

    # Ascending order, so the last row written per host is its latest state.
    latest_by_host: Dict[str, AlertEvent] = {}
    for row in rows:
        latest_by_host[row.hostname] = row
    affected = sorted(host for host, row in latest_by_host.items() if row.is_red)
    aggregate_current_value = float(sum(row.count or 0 for row in latest_by_host.values() if row.is_red))

    by_time: Dict[datetime, float] = {}
    by_time_delta: Dict[datetime, float] = {}
    for row in rows:
        observed_at = row.observed_at or row.processed_at or row.created_at
        by_time[observed_at] = by_time.get(observed_at, 0.0) + float(row.count or 0)
        if row.interval_delta is not None:
            by_time_delta[observed_at] = by_time_delta.get(observed_at, 0.0) + float(row.interval_delta)
    synthetic = [
        Observation(observed_at=t, value=v, interval_delta=by_time_delta.get(t))
        for t, v in sorted(by_time.items())
    ]

    aggregate_change_1h = None
    aggregate_slope_1h = None
    if synthetic:
        windows = compute_window_changes(synthetic, synthetic[-1].observed_at, config)
        aggregate_change_1h = windows["1h"]["change"]
        aggregate_slope_1h = compute_slope(synthetic, synthetic[-1].observed_at, 1.0, config)

    return MultiVMPattern(
        affected_vm_count=len(affected),
        affected_vms=affected,
        aggregate_current_value=aggregate_current_value,
        aggregate_change_1h=aggregate_change_1h,
        aggregate_slope_1h=aggregate_slope_1h,
        first_seen_at=min((row.processed_at for row in rows), default=None),
        last_seen_at=max((row.processed_at for row in rows), default=None),
    )


def get_affected_vm_counts_for_batch(db: Session, batch_id: str) -> Dict[Tuple[str, str, str, str], int]:
    """One query: for every (tenant, system, error_type, log_file) signature
    currently red in the given batch, how many distinct hostnames are
    affected. Used to populate affected_vm_count on each returned alert
    without an N+1 query per row (see backend/routes/alerts.py)."""
    rows = (
        db.query(
            AlertEvent.tenant, AlertEvent.system, AlertEvent.error_type, AlertEvent.log_file, AlertEvent.hostname
        )
        .filter(AlertEvent.batch_id == batch_id, AlertEvent.is_red.is_(True))
        .distinct()
        .all()
    )
    counts: Dict[Tuple[str, str, str, str], int] = {}
    for tenant, system, error_type, log_file, _hostname in rows:
        key = (tenant, system, error_type, log_file)
        counts[key] = counts.get(key, 0) + 1
    return counts
