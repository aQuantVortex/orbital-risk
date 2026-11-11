#!/usr/bin/env python3
"""
End-to-end pipeline verification on synthetic data.

NOTE: every number this produces is synthetic. The point is not the
result, it is that the full chain -- trace -> detection -> panel ->
survival model -> premium -> market comparison -- runs and produces
sane, well-typed output before any real API time is spent on it.

The synthetic generator is calibrated to magnitudes measured from real
Space-Track data on 2026-11-11 (see data/processed/validation_observations.csv):

    maintenance burn size     ~0.016 km per burn
    decay at ~766 km          ~0.001 km/day
    pos_frac while maintained 0.09 to 0.25, varying BY SATELLITE
    pos_frac after cessation  ~0.018

Satellites in denser shells are given shorter characteristic lives, so a
working pipeline should recover a positive density coefficient. A share
of satellites also wind down gradually rather than failing, reproducing
the Terra case the detector has to exclude.

Run:
    python scripts/pipeline_smoke_test.py
"""

import logging
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.failure_detection import (
    STATUS_FAILED,
    STATUS_WOUND_DOWN,
    daily_series,
    detect_population,
    quarterly_activity,
)
from src.models import (
    annual_failure_probability,
    check_proportional_hazards,
    compare_to_market,
    evaluate_cox,
    fit_cox,
    fit_logistic_baseline,
    fit_weibull,
    premium_rate,
    temporal_split,
)
from src.panel import build_panel

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

EARTH_RADIUS_KM = 6378.137

# Synthetic shells: higher density -> shorter characteristic life.
SHELLS = {
    "500-600km": {"altitude": 550.0, "density": 0.9, "scale_days": 2600},
    "600-700km": {"altitude": 650.0, "density": 2.8, "scale_days": 1500},
    "700-800km": {"altitude": 750.0, "density": 1.4, "scale_days": 2200},
    "800-900km": {"altitude": 850.0, "density": 0.6, "scale_days": 3000},
}

# Fraction of satellites that wind down gradually instead of failing.
WIND_DOWN_SHARE = 0.15


def make_population(n_per_shell=40, n_days=4400, seed=11):
    """
    Generate synthetic satellites at realistic magnitudes.

    Launch dates are staggered. This is not cosmetic: if every satellite
    enters the study at the same instant, every censored one leaves it at
    an identical duration, and the Weibull fit collapses onto that spike
    instead of describing the failure process.

    Each satellite gets its OWN maintenance rate, drawn between 0.08 and
    0.28, matching the spread observed between Terra and Envisat. A
    detector keyed to an absolute threshold would fail on this population.
    """
    rng = np.random.default_rng(seed)
    frames = []
    truth = []
    norad = 90000

    for shell, spec in SHELLS.items():
        for _ in range(n_per_shell):
            norad += 1

            launch_offset = int(rng.uniform(0, n_days * 0.45))
            observed_days = n_days - launch_offset

            scale = spec["scale_days"]
            draw = int(rng.weibull(1.7) * scale)

            cessation_day = None
            wind_down = 0
            outcome = "active"
            if 500 < draw < observed_days - 400:
                cessation_day = draw
                if rng.random() < WIND_DOWN_SHARE:
                    wind_down = int(rng.uniform(1100, 1600))  # ~3-4 years
                    outcome = "wind_down"
                else:
                    outcome = "failed"

            altitude = spec["altitude"] + rng.normal(0, 10)
            decay = 0.0010 + rng.normal(0, 0.0002)
            burn_prob = float(rng.uniform(0.08, 0.28))

            values = []
            current = altitude
            for day in range(observed_days):
                if cessation_day is None:
                    p = burn_prob
                elif wind_down > 0:
                    ramp_start = cessation_day - wind_down
                    if day < ramp_start:
                        p = burn_prob
                    elif day < cessation_day:
                        p = burn_prob * (1 - (day - ramp_start) / wind_down)
                    else:
                        p = 0.0
                else:
                    p = burn_prob if day < cessation_day else 0.0

                current -= decay
                if rng.random() < p:
                    current += 0.016
                values.append(current + rng.normal(0, 0.0003))

            launch_date = pd.Timestamp("2012-01-01") + pd.DateOffset(
                days=int(launch_offset)
            )
            epochs = pd.date_range(launch_date, periods=observed_days, freq="D")

            frames.append(
                pd.DataFrame(
                    {
                        "EPOCH": epochs,
                        "NORAD_CAT_ID": norad,
                        "SEMIMAJOR_AXIS": np.array(values) + EARTH_RADIUS_KM,
                        "INCLINATION": 97.0 + rng.normal(0, 1.5),
                        "ECCENTRICITY": 0.001,
                        "BSTAR": 1e-5,
                    }
                )
            )
            truth.append(
                {
                    "norad_id": norad,
                    "shell": shell,
                    "outcome": outcome,
                    "truly_failed": outcome == "failed",
                    "burn_prob": burn_prob,
                }
            )

    return pd.concat(frames, ignore_index=True), pd.DataFrame(truth)


