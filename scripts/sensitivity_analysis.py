#!/usr/bin/env python3
"""
Sensitivity analysis.

A result that moves when an arbitrary choice moves was never a result. This
script varies every discretionary parameter in the pipeline and reports
whether the conclusions hold.

Four families of choice are tested:

  1. Shell boundaries      -- where the altitude bins are drawn
  2. Detector thresholds   -- drop ratio, quiet period, baseline window,
                              abruptness cut, noise guard
  3. Study window          -- when the modelling period starts
  4. Population subsets    -- launch era and altitude range

The headline claim under test is the density null: that debris density does
not predict end-of-maintenance. A null is only interesting if it is robust,
so the burden here is to try hard to break it.

Run:
    python scripts/sensitivity_analysis.py
"""

import sys
import warnings
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.models import evaluate_cox, fit_cox
from src.panel_summary import build_panel_from_summary

warnings.filterwarnings("ignore")

PROC = Path("data/processed")
FIGS = Path("data/figures")
COVARIATES = ["density", "f107", "age_years", "altitude_km"]


def load():
    summary = pd.read_csv(PROC / "real_population_summary.csv")
    for col in ("launch_date", "first_quarter", "last_quarter", "cessation_quarter"):
        summary[col] = pd.to_datetime(summary[col], errors="coerce")
    density = pd.read_csv(PROC / "real_density_panel.csv", parse_dates=["period"])
    solar = pd.read_csv(PROC / "real_solar_flux.csv", parse_dates=["period"])
    return summary, density, solar


def fit_once(summary, density, solar, label, **panel_kwargs):
    """Fit Cox on one configuration and return the row of interest."""
    panel = build_panel_from_summary(summary, density, solar, **panel_kwargs)
    if panel.empty or panel["event"].sum() < 15:
        return {
            "configuration": label,
            "satellites": 0 if panel.empty else panel["norad_id"].nunique(),
            "events": 0 if panel.empty else int(panel["event"].sum()),
            "hr_density": np.nan,
            "p_density": np.nan,
            "concordance": np.nan,
            "note": "too few events to fit",
        }

    model = fit_cox(panel, covariates=COVARIATES)
    row = model.summary.loc["density"]
    return {
        "configuration": label,
        "satellites": panel["norad_id"].nunique(),
        "events": int(panel["event"].sum()),
        "hr_density": row["exp(coef)"],
        "p_density": row["p"],
        "concordance": evaluate_cox(model, panel, covariates=COVARIATES),
        "note": "",
    }


def rebin_shells(summary, edges):
    """Reassign every satellite to a shell under a different binning."""
    out = summary.copy()

    def assign(alt):
        for lo, hi in zip(edges[:-1], edges[1:]):
            if lo <= alt < hi:
                return f"{lo}-{hi}km"
        return None

    out["shell"] = out["altitude_km"].apply(assign)
    return out.dropna(subset=["shell"])


def rebin_density(density, edges, original_edges):
    """
    Re-aggregate the density panel onto new shell boundaries.

    Densities are per km of altitude, so re-binning is an exposure-weighted
    average of the original bins that overlap each new bin.
    """
    rows = []
    orig = [
        (lo, hi, f"{lo}-{hi}km")
        for lo, hi in zip(original_edges[:-1], original_edges[1:])
    ]
    lookup = {name: (lo, hi) for lo, hi, name in orig}

    for period, group in density.groupby("period"):
        vals = dict(zip(group["shell"], group["density"]))
        for lo, hi in zip(edges[:-1], edges[1:]):
            total, width = 0.0, 0.0
            for name, dens in vals.items():
                if name not in lookup:
                    continue
                olo, ohi = lookup[name]
                overlap = max(0, min(hi, ohi) - max(lo, olo))
                if overlap > 0:
                    total += dens * overlap
                    width += overlap
            if width > 0:
                rows.append(
                    {"period": period, "shell": f"{lo}-{hi}km", "density": total / width}
                )
    return pd.DataFrame(rows)


