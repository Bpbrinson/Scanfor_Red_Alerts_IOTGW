"""
Tests for backend/services/trends.py — rate-based multi-window growth,
regression-based slope/acceleration, robust median/MAD baseline,
classification (14 states + kept `improving`), and the Change Score.

All timestamps are fixed (never datetime.utcnow() inside a test) so results
are fully deterministic. Fixtures build Observations directly from
interval_delta/rate_per_hour (as real ingestion would compute them) rather
than raw value sequences — trend math must never re-derive a delta from two
raw counts, since that's exactly the counter-reset bug this rewrite exists to
close (see test_reset_safe_* below for the acceptance case).
"""

from datetime import datetime, timedelta

import pytest

from backend.database.models import AlertBatch, AlertEvent
from backend.services.config import TrendConfig
from backend.services.trends import (
    Observation,
    RateBaseline,
    compute_acceleration,
    compute_change_score,
    compute_percentage_change,
    compute_rate_baseline,
    compute_red_persistence,
    compute_slope,
    compute_threshold_excess_percentage,
    compute_trends,
    compute_window_changes,
    get_affected_vm_counts_for_batch,
    get_multi_vm_pattern,
    get_trends_for_alert_keys,
)

BASE = datetime(2026, 1, 1, 0, 0, 0)
CFG = TrendConfig()  # default config, explicit for readability in assertions


def obs(hours, interval_delta=None, interval_seconds=3600.0, is_red=True, color="red",
        category=None, red_threshold=None, data_quality_status=None):
    """One Observation at BASE + hours. interval_delta is the new errors
    since the previous observation — already reset-aware, exactly as
    real ingestion (backend/services/counter_math.py) would compute it.
    rate_per_hour is derived from it, matching compute_rate_per_hour."""
    rate_per_hour = None
    if interval_delta is not None and interval_seconds:
        rate_per_hour = interval_delta / (interval_seconds / 3600.0)
    return Observation(
        observed_at=BASE + timedelta(hours=hours),
        value=interval_delta if interval_delta is not None else 0,
        interval_delta=interval_delta,
        interval_seconds=interval_seconds if interval_delta is not None else None,
        rate_per_hour=rate_per_hour,
        data_quality_status=data_quality_status,
        color=color,
        is_red=is_red,
        red_threshold=red_threshold,
        category=category,
    )


# A realistic established baseline: modest natural variance around ~5/hr,
# median=5.5, MAD~1.48 -> mild threshold ~6.98, worsening threshold ~8.47.
# Reused by several classification tests below.
_BASELINE_RATES = [3, 5, 4, 6, 5, 4, 5, 6, 4, 5]


def _with_baseline(*extra):
    return [obs(i, d) for i, d in enumerate(_BASELINE_RATES)] + list(extra)


# ─── 1-6: absolute/percentage change, growth rate, edge cases ──────────────

def test_1_first_ever_observation_has_no_previous():
    result = compute_trends([obs(0, interval_delta=10)])
    assert result.previous_value is None
    assert result.absolute_change is None
    assert result.percentage_change is None
    assert result.trend_state == "new"


def test_2_percentage_change_undefined_when_baseline_is_zero_or_missing():
    # Generic helper: previous=0, current positive -> undefined (not infinity).
    assert compute_percentage_change(current=5, previous=0) is None
    assert compute_percentage_change(current=0, previous=0) == 0.0

    # Only 2 observations exist -> baseline is insufficient (needs
    # min_baseline_points=3) -> percentage_change is None, not fabricated.
    result = compute_trends([obs(0, interval_delta=0, is_red=False), obs(1, interval_delta=5)], now=BASE + timedelta(hours=1))
    assert result.absolute_change == 5
    assert result.percentage_change is None


def test_3_zero_change_against_an_established_zero_baseline_is_zero_percent():
    history = [obs(i, interval_delta=0, is_red=False) for i in range(4)]
    result = compute_trends(history, now=BASE + timedelta(hours=3))
    assert result.absolute_change == 0
    assert result.percentage_change == pytest.approx(0.0)


