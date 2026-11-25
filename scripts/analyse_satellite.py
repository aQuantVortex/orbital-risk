#!/usr/bin/env python3
"""
Run ANY satellite through the pipeline, live.

    python scripts/analyse_satellite.py 25994
    python scripts/analyse_satellite.py 25994 --history my_download.csv
    python scripts/analyse_satellite.py 25994 --offline

Pick any NORAD catalogue number -- from CelesTrak's search page, a news
story, anywhere. The script:

    1. pulls the catalogue record from CelesTrak (no account needed)
    2. pulls the current orbit from CelesTrak
    3. pulls the element-set history from Space-Track
    4. runs the failure detector on that history
    5. cross-checks the verdict against CelesTrak's own status code
    6. scores the satellite against the fitted population model
    7. writes a figure and a JSON report

WHY TWO SOURCES. CelesTrak publishes the current element set only. The
detector needs years of history to establish a baseline and see a change
against it, and that history lives in Space-Track's gp_history -- the same
US Space Force catalogue CelesTrak redistributes. Space-Track needs a free
account (config.ini). Without one, pass --history with a file exported from
Space-Track's Query Builder, or the script stops after the CelesTrak steps
and says so.

Outputs:
    data/figures/satellites/<NORAD>.png
    data/processed/satellites/<NORAD>.json
"""

import argparse
import json
import logging
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.celestrak import CelesTrakClient, CelesTrakError
from src.failure_detection import (
    STATUS_ABSTAIN,
    STATUS_ACTIVE,
    STATUS_FAILED,
    STATUS_WOUND_DOWN,
    classify_activity,
    daily_series,
    quarterly_activity,
)
from src.features import shell_from_altitude

warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.WARNING, format="  %(levelname)s %(message)s")

EARTH_RADIUS_KM = 6378.137
MU_EARTH = 398600.4418
MARKET_RATE = 0.085
LOADING = 0.4
PROC = Path("data/processed")
FIGS = Path("data/figures/satellites")
OUT = PROC / "satellites"

VERDICT_TEXT = {
    STATUS_FAILED: "FAILED — orbit maintenance stopped abruptly",
    STATUS_WOUND_DOWN: "MAINTENANCE ENDED GRADUALLY — planned wind-down, not a failure",
    STATUS_ACTIVE: "ACTIVE — still maintaining its orbit",
    STATUS_ABSTAIN: "ABSTAIN — the detector cannot form a view",
}

ABSTAIN_TEXT = {
    "below_min_altitude": "below 400 km drag decays any satellite quickly, and "
                          "some craft use continuous thrust, so the signal is "
                          "meaningless here",
    "noise_dominated": "drag is too weak at this altitude for the sign of the "
                       "daily change to carry information",
    "no_station_keeping": "this object never showed orbit-raising activity, so "
                          "there is no maintenance to see stop",
    "insufficient_quarters": "fewer than 16 usable quarters of history — too "
                             "little to establish a baseline and see a change",
    "insufficient_history": "too little history to analyse",
}


# --------------------------------------------------------------------- output
def header(step, title):
    print(f"\n[{step}] {title}")
    print("    " + "-" * 66)


def kv(key, value):
    print(f"    {key:<28} {value}")


def fmt_date(value):
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "—"
    return str(pd.Timestamp(value).date())


# --------------------------------------------------------------------- history
def load_history_file(path, norad_id):
    """
    Load element sets exported from Space-Track's Query Builder (CSV or
    JSON). Column names are normalised to upper case; semi-major axis is
    derived from mean motion if the export does not carry it.
    """
    path = Path(path)
    if path.suffix.lower() == ".json":
        frame = pd.DataFrame(json.loads(path.read_text()))
    else:
        frame = pd.read_csv(path)
    frame.columns = [c.strip().upper() for c in frame.columns]

    if "EPOCH" not in frame.columns:
        raise ValueError(f"{path} has no EPOCH column")

    if "SEMIMAJOR_AXIS" not in frame.columns:
        if "MEAN_MOTION" not in frame.columns:
            raise ValueError(f"{path} has neither SEMIMAJOR_AXIS nor MEAN_MOTION")
        n = pd.to_numeric(frame["MEAN_MOTION"], errors="coerce") * 2 * np.pi / 86400
        frame["SEMIMAJOR_AXIS"] = (MU_EARTH / n**2) ** (1 / 3)

    frame["EPOCH"] = pd.to_datetime(frame["EPOCH"], errors="coerce")
    frame["SEMIMAJOR_AXIS"] = pd.to_numeric(frame["SEMIMAJOR_AXIS"], errors="coerce")
    if "NORAD_CAT_ID" in frame.columns:
        frame = frame[pd.to_numeric(frame["NORAD_CAT_ID"], errors="coerce") == norad_id]
    frame["NORAD_CAT_ID"] = norad_id
    return frame.dropna(subset=["EPOCH", "SEMIMAJOR_AXIS"]).sort_values("EPOCH")