def synth_density_panel(histories):
    """Density panel matching the synthetic shells, with upward drift."""
    periods = (
        histories["EPOCH"].dt.to_period("Q").dt.to_timestamp().drop_duplicates().sort_values()
    )
    rows = []
    for i, period in enumerate(periods):
        drift = 1.0 + 0.012 * i
        for shell, spec in SHELLS.items():
            rows.append(
                {"period": period, "shell": shell, "density": spec["density"] * drift}
            )
    return pd.DataFrame(rows)


def synth_solar(histories):
    """An 11-year solar cycle over the study window."""
    dates = pd.date_range(histories["EPOCH"].min(), histories["EPOCH"].max(), freq="MS")
    t = np.arange(len(dates))
    return pd.DataFrame({"date": dates, "f107": 130 + 60 * np.sin(2 * np.pi * t / 132)})


def main():
    print("=" * 70)
    print("PIPELINE SMOKE TEST — SYNTHETIC DATA, NOT RESULTS")
    print("=" * 70)

    print("\n[1/6] Generating synthetic population...")
    histories, truth = make_population()
    print(f"      {len(truth)} satellites, {len(histories):,} daily rows")
    print(f"      Outcomes: {truth['outcome'].value_counts().to_dict()}")
    print(
        f"      Maintenance rates span "
        f"{truth['burn_prob'].min():.2f} to {truth['burn_prob'].max():.2f}"
    )

    print("\n[2/6] Running failure detection...")
    detections = detect_population(histories)
    merged = detections.merge(truth, on="norad_id")

    tp = int((merged["failed"] & merged["truly_failed"]).sum())
    fp = int((merged["failed"] & ~merged["truly_failed"]).sum())
    fn = int((~merged["failed"] & merged["truly_failed"]).sum())
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    print(f"      Status counts: {detections['status'].value_counts().to_dict()}")
    print(f"      TP={tp}  FP={fp}  FN={fn}")
    print(f"      Precision {precision:.3f} | Recall {recall:.3f}")

    wind = merged[merged["outcome"] == "wind_down"]
    if len(wind):
        caught = int((wind["status"] == STATUS_WOUND_DOWN).sum())
        print(
            f"      Gradual wind-downs correctly separated: "
            f"{caught}/{len(wind)} (the Terra case)"
        )

    print("\n[3/6] Building survival panel...")
    panel = build_panel(
        histories,
        detections,
        synth_density_panel(histories),
        solar_flux=synth_solar(histories),
    )
    print(f"      {len(panel):,} satellite-quarter rows")
    print(f"      {panel['norad_id'].nunique()} objects, {int(panel['event'].sum())} events")
    censored = 1 - panel.groupby("norad_id")["event"].max().mean()
    print(f"      Censoring rate: {censored:.1%}")

    print("\n[4/6] Fitting models...")
    train, test = temporal_split(panel, cutoff="2020-01-01")

    cox = fit_cox(train)
    print("\n      Cox proportional hazards:")
    for name, row in cox.summary[["coef", "exp(coef)", "p"]].iterrows():
        print(
            f"        {name:<14} coef {row['coef']:+.4f}  "
            f"HR {row['exp(coef)']:.3f}  p {row['p']:.4f}"
        )

    c_train = evaluate_cox(cox, train)
    c_test = evaluate_cox(cox, test)
    print(f"\n      Concordance  train {c_train:.3f} | test {c_test:.3f}")

    n_events = int(train["event"].sum())
    n_cov = len(cox.params_)
    print(f"\n      NOTE: {n_events} events for {n_cov} covariates "
          f"(rule of thumb wants >={10 * n_cov}).")

    ph = check_proportional_hazards(cox, train)
    if ph is not None:
        print(f"      PH assumption violated for "
              f"{(ph.summary['p'] < 0.05).sum()}/{len(ph.summary)} covariates")

    weibull, _ = fit_weibull(panel)
    print(f"      Weibull shape rho {weibull.rho:.2f} (>1 means hazard rises with age)")

    logit, _, baseline_frame = fit_logistic_baseline(train)
    if logit is not None:
        pos = int(baseline_frame["label"].sum())
        print(f"      Logistic baseline: {len(baseline_frame)} rows, {pos} positives")

    print("\n[5/6] Pricing layer...")
    rates = {
        shell: premium_rate(
            annual_failure_probability(
                weibull,
                {
                    "density": spec["density"],
                    "f107": 130.0,
                    "age_years": 5.0,
                    "altitude_km": spec["altitude"],
                },
                current_age_weeks=260,
            )
        )
        for shell, spec in SHELLS.items()
    }
    comparison = compare_to_market(rates)
    print()
    print(comparison.to_string(index=False))

    print("\n[6/6] Writing figure...")
    fig, axes = plt.subplots(1, 3, figsize=(16, 4.4))

    failed_id = merged[merged["outcome"] == "failed"]["norad_id"].iloc[0]
    wound_id = merged[merged["outcome"] == "wind_down"]["norad_id"].iloc[0]

    for ax, sat_id, label in (
        (axes[0], failed_id, "Abrupt failure"),
        (axes[1], wound_id, "Gradual wind-down"),
    ):
        hist = histories[histories["NORAD_CAT_ID"] == sat_id]
        activity = quarterly_activity(daily_series(hist))
        ax.plot(activity["period"], activity["pos_frac"], color="#1f77b4", linewidth=1.3)
        ax.axhline(0.018, color="#d62728", linestyle=":", linewidth=1,
                   label="Envisat post-failure (0.018)")
        ax.set_title(f"{label} — manoeuvre frequency", fontsize=10)
        ax.set_ylabel("Fraction of days with altitude rise")
        ax.set_ylim(0, 0.45)
        ax.legend(fontsize=7)
        ax.grid(alpha=0.25)
        ax.tick_params(axis="x", labelrotation=30, labelsize=7)

    ordered = comparison.sort_values("modelled_rate")
    axes[2].barh(ordered["shell"], ordered["modelled_rate"] * 100, color="#1f77b4")
    axes[2].axvline(8.5, color="#d62728", linestyle="--", linewidth=1.5,
                    label="Market flat rate")
    axes[2].set_xlabel("Annual premium (% of insured value)")
    axes[2].set_title("Modelled vs flat market rate (SYNTHETIC)", fontsize=10)
    axes[2].legend(fontsize=8)
    axes[2].grid(alpha=0.25, axis="x")

    plt.tight_layout()
    out = Path("data/figures")
    out.mkdir(parents=True, exist_ok=True)
    fig.savefig(out / "pipeline_smoke_test.png", dpi=150, bbox_inches="tight")
    print(f"      Written to {out / 'pipeline_smoke_test.png'}")

    print("\n" + "=" * 70)
    print("Pipeline runs end to end. Figures are synthetic; next step is")
    print("the same chain on the real Space-Track population.")
    print("=" * 70)


if __name__ == "__main__":
    main()