def test_4_positive_absolute_and_percentage_growth():
    # Baseline (first 3 scans) steady at 10/hr; then a scan at 20/hr -> the
    # latest interval delta is 20, +100% relative to the established baseline.
    history = [obs(i, interval_delta=10) for i in range(3)] + [obs(3, interval_delta=20)]
    result = compute_trends(history, now=BASE + timedelta(hours=3))
    assert result.absolute_change == 20
    assert result.percentage_change == pytest.approx(100.0)


def test_5_negative_growth():
    history = [obs(i, interval_delta=10) for i in range(3)] + [obs(3, interval_delta=6)]
    result = compute_trends(history, now=BASE + timedelta(hours=3))
    assert result.absolute_change == 6  # latest interval delta, as-is
    assert result.percentage_change == pytest.approx(-40.0)  # -40% vs. the baseline of 10


def test_6_irregular_intervals_use_actual_elapsed_observed_time():
    # 30 minutes apart, not the "assumed" 1 hour.
    history = [obs(0, interval_delta=10, interval_seconds=1800), obs(0.5, interval_delta=15, interval_seconds=1800)]
    result = compute_trends(history, now=BASE + timedelta(minutes=30))
    assert result.growth_rate_per_hour == pytest.approx(30.0)  # 15 units over 0.5h
    # Only 30 minutes of real history exists — a "1h ago" baseline must not
    # be fabricated just because the window is nominally 1h wide.
    windows = compute_window_changes(history, now=BASE + timedelta(minutes=30))
    assert windows["1h"]["change"] is None


# ─── 7-9: multi-window changes tolerate missing history ────────────────────

def test_7_missing_15m_history_returns_null_not_fabricated():
    history = [obs(0, interval_delta=10), obs(5 / 60, interval_delta=5, interval_seconds=300)]
    windows = compute_window_changes(history, now=BASE + timedelta(minutes=5))
    assert windows["15m"]["change"] is None
    assert windows["15m"]["percentage_change"] is None


def test_8_missing_1h_history_returns_null():
    history = [obs(0, interval_delta=10)]
    windows = compute_window_changes(history, now=BASE)
    assert windows["1h"]["change"] is None


def test_9_missing_6h_history_returns_null_while_shorter_windows_succeed():
    history = [obs(0, interval_delta=10), obs(0.9, interval_delta=5)]
    now = BASE + timedelta(hours=1)
    windows = compute_window_changes(history, now=now)
    assert windows["1h"]["change"] == pytest.approx(5)  # baseline at hour 0 exists
    assert windows["6h"]["change"] is None  # nothing 6h back


def test_30m_window_added_for_the_rolling_rate_request():
    history = [obs(0, interval_delta=10), obs(0.5, interval_delta=15)]
    windows = compute_window_changes(history, now=BASE + timedelta(minutes=30))
    assert windows["30m"]["change"] == pytest.approx(15)


# ─── 10-11: regression slope on reset-safe cumulative delta ────────────────

def test_10_slope_with_known_values():
    # Perfectly steady +10/hr for 4 hours -> cumulative-delta slope = 10/hr.
    history = [obs(i, interval_delta=10) for i in range(5)]
    slope = compute_slope(history, now=BASE + timedelta(hours=4), window_hours=4, config=CFG)
    assert slope == pytest.approx(10.0, abs=0.01)


def test_11_too_few_points_for_regression_returns_null():
    history = [obs(0, interval_delta=10), obs(1, interval_delta=20)]  # only 2 points; default minimum is 3
    slope = compute_slope(history, now=BASE + timedelta(hours=1), window_hours=1, config=CFG)
    assert slope is None


# ─── 12: acceleration (regression over multiple rate observations) ────────

def test_12_acceleration_confirmed_across_three_points_not_just_the_last_two():
    # Rate itself rising by +10/hr each hour, confirmed across 3 points (not
    # just the most recent pair, which the request explicitly warns against
    # using alone) -> acceleration regression slope = +10/hr/hr.
    history = [obs(0, interval_delta=10), obs(1, interval_delta=20), obs(2, interval_delta=30)]
    result = compute_trends(history, now=BASE + timedelta(hours=2))
    assert result.acceleration == pytest.approx(10.0)


def test_acceleration_none_below_minimum_points():
    history = [obs(0, interval_delta=0), obs(1, interval_delta=10)]
    assert compute_acceleration(history, CFG) is None


# ─── 13-22: trend classification (14 states + kept `improving`) ───────────

