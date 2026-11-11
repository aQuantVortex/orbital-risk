"""
Failure labelling from orbital behaviour.

The premise: an operational satellite in LEO fights atmospheric drag by
periodically raising its orbit. When active orbit maintenance ends, the
raising stops and the altitude trace becomes monotonic decay. Detecting
that transition gives labels for the whole population on a uniform
definition, rather than inheriting the reporting bias of curated failure
registries, which cover mostly large, insured, Western spacecraft.

WHAT THE REAL DATA CHANGED
--------------------------
An earlier version of this module looked for individual orbit-raising
burns above a fixed altitude threshold (0.3 km). Validation against real
Space-Track `gp_history` showed that threshold is wrong by roughly a
factor of twenty: Envisat's real maintenance burns move semi-major axis
by about 0.016 km/day at the 99th percentile. The magnitude-threshold
detector found ZERO manoeuvres across Envisat's entire operational life
and would have silently discarded a documented failure.

What does work is manoeuvre FREQUENCY. Measured on Envisat:

    fraction of days with a positive altitude change
      before 2012-04-08 (documented contact loss) : 0.251
      after                                        : 0.018

That is the statistic this module now uses.

MAINTENANCE CESSATION IS NOT THE SAME AS FAILURE
------------------------------------------------
Terra (NORAD 25994) is operational as of 2026 — instruments working,
data downlinked — but NASA ended its orbit maintenance around 2020 and
let it drift from its 10:30 mean local time. Its positive-delta fraction
reads 0.019 in 2021 and 0.000 in 2026, which is indistinguishable from a
dead satellite on the frequency statistic alone.

The discriminator is ABRUPTNESS. Envisat collapsed from 0.24 to 0.04 in
a single quarter. Terra declined over roughly four years (0.31, 0.30,
0.24, 0.12, 0.019). A failure is a step; a planned wind-down is a ramp.

The detector therefore reports two things: whether maintenance ceased,
and whether it ceased abruptly. Only abrupt cessation is labelled as a
probable failure. Gradual cessation is labelled separately so the
modelling stage can decide how to treat it rather than having the
ambiguity hidden inside a boolean.

Caveat still handled: objects below roughly 400 km decay quickly under
drag whether or not they are healthy, and some (GOCE) use continuous
low-thrust propulsion that makes the frequency statistic meaningless.
`min_altitude_km` excludes that regime.
"""

import logging
from dataclasses import dataclass, asdict

import numpy as np
import pandas as pd

LOGGER = logging.getLogger(__name__)

EARTH_RADIUS_KM = 6378.137

# Label values for `status`.
STATUS_ACTIVE = "active"
STATUS_FAILED = "failed_abrupt"
STATUS_WOUND_DOWN = "maintenance_ended_gradual"
STATUS_ABSTAIN = "abstain"


@dataclass
class DetectionResult:
    """Outcome of running the detector on one object."""

    norad_id: int
    status: str
    failed: bool               # True only for abrupt cessation
    failure_epoch: pd.Timestamp | None
    baseline_pos_frac: float | None
    final_pos_frac: float | None
    transition_quarters: float | None   # how long the decline took
    decay_slope_km_per_day: float | None
    n_periods: int
    reason: str

    def to_dict(self):
        return asdict(self)


def daily_series(history):
    """
    Collapse an element-set history to one median altitude per day.

    Space-Track may hold several element sets per object per day, and
    individual fits carry noise well above the real day-to-day change.
    Taking the daily median suppresses that without touching the signal.
    """
    frame = history.copy()

    if "altitude_km" not in frame.columns:
        if "SEMIMAJOR_AXIS" not in frame.columns:
            return pd.DataFrame(columns=["date", "altitude_km"])
        frame["altitude_km"] = frame["SEMIMAJOR_AXIS"] - EARTH_RADIUS_KM

    frame = frame.dropna(subset=["altitude_km", "EPOCH"])
    if frame.empty:
        return pd.DataFrame(columns=["date", "altitude_km"])

    frame["date"] = pd.to_datetime(frame["EPOCH"]).dt.normalize()
    daily = (
        frame.groupby("date")["altitude_km"]
        .median()
        .reset_index()
        .sort_values("date")
        .reset_index(drop=True)
    )
    return daily


def positive_delta_fraction(daily, max_gap_days=3):
    """
    Fraction of consecutive days on which altitude rose.

    Drag pulls altitude down continuously, so on an unmaintained
    satellite almost every day is negative. Orbit-raising produces the
    positive days. Gaps longer than `max_gap_days` are skipped, since a
    rise across a long gap says nothing about a single manoeuvre.

    Returns (fraction, n_comparisons).
    """
    if len(daily) < 2:
        return np.nan, 0

    dates = daily["date"].values
    altitudes = daily["altitude_km"].values

    gaps = (dates[1:] - dates[:-1]) / np.timedelta64(1, "D")
    deltas = altitudes[1:] - altitudes[:-1]

    usable = gaps <= max_gap_days
    if usable.sum() == 0:
        return np.nan, 0

    return float((deltas[usable] > 0).mean()), int(usable.sum())


