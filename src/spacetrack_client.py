"""
Rate-limited client for the Space-Track.org REST API.

Space-Track enforces 30 requests/minute and 300 requests/hour. Exceeding
these can get an account suspended, so every request passes through a
token-bucket limiter rather than relying on fixed sleeps.

Note on API classes: the legacy `tle` and `tle_latest` classes were
deprecated and return 404 as of January 2026. This client uses `gp` and
`gp_history`, which also expose SEMIMAJOR_AXIS and BSTAR directly.
"""

import configparser
import json
import logging
import time
from collections import deque
from pathlib import Path

import pandas as pd
import requests

LOGGER = logging.getLogger(__name__)

BASE_URL = "https://www.space-track.org"
LOGIN_URL = f"{BASE_URL}/ajaxauth/login"
QUERY_URL = f"{BASE_URL}/basicspacedata/query"

# Space-Track published limits.
MAX_PER_MINUTE = 30
MAX_PER_HOUR = 300


class RateLimiter:
    """Token bucket enforcing both the per-minute and per-hour caps."""

    def __init__(self, per_minute=MAX_PER_MINUTE, per_hour=MAX_PER_HOUR):
        self.per_minute = per_minute
        self.per_hour = per_hour
        self.minute_log = deque()
        self.hour_log = deque()

    def _prune(self, now):
        while self.minute_log and now - self.minute_log[0] > 60:
            self.minute_log.popleft()
        while self.hour_log and now - self.hour_log[0] > 3600:
            self.hour_log.popleft()

    def acquire(self):
        """Block until a request slot is free under both limits."""
        while True:
            now = time.time()
            self._prune(now)

            waits = []
            if len(self.minute_log) >= self.per_minute:
                waits.append(60 - (now - self.minute_log[0]))
            if len(self.hour_log) >= self.per_hour:
                waits.append(3600 - (now - self.hour_log[0]))

            if not waits:
                self.minute_log.append(now)
                self.hour_log.append(now)
                return

            sleep_for = max(min(waits), 0) + 0.5
            LOGGER.info("Rate limit reached, sleeping %.1fs", sleep_for)
            time.sleep(sleep_for)


class SpaceTrackClient:
    """Authenticated, rate-limited, locally-cached Space-Track client."""

    def __init__(self, config_path="config.ini", cache_dir="data/raw"):
        self.config_path = Path(config_path)
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.limiter = RateLimiter()
        self._authenticated = False

    def _credentials(self):
        if not self.config_path.exists():
            raise FileNotFoundError(
                f"{self.config_path} not found. Copy config.example.ini to "
                "config.ini and fill in your Space-Track credentials."
            )
        parser = configparser.ConfigParser()
        parser.read(self.config_path)
        return parser["spacetrack"]["username"], parser["spacetrack"]["password"]

    def login(self):
        """Authenticate once; the session cookie is reused for all queries."""
        if self._authenticated:
            return
        username, password = self._credentials()
        self.limiter.acquire()
        response = self.session.post(
            LOGIN_URL, data={"identity": username, "password": password}, timeout=30
        )
        response.raise_for_status()
        if "Failed" in response.text:
            raise RuntimeError("Space-Track login failed: check credentials.")
        self._authenticated = True
        LOGGER.info("Authenticated with Space-Track")

    def query(self, path, cache_key=None):
        """
        Run a query against basicspacedata and return a DataFrame.

        `path` is the portion after /basicspacedata/query, e.g.
        "class/gp_history/NORAD_CAT_ID/27386/orderby/EPOCH asc/format/json"

        Results are cached on disk so repeated runs do not re-hit the API.
        """
        if cache_key:
            cache_file = self.cache_dir / f"{cache_key}.json"
            if cache_file.exists():
                LOGGER.info("Cache hit: %s", cache_key)
                with open(cache_file) as handle:
                    return pd.DataFrame(json.load(handle))

        self.login()
        self.limiter.acquire()
        url = f"{QUERY_URL}/{path}"
        LOGGER.info("GET %s", url)
        response = self.session.get(url, timeout=120)
        response.raise_for_status()
        payload = response.json()

        if cache_key:
            with open(self.cache_dir / f"{cache_key}.json", "w") as handle:
                json.dump(payload, handle)

        return pd.DataFrame(payload)

    def get_satellite_history(self, norad_id, use_cache=True):
        """
        Full orbital element history for one object.

        Returns a DataFrame with EPOCH parsed to datetime and the numeric
        orbital columns cast to float.
        """
        path = (
            f"class/gp_history/NORAD_CAT_ID/{norad_id}"
            f"/orderby/EPOCH asc/format/json"
        )
        cache_key = f"gp_history_{norad_id}" if use_cache else None
        frame = self.query(path, cache_key=cache_key)
        return self._clean(frame)

    def get_satcat(self, norad_ids=None, use_cache=True):
        """Catalog metadata (names, launch dates, object types, sizes)."""
        if norad_ids:
            ids = ",".join(str(i) for i in norad_ids)
            path = f"class/satcat/NORAD_CAT_ID/{ids}/format/json"
            cache_key = f"satcat_{len(norad_ids)}_objects" if use_cache else None
        else:
            path = "class/satcat/CURRENT/Y/OBJECT_TYPE/PAYLOAD/format/json"
            cache_key = "satcat_all_payloads" if use_cache else None
        return self.query(path, cache_key=cache_key)

    @staticmethod
    def _clean(frame):
        """Parse epochs and cast numeric columns."""
        if frame.empty:
            return frame
        frame = frame.copy()
        frame["EPOCH"] = pd.to_datetime(frame["EPOCH"], errors="coerce")
        numeric_cols = [
            "SEMIMAJOR_AXIS",
            "ECCENTRICITY",
            "INCLINATION",
            "BSTAR",
            "MEAN_MOTION",
            "APOAPSIS",
            "PERIAPSIS",
            "PERIOD",
            "RA_OF_ASC_NODE",
            "ARG_OF_PERICENTER",
        ]
        for col in numeric_cols:
            if col in frame.columns:
                frame[col] = pd.to_numeric(frame[col], errors="coerce")
        return frame.sort_values("EPOCH").reset_index(drop=True)
