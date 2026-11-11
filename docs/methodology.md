# Methodology

## 1. Research question

Can a satellite's failure hazard be estimated from its orbital environment using only public data, and how far does the modelled risk sit from the flat rate the insurance market charges?

The claim is one of **association**, conditional on the included covariates. This is observational data; popular orbits attract both debris and expensive, well-monitored satellites, so no causal claim is made.

---

## 2. Data acquisition

**Source.** Space-Track.org `gp_history`, 138M+ historical element sets. The legacy `tle` and `tle_latest` classes were deprecated and return 404 as of January 2026; `gp_history` also exposes `SEMIMAJOR_AXIS` and `BSTAR` directly, removing the need to convert from mean motion.

**Rate limits.** 30 requests/minute, 300/hour. Exceeding these risks account suspension, so requests pass through a token-bucket limiter enforcing both windows simultaneously. Responses are cached to disk, so a re-run costs nothing.

**Sampling.** A full pull is infeasible. Two reductions:

1. *Stratified object sampling.* Objects are sampled by altitude shell, so every shell is represented. Taking whatever the catalogue returns first would over-represent whichever constellation launched most recently.
2. *Weekly decimation.* Space-Track may hold several element sets per object per day. Orbital elements change slowly, so resampling to weekly loses almost nothing and cuts volume by one to two orders of magnitude.

---

## 3. Feature engineering

**Altitude** is derived from semi-major axis as `a − R_earth`, with `R_earth = 6378.137 km`.

**Shell assignment** uses boundaries at 200, 400, 500, 600, 700, 800, 900, 1000, 1200, 1500 and 2000 km, chosen around known population concentrations.

**Debris density** is estimated per shell per epoch by kernel density estimation over the altitude distribution of all tracked objects. A histogram would be discontinuous and sensitive to bin placement, which is a poor input to a regression.

Bandwidth is the consequential choice. Debris concentrates in narrow shells, especially with mega-constellations parked at specific altitudes, so over-smoothing erases exactly the structure being measured while under-smoothing produces sampling noise. The default is Scott's rule, and the evaluation stage sweeps it.

Objects can optionally be weighted by cross-sectional area, since a spent rocket body and a CubeSat are not equally hazardous targets.

---

## 4. Failure labelling

This is the central methodological choice.

### Why not use published failure records

Curated registries cover mostly large, insured, Western spacecraft. Training on them would inherit that selection and leave too few events to fit anything: the rule of thumb wants ten events per covariate, and a curated list does not comfortably supply that.

### The derived approach

An operational satellite in LEO fights atmospheric drag by periodically raising its orbit. When maintenance ends, the raising stops and the trace becomes monotonic decay.

**The statistic is manoeuvre frequency, not magnitude.** An earlier version of this method counted individual orbit-raising burns above a 0.3 km threshold. Validation against real Space-Track data on 11 November 2026 showed that threshold is wrong by roughly a factor of twenty: Envisat's real maintenance burns move semi-major axis by about 0.016 km/day at the 99th percentile. The magnitude detector found zero manoeuvres across Envisat's entire operational life and would have silently discarded a documented failure.

What works is the **fraction of consecutive days on which median altitude rose**. Drag pulls altitude down continuously, so on an unmaintained satellite almost every day is negative; orbit-raising produces the positive days. Measured on Envisat:

| | Positive-delta fraction |
|---|---|
| Before 2012-04-08 (documented contact loss) | 0.251 |
| After | 0.018 |

Element sets are first collapsed to one median altitude per day, since individual fits carry noise well above the real day-to-day change. Quarterly aggregation then gives a series stable enough to threshold but fine enough to date a transition.

### Baselines are per satellite

Envisat ran at 0.25 and Terra at 0.09, both while fully maintained. No absolute threshold separates them, so each satellite's baseline is taken from its own early history (default eight quarters), and cessation is defined relative to that baseline.

### Cessation is not the same as failure

Terra (NORAD 25994) is operational in 2026 — instruments working, data downlinked — but NASA ended its orbit maintenance around 2020 and let it drift from its 10:30 mean local time. Its positive-delta fraction reads 0.019 in 2021 and 0.000 in 2026, which on the frequency statistic alone is indistinguishable from a dead satellite.

For an insurance model these are different things: a drifting-but-working satellite is not a claim.

The discriminator is **abruptness**:

| | Decline duration |
|---|---|
| Envisat (failure) | ~1 quarter (0.24 → 0.04) |
| Terra (planned wind-down) | ~12 quarters (0.31 → 0.30 → 0.24 → 0.12 → 0.019) |

