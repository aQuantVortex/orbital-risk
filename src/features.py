"""
Feature engineering: altitude derivation and shell debris density.

Two products:
  - per-object geometry (altitude, shell assignment) from orbital elements
  - per-shell, per-epoch debris density via kernel density estimation
"""

import logging

import numpy as np
import pandas as pd
from scipy.stats import gaussian_kde

LOGGER = logging.getLogger(__name__)

EARTH_RADIUS_KM = 6378.137

SHELL_EDGES = [200, 400, 500, 600, 700, 800, 900, 1000, 1200, 1500, 2000]


def altitude_from_sma(semimajor_axis_km):
    """Mean altitude above a spherical Earth, from semi-major axis in km."""
    return semimajor_axis_km - EARTH_RADIUS_KM


def shell_from_altitude(altitude_km):
    """Label the altitude shell an object belongs to, e.g. '600-700km'."""
    if pd.isna(altitude_km):
        return None
    for lower, upper in zip(SHELL_EDGES[:-1], SHELL_EDGES[1:]):
        if lower <= altitude_km < upper:
            return f"{lower}-{upper}km"
    return None


def add_geometry(frame):
    """Attach altitude and shell columns to an element-set DataFrame."""
    out = frame.copy()
    out["altitude_km"] = altitude_from_sma(out["SEMIMAJOR_AXIS"])
    out["shell"] = out["altitude_km"].apply(shell_from_altitude)
    return out


def shell_density_kde(altitudes, grid=None, bandwidth=None, weights=None):
    """
    Estimate object density as a function of altitude.

    A histogram would be discontinuous and sensitive to bin placement, which
    is a poor input to a regression. KDE gives a smooth curve.

    Bandwidth matters: debris concentrates in narrow shells (mega-
    constellations sit at specific altitudes), so over-smoothing erases the
    structure we are trying to measure. Default is Scott's rule; the
    evaluation stage sweeps this.

    `weights` optionally weights each object by cross-sectional area, since
    a spent rocket body and a CubeSat are not equally hazardous.
    """
    altitudes = np.asarray(altitudes, dtype=float)
    altitudes = altitudes[np.isfinite(altitudes)]

    if len(altitudes) < 5:
        return None, None

    if grid is None:
        grid = np.arange(SHELL_EDGES[0], SHELL_EDGES[-1], 10.0)

    kde = gaussian_kde(altitudes, bw_method=bandwidth, weights=weights)
    density = kde(grid) * len(altitudes)  # scale to objects per km
    return grid, density


def density_by_shell(altitudes, bandwidth=None, weights=None):
    """
    Mean KDE density within each altitude shell.

    Returns a dict of shell label -> density (objects per km of altitude).
    """
    grid, density = shell_density_kde(altitudes, bandwidth=bandwidth, weights=weights)
    if grid is None:
        return {}

    result = {}
    for lower, upper in zip(SHELL_EDGES[:-1], SHELL_EDGES[1:]):
        mask = (grid >= lower) & (grid < upper)
        if mask.any():
            result[f"{lower}-{upper}km"] = float(density[mask].mean())
    return result


def build_density_panel(histories, freq="Q", bandwidth=None):
    """
    Debris density per shell per time period, across the whole population.

    `histories` is the concatenated weekly element-set table for all objects.
    Quarterly is the default because the catalog population changes slowly
    and a quarterly field is far cheaper to compute than a weekly one.
    """
    frame = add_geometry(histories).dropna(subset=["altitude_km", "EPOCH"])
    frame["period"] = frame["EPOCH"].dt.to_period(freq).dt.to_timestamp()

    rows = []
    for period, group in frame.groupby("period"):
        # One altitude per object per period, so a satellite with more
        # element sets does not count more than once.
        per_object = group.groupby("NORAD_CAT_ID")["altitude_km"].median()
        densities = density_by_shell(per_object.values, bandwidth=bandwidth)
        for shell, value in densities.items():
            rows.append({"period": period, "shell": shell, "density": value})

    panel = pd.DataFrame(rows)
    LOGGER.info(
        "Built density panel: %d periods x %d shells",
        panel["period"].nunique() if not panel.empty else 0,
        panel["shell"].nunique() if not panel.empty else 0,
    )
    return panel