def test_13_new_red_alert():
    result = compute_trends([obs(0, interval_delta=50)])
    assert result.trend_state == "new"


def test_14_steady_worsening_alert():
    # An established, moderately-varying baseline (~5/hr), then 3 consecutive
    # scans consistently above the "mild" threshold but below "worsening" —
    # a confirmed multi-scan pattern, not a single dramatic jump.
    history = _with_baseline(obs(10, 8), obs(11, 8), obs(12, 8))
    result = compute_trends(history, now=BASE + timedelta(hours=12))
    assert result.trend_state == "worsening_steadily"


def test_15_accelerating_alert():
    history = [obs(0, interval_delta=2), obs(1, interval_delta=2), obs(2, interval_delta=3),
               obs(3, interval_delta=10), obs(4, interval_delta=20), obs(5, interval_delta=30)]
    result = compute_trends(history, now=BASE + timedelta(hours=5))
    assert result.acceleration >= CFG.minimum_acceleration
    assert result.trend_state == "accelerating"


def test_16_worsening_rapidly_requires_a_confirmed_second_scan():
    # A jump to well above the "worsening" threshold, sustained for 3
    # consecutive scans (already plateaued -> acceleration ~0, isolating this
    # from "accelerating") -> confirmed, not just a one-off spike.
    history = _with_baseline(
        obs(10.0, 40, interval_seconds=1200), obs(10.3, 41, interval_seconds=1200), obs(10.6, 40, interval_seconds=1200),
    )
    result = compute_trends(history, now=BASE + timedelta(hours=10.6))
    assert result.acceleration == pytest.approx(0.0, abs=0.5)
    assert result.trend_state == "worsening_rapidly"


def test_17_one_time_spike_not_yet_confirmed():
    # A single scan jumps above the "worsening" threshold but hasn't
    # persisted for a second scan yet — not yet confirmed as sustained.
    history = _with_baseline(obs(10, 9))
    result = compute_trends(history, now=BASE + timedelta(hours=10))
    assert result.trend_state == "spike"


def test_18_slow_growth_is_positive_but_modest_and_not_yet_a_confirmed_pattern():
    history = _with_baseline(obs(10, 3))
    result = compute_trends(history, now=BASE + timedelta(hours=10))
    assert result.trend_state == "slow_growth"


def test_19_cooling_still_elevated_but_decelerating():
    # Was meaningfully above baseline, now declining, but still above the
    # "mild" threshold — "remains present, but arrival rate is decreasing."
    history = _with_baseline(obs(10, 12), obs(10.5, 9), obs(11, 6.5))
    result = compute_trends(history, now=BASE + timedelta(hours=11))
    assert result.acceleration < 0
    assert result.trend_state == "cooling"


def test_20_resolving_alert_back_at_baseline_and_still_declining():
    history = _with_baseline(obs(10, 20), obs(10.5, 10), obs(11, 4))
    result = compute_trends(history, now=BASE + timedelta(hours=11))
    assert result.acceleration < 0
    assert result.trend_state == "resolving"


def test_21_persistent_red_alert():
    # Quiet (below the absolute rate floor), flat, red for well beyond
    # persistent_red_hours (default 2h) — neither growing nor declining.
    history = [obs(i * 0.5, 0) for i in range(7)]  # 3 hours, unchanging, rate 0
    result = compute_trends(history, now=BASE + timedelta(hours=3))
    assert result.red_duration_seconds >= CFG.persistent_red_hours * 3600
    assert result.trend_state == "persistent"


def test_22_stable_quiet_and_uneventful():
    history = [obs(i * 0.2, 0) for i in range(4)]
    result = compute_trends(history, now=BASE + timedelta(hours=0.6))
    assert result.trend_state == "stable"


def test_improving_kept_as_an_additional_state_for_the_cooldown_period():
    # Was red a while ago, resolved on an earlier scan (not this one — see
    # test_resolved below), and remains non-red now.
    history = [
        obs(0, interval_delta=80, color="red", is_red=True),
        obs(1, interval_delta=0, color="black", is_red=False),
        obs(2, interval_delta=0, color="black", is_red=False),
    ]
    result = compute_trends(history, now=BASE + timedelta(hours=2))
    assert result.trend_state == "improving"


