#!/usr/bin/env python3
"""
Validate the failure detector against satellites with documented outcomes.

Run:
    python scripts/validate_detector.py

Produces data/figures/detector_validation.png and prints a comparison of
detected failure dates against independently documented ones.

The test set is deliberately small and hand-picked: these are satellites
whose end-of-life dates are a matter of public record, so any disagreement
is the detector's fault rather than ambiguity in the ground truth.
"""

import logging
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.spacetrack_client import SpaceTrackClient
from src.features import add_geometry
from src.failure_detection import detect_failure, detect_maneuvers
from src.ingest import decimate_weekly

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

# NORAD ID -> (name, documented outcome date or None, note)
VALIDATION_SET = {
    27386: (
        "Envisat",
        "2012-04-08",
        "ESA Earth observation. Abrupt, permanent contact loss.",
    ),
    34602: (
        "GOCE",
        "2013-10-21",
        "Ion thruster ran to propellant exhaustion; reentered 3 weeks later.",
    ),
    25994: (
        "Terra",
        None,
        "NASA EOS flagship, still operational. Control case: must NOT fire.",
    ),
    28376: (
        "Aura",
        None,
        "NASA EOS, still operational. Second control case.",
    ),
}


def plot_satellite(ax, frame, name, documented, detection):
    """Altitude trace with manoeuvres, documented date and detected date."""
    geo = add_geometry(frame).dropna(subset=["altitude_km"])
    ax.plot(
        geo["EPOCH"], geo["altitude_km"], linewidth=0.9, color="#1f77b4", label="Altitude"
    )

    maneuvers = detect_maneuvers(geo["altitude_km"].values)
    if len(maneuvers) > 0:
        ax.scatter(
            geo["EPOCH"].iloc[maneuvers],
            geo["altitude_km"].iloc[maneuvers],
            s=6,
            color="#2ca02c",
            alpha=0.6,
            label=f"Detected manoeuvres (n={len(maneuvers)})",
            zorder=3,
        )

    if documented:
        ax.axvline(
            pd.Timestamp(documented),
            color="#d62728",
            linestyle="--",
            linewidth=1.5,
            label=f"Documented: {documented}",
        )

    if detection.failed and detection.failure_epoch is not None:
        ax.axvline(
            detection.failure_epoch,
            color="#ff7f0e",
            linestyle="-",
            linewidth=1.5,
            label=f"Detected: {detection.failure_epoch.date()}",
        )

    verdict = "FAILURE DETECTED" if detection.failed else f"no failure ({detection.reason})"
    ax.set_title(f"{name} (#{detection.norad_id}) — {verdict}", fontsize=10)
    ax.set_ylabel("Altitude (km)")
    ax.legend(fontsize=7, loc="best")
    ax.grid(alpha=0.25)


def main():
    client = SpaceTrackClient()
    results = []

    fig, axes = plt.subplots(len(VALIDATION_SET), 1, figsize=(11, 3.2 * len(VALIDATION_SET)))
    if len(VALIDATION_SET) == 1:
        axes = [axes]

    for ax, (norad_id, (name, documented, note)) in zip(axes, VALIDATION_SET.items()):
        print(f"\n--- {name} (#{norad_id}) ---")
        print(f"    {note}")

        history = client.get_satellite_history(norad_id)
        if history.empty:
            print("    No data returned.")
            continue

        weekly = decimate_weekly(history)
        weekly["NORAD_CAT_ID"] = norad_id
        weekly = add_geometry(weekly)

        print(f"    {len(history)} element sets -> {len(weekly)} weekly rows")
        print(f"    Span: {weekly['EPOCH'].min().date()} to {weekly['EPOCH'].max().date()}")

        detection = detect_failure(weekly)
        plot_satellite(ax, weekly, name, documented, detection)

        error_days = None
        if documented and detection.failure_epoch is not None:
            error_days = (detection.failure_epoch - pd.Timestamp(documented)).days

        print(f"    Manoeuvres found: {detection.n_maneuvers}")
        print(f"    Verdict: {'FAILED' if detection.failed else 'no failure'} ({detection.reason})")
        if detection.failure_epoch is not None:
            print(f"    Detected date: {detection.failure_epoch.date()}")
        if error_days is not None:
            print(f"    Error vs documented: {error_days:+d} days")
        if detection.bstar_ratio is not None:
            print(f"    BSTAR ratio after/before: {detection.bstar_ratio:.2f}")

        results.append(
            {
                "norad_id": norad_id,
                "name": name,
                "documented": documented,
                "detected": detection.failure_epoch,
                "error_days": error_days,
                "n_maneuvers": detection.n_maneuvers,
                "reason": detection.reason,
                "correct": (
                    (documented is not None and detection.failed)
                    or (documented is None and not detection.failed)
                ),
            }
        )

    plt.tight_layout()
    out_dir = Path("data/figures")
    out_dir.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_dir / "detector_validation.png", dpi=150, bbox_inches="tight")
    print(f"\nFigure written to {out_dir / 'detector_validation.png'}")

    summary = pd.DataFrame(results)
    summary.to_csv("data/processed/detector_validation.csv", index=False)
    print("\n" + summary.to_string(index=False))
    if not summary.empty:
        print(f"\nCorrect classifications: {summary['correct'].sum()}/{len(summary)}")


if __name__ == "__main__":
    main()
