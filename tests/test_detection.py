"""
Unit tests for the failure detector.

Synthetic traces are used for most tests because we control exactly when
the simulated satellite stops being maintained, so any disagreement is
the detector's error rather than ambiguity in the ground truth.

The synthetic generator is calibrated to REAL magnitudes measured from
Space-Track on 2026-11-11, not to guessed ones:

    Envisat maintenance burns : ~0.016 km/day at the 99th percentile
    Envisat decay at 766 km   : ~0.001 km/day
    pos_frac while maintained : 0.25 (Envisat), 0.09 (Terra)
    pos_frac after cessation  : 0.018 (Envisat)

An earlier version of this module assumed 0.3 km burns and 0.05 km/week
decay. Both were wrong by more than an order of magnitude, which is why
these constants are now pinned to observation.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.failure_detection import (
    STATUS_ABSTAIN,
    STATUS_ACTIVE,
    STATUS_FAILED,
    STATUS_WOUND_DOWN,
    daily_series,
    detect_failure,
    positive_delta_fraction,
    quarterly_activity,
)

EARTH_RADIUS_KM = 6378.137


def synth_trace(
    n_days=3650,
    start_altitude=766.0,
    cessation_day=None,
    wind_down_days=0,
    decay_km_per_day=0.0010,
    burn_km=0.016,
    burn_prob=0.25,
    noise_km=0.0004,
    seed=0,
):
    """
    Synthetic daily altitude trace at realistic magnitudes.

    While maintained, each day has `burn_prob` chance of a small
    orbit-raising burn. After `cessation_day` the burns stop.
    `wind_down_days` ramps burn probability down linearly instead of
    cutting it off, reproducing Terra's gradual pattern.
    """
    rng = np.random.default_rng(seed)
    altitude = start_altitude
    values = []

    for day in range(n_days):
        if cessation_day is None:
            p = burn_prob
        elif wind_down_days > 0:
            ramp_start = cessation_day - wind_down_days
            if day < ramp_start:
                p = burn_prob
            elif day < cessation_day:
                frac = (day - ramp_start) / wind_down_days
                p = burn_prob * (1 - frac)
            else:
                p = 0.0
        else:
            p = burn_prob if day < cessation_day else 0.0

        altitude -= decay_km_per_day
        if rng.random() < p:
            altitude += burn_km

        values.append(altitude + rng.normal(0, noise_km))

    dates = pd.date_range("2008-01-01", periods=n_days, freq="D")
    return pd.DataFrame(
        {
            "EPOCH": dates,
            "NORAD_CAT_ID": 99999,
            "SEMIMAJOR_AXIS": np.array(values) + EARTH_RADIUS_KM,
            "BSTAR": 1e-5,
        }
    )


class TestDailySeries:
    def test_collapses_multiple_elsets_per_day(self):
        frame = pd.DataFrame(
            {
                "EPOCH": pd.to_datetime(
                    ["2020-01-01 03:00", "2020-01-01 15:00", "2020-01-02 06:00"]
                ),
                "NORAD_CAT_ID": 1,
                "SEMIMAJOR_AXIS": [7000.0, 7000.2, 6999.9],
            }
        )
        daily = daily_series(frame)
        assert len(daily) == 2
        assert daily["altitude_km"].iloc[0] == pytest.approx(7000.1 - EARTH_RADIUS_KM)

    def test_derives_altitude_when_absent(self):
        frame = pd.DataFrame(
            {
                "EPOCH": pd.to_datetime(["2020-01-01"]),
                "NORAD_CAT_ID": 1,
                "SEMIMAJOR_AXIS": [7144.137],
            }
        )
        assert daily_series(frame)["altitude_km"].iloc[0] == pytest.approx(766.0)


class TestPositiveDeltaFraction:
    def test_matches_envisat_maintained_rate(self):
        trace = synth_trace(n_days=1460, cessation_day=None, seed=3)
        frac, n = positive_delta_fraction(daily_series(trace))
        # Observed on real Envisat while maintained: 0.251
        assert 0.18 <= frac <= 0.32, frac
        assert n > 1400

    def test_matches_envisat_dead_rate(self):
        trace = synth_trace(n_days=1460, cessation_day=0, seed=4)
        frac, _ = positive_delta_fraction(daily_series(trace))
        # Observed on real Envisat after contact loss: 0.018
        assert frac < 0.08, frac

    def test_long_gaps_are_skipped(self):
        dates = list(pd.date_range("2020-01-01", periods=5, freq="D"))
        dates += list(pd.date_range("2021-01-01", periods=5, freq="D"))
        daily = pd.DataFrame(
            {"date": dates, "altitude_km": [700 - 0.001 * i for i in range(10)]}
        )
        _, n = positive_delta_fraction(daily)
        assert n == 8  # 9 consecutive pairs minus the one spanning a year


class TestQuarterlyActivity:
    def test_produces_one_row_per_quarter(self):
        trace = synth_trace(n_days=730, seed=5)
        activity = quarterly_activity(daily_series(trace))
        assert 7 <= len(activity) <= 9
        assert {"period", "pos_frac", "altitude_km", "n_days"} <= set(activity.columns)

    def test_detects_the_drop(self):
        trace = synth_trace(n_days=2920, cessation_day=1460, seed=6)
        activity = quarterly_activity(daily_series(trace))
        first_half = activity["pos_frac"].iloc[:14].median()
        second_half = activity["pos_frac"].iloc[-14:].median()
        assert first_half > 0.15
        assert second_half < 0.08


class TestFailureDetection:
    def test_detects_abrupt_cessation(self):
        trace = synth_trace(n_days=3650, cessation_day=1825, seed=7)
        result = detect_failure(trace)
        assert result.status == STATUS_FAILED
        assert result.failed

        true_date = trace["EPOCH"].iloc[1825]
        error_days = abs((result.failure_epoch - true_date).days)
        assert error_days <= 180, f"off by {error_days} days"

    def test_maintained_satellite_not_flagged(self):
        trace = synth_trace(n_days=3650, cessation_day=None, seed=8)
        result = detect_failure(trace)
        assert result.status == STATUS_ACTIVE
        assert not result.failed

    def test_gradual_wind_down_is_not_called_failure(self):
        """
        The Terra case. Maintenance ends over roughly four years while the
        spacecraft stays operational. The detector must separate this from
        an abrupt failure rather than labelling both as dead.
        """
        trace = synth_trace(
            n_days=4380, cessation_day=2920, wind_down_days=1460, seed=9
        )
        result = detect_failure(trace)
        assert result.status == STATUS_WOUND_DOWN
        assert not result.failed
        assert result.transition_quarters > 2

    def test_abstains_in_low_orbit(self):
        trace = synth_trace(n_days=3650, start_altitude=300.0, cessation_day=1825)
        result = detect_failure(trace)
        assert result.status == STATUS_ABSTAIN
        assert result.reason == "below_min_altitude"

    def test_abstains_without_station_keeping(self):
        trace = synth_trace(n_days=3650, burn_prob=0.0, seed=10)
        result = detect_failure(trace)
        assert result.status == STATUS_ABSTAIN
        assert result.reason == "no_station_keeping"

    def test_abstains_on_short_history(self):
        trace = synth_trace(n_days=60)
        result = detect_failure(trace)
        assert result.status == STATUS_ABSTAIN
        assert result.reason == "insufficient_history"

    def test_baseline_is_per_satellite(self):
        """
        Envisat ran at pos_frac 0.25 and Terra at 0.09, both while fully
        maintained. A detector keyed to an absolute threshold would call
        Terra dead for its entire life, so the baseline must be the
        satellite's own.
        """
        quiet = synth_trace(n_days=3650, burn_prob=0.09, cessation_day=None, seed=11)
        result = detect_failure(quiet)
        assert result.status == STATUS_ACTIVE
        assert result.baseline_pos_frac < 0.15

    @pytest.mark.parametrize("cessation_day", [1200, 1825, 2400, 2900])
    def test_robust_across_cessation_times(self, cessation_day):
        trace = synth_trace(n_days=3650, cessation_day=cessation_day, seed=cessation_day)
        result = detect_failure(trace)
        assert result.failed, f"missed cessation at day {cessation_day}"

    @pytest.mark.parametrize("noise", [0.0001, 0.0002, 0.0004])
    def test_robust_to_noise(self, noise):
        """
        Noise levels here stay below the daily decay rate (~0.001 km/day),
        which is the regime real daily-median data occupies. Envisat's
        post-failure pos_frac of 0.018 confirms noise rarely overcomes
        decay once element sets are collapsed to daily medians.
        """
        trace = synth_trace(n_days=3650, cessation_day=1825, noise_km=noise, seed=12)
        result = detect_failure(trace)
        assert result.failed, f"missed cessation at noise={noise}"

    @pytest.mark.parametrize("burn_prob", [0.12, 0.25, 0.40])
    def test_robust_across_maintenance_rates(self, burn_prob):
        trace = synth_trace(
            n_days=3650, cessation_day=1825, burn_prob=burn_prob, seed=13
        )
        result = detect_failure(trace)
        assert result.failed, f"missed cessation at burn_prob={burn_prob}"


class TestRealMagnitudes:
    """Guards against regressing to the wrong order of magnitude."""

    def test_real_burn_size_is_detected(self):
        """
        Envisat's burns move SMA by ~0.016 km/day. The previous detector
        used a 0.3 km magnitude threshold and found zero manoeuvres across
        its entire operational life.
        """
        trace = synth_trace(n_days=2190, burn_km=0.016, cessation_day=None, seed=14)
        frac, _ = positive_delta_fraction(daily_series(trace))
        assert frac > 0.15, "burns at the real observed magnitude must register"

    def test_real_decay_rate_does_not_mask_burns(self):
        """Decay at 766 km is ~0.001 km/day, well below burn size."""
        trace = synth_trace(
            n_days=2190, decay_km_per_day=0.0010, burn_km=0.016, seed=15
        )
        frac, _ = positive_delta_fraction(daily_series(trace))
        assert frac > 0.15


class TestKnownLimitations:
    """
    Tests that DOCUMENT where the method breaks rather than asserting it
    works. Each one is a limitation stated in docs/methodology.md.
    """

    def test_breaks_when_noise_exceeds_decay(self):
        """
        The frequency statistic assumes drag reliably pushes altitude down
        each day, so positive days signal manoeuvres. Where observation
        noise exceeds the daily decay, roughly half of all days read
        positive whether or not the satellite is alive, and the signal
        disappears.

        This is the regime to watch for at high altitude, where decay is
        slowest. Real Envisat at 766 km stays clear of it, but a satellite
        at 1200 km might not.
        """
        noisy_dead = synth_trace(
            n_days=2190, cessation_day=0, decay_km_per_day=0.0005,
            noise_km=0.003, seed=16,
        )
        frac, _ = positive_delta_fraction(daily_series(noisy_dead))
        # A dead satellite reading near 0.5 is the failure mode.
        assert frac > 0.3, "expected the statistic to degrade under heavy noise"

        result = detect_failure(noisy_dead)
        assert not result.failed, "detector should not claim a failure it cannot see"

    def test_cannot_distinguish_drift_from_death_without_abruptness(self):
        """
        A satellite that stops manoeuvring looks identical to a failed one
        on the frequency statistic alone. Only the SHAPE of the decline
        separates them, which is why `transition_quarters` exists.
        """
        abrupt = detect_failure(
            synth_trace(n_days=4380, cessation_day=2920, seed=17)
        )
        gradual = detect_failure(
            synth_trace(n_days=4380, cessation_day=2920, wind_down_days=1460, seed=17)
        )

        # Final activity levels are indistinguishable...
        assert abs(abrupt.final_pos_frac - gradual.final_pos_frac) < 0.08
        # ...but the transition shape separates them.
        assert abrupt.transition_quarters < gradual.transition_quarters
        assert abrupt.failed and not gradual.failed


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
