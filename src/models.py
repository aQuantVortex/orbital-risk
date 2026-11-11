"""
Survival models and the pricing layer.

Three models, each with a job:

  Cox proportional hazards -- primary. Leaves the baseline hazard
  unspecified, which matters because spacecraft ageing is not a shape we
  can responsibly assume (infant mortality, flat middle, wear-out as
  propellant depletes). Supports time-varying covariates.

  Weibull AFT -- forecasting. Cox estimates the baseline only at times
  where failures were observed, so it cannot extrapolate past the study
  window. Remaining-life estimates need a parametric survival function.

  Logistic regression -- the baseline to beat. A fixed one-year window,
  failed or not. If Cox does not beat it, the added complexity is not
  earning its place, and the report should say so.
"""

import logging

import numpy as np
import pandas as pd
from lifelines import CoxPHFitter, CoxTimeVaryingFitter, WeibullAFTFitter
from lifelines.statistics import proportional_hazard_test
from lifelines.utils import concordance_index
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

LOGGER = logging.getLogger(__name__)

DEFAULT_COVARIATES = ["density", "f107", "age_years", "altitude_km"]


def temporal_split(panel, cutoff="2020-01-01"):
    """
    Split by calendar time, not at random.

    Random splitting would put the same satellite's periods on both sides
    and leak. Splitting by time also matches how the model would be used:
    fit on history, predict forward.
    """
    cutoff = pd.Timestamp(cutoff)
    train = panel[panel["period"] < cutoff].copy()
    test = panel[panel["period"] >= cutoff].copy()
    LOGGER.info(
        "Train: %d rows / %d events | Test: %d rows / %d events",
        len(train),
        int(train["event"].sum()),
        len(test),
        int(test["event"].sum()),
    )
    return train, test


def fit_cox(panel, covariates=None, penalizer=0.1):
    """
    Fit Cox PH with time-varying covariates in counting-process format.

    `penalizer` applies ridge regularisation. With a modest event count
    relative to covariates, some shrinkage is prudent.
    """
    covariates = covariates or DEFAULT_COVARIATES
    columns = ["norad_id", "t_start", "t_stop", "event"] + covariates
    frame = panel[columns].dropna()

    n_events = int(frame["event"].sum())
    if n_events < 10 * len(covariates):
        LOGGER.warning(
            "Only %d events for %d covariates. Rule of thumb wants >=%d; "
            "estimates will be unstable.",
            n_events,
            len(covariates),
            10 * len(covariates),
        )

    # CoxTimeVaryingFitter is the counting-process form: it accepts one row
    # per subject per interval, which is what makes time-varying covariates
    # possible. Plain CoxPHFitter takes one row per subject and cannot.
    model = CoxTimeVaryingFitter(penalizer=penalizer)
    model.fit(
        frame,
        id_col="norad_id",
        start_col="t_start",
        stop_col="t_stop",
        event_col="event",
        show_progress=False,
    )
    return model


def check_proportional_hazards(model, panel, covariates=None):
    """
    Test the one assumption Cox actually makes.

    Cox assumes the hazard ratio between two satellites is constant over
    time. Scaled Schoenfeld residuals regressed on time will show a
    significant slope where that fails. The remedies are stratification or
    an explicit covariate-by-time interaction.

    lifelines' Schoenfeld test targets CoxPHFitter, so the panel is
    collapsed to one interval per satellite and refitted for the test.
    This checks the assumption on the same covariates at their mean
    values, which is the standard compromise when covariates vary.
    """
    covariates = covariates or DEFAULT_COVARIATES

    collapsed = (
        panel.groupby("norad_id")
        .agg(
            duration=("t_stop", "max"),
            event=("event", "max"),
            **{c: (c, "mean") for c in covariates},
        )
        .reset_index()
        .dropna()
    )
    collapsed = collapsed[collapsed["duration"] > 0].drop(columns=["norad_id"])

    try:
        static = CoxPHFitter(penalizer=0.1)
        static.fit(collapsed, duration_col="duration", event_col="event")
        return proportional_hazard_test(static, collapsed, time_transform="rank")
    except Exception as error:  # noqa: BLE001
        LOGGER.warning("PH test failed: %s", error)
        return None


