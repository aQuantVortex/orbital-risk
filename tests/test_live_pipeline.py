"""
Tests for the single-satellite live path: CelesTrak parsing, history
loading, and the detector-vs-CelesTrak cross-check.

The CelesTrak fixtures are real responses captured on 2026-11-24 for six
deliberately awkward objects: a failed satellite (Envisat), an operational
one whose maintenance ended (Terra), a decayed one (GOCE), a geostationary
one (GOES 16), a piece of debris (Fengyun 1C), and the ISS.
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from src.celestrak import (
    CelesTrakClient,
    CelesTrakError,
    altitude_from_mean_motion,
    rcs_to_mass_class,
)
from src.failure_detection import (
    STATUS_ABSTAIN,
    STATUS_ACTIVE,
    STATUS_FAILED,
    STATUS_WOUND_DOWN,
)

import analyse_satellite as live  # noqa: E402

FIXTURES = {
    27386: (
        '[{"OBJECT_NAME":"ENVISAT","OBJECT_ID":"2002-009A","NORAD_CAT_ID":27386,'
        '"OBJECT_TYPE":"PAY","OPS_STATUS_CODE":"-","OWNER":"ESA","LAUNCH_DATE":'
        '"2002-03-01","LAUNCH_SITE":"FRGUI","DECAY_DATE":"","PERIOD":100.06,'
        '"INCLINATION":98.41,"APOGEE":762,"PERIGEE":761,"RCS":18.597}]',
        '[{"OBJECT_NAME":"ENVISAT","EPOCH":"2026-11-23T21:06:16.600320",'
        '"MEAN_MOTION":14.39097136,"ECCENTRICITY":0.00011647,"INCLINATION":98.4057,'
        '"NORAD_CAT_ID":27386,"BSTAR":2.5310793e-5}]',
    ),
    34602: (
        '[{"OBJECT_NAME":"GOCE","OBJECT_ID":"2009-013A","NORAD_CAT_ID":34602,'
        '"OBJECT_TYPE":"PAY","OPS_STATUS_CODE":"D","OWNER":"ESA","LAUNCH_DATE":'
        '"2009-03-17","DECAY_DATE":"2013-11-11","PERIOD":86.82,"INCLINATION":96.57,'
        '"APOGEE":123,"PERIGEE":110,"RCS":1.507}]',
        None,  # decayed: CelesTrak answers "No GP data found"
    ),
    41866: (
        '[{"OBJECT_NAME":"GOES 16","OBJECT_ID":"2016-071A","NORAD_CAT_ID":41866,'
        '"OBJECT_TYPE":"PAY","OPS_STATUS_CODE":"+","OWNER":"US","LAUNCH_DATE":'
        '"2016-11-19","DECAY_DATE":"","PERIOD":1436.11,"INCLINATION":0.73,'
        '"APOGEE":35799,"PERIGEE":35774,"RCS":13.1623}]',
        '[{"OBJECT_NAME":"GOES 16","EPOCH":"2026-11-24T02:27:34.277184",'
        '"MEAN_MOTION":1.00270444,"ECCENTRICITY":0.0002991,"INCLINATION":0.7359,'
        '"NORAD_CAT_ID":41866,"BSTAR":0}]',
    ),
    29733: (
        '[{"OBJECT_NAME":"FENGYUN 1C DEB","OBJECT_ID":"1999-025X","NORAD_CAT_ID":29733,'
        '"OBJECT_TYPE":"DEB","OPS_STATUS_CODE":"","OWNER":"PRC","LAUNCH_DATE":'
        '"1999-05-10","DECAY_DATE":"","PERIOD":111.03,"INCLINATION":99.2,'
        '"APOGEE":1706,"PERIGEE":841,"RCS":0.0391}]',
        '[{"OBJECT_NAME":"FENGYUN 1C DEB","EPOCH":"2026-11-23T22:46:16.484160",'
        '"MEAN_MOTION":12.97007294,"ECCENTRICITY":0.0565328,"INCLINATION":99.1991,'
        '"NORAD_CAT_ID":29733,"BSTAR":0.0018842}]',
    ),
}


@pytest.fixture
def client(tmp_path):
    for norad, (satcat, gp) in FIXTURES.items():
        (tmp_path / f"satcat_{norad}.json").write_text(satcat)
        if gp is not None:
            (tmp_path / f"gp_{norad}.json").write_text(gp)
    return CelesTrakClient(cache_dir=tmp_path, offline=True)


class TestOrbitalMechanics:
    @pytest.mark.parametrize(
        "mean_motion, catalogue_alt",
        [
            (14.39097136, 761.5),   # Envisat: apogee 762, perigee 761
            (14.61203971, 689.5),   # Terra:   apogee 692, perigee 687
            (15.49568558, 418.0),   # ISS:     apogee 423, perigee 413
            (1.00270444, 35786.5),  # GOES 16: apogee 35799, perigee 35774
        ],
    )
    def test_altitude_from_mean_motion_matches_catalogue(self, mean_motion, catalogue_alt):
        """Kepler's third law reproduces CelesTrak's own apogee/perigee."""
        assert altitude_from_mean_motion(mean_motion) == pytest.approx(catalogue_alt, abs=2.0)

    @pytest.mark.parametrize(
        "rcs, expected",
        [(0.0391, "SMALL"), (0.5, "MEDIUM"), (18.6, "LARGE"), (None, "UNKNOWN"), ("x", "UNKNOWN")],
    )
    def test_rcs_bucketing(self, rcs, expected):
        assert rcs_to_mass_class(rcs) == expected


class TestCelesTrakParsing:
    def test_catalogue_record(self, client):
        rec = client.catalogue_record(27386)
        assert rec["name"] == "ENVISAT"
        assert rec["object_type"] == "payload"
        assert rec["ops_status"] == "nonoperational"
        assert rec["mass_class"] == "LARGE"
        assert rec["mean_altitude_km"] == pytest.approx(761.5)

    def test_debris_is_labelled(self, client):
        assert client.catalogue_record(29733)["object_type"] == "debris"

    def test_decayed_object_has_no_current_elements(self, client):
        assert client.catalogue_record(34602)["decay_date"] == "2013-11-11"
        assert client.current_elements(34602) is None

    def test_unknown_object_raises(self, client):
        with pytest.raises(CelesTrakError):
            client.catalogue_record(999999)


class TestHistoryLoading:
    def test_csv_with_semimajor_axis(self, tmp_path):
        path = tmp_path / "h.csv"
        pd.DataFrame({
            "EPOCH": ["2020-01-01", "2020-01-02"],
            "SEMIMAJOR_AXIS": [7140.0, 7139.9],
            "NORAD_CAT_ID": [123, 123],
        }).to_csv(path, index=False)
        frame = live.load_history_file(path, 123)
        assert len(frame) == 2
        assert frame["SEMIMAJOR_AXIS"].iloc[0] == pytest.approx(7140.0)

    def test_mean_motion_only_is_converted(self, tmp_path):
        """Some Query Builder exports carry mean motion but not SMA."""
        path = tmp_path / "h.json"
        path.write_text(json.dumps([{"EPOCH": "2020-01-01", "MEAN_MOTION": 14.39097136}]))
        frame = live.load_history_file(path, 27386)
        assert frame["SEMIMAJOR_AXIS"].iloc[0] - 6378.137 == pytest.approx(761.5, abs=2.0)

    def test_lowercase_columns_and_other_objects_filtered(self, tmp_path):
        path = tmp_path / "h.csv"
        pd.DataFrame({
            "epoch": ["2020-01-01", "2020-01-01"],
            "semimajor_axis": [7140.0, 7000.0],
            "norad_cat_id": [123, 999],
        }).to_csv(path, index=False)
        frame = live.load_history_file(path, 123)
        assert len(frame) == 1

    def test_missing_columns_fail_clearly(self, tmp_path):
        path = tmp_path / "h.csv"
        pd.DataFrame({"EPOCH": ["2020-01-01"], "FOO": [1]}).to_csv(path, index=False)
        with pytest.raises(ValueError, match="neither SEMIMAJOR_AXIS nor MEAN_MOTION"):
            live.load_history_file(path, 123)


class TestCrossCheck:
    """
    The detector and CelesTrak answer different questions -- maintained
    versus operating -- so agreement is defined by what each implies.
    """

    def test_envisat_case(self):
        assert live.cross_check(STATUS_FAILED, "-")[0] == "AGREE"

    def test_terra_case(self):
        """Maintenance ended, spacecraft still operating: the pattern the
        abruptness test exists for."""
        assert live.cross_check(STATUS_WOUND_DOWN, "X")[0] == "AGREE"

    def test_operating_and_maintained(self):
        assert live.cross_check(STATUS_ACTIVE, "+")[0] == "AGREE"

    def test_disagreements_are_surfaced(self):
        assert live.cross_check(STATUS_FAILED, "+")[0] == "DISAGREE"
        assert live.cross_check(STATUS_ACTIVE, "-")[0] == "DISAGREE"

    def test_no_comparison_when_either_side_is_silent(self):
        assert live.cross_check(STATUS_ABSTAIN, "+")[0] == "not compared"
        assert live.cross_check(STATUS_FAILED, "")[0] == "not compared"


class TestEndToEndOnRealHistory:
    """
    The whole seven-step script on real Space-Track history (daily medians
    of gp_history, pulled 2026-11-25), offline. These lock in the two
    validation cases: if a change to the detector breaks either, this fails.
    """

    @pytest.mark.parametrize(
        "norad, verdict, quarter, cross",
        [
            (27386, "FAILED — orbit maintenance stopped abruptly", "2012-04-01", "AGREE"),
            (25994, "MAINTENANCE ENDED GRADUALLY", "2022-07-01", "AGREE"),
        ],
    )
    def test_script_reproduces_validation(self, norad, verdict, quarter, cross, tmp_path):
        import subprocess

        history = ROOT / "data" / "examples" / f"{norad}_history.csv"
        out = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "analyse_satellite.py"), str(norad),
             "--offline", "--history", str(history)],
            capture_output=True, text=True, cwd=ROOT, timeout=180,
        ).stdout
        assert verdict in out
        assert f"Cessation quarter            {quarter}" in out
        assert f"Result                       {cross}" in out
