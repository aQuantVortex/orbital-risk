"""
Failure labelling from orbital behaviour.

The premise: an operational satellite in LEO fights atmospheric drag by
periodically raising its orbit. Its altitude trace is a sawtooth -- slow
decay punctuated by positive jumps. When control ends (propellant
exhaustion, subsystem failure, end of mission), the jumps stop and the
trace becomes monotonic decay.

Detecting that transition gives failure labels for the whole population
on a uniform definition, rather than inheriting the reporting bias of
curated failure registries, which cover mostly large, insured, Western
spacecraft.

Two independent signals are combined:
  1. Cessation of station-keeping manoeuvres (positive SMA jumps).
  2. Sustained negative slope in semi-major axis afterwards.

A third corroborating signal is available in BSTAR: a satellite that
loses attitude control starts tumbling, changing its effective cross-
sectional area, which shows up as a jump in the fitted drag term.

Caveat handled here: objects below roughly 400 km decay quickly under
drag whether or not they are healthy, so natural decay can masquerade as
failure. `min_altitude_km` excludes that regime.
"""

import logging
from dataclasses import dataclass, asdict

import numpy as np
import pandas as pd

LOGGER = logging.getLogger(__name__)

EARTH_RADIUS_KM = 6378.137


@dataclass
class DetectionResult:
    """Outcome of running the detector on one object."""

    norad_id: int
    failed: bool
    failure_epoch: pd.Timestamp | None
    last_maneuver_epoch: pd.Timestamp | None
    n_maneuvers: int
    decay_slope_km_per_week: float | None
    bstar_ratio: float | None
    reason: str

    def to_dict(self):
        return asdict(self)


def rolling_slope(series, window):
    """
    Slope of a least-squares line fitted over a trailing window.

    Implemented directly rather than pulled from a library so the
    computation is transparent: for evenly spaced x, the OLS slope is
    cov(x, y) / var(x).
    """
    values = np.asarray(series, dtype=float)
    n = len(values)
    slopes = np.full(n, np.nan)

    if n < window:
        return slopes

    x = np.arange(window, dtype=float)
    x_centred = x - x.mean()
    x_var = (x_centred ** 2).sum()

    for i in range(window - 1, n):
        y = values[i - window + 1 : i + 1]
        if np.isnan(y).any():
            continue
        slopes[i] = (x_centred * (y - y.mean())).sum() / x_var

    return slopes


def detect_maneuvers(altitudes, threshold_km=0.3):
    """
    Index positions where altitude rose by more than `threshold_km`.

    A positive jump against a backdrop of drag decay is evidence of an
    orbit-raising burn. The threshold sits above typical element-set
    noise but below a real station-keeping manoeuvre.
    """
    values = np.asarray(altitudes, dtype=float)
    deltas = np.diff(values, prepend=values[0])
    return np.where(deltas > threshold_km)[0]