def load_history_spacetrack(norad_id):
    from src.spacetrack_client import SpaceTrackClient

    client = SpaceTrackClient()
    return client.get_satellite_history(norad_id)


# --------------------------------------------------------------------- scoring
def cross_check(verdict, celestrak_code):
    """
    Compare the detector's verdict with CelesTrak's independent status code.

    The two answer different questions -- CelesTrak reports whether the
    spacecraft operates, the detector reports whether its orbit is still
    maintained -- so 'agreement' is defined by what each verdict implies.
    """
    operating = {"+", "P", "B", "S", "X"}
    dead = {"-", "D"}

    if verdict == STATUS_ABSTAIN:
        return "not compared", "the detector abstained"
    if celestrak_code in ("", "?"):
        return "not compared", "CelesTrak has no status for this object"

    if verdict == STATUS_FAILED:
        if celestrak_code in dead:
            return "AGREE", "both say the satellite is no longer working"
        return ("DISAGREE", "the detector sees an abrupt stop, but CelesTrak "
                "lists it as operating — possibly a satellite that lost "
                "propulsion but kept its payload running")

    if verdict == STATUS_WOUND_DOWN:
        if celestrak_code in operating:
            return ("AGREE", "maintenance ended but the spacecraft still "
                    "operates — exactly the Terra pattern the abruptness test "
                    "was built for")
        return ("CONSISTENT", "maintenance wound down and the spacecraft has "
                "since stopped; a planned end of mission")

    if verdict == STATUS_ACTIVE:
        if celestrak_code in operating:
            return "AGREE", "both say the satellite is alive and maintained"
        return ("DISAGREE", "the detector still sees manoeuvring but CelesTrak "
                "lists it as non-operational — check how recent the status is")

    return "not compared", ""


def score(altitude_km, launch_date):
    """Place the satellite against the fitted population model."""
    pricing = pd.read_csv(PROC / "real_pricing_comparison.csv")
    cox = pd.read_csv(PROC / "real_cox_coefficients.csv", index_col=0)
    density = pd.read_csv(PROC / "real_density_panel.csv", parse_dates=["period"])
    solar = pd.read_csv(PROC / "real_solar_flux.csv", parse_dates=["period"])
    panel = pd.read_csv(PROC / "real_panel.csv")

    shell = shell_from_altitude(altitude_km)
    out = {"shell": shell}

    shell_density = density[density["shell"] == shell].sort_values("period")
    if not shell_density.empty:
        out["density_now"] = float(shell_density["density"].iloc[-1])
        out["density_2002"] = float(shell_density["density"].iloc[0])
        out["density_series"] = shell_density
    out["f107_now"] = float(solar["f107"].iloc[-1])

    row = pricing[pricing["shell"] == shell]
    if row.empty:
        out["in_study"] = False
        return out

    row = row.iloc[0]
    out.update({
        "in_study": True,
        "shell_satellites": int(row["satellites"]),
        "shell_events": int(row["events"]),
        "shell_exposure_years": float(row["exposure_years"]),
        "empirical_rate": float(row["empirical_rate"]),
        "premium": float(row["empirical_rate"]) * (1 + LOADING),
    })
    out["vs_market"] = out["premium"] / MARKET_RATE

    # Relative hazard from the fitted Cox model: this satellite's covariates
    # against the study population's average.
    age = 0.0
    if launch_date:
        age = (pd.Timestamp.now() - pd.Timestamp(launch_date)).days / 365.25
    x = {
        "density": out.get("density_now", panel["density"].mean()),
        "f107": out["f107_now"],
        "age_years": age,
        "altitude_km": altitude_km,
    }
    lp = sum(cox.loc[c, "coef"] * (x[c] - panel[c].mean()) for c in cox.index)
    out["relative_hazard"] = float(np.exp(lp))
    out["age_years"] = age
    out["all_shells"] = pricing
    return out


