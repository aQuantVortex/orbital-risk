"""
CelesTrak client: catalogue record and current orbit for one object.

CelesTrak needs no account, which makes it the natural first stop for an
arbitrary satellite. What it does NOT publish is element-set history for
arbitrary objects -- its GP endpoint returns the current element set only.
The failure detector needs years of history, so that comes from Space-Track
(the same US Space Force catalogue that CelesTrak redistributes).

Two endpoints are used:

    satcat/records.php   catalogue record: name, owner, launch and decay
                         dates, apogee, perigee, radar cross-section, and an
                         operational status code
    NORAD/elements/gp.php
                         the current element set

Responses are cached under data/raw/celestrak/ so a repeated run works
offline.
"""

import json
import logging
import math
from pathlib import Path

import requests

LOGGER = logging.getLogger(__name__)

SATCAT_URL = "https://celestrak.org/satcat/records.php"
GP_URL = "https://celestrak.org/NORAD/elements/gp.php"

EARTH_RADIUS_KM = 6378.137
MU_EARTH_KM3_S2 = 398600.4418

# CelesTrak's operational status codes.
OPS_STATUS = {
    "+": "operational",
    "-": "nonoperational",
    "P": "partially operational",
    "B": "backup / standby",
    "S": "spare",
    "X": "extended mission",
    "D": "decayed",
    "?": "unknown",
    "": "unknown",
}

OBJECT_TYPES = {
    "PAY": "payload",
    "R/B": "rocket body",
    "DEB": "debris",
    "UNK": "unknown",
}


class CelesTrakError(RuntimeError):
    """Raised when CelesTrak has no record for the requested object."""


def altitude_from_mean_motion(revs_per_day):
    """
    Mean altitude from mean motion, via Kepler's third law.

    CelesTrak's GP records carry mean motion rather than semi-major axis:
        n = 2*pi*revs / 86400   (rad/s)
        a = (mu / n^2)^(1/3)    (km)
    """
    n = revs_per_day * 2.0 * math.pi / 86400.0
    semi_major_axis = (MU_EARTH_KM3_S2 / (n * n)) ** (1.0 / 3.0)
    return semi_major_axis - EARTH_RADIUS_KM


def rcs_to_mass_class(rcs_m2):
    """
    Bucket radar cross-section the way Space-Track's RCS_SIZE does:
    SMALL < 0.1 m^2, MEDIUM 0.1-1 m^2, LARGE > 1 m^2.
    """
    if rcs_m2 is None:
        return "UNKNOWN"
    try:
        value = float(rcs_m2)
    except (TypeError, ValueError):
        return "UNKNOWN"
    if value < 0.1:
        return "SMALL"
    if value <= 1.0:
        return "MEDIUM"
    return "LARGE"


class CelesTrakClient:
    def __init__(self, cache_dir="data/raw/celestrak", offline=False):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.offline = offline

    def _get(self, url, params, cache_name):
        """
        Fetch JSON, falling back to the cache if the network is unavailable.

        CelesTrak answers a missing object with a plain-text sentence rather
        than an HTTP error, so the body is checked before parsing.
        """
        cache_file = self.cache_dir / cache_name

        if not self.offline:
            try:
                response = requests.get(url, params=params, timeout=30)
                response.raise_for_status()
                text = response.text.strip()
                if text.startswith("No ") or not text.startswith("["):
                    return None, text
                payload = json.loads(text)
                cache_file.write_text(json.dumps(payload))
                return payload, None
            except requests.RequestException as error:
                LOGGER.warning("CelesTrak unreachable (%s); trying cache", error)

        if cache_file.exists():
            LOGGER.info("Using cached %s", cache_file)
            return json.loads(cache_file.read_text()), None

        return None, "CelesTrak unreachable and no cached copy"

    def catalogue_record(self, norad_id):
        payload, message = self._get(
            SATCAT_URL,
            {"CATNR": norad_id, "FORMAT": "json"},
            f"satcat_{norad_id}.json",
        )
        if not payload:
            raise CelesTrakError(
                f"No catalogue record for NORAD {norad_id}: {message}"
            )

        record = payload[0]
        apogee = _num(record.get("APOGEE"))
        perigee = _num(record.get("PERIGEE"))
        status_code = (record.get("OPS_STATUS_CODE") or "").strip()

        return {
            "norad_id": int(record["NORAD_CAT_ID"]),
            "name": record.get("OBJECT_NAME", "").strip(),
            "international_designator": record.get("OBJECT_ID", ""),
            "object_type": OBJECT_TYPES.get(
                record.get("OBJECT_TYPE", ""), record.get("OBJECT_TYPE", "")
            ),
            "owner": record.get("OWNER", ""),
            "launch_date": record.get("LAUNCH_DATE") or None,
            "decay_date": record.get("DECAY_DATE") or None,
            "apogee_km": apogee,
            "perigee_km": perigee,
            "mean_altitude_km": (
                (apogee + perigee) / 2.0
                if apogee is not None and perigee is not None
                else None
            ),
            "inclination_deg": _num(record.get("INCLINATION")),
            "period_min": _num(record.get("PERIOD")),
            "rcs_m2": _num(record.get("RCS")),
            "mass_class": rcs_to_mass_class(record.get("RCS")),
            "ops_status_code": status_code,
            "ops_status": OPS_STATUS.get(status_code, status_code or "unknown"),
        }

    def current_elements(self, norad_id):
        """
        The current element set, or None for an object that has decayed.
        """
        payload, _ = self._get(
            GP_URL,
            {"CATNR": norad_id, "FORMAT": "json"},
            f"gp_{norad_id}.json",
        )
        if not payload:
            return None

        record = payload[0]
        mean_motion = _num(record.get("MEAN_MOTION"))
        return {
            "epoch": record.get("EPOCH"),
            "mean_motion_rev_day": mean_motion,
            "altitude_km": (
                altitude_from_mean_motion(mean_motion) if mean_motion else None
            ),
            "eccentricity": _num(record.get("ECCENTRICITY")),
            "inclination_deg": _num(record.get("INCLINATION")),
            "bstar": _num(record.get("BSTAR")),
        }


def _num(value):
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
