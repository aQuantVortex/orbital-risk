# Project Status

**Pricing Orbital Risk** — Foundations of Data Science
Last updated: 11 November 2026

---

## One-line summary

The data pipeline and modelling layer are built and tested end to end on synthetic data with known ground truth; the next step is running the same chain on the real Space-Track catalogue.

---

## Completed

### Data access
- Space-Track.org account registered and API access verified
- Rate-limited client enforcing both published caps (30 requests/minute, 300/hour) via a token-bucket limiter
- Disk caching, so re-runs cost no API quota
- Confirmed the legacy `tle` endpoints were deprecated (404 as of January 2026) and migrated to `gp_history`, which also exposes `SEMIMAJOR_AXIS` and `BSTAR` directly

### Pipeline
- Stratified sampling by altitude shell, so every shell is represented rather than over-weighting whichever constellation launched most recently
- Weekly epoch decimation, reducing volume by one to two orders of magnitude at negligible information cost
- Altitude and shell derivation from orbital elements
- Kernel density estimation of debris density per shell per epoch

### Failure labelling
- Changepoint detector identifying cessation of station-keeping from altitude traces
- Three combined signals: manoeuvre detection, sustained decay slope, and `BSTAR` drag-term jump
- Five explicit abstention cases, so the detector returns a reason rather than forcing a label it cannot support
- 19 unit tests against synthetic traces with controlled ground truth, all passing
- Current synthetic performance: precision 1.00, recall 0.95

### Modelling
- Counting-process panel assembly (one row per satellite per quarter), which is what makes time-varying covariates possible
- Cox proportional hazards with time-varying covariates
- Proportional hazards assumption testing via scaled Schoenfeld residuals
- Weibull accelerated failure time model for extrapolation
- Logistic regression baseline for comparison
- Temporal train/test split and concordance index evaluation
- Pricing layer converting conditional failure probability into a premium rate

### Verification
- Full end-to-end smoke test on synthetic data, run before spending real API quota
- Pipeline confirmed to run cleanly from raw trace through to market comparison

---

## In progress

- **Detector validation on real satellites.** Script written (`scripts/validate_detector.py`), tests Envisat (contact lost 8 April 2012) and GOCE (propellant exhausted October 2013) as positives, with Terra and Aura as still-operational controls that must not trigger.
- **Population ingestion.** Stratified pull across LEO shells.

---

## Remaining

| Task | Notes |
|---|---|
| Model fitting on the real panel | Depends on ingestion completing |
| Sensitivity analysis | KDE bandwidth and shell boundary choices |
| External validation | Aggregate predicted loss against published market loss ratios; specific test is reproducing the 2023 loss spike |
| Pricing comparison | Modelled rate per shell versus the flat 5–12% market rate |
| Written report | Methodology, validation, and limitations |

---

## Two issues found and fixed during testing

Documented because they were not obvious and both would have produced plausible-looking but wrong results.

**The Weibull model was fitting the censoring boundary rather than the failure process.** A temporal train/test split censors every surviving satellite at the same calendar instant, which piles most observed durations onto a single value. The shape parameter then describes where the split was drawn rather than how satellites age. Fixed by fitting the Weibull on the full panel and reserving the temporal split for evaluating the Cox model's ranking.

**The logistic baseline had a degenerate label.** Labelling on total observed lifetime made every satellite observed longer than the one-year horizon a negative, collapsing the target to a single class. Fixed by labelling per observation row: for each satellite-quarter, did that satellite fail within the following 52 weeks?

---

## Code

1,962 lines of Python across 8 modules, with tests.

```
src/spacetrack_client.py    Rate-limited API client with caching
src/ingest.py               Stratified sampling, weekly decimation
src/features.py             Altitude derivation, KDE debris density
src/failure_detection.py    Changepoint-based failure labelling
src/panel.py                Counting-process panel assembly
src/models.py               Cox, Weibull, logistic, pricing layer

scripts/validate_detector.py    Validation against documented failures
scripts/pipeline_smoke_test.py  End-to-end verification

tests/test_detection.py     19 unit tests on synthetic traces
docs/methodology.md         Full method, assumptions, limitations
```