# ----------------------------------------------------------------------- main
def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("norad_id", type=int, help="NORAD catalogue number")
    parser.add_argument("--history", help="element-set file exported from Space-Track")
    parser.add_argument("--offline", action="store_true",
                        help="use cached CelesTrak responses only")
    args = parser.parse_args()
    norad = args.norad_id

    print("=" * 72)
    print(f"  PRICING ORBITAL RISK — single-satellite run: NORAD {norad}")
    print(f"  {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}")
    print("=" * 72)

    report = {"norad_id": norad, "run_at": datetime.now(timezone.utc).isoformat()}

    # ---------------------------------------------------------------- 1
    header("1/7", "CelesTrak catalogue record")
    celestrak = CelesTrakClient(offline=args.offline)
    try:
        cat = celestrak.catalogue_record(norad)
    except CelesTrakError as error:
        print(f"    {error}")
        print("    Check the number — CelesTrak has no object with this ID.")
        sys.exit(1)

    kv("Name", cat["name"])
    kv("International designator", cat["international_designator"])
    kv("Object type", cat["object_type"])
    kv("Owner", cat["owner"])
    kv("Launched", cat["launch_date"] or "—")
    kv("Decayed", cat["decay_date"] or "no — still in orbit")
    kv("Apogee / perigee", f"{cat['apogee_km']:.0f} / {cat['perigee_km']:.0f} km"
       if cat["apogee_km"] is not None else "—")
    kv("Inclination", f"{cat['inclination_deg']:.2f}°" if cat["inclination_deg"] else "—")
    kv("Radar cross-section", f"{cat['rcs_m2']:.2f} m²  ({cat['mass_class']})"
       if cat["rcs_m2"] is not None else "—")
    kv("CelesTrak status", f"{cat['ops_status_code'] or '?'}  ({cat['ops_status']})")
    report["catalogue"] = cat

    notes = []
    if cat["object_type"] != "payload":
        notes.append(f"This object is {cat['object_type']}, not a payload. It has "
                     "no propulsion, so the detector should abstain, and it is "
                     "not something anyone insures — no price is produced.")
    if any(k in cat["name"].upper() for k in ("STARLINK", "ONEWEB")):
        notes.append("Mega-constellation satellite. These were excluded from the "
                     "study population and treated separately, so it is scored "
                     "against the shell average with that caveat.")
    for n in notes:
        print(f"\n    NOTE  {n}")

    # ---------------------------------------------------------------- 2
    header("2/7", "CelesTrak current orbit")
    current = celestrak.current_elements(norad)
    if current is None:
        print("    No current element set — the object has decayed, so CelesTrak")
        print("    no longer publishes its orbit. History still exists.")
    else:
        kv("Epoch", current["epoch"])
        kv("Mean motion", f"{current['mean_motion_rev_day']:.6f} rev/day")
        kv("Altitude (from mean motion)", f"{current['altitude_km']:.1f} km")
        kv("Eccentricity", f"{current['eccentricity']:.6f}")
        kv("BSTAR drag term", f"{current['bstar']:.3e}")
    report["current"] = current

    # ---------------------------------------------------------------- 3
    header("3/7", "Element-set history")
    print("    CelesTrak publishes the current element set only. The detector")
    print("    needs years of history, which comes from Space-Track gp_history.")

    history = None
    if args.history:
        history = load_history_file(args.history, norad)
        kv("Source", f"file: {args.history}")
    else:
        try:
            history = load_history_spacetrack(norad)
            kv("Source", "Space-Track gp_history (live)")
        except FileNotFoundError:
            print("\n    No config.ini, so Space-Track cannot be queried. Either")
            print("    copy config.example.ini to config.ini with your login, or")
            print("    export the history from Space-Track's Query Builder and")
            print("    re-run with --history <file>.")
        except Exception as error:  # noqa: BLE001 — report and continue
            print(f"\n    Space-Track query failed: {error}")

    if history is not None and not history.empty:
        history = history.copy()
        history["NORAD_CAT_ID"] = norad
        history["altitude_km"] = history["SEMIMAJOR_AXIS"] - EARTH_RADIUS_KM
        days = pd.to_datetime(history["EPOCH"]).dt.normalize().nunique()
        if days == len(history):
            kv("Records", f"{len(history):,}  (one per day — daily medians)")
        else:
            kv("Element sets", f"{len(history):,}")
        kv("Span", f"{fmt_date(history['EPOCH'].min())} to "
                   f"{fmt_date(history['EPOCH'].max())}")
        kv("Altitude, first → last", f"{history['altitude_km'].iloc[0]:.1f} → "
                                     f"{history['altitude_km'].iloc[-1]:.1f} km")
    elif history is not None:
        print("    Space-Track returned no element sets for this object.")
        history = None

    # Altitude to score against: measured if we have it, else catalogue.
    if history is not None:
        recent = history[history["EPOCH"] >= history["EPOCH"].max() - pd.Timedelta(days=730)]
        altitude = float(recent["altitude_km"].median())
        altitude_source = "median of last two years of history"
    elif current is not None:
        altitude = current["altitude_km"]
        altitude_source = "CelesTrak current orbit"
    else:
        altitude = cat["mean_altitude_km"]
        altitude_source = "CelesTrak catalogue apogee/perigee"
        if cat["decay_date"]:
            altitude_source += (" — for a decayed object this is the final "
                                "orbit before re-entry, not where it operated")

    if altitude is not None and altitude > 2000:
        print(f"\n    Altitude {altitude:,.0f} km is outside low Earth orbit. The")
        print("    detector relies on atmospheric drag pulling the orbit down")
        print("    every day; there is effectively no drag up here, so the")
        print("    method does not apply and the satellite is out of scope.")
        report["out_of_scope"] = f"altitude {altitude:.0f} km"
        _write(report, norad)
        sys.exit(0)

    # ---------------------------------------------------------------- 4
    header("4/7", "Failure detector")
    detection, activity, daily = None, None, None
    if history is None:
        print("    Skipped — no history available.")
    else:
        daily = daily_series(history)
        activity = quarterly_activity(daily)
        detection = classify_activity(activity, norad_id=norad, daily=daily)

        kv("Daily median altitudes", f"{len(daily):,}")
        kv("Usable quarters", f"{len(activity)}")
        if detection.baseline_pos_frac is not None:
            kv("Baseline manoeuvre frequency",
               f"{detection.baseline_pos_frac:.3f}  (first 8 quarters)")
            kv("Cut-off (35% of baseline)", f"{detection.baseline_pos_frac * 0.35:.3f}")
        if detection.final_pos_frac is not None:
            kv("Recent manoeuvre frequency", f"{detection.final_pos_frac:.3f}  (last 4 quarters)")
        if detection.failure_epoch is not None:
            kv("Cessation quarter", fmt_date(detection.failure_epoch))
            kv("Decline took", f"{detection.transition_quarters:.0f} quarter(s)")
        if detection.decay_slope_km_per_day is not None:
            kv("Altitude trend after", f"{detection.decay_slope_km_per_day * 1000:+.2f} m/day")

        print(f"\n    VERDICT  {VERDICT_TEXT[detection.status]}")
        if detection.status == STATUS_ABSTAIN:
            print(f"             reason: {detection.reason} — "
                  f"{ABSTAIN_TEXT.get(detection.reason, '')}")

        if detection.failure_epoch is not None and not activity.empty:
            ces = pd.Timestamp(detection.failure_epoch)
            window = activity[(activity["period"] >= ces - pd.DateOffset(months=18))
                              & (activity["period"] <= ces + pd.DateOffset(months=12))]
            print("\n    Manoeuvre frequency around the transition:")
            for _, r in window.iterrows():
                bar = "█" * int(round(r["pos_frac"] * 60))
                mark = "  ← cessation" if r["period"] == ces else ""
                print(f"      {r['period']:%Y} Q{(r['period'].month - 1) // 3 + 1}  "
                      f"{r['pos_frac']:.3f}  {bar}{mark}")

        report["detection"] = {k: (str(v) if isinstance(v, pd.Timestamp) else v)
                               for k, v in detection.to_dict().items()}

    # ---------------------------------------------------------------- 5
    header("5/7", "Cross-check against CelesTrak's independent status")
    if detection is None:
        print("    Skipped — detector did not run.")
    else:
        outcome, reason = cross_check(detection.status, cat["ops_status_code"])
        kv("Detector says", detection.status)
        kv("CelesTrak says", f"{cat['ops_status_code'] or '?'} ({cat['ops_status']})")
        kv("Result", outcome)
        print(f"    {reason}")
        report["cross_check"] = {"outcome": outcome, "reason": reason}

    # ---------------------------------------------------------------- 6
    header("6/7", "Risk and price against the fitted population")
    kv("Altitude used", f"{altitude:.0f} km  ({altitude_source})")

    if cat["object_type"] != "payload":
        print(f"    Not priced: this object is {cat['object_type']}. Insurance")
        print("    covers payloads; a price for debris would be meaningless.")
        risk = {"shell": shell_from_altitude(altitude), "in_study": False}
    elif altitude < 400:
        print("    Below the 400 km study floor — no population comparison.")
        risk = {"shell": None, "in_study": False}
    else:
        risk = score(altitude, cat["launch_date"])
        kv("Altitude shell", risk["shell"])
        if "density_now" in risk:
            kv("Debris density, 2002 → now",
               f"{risk['density_2002']:.1f} → {risk['density_now']:.1f} objects/km")
        if not risk["in_study"]:
            print("    No satellites from this shell entered the study panel, so")
            print("    there is no empirical rate to price against.")
        else:
            kv("Shell in the study", f"{risk['shell_satellites']} satellites, "
               f"{risk['shell_events']} failures, {risk['shell_exposure_years']:.0f} "
               f"satellite-years")
            kv("Empirical failure rate", f"{risk['empirical_rate']:.2%} per year")
            if risk["shell_satellites"] < 10 or risk["shell_events"] < 5:
                print(f"    WARNING  Thin data: only {risk['shell_satellites']} "
                      f"satellite(s) and {risk['shell_events']} failure(s) in this")
                print("             shell. Treat this rate as indicative, not reliable.")
                risk["thin_data"] = True
            kv("Risk-loaded premium", f"{risk['premium']:.2%} of insured value per year")
            kv("Market flat rate", f"{MARKET_RATE:.1%}")
            verdict = ("BELOW the market rate — the market over-charges this orbit"
                       if risk["vs_market"] < 0.8 else
                       "ABOVE the market rate — the market under-charges this orbit"
                       if risk["vs_market"] > 1.2 else "close to the market rate")
            kv("Model vs market", f"{risk['vs_market']:.2f}× — {verdict}")
            kv("Cox relative hazard", f"{risk['relative_hazard']:.3f}× the study average")
            print("    (None of the Cox coefficients is significant, so a relative")
            print("     hazard near 1 is expected. The shell rate carries the price.)")

            if detection is not None and detection.status == STATUS_FAILED:
                print("\n    This satellite has already failed, so it is no longer")
                print("    insurable in orbit. The price is what a satellite with")
                print("    this profile would have been charged.")
        report["risk"] = {k: v for k, v in risk.items()
                          if k not in ("density_series", "all_shells")}

    # ---------------------------------------------------------------- 7
    header("7/7", "Outputs")
    fig_path = _figure(norad, cat, history, daily, activity, detection, risk, altitude)
    json_path = _write(report, norad)
    kv("Figure", fig_path)
    kv("Report", json_path)
    print("\n" + "=" * 72)


