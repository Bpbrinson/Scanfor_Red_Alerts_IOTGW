"""
services/counter_math.py
─────────────────────────────────────────────────────────────────────────────
Reset-aware cumulative-counter math for scanfor_errors metrics.

The source count is a cumulative counter that resets whenever its daily log
file rolls over to a new date suffix (e.g. aerislistener-main.20260716 ->
aerislistener-main.20260717). Naively subtracting (current - previous)
across that boundary produces a large negative number that would otherwise
be misread as a huge improvement. compute_counter_delta() detects a reset
and reports a correct, never-negative interval_delta instead, while always
preserving the raw signed delta for audit.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class CounterMathResult:
    raw_signed_delta: int
    interval_delta: int
    counter_reset_detected: bool
    data_quality_status: str  # "ok" | "unexpected_decrease"


def compute_counter_delta(
    *,
    current_count: int,
    previous_count: Optional[int],
    current_epoch: Optional[str],
    previous_epoch: Optional[str],
    current_raw_filename: Optional[str],
    previous_raw_filename: Optional[str],
    current_state_file: Optional[str],
    previous_state_file: Optional[str],
) -> CounterMathResult:
    """
    Normal update: same epoch/filename/state-file, current >= previous ->
        interval_delta = current - previous.
    Confirmed reset: the date-suffix epoch changed, OR the raw dated log
        filename changed, OR the source state-file identifier changed ->
        interval_delta = current_count (the counter restarted, so the current
        reading already IS this new epoch's total-so-far).
    Unexpected decrease: current < previous but nothing above confirms a
        reset -> can't confidently call it a rollover, so interval_delta is
        conservatively 0 (never negative, never assumed to be new errors)
        and data_quality_status is flagged for review rather than trusted
        silently.
    """
    if previous_count is None:
        # First-ever observation of this alert_key — nothing to compare against.
        return CounterMathResult(
            raw_signed_delta=current_count,
            interval_delta=current_count,
            counter_reset_detected=False,
            data_quality_status="ok",
        )

    raw_signed_delta = current_count - previous_count

    epoch_changed = bool(current_epoch) and bool(previous_epoch) and current_epoch != previous_epoch
    filename_changed = (
        bool(current_raw_filename) and bool(previous_raw_filename) and current_raw_filename != previous_raw_filename
    )
    state_file_changed = (
        bool(current_state_file) and bool(previous_state_file) and current_state_file != previous_state_file
    )
    confirmed_reset = epoch_changed or filename_changed or state_file_changed

    if confirmed_reset:
        return CounterMathResult(
            raw_signed_delta=raw_signed_delta,
            interval_delta=max(current_count, 0),
            counter_reset_detected=True,
            data_quality_status="ok",
        )

    if current_count < previous_count:
        return CounterMathResult(
            raw_signed_delta=raw_signed_delta,
            interval_delta=0,
            counter_reset_detected=False,
            data_quality_status="unexpected_decrease",
        )

    return CounterMathResult(
        raw_signed_delta=raw_signed_delta,
        interval_delta=raw_signed_delta,
        counter_reset_detected=False,
        data_quality_status="ok",
    )


def compute_interval_seconds(current_observed_at: Optional[datetime], previous_observed_at: Optional[datetime]) -> Optional[float]:
    """Elapsed seconds between two observed_at (source-generated) timestamps.
    None if either is missing or the elapsed time isn't strictly positive —
    never a negative or zero denominator for rate calculations."""
    if current_observed_at is None or previous_observed_at is None:
        return None
    delta = (current_observed_at - previous_observed_at).total_seconds()
    return delta if delta > 0 else None


def compute_rate_per_hour(interval_delta: Optional[int], interval_seconds: Optional[float]) -> Optional[float]:
    if interval_delta is None or interval_seconds is None or interval_seconds <= 0:
        return None
    return interval_delta / (interval_seconds / 3600.0)