def detect_failure(
    history,
    window=8,
    maneuver_threshold_km=0.3,
    quiet_weeks=52,
    decay_threshold_km_per_week=-0.05,
    min_altitude_km=400,
):
    """
    Detect end-of-life for one satellite from its weekly element history.

    Parameters
    ----------
    history : DataFrame
        Weekly element sets for one object, with EPOCH and altitude_km.
    window : int
        Weeks in the rolling slope window.
    maneuver_threshold_km : float
        Altitude rise counted as a station-keeping burn.
    quiet_weeks : int
        Weeks without a manoeuvre before the satellite is called inactive.
        One year is conservative: some missions manoeuvre infrequently.
    decay_threshold_km_per_week : float
        Slope that must be sustained after the last burn to confirm decay.
    min_altitude_km : float
        Below this, drag decay is rapid regardless of health, so the
        detector abstains rather than producing a false positive.

    Returns
    -------
    DetectionResult
    """
    norad_id = int(history["NORAD_CAT_ID"].iloc[0])

    frame = history.copy()
    if "altitude_km" not in frame.columns:
        if "SEMIMAJOR_AXIS" not in frame.columns:
            return DetectionResult(
                norad_id, False, None, None, 0, None, None, "no_altitude_data"
            )
        frame["altitude_km"] = frame["SEMIMAJOR_AXIS"] - EARTH_RADIUS_KM

    frame = frame.dropna(subset=["altitude_km", "EPOCH"]).reset_index(drop=True)

    if len(frame) < window * 3:
        return DetectionResult(
            norad_id, False, None, None, 0, None, None, "insufficient_history"
        )

    altitudes = frame["altitude_km"].values
    epochs = frame["EPOCH"].values

    if np.nanmedian(altitudes) < min_altitude_km:
        return DetectionResult(
            norad_id, False, None, None, 0, None, None, "below_min_altitude"
        )

    maneuver_idx = detect_maneuvers(altitudes, maneuver_threshold_km)
    n_maneuvers = len(maneuver_idx)

    # A satellite that never manoeuvred was never station-keeping, so this
    # detector cannot speak to whether or when it failed.
    if n_maneuvers < 3:
        return DetectionResult(
            norad_id, False, None, None, n_maneuvers, None, None, "no_station_keeping"
        )

    last_maneuver = int(maneuver_idx[-1])
    last_maneuver_epoch = pd.Timestamp(epochs[last_maneuver])
    weeks_since_last = len(frame) - last_maneuver - 1

    if weeks_since_last < quiet_weeks:
        return DetectionResult(
            norad_id,
            False,
            None,
            last_maneuver_epoch,
            n_maneuvers,
            None,
            None,
            "still_manoeuvring",
        )

    # Confirm sustained decay after the last burn.
    post = altitudes[last_maneuver:]
    slopes = rolling_slope(post, window)
    valid = slopes[~np.isnan(slopes)]

    if len(valid) == 0:
        return DetectionResult(
            norad_id,
            False,
            None,
            last_maneuver_epoch,
            n_maneuvers,
            None,
            None,
            "no_slope_estimate",
        )

    median_slope = float(np.median(valid))
    decaying = median_slope < decay_threshold_km_per_week

    bstar_ratio = _bstar_jump(frame, last_maneuver)

    if not decaying:
        return DetectionResult(
            norad_id,
            False,
            None,
            last_maneuver_epoch,
            n_maneuvers,
            median_slope,
            bstar_ratio,
            "quiet_but_not_decaying",
        )

    return DetectionResult(
        norad_id,
        True,
        last_maneuver_epoch,
        last_maneuver_epoch,
        n_maneuvers,
        median_slope,
        bstar_ratio,
        "station_keeping_ceased",
    )


def _bstar_jump(frame, split_index):
    """
    Ratio of median BSTAR after the last burn to before it.

    A tumbling satellite presents a different cross-section to the
    atmosphere, so a ratio well above 1 corroborates loss of control.
    Returns None when BSTAR is unavailable or degenerate.
    """
    if "BSTAR" not in frame.columns:
        return None

    before = frame["BSTAR"].iloc[:split_index].dropna()
    after = frame["BSTAR"].iloc[split_index:].dropna()

    if len(before) < 5 or len(after) < 5:
        return None

    before_median = float(before.median())
    after_median = float(after.median())

    if before_median <= 0:
        return None
    return after_median / before_median


def detect_population(histories, **kwargs):
    """Run the detector over every object and return a label table."""
    results = []
    for norad_id, group in histories.groupby("NORAD_CAT_ID"):
        results.append(detect_failure(group, **kwargs).to_dict())

    frame = pd.DataFrame(results)
    if not frame.empty:
        LOGGER.info(
            "Detected %d failures across %d objects (%.1f%%)",
            int(frame["failed"].sum()),
            len(frame),
            100 * frame["failed"].mean(),
        )
    return frame


def validate_against_known(detections, known_failures, tolerance_days=180):
    """
    Score detected failure dates against independently documented ones.

    `known_failures` maps NORAD ID -> documented failure date. Returns a
    per-object comparison plus summary accuracy within `tolerance_days`.
    """
    rows = []
    for norad_id, true_date in known_failures.items():
        match = detections[detections["norad_id"] == norad_id]
        if match.empty:
            rows.append(
                {
                    "norad_id": norad_id,
                    "true_date": true_date,
                    "detected_date": None,
                    "error_days": None,
                    "within_tolerance": False,
                    "reason": "not_in_population",
                }
            )
            continue

        row = match.iloc[0]
        detected = row["failure_epoch"]
        if pd.isna(detected) or detected is None:
            rows.append(
                {
                    "norad_id": norad_id,
                    "true_date": true_date,
                    "detected_date": None,
                    "error_days": None,
                    "within_tolerance": False,
                    "reason": row["reason"],
                }
            )
            continue

        error = (pd.Timestamp(detected) - pd.Timestamp(true_date)).days
        rows.append(
            {
                "norad_id": norad_id,
                "true_date": true_date,
                "detected_date": detected,
                "error_days": error,
                "within_tolerance": abs(error) <= tolerance_days,
                "reason": row["reason"],
            }
        )

    return pd.DataFrame(rows)