def test_resolved_uses_the_authoritative_category_marker():
    # Phase 2's authoritative marker (category == "resolved"), not a fragile
    # color-transition guess.
    history = [obs(0, interval_delta=80, is_red=True), obs(1, interval_delta=0, is_red=False, category="resolved")]
    result = compute_trends(history, now=BASE + timedelta(hours=1))
    assert result.trend_state == "resolved"


def test_flapping_alert():
    colors = ["black", "red", "black", "red", "black", "red"]
    history = [obs(i / 6, 10 if c == "red" else 0, is_red=(c == "red"), color=c) for i, c in enumerate(colors)]
    result = compute_trends(history, now=BASE + timedelta(hours=5 / 6))
    assert result.red_state_transition_count >= CFG.flapping_transition_threshold
    assert result.is_flapping is True
    assert result.trend_state == "flapping"


def test_resolved_outranks_flapping_per_precedence():
    colors = ["red", "black", "red", "black", "red", "black"]
    history = [obs(i / 6, 20 if c == "red" else 0, is_red=(c == "red"), color=c, category=("resolved" if i == 5 else None)) for i, c in enumerate(colors)]
    result = compute_trends(history, now=BASE + timedelta(hours=5 / 6))
    assert result.trend_state == "resolved"


# ─── data_unavailable (wired to Phase 2's source-health signal) ────────────

@pytest.mark.parametrize("status", ["source_missing", "source_stale", "source_parse_failure"])
def test_data_unavailable_for_each_unhealthy_source_status(status):
    history = [obs(0, interval_delta=10), obs(1, interval_delta=None, data_quality_status=status)]
    result = compute_trends(history, now=BASE + timedelta(hours=1))
    assert result.trend_state == "data_unavailable"


def test_pending_resolution_is_not_data_unavailable():
    # A healthy source with an unconfirmed absence is a real (if not yet
    # certain) signal, not an untrustworthy one.
    history = [obs(0, interval_delta=10), obs(1, interval_delta=None, data_quality_status="pending_resolution")]
    result = compute_trends(history, now=BASE + timedelta(hours=1))
    assert result.trend_state != "data_unavailable"


# ─── The reset-safe acceptance case: this phase's whole reason to exist ───

def test_reset_safe_midnight_rollover_does_not_corrupt_change_or_acceleration():
    # Steady +10/hr growth for 3 hours, then a midnight rollover between hour
    # 3 and 4: the raw counter would have dropped sharply, but interval_delta
    # (already reset-aware, exactly as backend/services/counter_math.py
    # computes it at ingestion) correctly reports a small positive delta for
    # the new epoch — never a huge negative "raw diff" style corruption.
    history = [obs(i, interval_delta=10) for i in range(4)] + [obs(4, interval_delta=5)]
    result = compute_trends(history, now=BASE + timedelta(hours=4))
    assert result.change_1h == 5  # not -115 or any other raw-count-diff artifact
    assert result.absolute_change == 5
    # Never raises, never produces a nonsensical/undefined state.
    assert result.trend_state in {
        "new", "insufficient_history", "stable", "slow_growth", "worsening_steadily",
        "worsening_rapidly", "accelerating", "spike", "persistent", "cooling",
        "resolving", "resolved", "flapping", "data_unavailable", "improving",
    }


def test_median_mad_baseline_is_not_dragged_by_a_single_spike():
    # Flat at rate=5 except for one huge one-scan spike (100) in the middle.
    # A mean would be dragged way up by it; the median must not be.
    values = [5, 5, 5, 100, 5, 5, 5]
    history = [obs(i, v) for i, v in enumerate(values)]
    baseline = compute_rate_baseline(history, now=BASE + timedelta(hours=6), window_hours=CFG.baseline_window_hours, min_points=CFG.min_baseline_points)
    naive_mean = sum(values) / len(values)
    assert baseline.median == pytest.approx(5.0)
    assert baseline.median < naive_mean  # confirms the spike really would have skewed a mean


# ─── 23-24: threshold excess (unchanged — count vs. threshold, not rate) ──

def test_23_threshold_equal_to_zero_returns_null():
    assert compute_threshold_excess_percentage(current_value=50, red_threshold=0) is None
    assert compute_threshold_excess_percentage(current_value=50, red_threshold=None) is None


