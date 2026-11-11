#!/usr/bin/env python3
"""
Run the detector against real Space-Track data for four documented satellites.

Reads data/processed/real_quarterly_activity.csv, which holds the quarterly
manoeuvre-frequency series aggregated from gp_history on 11 November 2026:

    Envisat  29,574 element sets   8,932 days   100 quarters
    Terra    33,164 element sets   9,785 days   109 quarters
    Aura     15,278 element sets   7,951 days    90 quarters
    GOCE      4,607 element sets   1,511 days    20 quarters

The aggregation (daily median altitude, then per-quarter positive-delta
fraction with gaps over three days skipped) is the same computation
`quarterly_activity` performs. It is done at the data source because
transferring 82,000 element sets to compute a 319-row table is wasteful.
`scripts/validate_detector.py` performs the identical run end to end from
the API when credentials are configured.

Run:
    python scripts/run_real_validation.py
"""

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.failure_detection import (
    STATUS_ABSTAIN,
    STATUS_FAILED,
    STATUS_WOUND_DOWN,
    classify_activity,
)

DATA = Path("data/processed/real_quarterly_activity.csv")

# name -> (documented cessation date or None, expected status, note)
EXPECTED = {
    "Envisat": (
        "2012-04-08",
        STATUS_FAILED,
        "ESA Earth observation. Abrupt, permanent contact loss.",
    ),
    "Terra": (
        None,
        STATUS_WOUND_DOWN,
        "NASA EOS. Operational in 2026; orbit maintenance ended ~2020. "
        "Must NOT be called a failure.",
    ),
    "Aura": (
        None,
        None,
        "NASA EOS. Operational control case.",
    ),
    "GOCE": (
        "2013-10-21",
        STATUS_ABSTAIN,
        "Continuous ion thrust at ~255 km, below the altitude floor.",
    ),
}


def main():
    if not DATA.exists():
        sys.exit(f"Missing {DATA}. See the module docstring.")

    frame = pd.read_csv(DATA, parse_dates=["period"])
    results = []

    fig, axes = plt.subplots(4, 2, figsize=(13, 12))

    for row_axes, (name, (documented, expected, note)) in zip(axes, EXPECTED.items()):
        group = frame[frame["name"] == name].sort_values("period").reset_index(drop=True)
        norad_id = int(group["norad_id"].iloc[0])

        detection = classify_activity(
            group[["period", "pos_frac", "altitude_km"]], norad_id=norad_id
        )

        print(f"\n--- {name} (#{norad_id}) ---")
        print(f"    {note}")
        print(f"    {len(group)} quarters, "
              f"{group['period'].min().date()} to {group['period'].max().date()}")
        print(f"    Status: {detection.status} ({detection.reason})")
        if detection.baseline_pos_frac is not None:
            print(f"    Baseline manoeuvre frequency: {detection.baseline_pos_frac:.3f}")
        if detection.final_pos_frac is not None:
            print(f"    Final manoeuvre frequency:    {detection.final_pos_frac:.3f}")
        if detection.transition_quarters is not None:
            print(f"    Decline took {detection.transition_quarters:.0f} quarters")
        if detection.failure_epoch is not None:
            print(f"    Detected cessation: {pd.Timestamp(detection.failure_epoch).date()}")

        error_days = None
        if documented and detection.failure_epoch is not None:
            error_days = (
                pd.Timestamp(detection.failure_epoch) - pd.Timestamp(documented)
            ).days
            print(f"    Error vs documented ({documented}): {error_days:+d} days")

        correct = expected is None or detection.status == expected
        print(f"    Expected {expected or 'any'} -> {'PASS' if correct else 'FAIL'}")

        # Plot
        ax_alt, ax_freq = row_axes
        ax_alt.plot(group["period"], group["altitude_km"], color="#1f77b4", linewidth=1.2)
        ax_alt.set_ylabel("Altitude (km)")
        ax_alt.set_title(f"{name} (#{norad_id}) — altitude", fontsize=10)

        ax_freq.plot(group["period"], group["pos_frac"], color="#1f77b4", linewidth=1.2)
        if detection.baseline_pos_frac:
            ax_freq.axhline(
                detection.baseline_pos_frac, color="#2ca02c", linestyle=":",
                linewidth=1, label=f"Baseline {detection.baseline_pos_frac:.2f}",
            )
        ax_freq.set_ylabel("Fraction of days with altitude rise")
        ax_freq.set_title(f"{name} — manoeuvre frequency → {detection.status}", fontsize=10)
        ax_freq.set_ylim(0, max(0.5, group["pos_frac"].max() * 1.1))

        for ax in row_axes:
            if documented:
                ax.axvline(pd.Timestamp(documented), color="#d62728", linestyle="--",
                           linewidth=1.4, label=f"Documented {documented}")
            if detection.failure_epoch is not None:
                ax.axvline(pd.Timestamp(detection.failure_epoch), color="#ff7f0e",
                           linewidth=1.4,
                           label=f"Detected {pd.Timestamp(detection.failure_epoch).date()}")
            ax.grid(alpha=0.25)
            ax.legend(fontsize=7, loc="best")
            ax.tick_params(axis="x", labelrotation=30, labelsize=7)

        results.append({
            "norad_id": norad_id, "name": name, "documented": documented,
            "detected": detection.failure_epoch, "status": detection.status,
            "expected": expected, "error_days": error_days,
            "baseline_pos_frac": detection.baseline_pos_frac,
            "final_pos_frac": detection.final_pos_frac,
            "transition_quarters": detection.transition_quarters,
            "correct": correct,
        })

    fig.suptitle(
        "Detector validation against real Space-Track data (pulled 11 Nov 2026)",
        fontsize=12, y=0.998,
    )
    plt.tight_layout()
    out = Path("data/figures")
    out.mkdir(parents=True, exist_ok=True)
    fig.savefig(out / "detector_validation.png", dpi=150, bbox_inches="tight")

    summary = pd.DataFrame(results)
    summary.to_csv("data/processed/detector_validation.csv", index=False)

    print("\n" + "=" * 72)
    print(summary[["name", "status", "expected", "error_days", "correct"]].to_string(index=False))
    print(f"\nCorrect: {summary['correct'].sum()}/{len(summary)}")
    print(f"Figure:  {out / 'detector_validation.png'}")
    print("=" * 72)


if __name__ == "__main__":
    main()