# --------------------------------------------------------------------- figure
def _figure(norad, cat, history, daily, activity, detection, risk, altitude):
    FIGS.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(2, 2, figsize=(14, 8.5))

    # (a) altitude
    ax = axes[0, 0]
    if daily is not None and not daily.empty:
        ax.plot(daily["date"], daily["altitude_km"], color="#1f77b4", linewidth=0.8)
    else:
        ax.text(0.5, 0.5, "no history available", ha="center", va="center",
                transform=ax.transAxes)
    if detection is not None and detection.failure_epoch is not None:
        ax.axvline(pd.Timestamp(detection.failure_epoch), color="#ff7f0e",
                   linewidth=1.6, label=f"Detected {fmt_date(detection.failure_epoch)}")
    if cat["decay_date"]:
        ax.axvline(pd.Timestamp(cat["decay_date"]), color="#7f7f7f", linestyle=":",
                   label=f"Decayed {cat['decay_date']}")
    ax.set_ylabel("Altitude (km)")
    ax.set_title("a. Altitude history (daily median)", fontsize=11, loc="left")
    ax.grid(alpha=0.25)
    if ax.get_legend_handles_labels()[0]:
        ax.legend(fontsize=8)

    # (b) manoeuvre frequency
    ax = axes[0, 1]
    if activity is not None and not activity.empty:
        ax.plot(activity["period"], activity["pos_frac"], color="#1f77b4",
                linewidth=1.4, marker="o", markersize=2.5)
        if detection.baseline_pos_frac is not None:
            ax.axhline(detection.baseline_pos_frac, color="#2ca02c", linestyle=":",
                       label=f"Baseline {detection.baseline_pos_frac:.2f}")
            ax.axhline(detection.baseline_pos_frac * 0.35, color="#ff7f0e",
                       linestyle=":", label=f"Cut-off {detection.baseline_pos_frac*0.35:.2f}")
        if detection.failure_epoch is not None:
            ax.axvline(pd.Timestamp(detection.failure_epoch), color="#ff7f0e", linewidth=1.6)
        ax.legend(fontsize=8)
        ax.set_ylim(0, max(0.5, activity["pos_frac"].max() * 1.1))
    else:
        ax.text(0.5, 0.5, "detector did not run", ha="center", va="center",
                transform=ax.transAxes)
    ax.set_ylabel("Fraction of days altitude rose")
    status = detection.status if detection is not None else "not run"
    ax.set_title(f"b. Manoeuvre frequency → {status}", fontsize=11, loc="left")
    ax.grid(alpha=0.25)

    # (c) debris environment
    ax = axes[1, 0]
    series = risk.get("density_series") if risk else None
    if series is not None and not series.empty:
        ax.plot(series["period"], series["density"], color="#9467bd", linewidth=1.6)
        if cat["launch_date"]:
            ax.axvline(pd.Timestamp(cat["launch_date"]), color="#7f7f7f",
                       linestyle=":", label=f"Launched {cat['launch_date']}")
            ax.legend(fontsize=8)
        ax.set_title(f"c. Debris environment in the {risk['shell']} shell",
                     fontsize=11, loc="left")
    else:
        ax.text(0.5, 0.5, "no density data for this altitude", ha="center",
                va="center", transform=ax.transAxes)
        ax.set_title("c. Debris environment", fontsize=11, loc="left")
    ax.set_ylabel("Tracked objects per km")
    ax.grid(alpha=0.25)

    # (d) pricing
    ax = axes[1, 1]
    if risk and risk.get("in_study"):
        shells = risk["all_shells"].sort_values("modelled_rate")
        colors = ["#d62728" if s == risk["shell"] else "#c7c7c7" for s in shells["shell"]]
        ax.barh(shells["shell"], shells["modelled_rate"] * 100, color=colors)
        ax.axvline(MARKET_RATE * 100, color="black", linestyle="--",
                   label=f"Market flat rate {MARKET_RATE:.1%}")
        ax.set_xlabel("Annual premium (% of insured value)")
        ax.legend(fontsize=8)
        ax.set_title(f"d. Price: {risk['premium']:.2%} vs market {MARKET_RATE:.1%}",
                     fontsize=11, loc="left")
    else:
        ax.text(0.5, 0.5, "no population comparison for this orbit", ha="center",
                va="center", transform=ax.transAxes)
        ax.set_title("d. Price", fontsize=11, loc="left")
    ax.grid(alpha=0.25, axis="x")

    fig.suptitle(f"{cat['name']} (NORAD {norad}) — {cat['object_type']}, "
                 f"launched {cat['launch_date']}, CelesTrak status: {cat['ops_status']}",
                 fontsize=12.5, y=0.995)
    plt.tight_layout(rect=[0, 0, 1, 0.965])
    path = FIGS / f"{norad}.png"
    fig.savefig(path, dpi=140, bbox_inches="tight")
    plt.close(fig)
    return str(path)


def _write(report, norad):
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{norad}.json"
    path.write_text(json.dumps(report, indent=2, default=str))
    return str(path)


if __name__ == "__main__":
    main()
