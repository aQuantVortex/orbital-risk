"""
Build the survival panel from per-satellite summaries.

`panel.build_panel` takes raw element-set histories. That is the right
entry point when the histories are already local, but transferring tens
of millions of element sets just to derive a few thousand panel rows is
wasteful. This module builds the identical panel from the aggregated
form: one summary row per satellite, plus the density and solar panels.

The counting-process format is unchanged -- one row per satellite per
quarter as (t_start, t_stop, event] -- so everything downstream in
`models.py` works the same either way.

Censoring rules, which are the substantive decisions here:

  failed_abrupt              event = 1 on the final row. A genuine failure.
  maintenance_ended_gradual  censored at cessation. The spacecraft was
                             still operational when orbit maintenance
                             stopped, so we observe it up to that point
                             and know nothing after. Treating it as a
                             failure would import the Terra error into
                             the model.
  active                     censored at study end.
  abstain                    excluded. The detector could not form a
                             view, and inventing one would be worse than
                             dropping the satellite.
"""

import logging

import numpy as np
import pandas as pd

LOGGER = logging.getLogger(__name__)

STUDY_END = pd.Timestamp("2026-10-01")

# NOAA's observed solar-cycle file reports F10.7 as -1 before October 2004,
# so the panel starts there rather than imputing a covariate across the
# first eleven quarters. Detection baselines still use each satellite's
# full history; only the modelling window is clipped.
STUDY_START = pd.Timestamp("2004-10-01")


def _quarters(start, end):
    """Quarter-start timestamps from `start` to `end` inclusive."""
    if end < start:
        return []
    return list(pd.date_range(start, end, freq="QS"))


def build_panel_from_summary(
    summary,
    density_panel,
    solar_flux=None,
    study_start=STUDY_START,
    study_end=STUDY_END,
    min_quarters=4,
):
    """
    Assemble the modelling table.

    Parameters
    ----------
    summary : DataFrame
        One row per satellite with columns:
            norad_id, shell, altitude_km, inclination, launch_date,
            first_quarter, last_quarter, status, cessation_quarter,
            mass_class
    density_panel : DataFrame
        Columns period, shell, density.
    solar_flux : DataFrame, optional
        Columns period, f107.

    Returns
    -------
    DataFrame in counting-process format.
    """
    rows = []
    skipped = {"abstain": 0, "too_short": 0, "no_quarters": 0}

    for _, sat in summary.iterrows():
        status = sat["status"]

        if status == "abstain":
            skipped["abstain"] += 1
            continue

        start = max(pd.Timestamp(sat["first_quarter"]), pd.Timestamp(study_start))

        if status == "failed_abrupt" and pd.notna(sat.get("cessation_quarter")):
            end = pd.Timestamp(sat["cessation_quarter"])
            event_at_end = 1
        elif status == "maintenance_ended_gradual" and pd.notna(
            sat.get("cessation_quarter")
        ):
            end = pd.Timestamp(sat["cessation_quarter"])
            event_at_end = 0          # censored, not failed
        else:
            end = min(pd.Timestamp(sat["last_quarter"]), pd.Timestamp(study_end))
            event_at_end = 0

        quarters = _quarters(start, end)
        if len(quarters) < min_quarters:
            skipped["too_short"] += 1
            continue

        launch = pd.Timestamp(sat["launch_date"]) if pd.notna(sat["launch_date"]) else start

        for i, period in enumerate(quarters):
            t_start = (period - start).days / 7.0
            if i + 1 < len(quarters):
                t_stop = (quarters[i + 1] - start).days / 7.0
            else:
                t_stop = t_start + 13.0

            if t_stop <= t_start:
                continue

            rows.append(
                {
                    "norad_id": int(sat["norad_id"]),
                    "period": period,
                    "t_start": t_start,
                    "t_stop": t_stop,
                    "event": int(event_at_end and i == len(quarters) - 1),
                    "shell": sat["shell"],
                    "altitude_km": float(sat["altitude_km"]),
                    "inclination": float(sat["inclination"]),
                    "age_years": max((period - launch).days / 365.25, 0.0),
                    "mass_class": sat.get("mass_class", "UNKNOWN"),
                    "status": status,
                }
            )

    panel = pd.DataFrame(rows)
    if panel.empty:
        LOGGER.warning("Panel is empty. Skipped: %s", skipped)
        return panel

    panel = _attach_density(panel, density_panel)
    if solar_flux is not None:
        panel = _attach_solar(panel, solar_flux)
    panel = _attach_bands(panel)

    LOGGER.info(
        "Panel: %d rows, %d satellites, %d events (skipped %s)",
        len(panel),
        panel["norad_id"].nunique(),
        int(panel["event"].sum()),
        skipped,
    )
    return panel


def _attach_density(panel, density_panel):
    if density_panel is None or density_panel.empty:
        panel["density"] = np.nan
        return panel

    dens = density_panel.copy()
    dens["period"] = pd.to_datetime(dens["period"])
    merged = panel.merge(dens, on=["period", "shell"], how="left")

    # Any shell-quarter the density panel does not cover falls back to the
    # shell's own median, then to the global median.
    shell_median = merged.groupby("shell")["density"].transform("median")
    merged["density"] = merged["density"].fillna(shell_median)
    merged["density"] = merged["density"].fillna(merged["density"].median())
    return merged


def _attach_solar(panel, solar_flux):
    flux = solar_flux.copy()
    flux["period"] = pd.to_datetime(flux["period"])
    merged = panel.merge(flux[["period", "f107"]], on="period", how="left")
    merged["f107"] = merged["f107"].ffill().bfill()
    return merged


def _attach_bands(panel):
    panel = panel.copy()
    panel["inclination_band"] = pd.cut(
        panel["inclination"],
        bins=[0, 30, 60, 85, 95, 120, 180],
        labels=["0-30", "30-60", "60-85", "85-95", "95-120", "120-180"],
    ).astype(str)
    return panel


def summarise_panel(panel):
    """Short human-readable description, for logging and the report."""
    if panel.empty:
        return "empty panel"

    per_sat = panel.groupby("norad_id").agg(
        events=("event", "max"), quarters=("event", "size")
    )
    return (
        f"{len(panel):,} rows | {panel['norad_id'].nunique()} satellites | "
        f"{int(panel['event'].sum())} events | "
        f"{1 - per_sat['events'].mean():.1%} censored | "
        f"median follow-up {per_sat['quarters'].median():.0f} quarters"
    )