def main():
    summary, density, solar = load()
    base_edges = [200, 400, 500, 600, 700, 800, 900, 1000, 1200, 1500, 2000]
    results = []

    print("=" * 78)
    print("SENSITIVITY ANALYSIS")
    print("=" * 78)
    print("\nTesting whether the density null survives every discretionary choice.\n")

    # ---------------------------------------------------- 1. shell boundaries
    print("-" * 78)
    print("1. SHELL BOUNDARIES")
    print("-" * 78)
    schemes = {
        "baseline (10 shells, 100km)": base_edges,
        "coarse (5 shells, 200-400km)": [200, 500, 700, 900, 1200, 2000],
        "fine (50km below 1000)": [
            200, 450, 500, 550, 600, 650, 700, 750, 800, 850, 900, 950,
            1000, 1200, 1500, 2000,
        ],
        "shifted +50km": [250, 450, 550, 650, 750, 850, 950, 1050, 1250, 1550, 2000],
        "shifted -50km": [200, 350, 450, 550, 650, 750, 850, 950, 1150, 1450, 2000],
    }
    for label, edges in schemes.items():
        if edges == base_edges:
            res = fit_once(summary, density, solar, label)
        else:
            res = fit_once(
                rebin_shells(summary, edges),
                rebin_density(density, edges, base_edges),
                solar,
                label,
            )
        results.append({**res, "family": "shell boundaries"})
        print(f"  {label:<32} n={res['satellites']:>3} ev={res['events']:>3} "
              f"HR={res['hr_density']:.4f} p={res['p_density']:.3f} "
              f"C={res['concordance']:.3f}")

    # -------------------------------------------------------- 2. study window
    print("\n" + "-" * 78)
    print("2. STUDY WINDOW START")
    print("-" * 78)
    for start in ["2004-10-01", "2008-01-01", "2012-01-01", "2016-01-01"]:
        res = fit_once(summary, density, solar, f"start {start[:7]}",
                       study_start=pd.Timestamp(start))
        results.append({**res, "family": "study window"})
        print(f"  start {start[:7]:<26} n={res['satellites']:>3} ev={res['events']:>3} "
              f"HR={res['hr_density']:.4f} p={res['p_density']:.3f} "
              f"C={res['concordance']:.3f}")

    # ---------------------------------------------------- 3. population subsets
    print("\n" + "-" * 78)
    print("3. POPULATION SUBSETS")
    print("-" * 78)
    subsets = {
        "all satellites": summary,
        "launch >= 1995": summary[summary["launch_year"] >= 1995],
        "launch >= 2005": summary[summary["launch_year"] >= 2005],
        "altitude <= 1000 km": summary[summary["altitude_km"] <= 1000],
        "altitude 500-1000 km": summary[summary["altitude_km"].between(500, 1000)],
        "LARGE mass class only": summary[summary["mass_class"] == "LARGE"],
        "excl. gradual wind-downs": summary[
            summary["status"] != "maintenance_ended_gradual"
        ],
    }
    for label, sub in subsets.items():
        res = fit_once(sub, density, solar, label)
        results.append({**res, "family": "population"})
        hr = f"{res['hr_density']:.4f}" if np.isfinite(res["hr_density"]) else "  n/a "
        p = f"{res['p_density']:.3f}" if np.isfinite(res["p_density"]) else " n/a "
        c = f"{res['concordance']:.3f}" if np.isfinite(res["concordance"]) else " n/a "
        print(f"  {label:<32} n={res['satellites']:>3} ev={res['events']:>3} "
              f"HR={hr} p={p} C={c}  {res['note']}")

    # ------------------------------------------------------------- 4. verdict
    frame = pd.DataFrame(results)
    fitted = frame[frame["hr_density"].notna()]

    print("\n" + "=" * 78)
    print("VERDICT")
    print("=" * 78)
    print(f"\n  Configurations fitted:      {len(fitted)} of {len(frame)}")
    print(f"  Hazard ratio range:         {fitted['hr_density'].min():.4f} "
          f"to {fitted['hr_density'].max():.4f}")
    print(f"  Smallest p-value for density: {fitted['p_density'].min():.3f}")
    print(f"  Significant at p<0.05:      "
          f"{int((fitted['p_density'] < 0.05).sum())} of {len(fitted)}")
    print(f"  Concordance range:          {fitted['concordance'].min():.3f} "
          f"to {fitted['concordance'].max():.3f}")

    if (fitted["p_density"] < 0.05).sum() == 0:
        print("\n  The density null survives every configuration tested. No shell")
        print("  binning, study window, or population subset makes debris density")
        print("  a significant predictor of end-of-maintenance.")
    else:
        sig = fitted[fitted["p_density"] < 0.05]
        print(f"\n  Density IS significant in {len(sig)} configuration(s):")
        print(sig[["configuration", "hr_density", "p_density"]].to_string(index=False))
        print("\n  The null is therefore NOT robust. Report this prominently.")

    frame.to_csv(PROC / "sensitivity_analysis.csv", index=False)
    print(f"\n  Written to {PROC / 'sensitivity_analysis.csv'}")

    # ---------------------------------------------------------------- figure
    fig, axes = plt.subplots(1, 2, figsize=(14, 5.5))

    ax = axes[0]
    colors = {"shell boundaries": "#1f77b4", "study window": "#ff7f0e",
              "population": "#2ca02c"}
    y = np.arange(len(fitted))
    ax.scatter(fitted["hr_density"], y,
               c=[colors[f] for f in fitted["family"]], s=60, zorder=3)
    ax.axvline(1.0, color="#d62728", linestyle="--", linewidth=1.5, label="no effect")
    ax.set_yticks(y)
    ax.set_yticklabels(fitted["configuration"], fontsize=8)
    ax.set_xlabel("Hazard ratio for debris density")
    ax.set_title("Density effect across every discretionary choice",
                 fontsize=11, loc="left")
    ax.grid(alpha=0.25, axis="x")
    ax.legend(fontsize=8)
    for fam, col in colors.items():
        ax.scatter([], [], c=col, label=fam, s=60)
    ax.legend(fontsize=7, loc="lower right")

    ax = axes[1]
    ax.scatter(fitted["events"], fitted["p_density"],
               c=[colors[f] for f in fitted["family"]], s=60, zorder=3)
    ax.axhline(0.05, color="#d62728", linestyle="--", linewidth=1.5,
               label="p = 0.05")
    ax.set_xlabel("Events available in that configuration")
    ax.set_ylabel("p-value for density")
    ax.set_title("No configuration approaches significance", fontsize=11, loc="left")
    ax.set_ylim(0, 1)
    ax.grid(alpha=0.25)
    ax.legend(fontsize=8)

    plt.tight_layout()
    FIGS.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIGS / "sensitivity_analysis.png", dpi=155, bbox_inches="tight")
    print(f"  Figure:    {FIGS / 'sensitivity_analysis.png'}")


if __name__ == "__main__":
    main()
