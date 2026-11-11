#!/usr/bin/env python3
"""
Validate the failure detector against satellites with documented outcomes.

Run:
    python scripts/validate_detector.py

Requires config.ini with Space-Track credentials. Produces
data/figures/detector_validation.png and prints detected cessation dates
against documented ones.

The test set is deliberately small and hand-picked: these are satellites
whose end-of-life circumstances are a matter of public record, so any
disagreement is the detector's fault rather than ambiguity in the truth.

Terra is the important case. It is still operational in 2026, but NASA
ended its orbit maintenance around 2020. On the frequency statistic alone
it is indistinguishable from a dead satellite, so the detector must
classify it as a gradual wind-down rather than a failure. Getting Terra
right is a harder test than getting Envisat right.
"""

import logging
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.failure_detection import (
    STATUS_FAILED,
    STATUS_WOUND_DOWN,
    daily_series,
    detect_failure,
    quarterly_activity,
)
from src.spacetrack_client import SpaceTrackClient

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

# NORAD ID -> (name, documented cessation date or None, expected status, note)
VALIDATION_SET = {
    27386: (
        "Envisat",
        "2012-04-08",
        STATUS_FAILED,
        "ESA Earth observation. Abrupt, permanent contact loss.",
    ),
    25994: (
        "Terra",
        None,
        STATUS_WOUND_DOWN,
        "NASA EOS flagship. Still operational; orbit maintenance ended ~2020. "
        "Must NOT be labelled a failure.",
    ),
    28376: (
        "Aura",
        None,
        None,
        "NASA EOS. Second control case.",
    ),
    34602: (
        "GOCE",
        "2013-10-21",
        None,
        "Ion thruster to propellant exhaustion at ~255 km. Below the "
        "altitude floor, so the detector should abstain.",
    ),
}


def plot_satellite(axes, hist, name, documented, detection):
    """Altitude trace and manoeuvre-frequency trace, side by side."""
    daily = daily_series(hist)
    activity = quarterly_activity(daily)

    ax_alt, ax_freq = axes

    ax_alt.plot(daily["date"], daily["altitude_km"], linewidth=0.7, color="#1f77b4")
    ax_alt.set_ylabel("Altitude (km)")
    ax_alt.set_title(f"{name} (#{detection.norad_id}) — altitude", fontsize=10)

    if not activity.empty:
        ax_freq.plot(
            activity["period"], activity["pos_frac"], linewidth=1.2, color="#1f77b4"
        )
    if detection.baseline_pos_frac:
        ax_freq.axhline(
            detection.baseline_pos_frac,
            color="#2ca02c",
            linestyle=":",
            linewidth=1,
            label=f"Baseline {detection.baseline_pos_frac:.2f}",
        )
    ax_freq.set_ylabel("Fraction of days with altitude rise")
    ax_freq.set_title(f"{name} — manoeuvre frequency ({detection.status})", fontsize=10)

    for ax in (ax_alt, ax_freq):
        if documented:
            ax.axvline(
                pd.Timestamp(documented),
                color="#d62728",
                linestyle="--",
                linewidth=1.4,
                label=f"Documented {documented}",
            )
        if detection.failure_epoch is not None:
            ax.axvline(
                detection.failure_epoch,
                color="#ff7f0e",
                linewidth=1.4,
                label=f"Detected {pd.Timestamp(detection.failure_epoch).date()}",
            )
        ax.grid(alpha=0.25)
        ax.legend(fontsize=7, loc="best")
        ax.tick_params(axis="x", labelrotation=30, labelsize=7)


def main():
    client = SpaceTrackClient()
    results = []

    fig, axes = plt.subplots(len(VALIDATION_SET), 2, figsize=(13, 3.2 * len(VALIDATION_SET)))

    for row_axes, (norad_id, (name, documented, expected, note)) in zip(
        axes, VALIDATION_SET.items()
    ):
        print(f"\n--- {name} (#{norad_id}) ---")
        print(f"    {note}")

        history = client.get_satellite_history(norad_id)
        if history.empty:
            print("    No data returned.")
            continue

        history["NORAD_CAT_ID"] = norad_id
        detection = detect_failure(history)
        plot_satellite(row_axes, history, name, documented, detection)

        error_days = None
        if documented and detection.failure_epoch is not None:
            error_days = (
                pd.Timestamp(detection.failure_epoch) - pd.Timestamp(documented)
            ).days

        print(f"    Element sets: {len(history):,}")
        print(f"    Status: {detection.status} ({detection.reason})")
        if detection.baseline_pos_frac is not None:
            print(f"    Baseline manoeuvre frequency: {detection.baseline_pos_frac:.3f}")
        if detection.final_pos_frac is not None:
            print(f"    Final manoeuvre frequency:    {detection.final_pos_frac:.3f}")
        if detection.transition_quarters is not None:
            print(f"    Transition took {detection.transition_quarters:.0f} quarters")
        if error_days is not None:
            print(f"    Error vs documented: {error_days:+d} days")

        correct = expected is None or detection.status == expected
        print(f"    Expected {expected or 'any'} -> {'PASS' if correct else 'FAIL'}")

        results.append(
            {
                "norad_id": norad_id,
                "name": name,
                "documented": documented,
                "detected": detection.failure_epoch,
                "status": detection.status,
                "expected": expected,
                "error_days": error_days,
                "baseline_pos_frac": detection.baseline_pos_frac,
                "final_pos_frac": detection.final_pos_frac,
                "correct": correct,
            }
        )

    plt.tight_layout()
    out_dir = Path("data/figures")
    out_dir.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_dir / "detector_validation.png", dpi=150, bbox_inches="tight")
    print(f"\nFigure written to {out_dir / 'detector_validation.png'}")

    summary = pd.DataFrame(results)
    Path("data/processed").mkdir(parents=True, exist_ok=True)
    summary.to_csv("data/processed/detector_validation.csv", index=False)
    print("\n" + summary.to_string(index=False))
    if not summary.empty:
        print(f"\nCorrect: {summary['correct'].sum()}/{len(summary)}")


if __name__ == "__main__":
    main()
