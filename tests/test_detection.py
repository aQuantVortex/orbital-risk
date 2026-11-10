"""
Unit tests for the failure detector, on synthetic traces with known truth.

Synthetic data is used here deliberately: we control exactly when the
simulated satellite "dies", so any disagreement is the detector's error
rather than ambiguity in the ground truth. Validation against real
satellites with documented outcomes is a separate step
(scripts/validate_detector.py).
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.failure_detection import (
    detect_failure,
    detect_maneuvers,
    rolling_slope,
)

EARTH_RADIUS_KM = 6378.137


def synth_trace(
    n_weeks=520,
    start_altitude=780.0,
    failure_week=None,
    decay_rate=0.08,
    boost_every=26,
    boost_size=2.5,
    noise=0.02,
    seed=0,
):
    """
    Build a synthetic weekly altitude trace.

    Before `failure_week`: drag decay offset by periodic orbit-raising
    burns, producing a sawtooth. After: pure decay, accelerating as the
    satellite drops into denser atmosphere.
    """
    rng = np.random.default_rng(seed)
    altitude = start_altitude
    altitudes = []

    for week in range(n_weeks):
        alive = failure_week is None or week < failure_week

        if alive:
            altitude -= decay_rate
            if week > 0 and week % boost_every == 0:
                altitude += boost_size
        else:
            weeks_dead = week - failure_week
            altitude -= decay_rate * (1 + weeks_dead / 200.0)

        altitudes.append(altitude + rng.normal(0, noise))

    epochs = pd.date_range("2010-01-03", periods=n_weeks, freq="W")
    return pd.DataFrame(
        {
            "EPOCH": epochs,
            "NORAD_CAT_ID": 99999,
            "altitude_km": altitudes,
            "SEMIMAJOR_AXIS": np.array(altitudes) + EARTH_RADIUS_KM,
            "BSTAR": [1e-5] * n_weeks,
        }
    )


class TestRollingSlope:
    def test_recovers_known_slope(self):
        y = np.arange(50, dtype=float) * 3.0
        slopes = rolling_slope(y, window=10)
        assert np.allclose(slopes[9:], 3.0)

    def test_leading_values_are_nan(self):
        slopes = rolling_slope(np.arange(20, dtype=float), window=5)
        assert np.isnan(slopes[:4]).all()
        assert not np.isnan(slopes[4])

    def test_short_series_returns_all_nan(self):
        slopes = rolling_slope(np.arange(3, dtype=float), window=10)
        assert np.isnan(slopes).all()


class TestManeuverDetection:
    def test_finds_station_keeping_burns(self):
        trace = synth_trace(n_weeks=260, boost_every=26, failure_week=None)
        found = detect_maneuvers(trace["altitude_km"].values, threshold_km=0.3)
        # 260 weeks at one burn every 26 weeks -> about 9 burns.
        assert 7 <= len(found) <= 11

    def test_no_burns_on_pure_decay(self):
        rng = np.random.default_rng(1)
        altitudes = 700 - np.arange(200) * 0.1 + rng.normal(0, 0.02, 200)
        found = detect_maneuvers(altitudes, threshold_km=0.3)
        assert len(found) == 0

    def test_noise_does_not_trigger_detection(self):
        rng = np.random.default_rng(2)
        altitudes = 700 - np.arange(300) * 0.08 + rng.normal(0, 0.05, 300)
        found = detect_maneuvers(altitudes, threshold_km=0.3)
        assert len(found) == 0


class TestFailureDetection:
    def test_detects_failure_at_right_time(self):
        failure_week = 260
        trace = synth_trace(n_weeks=520, failure_week=failure_week)
        result = detect_failure(trace)

        assert result.failed
        assert result.reason == "station_keeping_ceased"

        true_date = trace["EPOCH"].iloc[failure_week]
        error_days = abs((result.failure_epoch - true_date).days)
        # Detection marks the last burn, which precedes death by up to one
        # boost interval (26 weeks). Half a year of tolerance is adequate
        # for a model operating on quarterly periods.
        assert error_days <= 200, f"off by {error_days} days"

    def test_healthy_satellite_not_flagged(self):
        trace = synth_trace(n_weeks=520, failure_week=None)
        result = detect_failure(trace)
        assert not result.failed
        assert result.reason == "still_manoeuvring"

    def test_abstains_in_low_orbit(self):
        trace = synth_trace(n_weeks=520, start_altitude=350.0, failure_week=260)
        result = detect_failure(trace)
        assert not result.failed
        assert result.reason == "below_min_altitude"

    def test_abstains_without_station_keeping(self):
        trace = synth_trace(n_weeks=520, boost_size=0.0, failure_week=260)
        result = detect_failure(trace)
        assert not result.failed
        assert result.reason == "no_station_keeping"

    def test_insufficient_history_handled(self):
        trace = synth_trace(n_weeks=10, failure_week=None)
        result = detect_failure(trace)
        assert not result.failed
        assert result.reason == "insufficient_history"

    @pytest.mark.parametrize("failure_week", [150, 200, 260, 320, 400])
    def test_robust_across_failure_times(self, failure_week):
        trace = synth_trace(n_weeks=520, failure_week=failure_week, seed=failure_week)
        result = detect_failure(trace)
        assert result.failed, f"missed failure at week {failure_week}"

    @pytest.mark.parametrize("noise", [0.01, 0.05, 0.1])
    def test_robust_to_noise(self, noise):
        trace = synth_trace(n_weeks=520, failure_week=260, noise=noise, seed=7)
        result = detect_failure(trace)
        assert result.failed, f"missed failure at noise={noise}"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
