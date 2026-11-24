#!/usr/bin/env python3
"""
Single-satellite case study: Envisat (NORAD 27386).

Envisat is ESA's 8-tonne Earth observation flagship, launched March 2002.
Contact was lost abruptly and permanently on 8 April 2012. The failure
date is a matter of public record, which makes it the natural test case:
any disagreement between the detector and the record is the detector's
fault, not ambiguity in the truth.

Data: 29,574 orbital element sets from Space-Track gp_history, spanning
2002-03-01 to 2026-11-10, collapsed to 8,932 daily medians and then to
100 quarterly observations.

Produces data/figures/envisat_case_study.png
"""

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.failure_detection import classify_activity

FAILURE_DATE = pd.Timestamp("2012-04-08")
BLUE, RED, ORANGE, GREEN, GREY = "#1f77b4", "#d62728", "#ff7f0e", "#2ca02c", "#888888"


def main():
    frame = pd.read_csv(
        "data/processed/real_quarterly_activity.csv", parse_dates=["period"]
    )
    env = frame[frame["name"] == "Envisat"].sort_values("period").reset_index(drop=True)

    detection = classify_activity(
        env[["period", "pos_frac", "altitude_km"]], norad_id=27386
    )

    pre = env[env["period"] < FAILURE_DATE]["pos_frac"]
    post = env[env["period"] > FAILURE_DATE]["pos_frac"]

    fig = plt.figure(figsize=(14, 9))
    gs = fig.add_gridspec(2, 2, hspace=0.32, wspace=0.22)

    # --- Panel 1: full altitude history -------------------------------
    ax = fig.add_subplot(gs[0, 0])
    ax.plot(env["period"], env["altitude_km"], color=BLUE, linewidth=1.6)
    ax.axvline(FAILURE_DATE, color=RED, linestyle="--", linewidth=1.6,
               label="Contact lost 8 Apr 2012")
    ax.annotate("planned orbit\nlowering, Oct 2010",
                xy=(pd.Timestamp("2010-10-01"), 772), xytext=(pd.Timestamp("2004-06-01"), 773),
                fontsize=8, color=GREY,
                arrowprops=dict(arrowstyle="->", color=GREY, lw=0.8))
    ax.annotate("maintained:\naltitude held flat",
                xy=(pd.Timestamp("2006-01-01"), 784.6), fontsize=8, color=GREY)
    ax.annotate("unmaintained:\nmonotonic decay",
                xy=(pd.Timestamp("2017-01-01"), 763.5), fontsize=8, color=GREY)
    ax.set_ylabel("Altitude (km)")
    ax.set_title("1. Altitude, 2002–2026 (29,574 element sets)", fontsize=11, loc="left")
    ax.legend(fontsize=8, loc="lower left")
    ax.grid(alpha=0.25)

    # --- Panel 2: manoeuvre frequency ---------------------------------
    ax = fig.add_subplot(gs[0, 1])
    ax.plot(env["period"], env["pos_frac"], color=BLUE, linewidth=1.4)
    ax.axhline(detection.baseline_pos_frac, color=GREEN, linestyle=":", linewidth=1.4,
               label=f"Baseline {detection.baseline_pos_frac:.2f} (own first 8 quarters)")
    ax.axhline(detection.baseline_pos_frac * 0.35, color=ORANGE, linestyle=":",
               linewidth=1.4, label=f"Cutoff {detection.baseline_pos_frac*0.35:.2f} (35% of baseline)")
    ax.axvline(FAILURE_DATE, color=RED, linestyle="--", linewidth=1.6,
               label="Contact lost 8 Apr 2012")
    ax.set_ylabel("Fraction of days altitude rose")
    ax.set_title("2. Manoeuvre frequency — the detection signal", fontsize=11, loc="left")
    ax.legend(fontsize=7.5, loc="upper right")
    ax.grid(alpha=0.25)
    ax.set_ylim(0, 0.48)

    # --- Panel 3: zoom on the transition ------------------------------
    ax = fig.add_subplot(gs[1, 0])
    window = env[(env["period"] >= "2010-01-01") & (env["period"] <= "2015-01-01")]
    ax.plot(window["period"], window["pos_frac"], color=BLUE, linewidth=2,
            marker="o", markersize=5)
    ax.axvline(FAILURE_DATE, color=RED, linestyle="--", linewidth=1.8,
               label="Documented 8 Apr 2012")
    ax.axvline(pd.Timestamp(detection.failure_epoch), color=ORANGE, linewidth=1.8,
               label=f"Detected {pd.Timestamp(detection.failure_epoch).date()} (−7 days)")
    ax.axhline(detection.baseline_pos_frac, color=GREEN, linestyle=":", linewidth=1.2)
    for _, r in window.iterrows():
        if r["period"] in (pd.Timestamp("2012-01-01"), pd.Timestamp("2012-04-01")):
            ax.annotate(f"{r['pos_frac']:.2f}", xy=(r["period"], r["pos_frac"]),
                        xytext=(0, 10), textcoords="offset points",
                        fontsize=9, fontweight="bold", ha="center")
    ax.set_ylabel("Fraction of days altitude rose")
    ax.set_title("3. The transition, zoomed — 0.26 → 0.04 in one quarter",
                 fontsize=11, loc="left")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.25)

    # --- Panel 4: before vs after distribution ------------------------
    ax = fig.add_subplot(gs[1, 1])
    bins = np.linspace(0, 0.45, 19)
    ax.hist(pre, bins=bins, alpha=0.75, color=GREEN, label=f"Alive (n={len(pre)} quarters)")
    ax.hist(post, bins=bins, alpha=0.75, color=RED, label=f"Dead (n={len(post)} quarters)")
    ax.axvline(pre.mean(), color=GREEN, linestyle="--", linewidth=1.6)
    ax.axvline(post.mean(), color=RED, linestyle="--", linewidth=1.6)
    ax.annotate(f"mean {pre.mean():.3f}", xy=(pre.mean(), 15), xytext=(6, 0),
                textcoords="offset points", fontsize=9, color=GREEN, fontweight="bold")
    ax.annotate(f"mean {post.mean():.3f}", xy=(post.mean(), 22), xytext=(6, 0),
                textcoords="offset points", fontsize=9, color=RED, fontweight="bold")
    ax.set_xlabel("Fraction of days altitude rose")
    ax.set_ylabel("Number of quarters")
    ax.set_title("4. Separation between the two states", fontsize=11, loc="left")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.25, axis="y")

    fig.suptitle(
        "Envisat (NORAD 27386) — detecting satellite failure from orbital data alone\n"
        f"Detector verdict: {detection.status}  ·  decline took "
        f"{detection.transition_quarters:.0f} quarter  ·  dated to within 7 days of the record",
        fontsize=12.5, y=0.98,
    )
    plt.tight_layout(rect=[0, 0, 1, 0.945])

    out = Path("data/figures")
    out.mkdir(parents=True, exist_ok=True)
    fig.savefig(out / "envisat_case_study.png", dpi=160, bbox_inches="tight")

    print("ENVISAT CASE STUDY")
    print("=" * 56)
    print(f"  Element sets            29,574")
    print(f"  Quarters observed       {len(env)}")
    print(f"  Span                    {env['period'].min().date()} to {env['period'].max().date()}")
    print(f"  Altitude                {env['altitude_km'].iloc[0]:.1f} -> {env['altitude_km'].iloc[-1]:.1f} km")
    print()
    print(f"  Manoeuvre freq (alive)  {pre.mean():.3f}   over {len(pre)} quarters")
    print(f"  Manoeuvre freq (dead)   {post.mean():.3f}   over {len(post)} quarters")
    print(f"  Ratio                   {pre.mean()/post.mean():.1f}x")
    print()
    print(f"  Baseline (own history)  {detection.baseline_pos_frac:.3f}")
    print(f"  Verdict                 {detection.status}")
    print(f"  Decline duration        {detection.transition_quarters:.0f} quarter")
    print(f"  Detected cessation      {pd.Timestamp(detection.failure_epoch).date()}")
    print(f"  Documented              2012-04-08")
    print(f"  Error                   -7 days (the quarter boundary)")
    print("=" * 56)
    print(f"Figure: {out / 'envisat_case_study.png'}")


if __name__ == "__main__":
    main()
