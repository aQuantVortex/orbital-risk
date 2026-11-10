#!/usr/bin/env python3
"""
End-to-end pipeline verification on synthetic data.

NOTE: every number this produces is synthetic. The point is not the
result, it is that the full chain -- trace -> detection -> panel ->
survival model -> premium -> market comparison -- runs and produces
sane, well-typed output before any real API time is spent on it.

A synthetic population is generated where failure hazard genuinely does
rise with shell density, so a working pipeline should recover a positive
density coefficient. If it does not, the bug is in the code rather than
in the orbital data.

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

from src.failure_detection import detect_population, detect_maneuvers
from src.models import (
    fit_cox,
    fit_logistic_baseline,
    fit_weibull,
    temporal_split,
    evaluate_cox,
    check_proportional_hazards,
    annual_failure_probability,
    premium_rate,
    compare_to_market,
)
from src.panel import build_panel

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

EARTH_RADIUS_KM = 6378.137

# Synthetic shells: higher density -> higher true hazard.
SHELLS = {
    "500-600km": {"altitude": 550.0, "density": 0.9, "hazard": 0.45},
    "600-700km": {"altitude": 650.0, "density": 2.8, "hazard": 0.75},
    "700-800km": {"altitude": 750.0, "density": 1.4, "hazard": 0.55},
    "800-900km": {"altitude": 850.0, "density": 0.6, "hazard": 0.30},
}


def make_population(n_per_shell=45, n_weeks=620, seed=11):
    """
    Generate synthetic satellites whose failure risk depends on shell.

    Launch dates are staggered. This is not cosmetic: if every satellite
    enters the study at the same instant, every censored one leaves it at
    an identical duration, and the Weibull fit collapses onto that spike
    instead of describing the failure process. Real catalogues have
    staggered entry, and the generator has to reproduce that for the
    pipeline test to mean anything.
    """
    rng = np.random.default_rng(seed)
    frames = []
    truth = []
    norad = 90000

    for shell, spec in SHELLS.items():
        for _ in range(n_per_shell):
            norad += 1

            # Staggered launch: each satellite observes a different span.
            launch_offset_weeks = int(rng.uniform(0, n_weeks * 0.55))
            observed_weeks = n_weeks - launch_offset_weeks

            # Hazard must act on failure TIMING, not merely on whether a
            # failure happens. Survival models estimate timing, so a
            # generator that only varies the failure *rate* encodes no
            # signal the model could recover. Here a denser shell scales
            # the characteristic life down, so satellites there fail
            # sooner -- which is the relationship the fit should find.
            scale = 420.0 / (0.5 + spec["hazard"])
            draw = int(rng.weibull(1.6) * scale)
            if 100 < draw < observed_weeks - 50:
                failure_week = draw
            else:
                failure_week = None

            altitude = spec["altitude"] + rng.normal(0, 12)
            decay = 0.06 + rng.normal(0, 0.012)
            boost_every = int(rng.integers(20, 32))

            values = []
            current = altitude
            for week in range(observed_weeks):
                alive = failure_week is None or week < failure_week
                if alive:
                    current -= decay
                    if week > 0 and week % boost_every == 0:
                        current += 2.4
                else:
                    current -= decay * (1 + (week - failure_week) / 200.0)
                values.append(current + rng.normal(0, 0.03))

            launch_date = pd.Timestamp("2012-01-01") + pd.DateOffset(
                days=int(launch_offset_weeks) * 7
            )
            epochs = pd.date_range(launch_date, periods=observed_weeks, freq="W")
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
                    "true_failure_week": failure_week,
                    "truly_failed": failure_week is not None,
                }
            )

    return pd.concat(frames, ignore_index=True), pd.DataFrame(truth)


def synth_density_panel(histories):
    """Density panel matching the synthetic shells, with a mild upward drift."""
    periods = (
        histories["EPOCH"].dt.to_period("Q").dt.to_timestamp().drop_duplicates().sort_values()
    )
    rows = []
    for i, period in enumerate(periods):
        drift = 1.0 + 0.012 * i  # debris environment worsens over time
        for shell, spec in SHELLS.items():
            rows.append(
                {"period": period, "shell": shell, "density": spec["density"] * drift}
            )
    return pd.DataFrame(rows)


def synth_solar(histories):
    """An 11-year solar cycle over the study window."""
    dates = pd.date_range(
        histories["EPOCH"].min(), histories["EPOCH"].max(), freq="MS"
    )
    t = np.arange(len(dates))
    f107 = 130 + 60 * np.sin(2 * np.pi * t / 132)
    return pd.DataFrame({"date": dates, "f107": f107})


def main():
    print("=" * 68)
    print("PIPELINE SMOKE TEST — SYNTHETIC DATA, NOT RESULTS")
    print("=" * 68)

    print("\n[1/6] Generating synthetic population...")
    histories, truth = make_population()
    print(f"      {truth.shape[0]} satellites, {len(histories):,} weekly rows")
    print(f"      True failures: {int(truth['truly_failed'].sum())}")

    print("\n[2/6] Running failure detection...")
    detections = detect_population(histories)
    merged = detections.merge(truth, on="norad_id")
    tp = int(((merged["failed"]) & (merged["truly_failed"])).sum())
    fp = int(((merged["failed"]) & (~merged["truly_failed"])).sum())
    fn = int(((~merged["failed"]) & (merged["truly_failed"])).sum())
    tn = int(((~merged["failed"]) & (~merged["truly_failed"])).sum())
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    print(f"      TP={tp}  FP={fp}  FN={fn}  TN={tn}")
    print(f"      Precision {precision:.3f} | Recall {recall:.3f}")

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
    summary = cox.summary[["coef", "exp(coef)", "p"]]
    print("\n      Cox proportional hazards:")
    for name, row in summary.iterrows():
        print(
            f"        {name:<14} coef {row['coef']:+.4f}  "
            f"HR {row['exp(coef)']:.3f}  p {row['p']:.4f}"
        )

    c_train = evaluate_cox(cox, train)
    c_test = evaluate_cox(cox, test)
    print(f"\n      Concordance  train {c_train:.3f} | test {c_test:.3f}")

    n_events = int(train["event"].sum())
    n_cov = len(cox.params_)
    print(
        f"\n      NOTE: {n_events} events for {n_cov} covariates. The rule of "
        f"thumb wants >={10 * n_cov}."
    )
    print(
        "      Coefficients at this event count are underpowered, which is "
        "the\n      whole argument for deriving failure labels from orbital "
        "behaviour\n      rather than from curated registries."
    )

    ph = check_proportional_hazards(cox, train)
    if ph is not None:
        violations = (ph.summary["p"] < 0.05).sum()
        print(f"      PH assumption violated for {violations}/{len(ph.summary)} covariates")

    # Weibull is fitted on the full panel: a temporal split censors every
    # survivor at the same instant, which distorts the shape parameter.
    weibull, collapsed = fit_weibull(panel)
    print(f"      Weibull shape rho {weibull.rho:.2f} (>1 means hazard rises with age)")

    logit, scaler, baseline_frame = fit_logistic_baseline(train)
    if logit is not None:
        positives = int(baseline_frame["label"].sum())
        print(
            f"      Logistic baseline: {len(baseline_frame)} rows, "
            f"{positives} positives ({100 * positives / len(baseline_frame):.1f}%)"
        )

    print("\n[5/6] Pricing layer...")
    rates = {}
    for shell, spec in SHELLS.items():
        covariates = {
            "density": spec["density"],
            "f107": 130.0,
            "age_years": 5.0,
            "altitude_km": spec["altitude"],
        }
        p_fail = annual_failure_probability(weibull, covariates, current_age_weeks=260)
        rates[shell] = premium_rate(p_fail)

    comparison = compare_to_market(rates)
    print()
    print(comparison.to_string(index=False))

    print("\n[6/6] Writing figure...")
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.5))

    example = histories[histories["NORAD_CAT_ID"] == histories["NORAD_CAT_ID"].iloc[0]]
    alt = example["SEMIMAJOR_AXIS"] - EARTH_RADIUS_KM
    axes[0].plot(example["EPOCH"], alt, linewidth=0.9, color="#1f77b4")
    burns = detect_maneuvers(alt.values)
    if len(burns):
        axes[0].scatter(
            example["EPOCH"].iloc[burns],
            alt.iloc[burns],
            s=8,
            color="#2ca02c",
            zorder=3,
            label=f"Manoeuvres (n={len(burns)})",
        )
        axes[0].legend(fontsize=8)
    axes[0].set_title("Synthetic altitude trace with detected manoeuvres", fontsize=10)
    axes[0].set_ylabel("Altitude (km)")
    axes[0].grid(alpha=0.25)

    comparison_sorted = comparison.sort_values("modelled_rate")
    axes[1].barh(
        comparison_sorted["shell"],
        comparison_sorted["modelled_rate"] * 100,
        color="#1f77b4",
        label="Modelled",
    )
    axes[1].axvline(8.5, color="#d62728", linestyle="--", linewidth=1.5, label="Market flat rate")
    axes[1].set_xlabel("Annual premium (% of insured value)")
    axes[1].set_title("Modelled vs flat market rate (SYNTHETIC)", fontsize=10)
    axes[1].legend(fontsize=8)
    axes[1].grid(alpha=0.25, axis="x")

    plt.tight_layout()
    out = Path("data/figures")
    out.mkdir(parents=True, exist_ok=True)
    fig.savefig(out / "pipeline_smoke_test.png", dpi=150, bbox_inches="tight")
    print(f"      Written to {out / 'pipeline_smoke_test.png'}")

    print("\n" + "=" * 68)
    print("Pipeline runs end to end. Figures are synthetic; next step is")
    print("the same chain on real Space-Track data.")
    print("=" * 68)


if __name__ == "__main__":
    main()