class WeibullPricer:
    """
    Weibull AFT with covariate standardisation, for the pricing layer.

    Standardisation matters here: raw covariates span very different
    magnitudes (altitude ~800, density ~2, age ~5), which conditions the
    optimiser badly and produces unstable shape estimates. The scaler is
    retained so predictions can be made on the same footing.
    """

    def __init__(self, model, scaler, covariates, collapsed):
        self.model = model
        self.scaler = scaler
        self.covariates = covariates
        self.collapsed = collapsed

    @property
    def rho(self):
        """Weibull shape. >1 means hazard rises with age (wear-out)."""
        return float(np.exp(self.model.params_[("rho_", "Intercept")]))

    def _standardise(self, covariate_row):
        values = np.array([[covariate_row[c] for c in self.covariates]])
        scaled = self.scaler.transform(values)
        return pd.DataFrame(scaled, columns=self.covariates)

    def survival_at(self, covariate_row, times):
        frame = self._standardise(covariate_row)
        return self.model.predict_survival_function(frame, times=times)


def fit_weibull(panel, covariates=None):
    """
    Weibull AFT on one interval per satellite, for extrapolation.

    Important: fit this on the FULL panel, not a temporally truncated
    training split. A temporal split censors every surviving satellite at
    the same calendar instant, piling most durations onto one value, and
    the shape parameter then describes the censoring boundary rather than
    the failure process. The temporal split exists to evaluate Cox's
    ranking; the pricing curve wants all available follow-up.
    """
    covariates = covariates or DEFAULT_COVARIATES

    collapsed = (
        panel.groupby("norad_id")
        .agg(
            duration=("t_stop", "max"),
            event=("event", "max"),
            **{c: (c, "mean") for c in covariates},
        )
        .reset_index()
        .dropna()
    )
    collapsed = collapsed[collapsed["duration"] > 0]

    scaler = StandardScaler().fit(collapsed[covariates].values)
    scaled = pd.DataFrame(
        scaler.transform(collapsed[covariates].values), columns=covariates
    )
    scaled["duration"] = collapsed["duration"].values
    scaled["event"] = collapsed["event"].values

    model = WeibullAFTFitter()
    model.fit(scaled, duration_col="duration", event_col="event")

    return WeibullPricer(model, scaler, covariates, collapsed), collapsed


def fit_logistic_baseline(panel, covariates=None, horizon_weeks=52):
    """
    The naive comparison: did this satellite fail within one year.

    Discards timing entirely -- a failure at week 4 and one at week 50 are
    the same observation -- and handles partial follow-up badly. That is
    precisely the information survival analysis keeps.

    The label is built per observation row, not per satellite: for each
    satellite-period, did that satellite fail within the following
    `horizon_weeks`? Labelling on total lifetime instead would make every
    satellite observed longer than the horizon a negative, which collapses
    to a single class and is not the comparison we want.
    """
    covariates = covariates or DEFAULT_COVARIATES

    frame = panel[["norad_id", "t_start", "t_stop", "event"] + covariates].dropna()
    frame = frame.copy()

    # Failure time per satellite, where one occurred.
    failure_times = (
        frame[frame["event"] == 1].groupby("norad_id")["t_stop"].max().to_dict()
    )

    def label_row(row):
        failure_time = failure_times.get(row["norad_id"])
        if failure_time is None:
            return 0
        return int(0 <= failure_time - row["t_start"] <= horizon_weeks)

    frame["label"] = frame.apply(label_row, axis=1)

    X = frame[covariates].values
    y = frame["label"].values

    if len(np.unique(y)) < 2:
        LOGGER.warning("Baseline has a single class; skipping.")
        return None, None, frame

    scaler = StandardScaler().fit(X)
    model = LogisticRegression(max_iter=1000, class_weight="balanced")
    model.fit(scaler.transform(X), y)
    LOGGER.info(
        "Baseline fitted: %d rows, %d positives (%.1f%%)",
        len(frame),
        int(y.sum()),
        100 * y.mean(),
    )
    return model, scaler, frame


