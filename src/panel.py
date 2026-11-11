"""
Build the survival panel.

Output is one row per satellite per observation period, in counting-process
format: (t_start, t_stop, event]. This is what lets the Cox model use
time-varying covariates -- debris density around a satellite launched in
2012 is not what it was at launch, and freezing it to a single value
discards the variable the study is about.

Satellites still operating at the end of the window are right-censored:
their last row carries event = 0, recording that they survived at least
that long rather than that they never fail.
"""

import logging

import numpy as np
import pandas as pd

from .features import add_geometry

LOGGER = logging.getLogger(__name__)


def build_panel(
    histories,
    detections,
    density_panel,
    solar_flux=None,
    satcat=None,
    freq="Q",
    study_end=None,
):
    """
    Assemble the modelling table.

    Parameters
    ----------
    histories : DataFrame
        Weekly element sets for the population.
    detections : DataFrame
        Output of failure_detection.detect_population.
    density_panel : DataFrame
        Output of features.build_density_panel (period, shell, density).
    solar_flux : DataFrame, optional
        Columns: date, f107. Joined on period.
    satcat : DataFrame, optional
        Static metadata: NORAD_CAT_ID, LAUNCH, OBJECT_TYPE, RCS_SIZE.
    freq : str
        Observation period. Quarterly keeps the table manageable while
        staying far finer than the timescale on which hazard changes.
    study_end : Timestamp, optional
        Censoring date. Defaults to the latest epoch in the data.

    Returns
    -------
    DataFrame with columns:
        norad_id, t_start, t_stop, event, shell, altitude_km,
        density, f107, age_years, mass_class, inclination_band
    """
    frame = add_geometry(histories).dropna(subset=["altitude_km", "EPOCH"])
    frame["period"] = frame["EPOCH"].dt.to_period(freq).dt.to_timestamp()

    if study_end is None:
        study_end = frame["EPOCH"].max()

    # One observation per object per period.
    periodic = (
        frame.groupby(["NORAD_CAT_ID", "period"])
        .agg(
            altitude_km=("altitude_km", "median"),
            inclination=("INCLINATION", "median"),
            shell=("shell", "first"),
        )
        .reset_index()
        .rename(columns={"NORAD_CAT_ID": "norad_id"})
    )

    failure_map = _failure_map(detections)
    launch_map = _launch_map(satcat) if satcat is not None else {}

    rows = []
    for norad_id, group in periodic.groupby("norad_id"):
        group = group.sort_values("period").reset_index(drop=True)
        failure_epoch = failure_map.get(norad_id)
        launch_date = launch_map.get(norad_id, group["period"].iloc[0])

        # Drop periods after failure: the satellite is no longer at risk.
        if failure_epoch is not None:
            group = group[group["period"] <= failure_epoch]
            if group.empty:
                continue

        start_period = group["period"].iloc[0]

        for i, row in group.iterrows():
            t_start = _weeks_between(start_period, row["period"])
            if i + 1 < len(group):
                t_stop = _weeks_between(start_period, group["period"].iloc[i + 1])
            else:
                t_stop = t_start + 13.0  # one quarter

            if t_stop <= t_start:
                continue

            is_last = i == len(group) - 1
            event = int(is_last and failure_epoch is not None)

            rows.append(
                {
                    "norad_id": norad_id,
                    "period": row["period"],
                    "t_start": t_start,
                    "t_stop": t_stop,
                    "event": event,
                    "shell": row["shell"],
                    "altitude_km": row["altitude_km"],
                    "inclination": row["inclination"],
                    "age_years": _years_between(launch_date, row["period"]),
                }
            )

    panel = pd.DataFrame(rows)
    if panel.empty:
        return panel

    panel = _attach_density(panel, density_panel)
    if solar_flux is not None:
        panel = _attach_solar(panel, solar_flux)
    panel = _attach_static(panel, satcat)

    LOGGER.info(
        "Panel built: %d rows, %d objects, %d events",
        len(panel),
        panel["norad_id"].nunique(),
        int(panel["event"].sum()),
    )
    return panel


def _failure_map(detections):
    failed = detections[detections["failed"]]
    return {
        int(row["norad_id"]): pd.Timestamp(row["failure_epoch"])
        for _, row in failed.iterrows()
        if row["failure_epoch"] is not None and not pd.isna(row["failure_epoch"])
    }


def _launch_map(satcat):
    if satcat is None or "LAUNCH" not in satcat.columns:
        return {}
    frame = satcat.copy()
    frame["LAUNCH"] = pd.to_datetime(frame["LAUNCH"], errors="coerce")
    return {
        int(row["NORAD_CAT_ID"]): row["LAUNCH"]
        for _, row in frame.dropna(subset=["LAUNCH"]).iterrows()
    }


def _weeks_between(start, end):
    return float((pd.Timestamp(end) - pd.Timestamp(start)).days) / 7.0


def _years_between(start, end):
    return float((pd.Timestamp(end) - pd.Timestamp(start)).days) / 365.25


def _attach_density(panel, density_panel):
    if density_panel is None or density_panel.empty:
        panel["density"] = np.nan
        return panel
    merged = panel.merge(
        density_panel, left_on=["period", "shell"], right_on=["period", "shell"],
        how="left",
    )
    merged["density"] = merged["density"].fillna(merged["density"].median())
    return merged


def _attach_solar(panel, solar_flux):
    flux = solar_flux.copy()
    flux["date"] = pd.to_datetime(flux["date"], errors="coerce")
    flux["period"] = flux["date"].dt.to_period("Q").dt.to_timestamp()
    quarterly = flux.groupby("period")["f107"].mean().reset_index()
    merged = panel.merge(quarterly, on="period", how="left")
    merged["f107"] = merged["f107"].fillna(merged["f107"].median())
    return merged


def _attach_static(panel, satcat):
    panel = panel.copy()
    panel["inclination_band"] = pd.cut(
        panel["inclination"],
        bins=[0, 30, 60, 85, 95, 120, 180],
        labels=["0-30", "30-60", "60-85", "85-95", "95-120", "120-180"],
    ).astype(str)

    if satcat is not None and "RCS_SIZE" in satcat.columns:
        size_map = {
            int(r["NORAD_CAT_ID"]): r["RCS_SIZE"]
            for _, r in satcat.dropna(subset=["RCS_SIZE"]).iterrows()
        }
        panel["mass_class"] = panel["norad_id"].map(size_map).fillna("UNKNOWN")
    else:
        panel["mass_class"] = "UNKNOWN"

    return panel
