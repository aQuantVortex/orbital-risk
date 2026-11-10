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

An operational satellite in LEO fights atmospheric drag by periodically raising its orbit, producing a sawtooth altitude trace. When control ends — propellant exhaustion, subsystem failure, end of mission — the burns stop and the trace becomes monotonic decay.

Detection combines two signals, with a third for corroboration:

1. **Cessation of station-keeping.** Positive jumps in altitude exceeding a threshold (default 0.3 km, above element-set noise but below a real burn) are counted as manoeuvres. The last such jump, followed by a quiet period (default 52 weeks), marks candidate end-of-life.
2. **Sustained decay afterwards.** A rolling least-squares slope over an 8-week window must stay below a negative threshold to confirm.
3. **BSTAR jump.** A satellite that loses attitude control tumbles, changing its effective cross-section, which appears as a rise in the fitted drag term. Agreement between signals strengthens the label.

### Abstention cases

The detector returns a reason rather than a forced label when it cannot speak:

| Reason | Meaning |
|---|---|
| `below_min_altitude` | Under ~400 km, drag decay is rapid regardless of health, so natural decay would masquerade as failure. |
| `no_station_keeping` | Fewer than three manoeuvres detected; the satellite was never station-keeping, so cessation says nothing. |
| `still_manoeuvring` | Recent burns; the satellite is alive. |
| `quiet_but_not_decaying` | Burns stopped but no sustained decay. Ambiguous, so no label. |
| `insufficient_history` | Too few observations to fit slopes. |

### Validation

Curated records become the **validation set** rather than the training target. The detector is scored against satellites whose outcomes are matters of public record — Envisat (contact lost 8 April 2012) and GOCE (propellant exhausted October 2013) as positives, Terra and Aura as still-operational controls that must not fire.

On synthetic traces with known ground truth, the detector currently achieves precision 1.00 and recall 0.95.

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

---

## 10. Reproducibility

All data is re-derivable from public sources. The repository tracks code, figures and small summary tables; raw pulls are gitignored and regenerated by running the pipeline with valid Space-Track credentials.

`scripts/pipeline_smoke_test.py` verifies the full chain on synthetic data with known ground truth before any real API time is spent. `tests/test_detection.py` covers the detector against controlled traces.
