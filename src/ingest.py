"""
Bulk ingestion with stratified sampling.

The full gp_history archive holds 138M+ element sets, which is far beyond
what the 30 req/min rate limit allows us to pull. Two reductions make the
problem tractable without losing information:

  1. Stratified object sampling. Sample objects by altitude shell so every
     shell is represented, rather than taking whatever the catalog returns
     first (which over-represents whichever constellation launched most).

  2. Weekly epoch decimation. Space-Track may hold several element sets per
     object per day. Orbital elements change slowly, so resampling to weekly
     means loses almost nothing and cuts volume by ~1-2 orders of magnitude.
"""

import logging
from pathlib import Path

import numpy as np
import pandas as pd

from .features import shell_from_altitude

LOGGER = logging.getLogger(__name__)

# Altitude shells in km. Boundaries chosen around known population
# concentrations; sensitivity to these boundaries is tested in the
# evaluation stage (see docs/methodology.md).
SHELL_EDGES = [200, 400, 500, 600, 700, 800, 900, 1000, 1200, 1500, 2000]


def stratified_object_sample(satcat, per_shell=60, random_state=42):
    """
    Pick objects for the study population, balanced across altitude shells.

    `satcat` must contain NORAD_CAT_ID and APOGEE/PERIGEE (km). Objects
    outside the LEO range defined by SHELL_EDGES are dropped.
    """
    frame = satcat.copy()
    for col in ("APOGEE", "PERIGEE"):
        frame[col] = pd.to_numeric(frame.get(col), errors="coerce")

    frame["mean_altitude"] = (frame["APOGEE"] + frame["PERIGEE"]) / 2
    frame = frame.dropna(subset=["mean_altitude"])
    frame = frame[
        (frame["mean_altitude"] >= SHELL_EDGES[0])
        & (frame["mean_altitude"] < SHELL_EDGES[-1])
    ]
    frame["shell"] = frame["mean_altitude"].apply(shell_from_altitude)

    sampled = (
        frame.groupby("shell", group_keys=False)
        .apply(
            lambda g: g.sample(min(len(g), per_shell), random_state=random_state),
            include_groups=True,
        )
        .reset_index(drop=True)
    )
    LOGGER.info(
        "Sampled %d objects across %d shells",
        len(sampled),
        sampled["shell"].nunique(),
    )
    return sampled


def decimate_weekly(history):
    """
    Resample one object's element history to one row per ISO week.

    Takes the last element set in each week, which is the most refined
    estimate available for that period.
    """
    if history.empty:
        return history
    frame = history.dropna(subset=["EPOCH"]).set_index("EPOCH")
    weekly = frame.resample("W").last().dropna(subset=["SEMIMAJOR_AXIS"])
    return weekly.reset_index()


def ingest_population(client, norad_ids, out_dir="data/processed"):
    """
    Pull and decimate histories for a list of objects.

    Writes one parquet file per object so a failed run can be resumed
    without re-querying what is already on disk.
    """
    out_path = Path(out_dir) / "histories"
    out_path.mkdir(parents=True, exist_ok=True)

    collected = []
    for index, norad_id in enumerate(norad_ids, start=1):
        target = out_path / f"{norad_id}.parquet"
        if target.exists():
            collected.append(pd.read_parquet(target))
            continue

        try:
            history = client.get_satellite_history(norad_id)
        except Exception as error:  # noqa: BLE001 - log and continue the batch
            LOGGER.warning("Failed to fetch %s: %s", norad_id, error)
            continue

        if history.empty:
            LOGGER.warning("No history returned for %s", norad_id)
            continue

        weekly = decimate_weekly(history)
        weekly["NORAD_CAT_ID"] = norad_id
        weekly.to_parquet(target, index=False)
        collected.append(weekly)

        if index % 25 == 0:
            LOGGER.info("Ingested %d/%d objects", index, len(norad_ids))

    if not collected:
        return pd.DataFrame()
    return pd.concat(collected, ignore_index=True)