def test_24_alert_above_and_below_threshold():
    assert compute_threshold_excess_percentage(current_value=100, red_threshold=50) == pytest.approx(100.0)
    assert compute_threshold_excess_percentage(current_value=50, red_threshold=50) == pytest.approx(0.0)
    assert compute_threshold_excess_percentage(current_value=25, red_threshold=50) == pytest.approx(-50.0)


# ─── 25-26: Change Score (request Section 7 — new formula + score_confidence) ─

@pytest.mark.parametrize("short_term,sustained,accel,duration,vm_count", [
    (10000.0, 10000.0, 100.0, 999999, 999),
    (-10000.0, -10000.0, -100.0, 0, 1),
    (10.0, 10.0, 0.0, 0, 1),
])
def test_25_change_score_always_clamped_0_to_100(short_term, sustained, accel, duration, vm_count):
    baseline = RateBaseline(median=10.0, mad=2.0, sample_count=5)
    score, confidence, components = compute_change_score(
        short_term_rate=short_term, sustained_1h_rate=sustained, baseline=baseline,
        acceleration=accel, red_duration_seconds=duration, affected_vm_count=vm_count,
        config=CFG,
    )
    if score is not None:
        assert 0 <= score <= 100
    if confidence is not None:
        assert 0 <= confidence <= 100
    for value in components.values():
        if value is not None:
            assert 0 <= value <= 100


def test_25b_change_score_none_when_nothing_available():
    baseline = RateBaseline(median=None, mad=None, sample_count=0)
    score, confidence, components = compute_change_score(
        short_term_rate=None, sustained_1h_rate=None, baseline=baseline,
        acceleration=None, red_duration_seconds=None, affected_vm_count=None,
        config=CFG,
    )
    assert score is None
    assert confidence is None
    assert all(v is None for v in components.values())


def test_26_change_score_rebalances_when_components_missing():
    # Only persistence available — baseline unavailable, so both
    # baseline-relative components are None; no acceleration/VM data either.
    baseline = RateBaseline(median=None, mad=None, sample_count=0)
    score, confidence, components = compute_change_score(
        short_term_rate=None, sustained_1h_rate=None, baseline=baseline,
        acceleration=None,
        red_duration_seconds=CFG.persistent_red_hours * 3600,  # exactly at 1x -> normalized 100
        affected_vm_count=None,
        config=CFG,
    )
    assert score == pytest.approx(100.0)  # rebalanced to 100% of the one available component
    assert components["persistence"] == pytest.approx(100.0)
    assert components["short_term_vs_baseline"] is None
    assert components["multi_vm_spread"] is None

    # score_confidence is the point of this phase: honestly reports that only
    # persistence's own weight (15%) was backed by real data, even though the
    # rebalanced score above looks like a "full" 100.
    assert confidence == pytest.approx(CFG.change_score_weights["persistence"] * 100.0)


def test_score_confidence_rises_as_more_components_become_available():
    baseline = RateBaseline(median=10.0, mad=2.0, sample_count=5)
    _, confidence_two, _ = compute_change_score(
        short_term_rate=None, sustained_1h_rate=None, baseline=baseline,
        acceleration=8.0, red_duration_seconds=7200, affected_vm_count=None,
        config=CFG,
    )
    _, confidence_five, _ = compute_change_score(
        short_term_rate=15.0, sustained_1h_rate=14.0, baseline=baseline,
        acceleration=8.0, red_duration_seconds=7200, affected_vm_count=5,
        config=CFG,
    )
    expected_two = (CFG.change_score_weights["acceleration"] + CFG.change_score_weights["persistence"]) * 100.0
    assert confidence_two == pytest.approx(expected_two)
    assert confidence_five == pytest.approx(100.0)
    assert confidence_five > confidence_two


def test_multi_vm_spread_component_normalization():
    baseline = RateBaseline(median=None, mad=None, sample_count=0)
    _, _, components_one_vm = compute_change_score(
        short_term_rate=None, sustained_1h_rate=None, baseline=baseline,
        acceleration=None, red_duration_seconds=None, affected_vm_count=1,
        config=CFG,
    )
    assert components_one_vm["multi_vm_spread"] == pytest.approx(0.0)  # just itself -> no spread concern

    _, _, components_many_vms = compute_change_score(
        short_term_rate=None, sustained_1h_rate=None, baseline=baseline,
        acceleration=None, red_duration_seconds=None,
        affected_vm_count=CFG.multi_vm_spread_reference_count + 1,
        config=CFG,
    )
    assert components_many_vms["multi_vm_spread"] == pytest.approx(100.0)