def quarterly_activity(daily, min_days=8, max_gap_days=3):
    """
    Positive-delta fraction and median altitude, per calendar quarter.

    Quarterly is the natural resolution: it is long enough that the
    fraction is stable, and short enough to date a transition usefully.
    Quarters with fewer than `min_days` usable comparisons are dropped.
    """
    if len(daily) < 2:
        return pd.DataFrame(columns=["period", "pos_frac", "altitude_km", "n_days"])

    frame = daily.copy()
    frame["gap"] = frame["date"].diff().dt.days
    frame["delta"] = frame["altitude_km"].diff()
    frame = frame[frame["gap"].notna() & (frame["gap"] <= max_gap_days)]

    if frame.empty:
        return pd.DataFrame(columns=["period", "pos_frac", "altitude_km", "n_days"])

    frame["period"] = frame["date"].dt.to_period("Q").dt.to_timestamp()

    grouped = (
        frame.groupby("period")
        .agg(
            pos_frac=("delta", lambda s: float((s > 0).mean())),
            altitude_km=("altitude_km", "median"),
            n_days=("delta", "size"),
        )
        .reset_index()
    )
    return grouped[grouped["n_days"] >= min_days].reset_index(drop=True)


def detect_failure(
    history,
    baseline_quarters=8,
    quiet_quarters=4,
    drop_ratio=0.35,
    abrupt_quarters=4,
    min_baseline_frac=0.04,
    min_altitude_km=400,
    min_quarters=16,
):
    """
    Detect end of orbit maintenance for one satellite.

    Parameters
    ----------
    history : DataFrame
        Element sets for one object, with EPOCH and SEMIMAJOR_AXIS or
        altitude_km, plus NORAD_CAT_ID.
    baseline_quarters : int
        Quarters used to establish the satellite's own maintenance rate.
        A per-object baseline is essential: Envisat ran at roughly 0.25
        while Terra ran at roughly 0.09, both while fully maintained, so
        no single absolute threshold separates them.
    quiet_quarters : int
        Consecutive quarters below the drop threshold before cessation
        is called.
    drop_ratio : float
        Fraction of baseline below which activity counts as ceased.
    abrupt_quarters : int
        A decline completing within this many quarters is treated as a
        failure; slower declines are treated as a planned wind-down.
        Four quarters sits well inside the observed gap: Envisat's
        decline took one quarter, Terra's took about twelve.
    min_baseline_frac : float
        If the satellite never showed this much activity, it was never
        station-keeping and the detector abstains.
    min_altitude_km : float
        Below this, drag decay is rapid regardless of health and some
        craft use continuous low thrust, so the detector abstains.
    min_quarters : int
        Minimum observed quarters for any verdict.

    Returns
    -------
    DetectionResult
    """
    norad_id = int(history["NORAD_CAT_ID"].iloc[0])

    def result(status, **kwargs):
        defaults = dict(
            norad_id=norad_id,
            status=status,
            failed=(status == STATUS_FAILED),
            failure_epoch=None,
            baseline_pos_frac=None,
            final_pos_frac=None,
            transition_quarters=None,
            decay_slope_km_per_day=None,
            n_periods=0,
            reason=status,
        )
        defaults.update(kwargs)
        return DetectionResult(**defaults)

    daily = daily_series(history)
    if len(daily) < 90:
        return result(STATUS_ABSTAIN, reason="insufficient_history")

    activity = quarterly_activity(daily)

    return classify_activity(
        activity,
        norad_id=norad_id,
        daily=daily,
        baseline_quarters=baseline_quarters,
        quiet_quarters=quiet_quarters,
        drop_ratio=drop_ratio,
        abrupt_quarters=abrupt_quarters,
        min_baseline_frac=min_baseline_frac,
        min_altitude_km=min_altitude_km,
        min_quarters=min_quarters,
    )


