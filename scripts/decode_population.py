#!/usr/bin/env python3
"""
Decode the packed per-satellite detection results into a population CSV.

The detector runs at the data source (see docs/methodology.md, "Running
detection at the source"), because transferring tens of millions of
element sets to derive a few hundred summary rows is wasteful. Each
satellite comes back as a single pipe-delimited record:

    id|shell|alt|incl|launchYYMM|status|cessYYQ|firstYYQ|lastYYQ|rcs|base|trans

Reads data/processed/raw_population_packed.txt (semicolon-separated
records, any number of lines) and writes real_population_summary.csv.
"""

import sys
from pathlib import Path

import pandas as pd

SHELLS = [
    "200-400km", "400-500km", "500-600km", "600-700km", "700-800km",
    "800-900km", "900-1000km", "1000-1200km", "1200-1500km", "1500-2000km",
]
SHELL_EDGES = [200, 400, 500, 600, 700, 800, 900, 1000, 1200, 1500, 2000]


def shell_from_altitude(altitude_km):
    """
    Assign a shell from the MEASURED orbit, not the catalogue summary.

    SATCAT's APOGEE/PERIGEE are a single current-or-final snapshot, while
    the detector's altitude is the median over the satellite's observed
    life. Where they disagree the measurement wins: the real population
    contained objects SATCAT places in a LEO shell whose measured
    semi-major axis is ~20,000 km, which would otherwise have been pooled
    with genuine LEO satellites and corrupted that shell's density
    covariate.
    """
    for lower, upper in zip(SHELL_EDGES[:-1], SHELL_EDGES[1:]):
        if lower <= altitude_km < upper:
            return f"{lower}-{upper}km"
    return None
STATUS = {
    "0": "abstain",
    "1": "active",
    "2": "failed_abrupt",
    "3": "maintenance_ended_gradual",
}
RCS = {"L": "LARGE", "M": "MEDIUM", "S": "SMALL", "U": "UNKNOWN"}

RAW = Path("data/processed/raw_population_packed.txt")
OUT = Path("data/processed/real_population_summary.csv")


def _year(yy):
    """Two-digit year -> four digits. Catalogue spans 1957-2026."""
    yy = int(yy)
    return 1900 + yy if yy >= 50 else 2000 + yy


def _quarter(token):
    """'124' -> 2012-10-01 (year 12, quarter 4)."""
    if not token:
        return None
    yy, q = token[:-1], int(token[-1])
    if q < 1 or q > 4:
        return None
    return pd.Timestamp(year=_year(yy), month=3 * q - 2, day=1)


def _launch(token):
    """'6111' -> 1961-11-01."""
    if not token or len(token) < 4:
        return None
    return pd.Timestamp(year=_year(token[:2]), month=int(token[2:4]), day=1)


def decode(text):
    rows = []
    seen = set()
    for record in text.replace("\n", ";").split(";"):
        record = record.strip()
        if not record:
            continue
        f = record.split("|")
        if len(f) < 12:
            print(f"  skipping malformed record: {record[:60]}", file=sys.stderr)
            continue
        norad = int(f[0])
        if norad in seen:
            continue
        seen.add(norad)

        measured_alt = float(f[2])
        rows.append({
            "norad_id": norad,
            "shell": shell_from_altitude(measured_alt) or SHELLS[int(f[1])],
            "catalogue_shell": SHELLS[int(f[1])],
            "altitude_km": measured_alt,
            "inclination": float(f[3]),
            "launch_date": _launch(f[4]),
            "status": STATUS[f[5]],
            "cessation_quarter": _quarter(f[6]),
            "first_quarter": _quarter(f[7]),
            "last_quarter": _quarter(f[8]),
            "mass_class": RCS.get(f[9], "UNKNOWN"),
            "baseline_pos_frac": float("0" + f[10]) if f[10] else None,
            "transition_quarters": float(f[11]) if f[11] else None,
        })
    return pd.DataFrame(rows)


def main():
    if not RAW.exists():
        sys.exit(f"Missing {RAW}")

    frame = decode(RAW.read_text())

    # Noise guard, applied here as well as in the detector so that records
    # produced before the guard existed are treated consistently. A baseline
    # near 0.5 means observation noise, not manoeuvres, decides the sign of
    # the daily altitude change, so the verdict carries no information.
    noisy = frame["baseline_pos_frac"] > 0.45
    if noisy.any():
        print(f"  {int(noisy.sum())} satellites reclassified as noise_dominated "
              f"(baseline > 0.45)")
        frame.loc[noisy, "status"] = "abstain"
        frame.loc[noisy, "cessation_quarter"] = pd.NaT
        frame.loc[noisy, "transition_quarters"] = None

    # Observation-window fallbacks. A satellite still maintaining its orbit
    # has no cessation date, and in the packed form it may carry no explicit
    # window either. For those the window is its whole tracked life: from
    # launch to the study end. Satellites with a cessation date always carry
    # an explicit window, so this only ever fills in censored records.
    missing_first = frame["first_quarter"].isna()
    if missing_first.any():
        print(f"  {int(missing_first.sum())} records took launch date as window start")
        frame.loc[missing_first, "first_quarter"] = frame.loc[
            missing_first, "launch_date"
        ]

    missing_last = frame["last_quarter"].isna()
    if missing_last.any():
        frame.loc[missing_last, "last_quarter"] = pd.Timestamp("2026-10-01")

    frame = frame.dropna(subset=["first_quarter", "last_quarter"])

    # Keep only objects whose measured orbit is inside the study range. The
    # detector already abstains below 400 km; this also removes objects the
    # catalogue mislabels as LEO.
    in_range = frame["altitude_km"].between(400, 2000)
    if not in_range.all():
        bad = frame.loc[~in_range, ["norad_id", "altitude_km", "catalogue_shell"]]
        print(f"  {len(bad)} dropped: measured orbit outside 400-2000 km")
        for _, r in bad.head(6).iterrows():
            print(f"      {int(r['norad_id'])}: {r['altitude_km']:.0f} km "
                  f"(catalogue said {r['catalogue_shell']})")
    frame = frame[in_range].copy()

    reassigned = (frame["shell"] != frame["catalogue_shell"]).sum()
    if reassigned:
        print(f"  {reassigned} shells reassigned from measured altitude")

    frame["launch_year"] = frame["launch_date"].dt.year
    frame = frame.sort_values("norad_id").reset_index(drop=True)
    frame.to_csv(OUT, index=False)

    print(f"{len(frame)} satellites -> {OUT}\n")
    print("By status:")
    for s, n in frame["status"].value_counts().items():
        print(f"  {s:<28} {n:>4}")
    print("\nBy shell:")
    print(frame.groupby("shell")["status"].value_counts().unstack(fill_value=0).to_string())
    print("\nBy launch era:")
    era = pd.cut(frame["launch_year"], [1950, 1980, 1995, 2005, 2030],
                 labels=["pre-1980", "1980-94", "1995-2004", "2005+"])
    print(era.value_counts().sort_index().to_string())


if __name__ == "__main__":
    main()