def test_short_term_vs_baseline_reuses_section_6_worsening_threshold():
    baseline = RateBaseline(median=10.0, mad=2.0, sample_count=5)

    _, _, at_baseline = compute_change_score(
        short_term_rate=baseline.median, sustained_1h_rate=None, baseline=baseline,
        acceleration=None, red_duration_seconds=None, affected_vm_count=None, config=CFG,
    )
    assert at_baseline["short_term_vs_baseline"] == pytest.approx(0.0)

    worsening_rate = baseline.median + CFG.baseline_worsening_multiplier * baseline.mad
    _, _, at_worsening = compute_change_score(
        short_term_rate=worsening_rate, sustained_1h_rate=None, baseline=baseline,
        acceleration=None, red_duration_seconds=None, affected_vm_count=None, config=CFG,
    )
    assert at_worsening["short_term_vs_baseline"] == pytest.approx(100.0)


def test_baseline_vs_component_falls_back_to_floor_when_baseline_is_perfectly_flat():
    # A zero-variance baseline (MAD=0) must not uniformly zero out this
    # component — it falls back to minimum_absolute_rate_floor as the scale.
    baseline = RateBaseline(median=5.0, mad=0.0, sample_count=5)
    rate = baseline.median + CFG.minimum_absolute_rate_floor
    _, _, components = compute_change_score(
        short_term_rate=rate, sustained_1h_rate=None, baseline=baseline,
        acceleration=None, red_duration_seconds=None, affected_vm_count=None, config=CFG,
    )
    assert components["short_term_vs_baseline"] == pytest.approx(100.0)


# ─── 27-29, 33-34: DB-integration (identity, multi-VM, retained history) ───

def _seed_event(db, **overrides):
    defaults = dict(
        alert_id=f"evt-{overrides.get('processed_at')}-{overrides.get('hostname', 'h')}-{overrides.get('error_type','e')}",
        batch_id="BATCH-1",
        status="new", category="new", signal_type="actionable",
        hostname="host-1", raw_filename="f", log_file="applog", error_type="SQLException",
        tenant="cars", system="cars", system_type="IotGW", error_index="1",
        count=10, growth=5, first_seen="t", last_seen="t",
        fingerprint="fp", fingerprint_exact="fpe-default", fingerprint_general="fpg-default",
        classification_reason="r", color="red", raw_known_error="false",
        is_red=True, processed_at=BASE,
        interval_delta=overrides.get("count", 10), interval_seconds=3600.0,
        rate_per_hour=overrides.get("count", 10), data_quality_status="ok",
    )
    defaults.update(overrides)
    event = AlertEvent(**defaults)
    db.add(event)
    return event


def test_27_same_alert_identity_correlated_across_runs(db_session):
    db_session.add(AlertBatch(batch_id="BATCH-1", source="s", environment="e"))
    db_session.flush()
    _seed_event(db_session, alert_id="a1", fingerprint_exact="KEY-A", processed_at=BASE, count=10, interval_delta=10)
    _seed_event(db_session, alert_id="a2", fingerprint_exact="KEY-A", processed_at=BASE + timedelta(hours=1), count=30, interval_delta=20)
    db_session.commit()

    trends = get_trends_for_alert_keys(db_session, ["KEY-A"], now=BASE + timedelta(hours=1))
    assert "KEY-A" in trends
    assert trends["KEY-A"].absolute_change == 20
    assert trends["KEY-A"].previous_value == 10


def test_28_different_vms_do_not_share_history(db_session):
    db_session.add(AlertBatch(batch_id="BATCH-1", source="s", environment="e"))
    db_session.flush()
    _seed_event(db_session, alert_id="vm1-a", hostname="vm-01", fingerprint_exact="KEY-VM1", processed_at=BASE, count=100)
    _seed_event(db_session, alert_id="vm2-a", hostname="vm-02", fingerprint_exact="KEY-VM2", processed_at=BASE, count=5)
    db_session.commit()

    trends = get_trends_for_alert_keys(db_session, ["KEY-VM1", "KEY-VM2"], now=BASE)
    assert trends["KEY-VM1"].current_value == 100
    assert trends["KEY-VM2"].current_value == 5