def evaluate_cox(model, panel, covariates=None):
    """
    Concordance index on held-out data.

    Of all pairs where we can tell which satellite failed first, the share
    the model ranked correctly. 0.5 is a coin flip. On messy real data,
    0.65-0.75 is a respectable result; 0.95 means something leaked.

    Note this measures discrimination, not calibration. The model can rank
    perfectly while being wrong about absolute probabilities, which is why
    the market-aggregate check exists separately.
    """
    covariates = covariates or DEFAULT_COVARIATES

    collapsed = (
        panel.groupby("norad_id")
        .agg(
            duration=("t_stop", "max"),
            event=("event", "max"),
            **{c: (c, "mean") for c in covariates},
        )
        .reset_index()
        .dropna()
    )

    if collapsed["event"].sum() < 2:
        return np.nan

    risk = model.predict_partial_hazard(collapsed[covariates])
    return concordance_index(collapsed["duration"], -risk, collapsed["event"])


def bandwidth_sensitivity(panel_builder, bandwidths):
    """
    Refit across KDE bandwidths and report coefficient stability.

    If conclusions flip when the smoothing parameter moves, they were not
    conclusions. `panel_builder` is a callable taking a bandwidth and
    returning a panel.
    """
    rows = []
    for bw in bandwidths:
        try:
            panel = panel_builder(bw)
            model = fit_cox(panel)
            summary = model.summary
            rows.append(
                {
                    "bandwidth": bw,
                    "density_coef": summary.loc["density", "coef"],
                    "density_hr": summary.loc["density", "exp(coef)"],
                    "density_p": summary.loc["density", "p"],
                    "n_events": int(panel["event"].sum()),
                }
            )
        except Exception as error:  # noqa: BLE001
            LOGGER.warning("Bandwidth %s failed: %s", bw, error)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Pricing layer
# ---------------------------------------------------------------------------


def annual_failure_probability(pricer, covariates_row, current_age_weeks):
    """
    P(fail within the next year | survived to current age).

    Conditional survival: 1 - S(t+52)/S(t). The conditioning matters --
    we are pricing a policy on a satellite that has already survived to
    `current_age_weeks`, not on one at launch.
    """
    t0 = float(current_age_weeks)
    t1 = t0 + 52.0

    curve = pricer.survival_at(covariates_row, times=[t0, t1])
    s0 = float(curve.values[0][0])
    s1 = float(curve.values[1][0])

    if s0 <= 1e-9:
        return 1.0
    return float(np.clip(1.0 - (s1 / s0), 0.0, 1.0))


def premium_rate(failure_probability, risk_loading=0.4):
    """
    Risk-adjusted premium as a fraction of insured value.

    Expected loss plus a loading. The loading exists because space losses
    are severe and correlated: one fragmentation event damages many
    satellites at once, so an insurer's variance far exceeds what
    independence would imply. That correlation is why capacity leaves the
    market after a bad year.
    """
    return float(failure_probability * (1 + risk_loading))


def compare_to_market(shell_rates, market_rate=0.085):
    """
    Modelled rate per shell against the market's flat rate.

    `market_rate` defaults to 8.5%, the midpoint of the 5-12% band quoted
    in broker market reports.
    """
    frame = pd.DataFrame(
        [{"shell": k, "modelled_rate": v} for k, v in shell_rates.items()]
    )
    frame["market_rate"] = market_rate
    frame["ratio"] = frame["modelled_rate"] / market_rate
    frame["verdict"] = np.where(
        frame["ratio"] > 1.2,
        "underpriced",
        np.where(frame["ratio"] < 0.8, "overpriced", "roughly fair"),
    )
    return frame.sort_values("ratio", ascending=False)
