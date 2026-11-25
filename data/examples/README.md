# Example histories

Real orbital history for the two satellites the detector is validated on,
so `analyse_satellite.py` runs end to end with no Space-Track login.

| File | Satellite | Days | Span | Built from |
|---|---|---|---|---|
| `27386_history.csv` | Envisat | 8,946 | 2002-03-01 → 2026-11-24 | 29,639 element sets |
| `25994_history.csv` | Terra   | 9,799 | 1999-12-18 → 2026-11-24 | 33,241 element sets |

**Source:** Space-Track `gp_history`, pulled 25 November 2026.

**Processing:** one row per day, the median `SEMIMAJOR_AXIS` (km) of that
day's element sets, rounded to 0.5 m. This is exactly the daily series the
detector builds internally (`daily_series` in `src/failure_detection.py`), and the
verdicts, baselines and cessation dates match the validation run on the raw
element sets (`STATUS.md`).

These are derived daily altitudes, not redistributed element sets.

```bash
python scripts/analyse_satellite.py 27386 --offline --history data/examples/27386_history.csv
python scripts/analyse_satellite.py 25994 --offline --history data/examples/25994_history.csv
```

Expected: Envisat `failed_abrupt`, cessation 2012-04-01, AGREE with CelesTrak
`-`; Terra `maintenance_ended_gradual` over 8 quarters, AGREE with CelesTrak
`X`. `tests/test_live_pipeline.py` checks both.