def test_29_same_error_across_multiple_vms_aggregated(db_session):
    db_session.add(AlertBatch(batch_id="BATCH-1", source="s", environment="e"))
    db_session.flush()
    for host, count in [("vm-01", 50), ("vm-02", 30), ("vm-03", 20)]:
        _seed_event(
            db_session, alert_id=f"multi-{host}", hostname=host,
            fingerprint_exact=f"KEY-{host}", tenant="cars", system="cars",
            error_type="SQLException", log_file="applog",
            processed_at=BASE, count=count, is_red=True, color="red",
        )
    db_session.commit()

    pattern = get_multi_vm_pattern(db_session, tenant="cars", system="cars", error_type="SQLException", log_file="applog", now=BASE)
    assert pattern.affected_vm_count == 3
    assert set(pattern.affected_vms) == {"vm-01", "vm-02", "vm-03"}
    assert pattern.aggregate_current_value == 100

    vm_counts = get_affected_vm_counts_for_batch(db_session, "BATCH-1")
    assert vm_counts[("cars", "cars", "SQLException", "applog")] == 3


def test_affected_vm_counts_thread_into_the_change_score(db_session):
    # Enough history for a real baseline (min_baseline_points=3).
    db_session.add(AlertBatch(batch_id="BATCH-1", source="s", environment="e"))
    db_session.flush()
    for i in range(4):
        _seed_event(
            db_session, alert_id=f"vm-thread-{i}", fingerprint_exact="KEY-VMTHREAD",
            processed_at=BASE + timedelta(hours=i), count=10 + i * 2,
            interval_delta=2, rate_per_hour=2,
        )
    db_session.commit()

    now = BASE + timedelta(hours=3)
    without_vm = get_trends_for_alert_keys(db_session, ["KEY-VMTHREAD"], now=now)
    with_vm = get_trends_for_alert_keys(db_session, ["KEY-VMTHREAD"], now=now, affected_vm_counts={"KEY-VMTHREAD": 6})

    assert without_vm["KEY-VMTHREAD"].change_score_components["multi_vm_spread"] is None
    assert with_vm["KEY-VMTHREAD"].change_score_components["multi_vm_spread"] == pytest.approx(100.0)
    # An extra real component pushes confidence up, never down.
    assert with_vm["KEY-VMTHREAD"].change_score_confidence > without_vm["KEY-VMTHREAD"].change_score_confidence


def test_33_noise_and_suppressed_rows_remain_in_history_for_trend_calc(db_session):
    db_session.add(AlertBatch(batch_id="BATCH-1", source="s", environment="e"))
    db_session.flush()
    _seed_event(
        db_session, alert_id="n1", fingerprint_exact="KEY-NOISE", signal_type="noise",
        color="black", is_red=False, processed_at=BASE, count=5, interval_delta=5,
    )
    _seed_event(
        db_session, alert_id="n2", fingerprint_exact="KEY-NOISE", signal_type="noise",
        color="black", is_red=False, processed_at=BASE + timedelta(hours=1), count=8, interval_delta=3,
    )
    db_session.commit()

    trends = get_trends_for_alert_keys(db_session, ["KEY-NOISE"], now=BASE + timedelta(hours=1))
    assert trends["KEY-NOISE"].absolute_change == 3


def test_34_resolved_alert_retains_previous_red_history(db_session):
    db_session.add(AlertBatch(batch_id="BATCH-1", source="s", environment="e"))
    db_session.flush()
    _seed_event(
        db_session, alert_id="r1", fingerprint_exact="KEY-RES", category="new",
        color="red", is_red=True, processed_at=BASE, count=80,
    )
    _seed_event(
        db_session, alert_id="r2", fingerprint_exact="KEY-RES", category="resolved", status="resolved",
        color="red", is_red=False, processed_at=BASE + timedelta(hours=1), count=0, interval_delta=0,
    )
    db_session.commit()

    trends = get_trends_for_alert_keys(db_session, ["KEY-RES"], now=BASE + timedelta(hours=1))
    result = trends["KEY-RES"]
    assert result.previous_value == 80  # the prior red observation is still visible in history
    assert result.trend_state == "resolved"