def classify_activity(
    activity,
    norad_id,
    daily=None,
    baseline_quarters=8,
    quiet_quarters=4,
    drop_ratio=0.35,
    abrupt_quarters=4,
    min_baseline_frac=0.04,
    min_altitude_km=400,
    min_quarters=16,
):
    """
    Decision logic, separated from the daily aggregation.

    Takes an activity table with columns period, pos_frac, altitude_km
    (the output of `quarterly_activity`) and returns a DetectionResult.

    Kept separate so the classifier can be run against an activity table
    computed elsewhere — for instance one aggregated at the data source
    to avoid transferring millions of element sets — and so the decision
    rules can be tested without synthesising daily traces.

    `daily` is optional and only used to fit the post-cessation decay
    slope, which is corroboration rather than part of the decision.
    """

    def result(status, **kwargs):
        defaults = dict(
            norad_id=norad_id,
            status=status,
            failed=(status == STATUS_FAILED),
            failure_epoch=None,
            baseline_pos_frac=None,
            final_pos_frac=None,
            transition_quarters=None,
            decay_slope_km_per_day=None,
            n_periods=len(activity),
            reason=status,
        )
        defaults.update(kwargs)
        return DetectionResult(**defaults)

    if activity.empty:
        return result(STATUS_ABSTAIN, reason="insufficient_history")

    if float(activity["altitude_km"].median()) < min_altitude_km:
        return result(STATUS_ABSTAIN, reason="below_min_altitude")

    n_periods = len(activity)

    if n_periods < min_quarters:
        return result(
            STATUS_ABSTAIN, reason="insufficient_quarters", n_periods=n_periods
        )

    baseline = float(activity["pos_frac"].iloc[:baseline_quarters].median())

    if not np.isfinite(baseline) or baseline < min_baseline_frac:
        return result(
            STATUS_ABSTAIN,
            reason="no_station_keeping",
            baseline_pos_frac=baseline if np.isfinite(baseline) else None,
            n_periods=n_periods,
        )

    threshold = baseline * drop_ratio
    below = (activity["pos_frac"] < threshold).values

    # Earliest index from which the satellite stays below threshold for
    # `quiet_quarters` and never recovers.
    cessation_index = None
    for i in range(baseline_quarters, len(below) - quiet_quarters + 1):
        if below[i : i + quiet_quarters].all() and below[i:].mean() > 0.8:
            cessation_index = i
            break

    final_frac = float(activity["pos_frac"].iloc[-quiet_quarters:].median())

    if cessation_index is None:
        return result(
            STATUS_ACTIVE,
            reason="still_maintaining",
            baseline_pos_frac=baseline,
            final_pos_frac=final_frac,
            n_periods=n_periods,
        )

    cessation_epoch = pd.Timestamp(activity["period"].iloc[cessation_index])

    # How long the decline took: quarters between the last quarter at
    # near-full rate and the first quarter below threshold.
    #
    # Measured on a 3-quarter rolling median rather than the raw series.
    # Quarterly pos_frac is noisy enough that a single high quarter part
    # way down a multi-year ramp would otherwise make a gradual wind-down
    # look abrupt, which is exactly the Terra-versus-Envisat distinction
    # this number has to carry.
    smoothed = (
        activity["pos_frac"]
        .rolling(3, center=True, min_periods=1)
        .median()
        .values
    )
    above_before = np.where(smoothed[:cessation_index] >= baseline * 0.8)[0]
    transition = float(
        cessation_index - above_before[-1] if len(above_before) else cessation_index
    )

    # Decay slope after cessation, as corroboration. Only available when
    # the daily series was supplied.
    slope = None
    if daily is not None and len(daily):
        post = daily[daily["date"] >= cessation_epoch]
        if len(post) > 30:
            days = (post["date"] - post["date"].iloc[0]).dt.days.values.astype(float)
            slope = float(np.polyfit(days, post["altitude_km"].values, 1)[0])

    status = STATUS_FAILED if transition <= abrupt_quarters else STATUS_WOUND_DOWN
    reason = (
        "abrupt_cessation" if status == STATUS_FAILED else "gradual_wind_down"
    )

    return result(
        status,
        reason=reason,
        failure_epoch=cessation_epoch,
        baseline_pos_frac=baseline,
        final_pos_frac=final_frac,
        transition_quarters=transition,
        decay_slope_km_per_day=slope,
        n_periods=n_periods,
    )


def detect_population(histories, **kwargs):
    """Run the detector over every object and return a label table."""
    results = []
    for _, group in histories.groupby("NORAD_CAT_ID"):
        results.append(detect_failure(group, **kwargs).to_dict())

    frame = pd.DataFrame(results)
    if not frame.empty:
        counts = frame["status"].value_counts().to_dict()
        LOGGER.info("Detection over %d objects: %s", len(frame), counts)
    return frame


def validate_against_known(detections, known_outcomes, tolerance_days=180):
    """
    Score detections against independently documented outcomes.

    `known_outcomes` maps NORAD ID -> documented cessation date, or None
    for satellites known to be still maintained.
    """
    rows = []
    for norad_id, true_date in known_outcomes.items():
        match = detections[detections["norad_id"] == norad_id]
        if match.empty:
            rows.append(
                {
                    "norad_id": norad_id,
                    "true_date": true_date,
                    "detected_date": None,
                    "status": "not_in_population",
                    "error_days": None,
                    "correct": False,
                }
            )
            continue

        row = match.iloc[0]
        detected = row["failure_epoch"]
        error_days = None
        if true_date is not None and detected is not None and not pd.isna(detected):
            error_days = (pd.Timestamp(detected) - pd.Timestamp(true_date)).days

        if true_date is None:
            correct = not row["failed"]
        else:
            correct = bool(row["failed"]) and (
                error_days is not None and abs(error_days) <= tolerance_days
            )

        rows.append(
            {
                "norad_id": norad_id,
                "true_date": true_date,
                "detected_date": detected,
                "status": row["status"],
                "error_days": error_days,
                "correct": correct,
            }
        )

    return pd.DataFrame(rows)