A failure is a step; a planned wind-down is a ramp. The detector reports `status` as `failed_abrupt` or `maintenance_ended_gradual`, so the ambiguity is visible to the modelling stage rather than hidden inside a boolean. The transition length is measured on a three-quarter rolling median, because a single high quarter part way down a multi-year ramp would otherwise make a wind-down look abrupt.

**This separation is currently the weakest part of the method.** On synthetic data it succeeds in only 6 of 15 cases. The real Envisat–Terra gap is wide, so the distinction is clearly present in real data, but the present statistic does not capture it reliably. Candidate improvements: fitting a changepoint model to the frequency series rather than thresholding it, or using the second derivative of the decline.

### Abstention cases

The detector returns a reason rather than a forced label when it cannot speak:

| Reason | Meaning |
|---|---|
| `below_min_altitude` | Under 400 km, drag decay is rapid regardless of health, and some craft (GOCE) use continuous low thrust that makes the frequency statistic meaningless. |
| `no_station_keeping` | The satellite never showed meaningful manoeuvre activity, so cessation says nothing about it. |
| `insufficient_history` | Fewer than 90 days of observations. |
| `insufficient_quarters` | Fewer than 16 usable quarters, too few to establish a baseline and detect a change against it. |
| `still_maintaining` | Activity has not dropped below the relative threshold. |

### Validation

Curated records become the **validation set** rather than the training target. The detector is scored against satellites whose circumstances are matters of public record:

| Satellite | Expected | Why it is a useful test |
|---|---|---|
| Envisat (27386) | `failed_abrupt` | Contact lost 8 April 2012; clean step in the frequency series at exactly that quarter |
| Terra (25994) | `maintenance_ended_gradual` | Still operational in 2026; orbit maintenance ended ~2020. The harder test — must not be labelled a failure |
| Aura (28376) | not a failure | Second operational control |
| GOCE (34602) | `abstain` | At 255 km with continuous ion thrust, below the altitude floor |

**Result on real data: 4 of 4 correct.**

| Satellite | Expected | Detected | Baseline | Decline | Error |
|---|---|---|---|---|---|
| Envisat | `failed_abrupt` | `failed_abrupt` | 0.212 | 1 quarter | −7 days |
| Terra | `maintenance_ended_gradual` | `maintenance_ended_gradual` | 0.089 | 8 quarters | — |
| Aura | not a failure | `maintenance_ended_gradual` | 0.072 | 6 quarters | — |
| GOCE | `abstain` | `abstain` | — | — | — |

The seven-day error on Envisat is the quarter boundary: the documented loss is 8 April 2012 and the detector dates cessation to 1 April, which is the finest resolution a quarterly series admits. Finer dating would need a monthly series, at the cost of a noisier frequency estimate.

On synthetic traces with known ground truth, detection of abrupt failures achieves precision 0.96 and recall 0.88. Separation of gradual wind-downs succeeds in only 6 of 15 cases, which remains the open weakness: the real Envisat–Terra gap (1 quarter versus 8) is wide enough to separate cleanly, but the synthetic cases are harder than the real ones, and the statistic is not yet robust across the full range.

Reproduce with `python scripts/run_real_validation.py`. Supporting measurements are in `data/processed/validation_observations.csv` and the full aggregated series in `data/processed/real_quarterly_activity.csv`.

---

## 5. Panel construction

Output is **counting-process format**: one row per satellite per quarter, as `(t_start, t_stop, event]`.

This is what makes time-varying covariates possible. Debris density around a satellite launched in 2012 is not what it was at launch, and freezing it to a single value discards the variable the study is about.

Satellites still operating at the study end are **right-censored**: their final row carries `event = 0`, recording that they survived at least that long rather than that they never fail.

Covariates: shell debris density (time-varying), F10.7 solar flux (time-varying), spacecraft age, altitude, inclination band, mass class.

---

## 6. Models

### Cox proportional hazards — primary

`h(t | x) = h₀(t) · exp(βᵀx)`

The baseline hazard `h₀(t)` is left entirely unspecified. This matters because spacecraft ageing is not a shape we can responsibly assume: infant mortality from manufacturing defects, a flat middle, then wear-out as propellant depletes. Assuming the wrong shape would corrupt everything downstream.

Estimation is by partial likelihood, in which `h₀` cancels. Censored satellites contribute through the risk-set denominator: they record who else was exposed and did not fail.

Fitted with `CoxTimeVaryingFitter`, which accepts the counting-process form. Plain `CoxPHFitter` takes one row per subject and cannot support time-varying covariates.

Ridge penalisation (default 0.1) is applied, since the event count is modest relative to covariate count.

### Assumption testing

