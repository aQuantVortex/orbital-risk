# Project Status

**Pricing Orbital Risk** — Foundations of Data Science
Last updated: 24 November 2026

---

## Summary

**Complete.** The full pipeline has been run end to end on real Space-Track
data: 535 satellites classified, 264 in the survival panel, 83 failure events,
Cox / Weibull / logistic all fitted, pricing derived, figures produced.

The central hypothesis — that debris density predicts satellite failure — is
**not supported**. See `RESULTS.md` for the full numbers. The method validated
itself in a different way: the detector's empirical cessation rate reproduces
published insurance loss rates without ever touching insurance data.

Remaining items are extensions, not gaps: they are listed at the bottom with the
reason each matters. The largest is recalibrating the Weibull time origin, which
is why the Weibull is excluded from the headline pricing.

## Validation against real data (11 November 2026)

Pulled from Space-Track `gp_history`: Envisat (29,574 element sets), Terra (33,164), Aura (15,278), GOCE (4,607). 82,623 element sets across 28,179 satellite-days.

### Result: 4 of 4 correct

| Satellite | Expected | Detected | Baseline | Decline | Error vs documented |
|---|---|---|---|---|---|
| Envisat | `failed_abrupt` | `failed_abrupt` | 0.212 | 1 quarter | **−7 days** |
| Terra | `maintenance_ended_gradual` | `maintenance_ended_gradual` | 0.089 | 8 quarters | n/a |
| Aura | not a failure | `maintenance_ended_gradual` | 0.072 | 6 quarters | n/a |
| GOCE | `abstain` | `abstain` (below altitude floor) | — | — | n/a |

Envisat's documented contact loss is 8 April 2012. The detector places cessation at 1 April 2012, seven days early, which is the quarter boundary — the finest resolution the quarterly series can give.

Terra and Aura are both operational, and both are correctly separated from failure by the abruptness test rather than being labelled dead. Aura's wind-down beginning 2023 is consistent with its A-train exit.

Figure: `data/figures/detector_validation.png`. Reproduce with `python scripts/run_real_validation.py`.

### The premise holds

Envisat lost contact on 8 April 2012 — the first week of Q2 2012. The manoeuvre signal collapses in exactly that quarter.

| Quarter | Altitude (km) | Fraction of days with altitude rise |
|---|---|---|
| 2011 Q4 | 766.8 | 0.32 |
| 2012 Q1 | 766.8 | 0.24 |
| **2012 Q2** | 766.8 | **0.04** |
| 2012 Q3 | 766.7 | 0.02 |
| 2013 Q4 | 766.3 | 0.01 |

Measured across the full history: 0.251 before the documented failure, 0.018 after. Altitude becomes monotonic decay immediately afterwards.

### Finding 1 — the original threshold was wrong by ~20×

The first detector looked for orbit-raising burns above 0.3 km. Envisat's real maintenance burns move semi-major axis by about **0.016 km/day** at the 99th percentile. Running that detector on real Envisat data found **zero** manoeuvres across its entire operational life, and would have silently discarded a documented failure as "never station-keeping."

Magnitude does not work. **Frequency does**: the fraction of days on which altitude rose moved 0.251 → 0.018 across the failure. The detector now uses that statistic.

### Finding 2 — maintenance cessation is not the same as failure

Terra is operational in 2026 — instruments working, data downlinked — but NASA ended its orbit maintenance around 2020 and let it drift from its 10:30 crossing time. Its manoeuvre frequency reads 0.019 in 2021 and 0.000 in 2026, which on the frequency statistic alone is indistinguishable from a dead satellite.

For an insurance model these are different things: a drifting-but-working satellite is not a claim.

The discriminator is **abruptness**. Envisat fell from 0.24 to 0.04 in one quarter. Terra declined over roughly four years (0.31, 0.30, 0.24, 0.12, 0.019). A failure is a step; a planned wind-down is a ramp. The detector now reports both cessation and its shape, and only abrupt cessation is labelled a probable failure.

### Finding 3 — baselines are per-satellite, not absolute

Envisat ran at 0.25 and Terra at 0.09, both while fully maintained. No single absolute threshold separates them, so the baseline is computed from each satellite's own early history.

### Finding 4 — the altitude floor works

GOCE sits at 281 km falling to 140 km, using continuous ion thrust in a drag-dominated regime where the frequency statistic is meaningless (0.25–0.49 throughout, including the year it died). The existing below-400 km abstention correctly refuses to label it.

---

## Completed

**Data access.** Space-Track account verified; rate-limited client enforcing both published caps (30/min, 300/hr); disk caching. Confirmed the legacy `tle` endpoints return 404 as of January 2026 and migrated to `gp_history`.