Cox assumes the hazard ratio between two satellites is **constant over time**. Scaled Schoenfeld residuals regressed against time reveal violations. Remedies: stratify on the offending covariate, giving each stratum its own baseline, or add an explicit covariate-by-time interaction.

### Weibull AFT — forecasting

Cox estimates the baseline only at times where failures were observed, so it cannot extrapolate past the study window. Remaining-life estimates require a parametric survival function.

Covariates are standardised before fitting. Raw values span very different magnitudes (altitude ~800, density ~2, age ~5), which conditions the optimiser badly and produces unstable shape estimates.

**Fit on the full panel, not the temporal training split.** A temporal split censors every surviving satellite at the same calendar instant, piling most durations onto one value; the shape parameter then describes the censoring boundary rather than the failure process. This was found during pipeline testing and is worth stating because it is not obvious.

### Logistic regression — baseline

Fixed one-year window, failed or not. This is what a competent analyst unfamiliar with survival methods would do.

The label is built **per observation row**: for each satellite-quarter, did that satellite fail within the following 52 weeks? Labelling on total lifetime instead would make every satellite observed longer than the horizon a negative, collapsing to a single class.

What it discards: timing (a failure at week 4 and one at week 50 are identical to it) and partial follow-up. If Cox does not beat it, the added complexity is not earning its place, and the report will say so.

---

## 7. Evaluation

**Temporal split**, not random. Train before 2020, test after. Random splitting would put the same satellite's quarters on both sides and leak. Time splitting also matches intended use: fit on history, predict forward.

**Concordance index.** Of all pairs where we can tell which satellite failed first, the share the model ranked correctly. 0.5 is a coin flip. On messy real data, 0.65–0.75 is respectable; 0.95 would indicate leakage.

Note that concordance measures **discrimination, not calibration**. A model can rank perfectly while being wrong about absolute probabilities, which is why external validation exists separately.

**Sensitivity analysis** over KDE bandwidth and shell boundaries. If conclusions flip when the smoothing parameter moves 20%, they were not conclusions.

**External validation.** Aggregate predicted expected loss across the insured fleet against published annual market loss ratios. Specific test: the model must reproduce the 2023 loss spike, when insurers paid $995M against $557M in premiums. A model that cannot see the market's worst recent year is not describing the world.

---

## 8. Pricing layer

Conditional annual failure probability:

`P(fail within a year | survived to t) = 1 − S(t+52)/S(t)`

The conditioning matters: a policy is priced on a satellite that has already survived to its current age, not on one at launch.

Premium = expected loss × (1 + risk loading). The loading exists because space losses are **severe and correlated**: one fragmentation event damages many satellites simultaneously, so an insurer's variance far exceeds what independence would imply. That correlation is why capacity leaves the market after a bad year.

Comparison is against a flat 8.5%, the midpoint of the 5–12% band quoted in broker market reports.

---

## 9. Limitations

| Limitation | Handling |
|---|---|
| Element sets carry km-scale positional error | Output is a relative hazard index, not a collision probability. No claim about any specific trajectory. |
| Disclosure favours large, insured spacecraft | Largely addressed by deriving labels; residual bias stated and scoped. |
| Solar activity drives drag and decay | F10.7 included as a covariate, so solar-cycle effects are not misattributed to debris density. |
| Low orbits decay regardless of health | Detector abstains below 400 km. |
| Starlink dominates recent population | Stratified out, analysed separately. |
| Per-policy premiums are proprietary | Validation at market aggregate level only. |
| Catalogue covers only objects >10 cm | Tracked density is a proxy, assuming untracked debris scales with tracked. The particle that destroyed SpainSat NG-2 was very likely smaller than the detection threshold. |
| Event count may limit power | The ten-events-per-covariate rule is checked at fit time and warned on. This constraint is the entire argument for deriving labels rather than inheriting them. |
| Operational satellites that stop orbit maintenance read as failures | Abruptness test separates them, imperfectly. Terra is the documented case. |
| The frequency statistic degrades where observation noise exceeds daily decay | A dead satellite then reads near 0.5 instead of near 0.02 and the signal vanishes. Most relevant at high altitude where decay is slowest; Envisat at 766 km stays clear of it. A regression test documents the breakdown rather than asserting it does not occur. |

---

## 10. Reproducibility

All data is re-derivable from public sources. The repository tracks code, figures and small summary tables; raw pulls are gitignored and regenerated by running the pipeline with valid Space-Track credentials.

`scripts/pipeline_smoke_test.py` verifies the full chain on synthetic data with known ground truth before any real API time is spent. `tests/test_detection.py` covers the detector against controlled traces.