**Pipeline.** Stratified sampling by altitude shell; weekly decimation; altitude and shell derivation; kernel density estimation of debris density per shell per epoch.

**Failure labelling.** Frequency-based detector with per-satellite baselines and an abruptness test separating failure from planned wind-down. Five explicit abstention cases, so the detector returns a reason rather than forcing a label it cannot support.

**Modelling.** Counting-process panel assembly; Cox proportional hazards with time-varying covariates; proportional hazards assumption testing; Weibull AFT for extrapolation; logistic baseline; temporal split and concordance evaluation; pricing layer.

**Testing.** 53 unit tests, all passing (29 on the detector, 24 on the live single-satellite path), with synthetic magnitudes calibrated to the real measurements above rather than to guesses. Two tests document known breakdowns rather than asserting success.

**Real validation.** 4 of 4 documented satellites classified correctly, with Envisat dated to within 7 days.

---

## Also complete

- **Population run** — 535 satellites pulled and classified; 264 in the survival panel, 83 events
- **Sensitivity analysis** — 16 configurations, density never significant (`scripts/sensitivity_analysis.py`)
- **Written report** — `REPORT.md`, with `RESULTS.md`, `docs/CODE_WALKTHROUGH.md`, `docs/VIVA_PREP.md`
- **Live single-satellite pipeline** — `scripts/analyse_satellite.py <NORAD_ID>`: CelesTrak catalogue and current orbit, Space-Track history, detector, cross-check against CelesTrak's status code, shell price

---

## Remaining

| Task | Why it matters |
|---|---|
| Fix the Weibull time origin | Durations start at first observation, not launch, so absolute pricing is 2–7x too high. Blocks any parametric pricing claim. |
| Handle the PH violation for solar flux | Stratify or add a flux-by-time interaction. |
| Improve wind-down separation | 6/15 on synthetic cases. |
| Widen the 400–500 km and 1500–2000 km shells | 3 satellites and 0 events respectively; neither rate is meaningful. |
| Test a rarer event class | Cessation is dominated by propellant exhaustion and retirement. Debris-driven failure would need fragmentation and anomaly events instead. |
| Year-by-year market validation | The pooled rate (2.59%/yr) matches the 1–3% loss-rate band; a year-by-year comparison, including the 2023 spike, is not done. |

## Open issues

**Wind-down separation is the weakest part of the method.** On synthetic data the detector separates gradual wind-downs from abrupt failures in only 6 of 15 cases, even after smoothing the quarterly series. The real Envisat–Terra gap is wide (1 quarter versus about 12), so the distinction is clearly present in real data, but the current statistic does not capture it reliably. Candidate improvements: fitting a changepoint model to the frequency series rather than thresholding it, or using the second derivative of the decline.

**Weibull shape is implausible on synthetic data** (rho ≈ 18), which makes the synthetic premium figures meaningless. This is an artifact of the generator producing nearly deterministic lifetimes within each shell, not a defect in the fitting code. It needs rechecking once real lifetimes are in.

---

## Earlier issues found and fixed

**The Weibull was fitting the censoring boundary.** A temporal split censors every surviving satellite at the same calendar instant, piling most durations onto one value, so the shape parameter described the split rather than how satellites age. Fixed by fitting Weibull on the full panel and reserving the temporal split for evaluating Cox's ranking.

**The logistic baseline had a degenerate label.** Labelling on total observed lifetime made every satellite observed longer than the one-year horizon a negative, collapsing the target to a single class. Fixed by labelling per observation row.

---

## Code

```
src/spacetrack_client.py    Rate-limited API client with caching
src/ingest.py               Stratified sampling, weekly decimation
src/features.py             Altitude derivation, KDE debris density
src/failure_detection.py    Frequency-based labelling with abruptness test
src/panel.py                Counting-process panel assembly
src/models.py               Cox, Weibull, logistic, pricing layer

src/celestrak.py            CelesTrak catalogue and current-orbit client
src/panel_summary.py        Panel assembly from the population summary

scripts/analyse_satellite.py    Any single satellite, live, seven steps
scripts/run_full_analysis.py    Full pipeline on the real population
scripts/sensitivity_analysis.py 16-configuration robustness check
scripts/run_real_validation.py  Detector vs four documented satellites
scripts/envisat_case_study.py   Single-satellite deep dive
scripts/validate_detector.py    Validation re-pulled from the API
scripts/pipeline_smoke_test.py  End-to-end verification on synthetic data

tests/test_detection.py         29 unit tests (detector)
tests/test_live_pipeline.py     24 unit tests (live path)
docs/methodology.md             Method, assumptions, limitations
data/processed/validation_observations.csv   Real measurements from 11 Nov
```
