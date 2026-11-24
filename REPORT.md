# Pricing Orbital Risk

### A Survival-Analysis Model of Satellite Failure Hazard in Low Earth Orbit

**Foundations of Data Science — Project Report**
BITS Pilani Dubai Campus · November 2026

---

## Abstract

The satellite insurance market prices in-orbit risk as a flat 5–12% of asset
value, with little adjustment for the orbital environment a spacecraft
occupies. Debris density in low Earth orbit varies by more than an order of
magnitude across altitude shells and has changed substantially over the past
two decades, so a flat rate appears on its face to be a coarse instrument.
This project tests whether that environment measurably predicts satellite
failure, using only public data.

The principal methodological problem is that failure labels do not exist in
usable form: published registries cover a few hundred large, insured, Western
spacecraft, which is both a biased sample and too few events to fit anything.
The project therefore derives labels from orbital behaviour. An operational
satellite in LEO periodically raises its orbit against atmospheric drag; when
maintenance ceases, that signature stops. Detecting the transition yields
labels on a uniform definition across the whole catalogue.

The detector was validated against four satellites with publicly documented
outcomes and classified all four correctly, dating Envisat's 2012 failure to
within seven days. Applied to a stratified sample of 535 LEO payloads, it
produced 93 abrupt-cessation events. A Cox proportional hazards model with
time-varying covariates was fitted to a 12,793-row counting-process panel
covering 264 satellites and 83 events.

**The central hypothesis is not supported.** Debris density does not
measurably predict end-of-maintenance (hazard ratio 1.002, p = 0.49), and this
null survives all sixteen configurations of a sensitivity analysis spanning
shell boundaries, study windows and population subsets — the smallest p-value
obtained for density in any specification is 0.360.

Two findings survive. First, the detector's empirical cessation rate of 2.59%
per satellite-year falls inside the 1–3% band of published in-orbit insurance
loss rates, reproduced from orbital geometry with no insurance data anywhere
in the pipeline. Second, on that basis the market's flat rate is conservative
rather than coarse: every altitude shell prices below the 8.5% midpoint,
inverting the direction of mispricing the project was built to find.

---

## 1. Introduction

### 1.1 Motivation

In January 2026 a military communications satellite insured for approximately
$400 million was declared a total loss following a particle impact. The policy
had been priced as a percentage of asset value with minimal adjustment for the
satellite's orbital regime.

This is characteristic of the market rather than exceptional. Roughly a dozen
underwriters write space insurance worldwide, collecting $500–600 million in
annual premiums. The market is small and volatile: in 2023 it paid $995
million in claims against $557 million in premiums, a loss ratio near 180%,
after which capacity withdrew and rates rose.

The consequence is a coverage gap. Fewer than 1% of active LEO satellites
carry in-orbit insurance — roughly 300 of 10,000. The common reading is that
underwriters cannot measure the risk with enough granularity to price it, and
so decline to write it.

### 1.2 Research question

> Can satellite failure hazard be estimated from orbital environment using
> publicly available data, and how far does the resulting risk estimate sit
> from the market's flat rate?

The claim under test is one of **association**, conditional on the covariates
included. This is observational data; no causal claim is made.

### 1.3 Contribution

The project's substantive contribution is not the model — Cox regression is
standard — but the **construction of the labels the model consumes**, and the
validation of that construction against independent ground truth.

---

## 2. Data

### 2.1 Sources

| Source | Content | Volume | Access |
|---|---|---|---|
| Space-Track.org `gp_history` | Historical orbital element sets | 138M+ records | Free account, REST API |
| Space-Track.org `satcat` | Catalogue metadata, launch and decay dates | 71,424 objects | Same |
| NOAA SWPC | F10.7 solar radio flux | Monthly since 1947 | Open |
| GCAT (planet4589.org) | Documented launch, decay and anomaly records | Full history | Open |
| Aon / Gallagher market reports | Market loss ratios | Quarterly | Open PDF |

The legacy `tle` and `tle_latest` API classes were deprecated and return HTTP
404 as of January 2026. This project uses `gp` and `gp_history`, which expose
`SEMIMAJOR_AXIS` and `BSTAR` directly and remove the need to convert from mean
motion.

### 2.2 Acquisition under constraint

Space-Track enforces 30 requests per minute and 300 per hour; exceeding these
risks account suspension. A full retrieval of 138 million element sets is
therefore infeasible, and the sampling design becomes part of the method.

Two reductions make the problem tractable:

**Stratified sampling.** Objects are sampled by altitude shell rather than
taken in catalogue order, which would over-represent whichever constellation
launched most recently. Mega-constellations (Starlink, OneWeb) are excluded
from the sampling frame and treated separately, following the stratification
rationale in §6.

**Temporal decimation.** Element sets are collapsed to one median altitude per
day. Orbital elements change slowly relative to the signal of interest, so this
costs almost nothing in information and reduces volume by one to two orders of
magnitude.

### 2.3 Robust aggregation

Daily collapse uses the **median**, not the mean. Individual orbit fits carry
noise, and occasional fits are badly wrong. The median has a breakdown point of
50% — half the observations can be arbitrary before the estimate fails —
whereas the mean's breakdown point is zero, so a single bad fit can move it
arbitrarily far.

This matters because the detection signal involves altitude changes of order
0.016 km while a bad fit can be off by kilometres.

### 2.4 Reconstructing the debris environment

Debris density per shell per quarter was reconstructed from the full
catalogue: for each quarter from 2002Q1 to 2026Q4, every object whose launch
date precedes the quarter and whose decay date follows it is binned by mean
altitude, and the count divided by shell width.

The resulting panel shows substantial variation both across shells and over
time:

| Shell | 2002 (objects/km) | 2026 (objects/km) |
|---|---|---|
| 200–400 km | 21.8 | 7.7 |
| 400–500 km | 11.5 | **107.7** |
| 500–600 km | 8.5 | 21.9 |
| 700–800 km | 23.3 | 27.5 |
| 800–900 km | 22.5 | 29.0 |
| 1500–2000 km | 1.7 | 1.7 |

The 400–500 km rise is the mega-constellation build-up; the 200–400 km decline
reflects natural decay of an earlier population.

**Limitation.** `APOGEE` and `PERIGEE` in the catalogue are a single
current-or-final snapshot rather than a time series, so each object's altitude
is treated as fixed over its life. For objects in stable orbits above ~600 km
this is a small error; for objects that decayed substantially it biases their
assigned shell downward.

### 2.5 Solar flux

NOAA's observed solar-cycle file reports F10.7 as `-1` before October 2004.
Rather than impute a covariate across eleven quarters, or splice a second
source with different calibration, the modelling window begins at 2004Q4. The
resulting series spans 89 quarters with F10.7 between 66 and 214, covering
one full solar cycle plus the rise of the next.

Detection baselines still use each satellite's complete history; only the
modelling window is clipped.

---

## 3. Methodology

### 3.1 The labelling problem

Supervised learning requires labels. For satellite failure, usable labels do
not exist:

- Published registries cover predominantly large, insured, Western spacecraft.
  Training on them would learn the disclosure process as much as the physics.
- They yield a few hundred events at most. Survival models are limited by
  **event count**, not row count, with a rule of thumb of ten events per
  covariate. A curated list does not comfortably supply enough.

### 3.2 Deriving labels from orbital behaviour

An operational satellite in LEO fights atmospheric drag by periodically
raising its orbit. Its altitude trace is a sawtooth: slow decay punctuated by
positive corrections. When active maintenance ends — propellant exhaustion,
subsystem failure, or planned retirement — the corrections stop and the trace
becomes monotonic decay.

This transition is detectable, applies uniformly to every tracked object, and
does not depend on anyone choosing to disclose it.

### 3.3 Frequency, not magnitude

The first implementation searched for individual orbit-raising burns above a
0.3 km threshold. Validation against real data showed this to be wrong by
roughly a factor of twenty: Envisat's actual maintenance burns move semi-major
axis by about **0.016 km/day** at the 99th percentile. The magnitude detector
found *zero* manoeuvres across Envisat's entire operational life and would have
discarded one of the best-documented failures in the catalogue.

What works is manoeuvre **frequency** — the fraction of consecutive days on
which median altitude rose:

$$\hat{p} = \frac{1}{n}\sum_{i=1}^{n}\mathbb{1}[\Delta a_i > 0]$$

The reasoning: each day, altitude changes by

$$\Delta a_i = -d + b_i + \varepsilon_i$$

where $d \approx 0.001$ km/day is drag, $b_i$ is the manoeuvre contribution
(zero on most days, ~0.016 km when a burn occurs), and $\varepsilon$ is
observation noise. With no manoeuvres $\Delta a_i < 0$ almost always, so
$\hat p \to 0$; with manoeuvres at rate $\lambda$, $\hat p \to \lambda$. The
statistic estimates manoeuvre rate directly and is indifferent to burn size,
requiring only that burns exceed drag rather than exceed a guessed threshold.

Measured on Envisat:

| Period | Positive-delta fraction |
|---|---|
| Before 2012-04-08 (documented contact loss) | **0.251** |
| After | **0.018** |

### 3.4 Per-satellite baselines

Envisat ran at 0.21 and Terra at 0.09, both while fully maintained. No absolute
threshold separates them, so each satellite's baseline is taken from its own
first eight quarters and cessation defined relative to that.

### 3.5 The noise-dominated regime

The statistic requires $d > \sigma_\varepsilon$ — drag must exceed noise, or
the sign of the daily change carries no information and roughly half of all
days read positive regardless of whether the satellite is alive.

This is not hypothetical. Running the detector across the real population
surfaced it immediately: several long-dead 1960s–80s payloads in the
1000–1500 km shells returned baselines of 0.46–0.61, where drag is of order
0.0001 km/day. Read naively they appear to be vigorous station-keepers.

Since real maintained satellites sit far lower (Envisat 0.21, Terra 0.09, Aura
0.07), a baseline above 0.45 is diagnostic of noise. The detector abstains
with reason `noise_dominated`. Discovering this also corrected a synthetic test
that had assumed a 0.40 maintenance rate no observed satellite approaches.

### 3.6 Cessation is not failure

Terra (NORAD 25994) is operational in 2026 — instruments working, data
downlinked — but NASA ended its orbit maintenance around 2020 and allowed it
to drift from its 10:30 mean local time. Its manoeuvre frequency reads 0.019 in
2021 and 0.000 in 2026, indistinguishable from a dead satellite on the
frequency statistic alone.

This is a **construct validity** problem: the measured quantity ("is this
satellite being maintained") is adjacent to but not identical with the target
("is this satellite functional"). No accuracy metric detects it, because the
model is confidently correct about the wrong quantity. For an insurance model
the distinction matters: a drifting but working satellite is not a claim.

The discriminator is **abruptness**:

| Satellite | Decline duration |
|---|---|
| Envisat (failure) | 1 quarter (0.24 → 0.04) |
| Terra (planned wind-down) | 8 quarters |
| Aura (planned wind-down) | 6 quarters |

A failure is a step; a planned wind-down is a ramp. The detector reports
`failed_abrupt` or `maintenance_ended_gradual` so the ambiguity is visible to
the modelling stage rather than hidden inside a boolean. Transition length is
measured on a three-quarter rolling median, because a single high quarter part
way down a multi-year ramp would otherwise make a wind-down look abrupt.

### 3.7 Abstention

The detector returns a reason rather than forcing a verdict:

| Reason | Meaning |
|---|---|
| `below_min_altitude` | Under 400 km, drag decay is rapid regardless of health, and some craft use continuous low thrust |
| `noise_dominated` | Baseline above 0.45; noise decides the sign |
| `no_station_keeping` | Never showed meaningful manoeuvre activity |
| `insufficient_quarters` | Fewer than 16 usable quarters |
| `still_maintaining` | Activity has not dropped below threshold |

Across the 535-satellite population, 46.4% abstained. This is the method
working, not failing: a forced label on an uninformative trace is worse than no
label.

### 3.8 Survival analysis

Most satellites have not failed, so their failure times are unknown. Dropping
them trains only on failures; labelling them successes asserts something
unknowable. Both are wrong in opposite directions.

This is **right-censoring**. One observes $Y_i = \min(T_i, C_i)$ and
$\delta_i = \mathbb{1}[T_i \le C_i]$. The likelihood

$$L = \prod_i h(Y_i)^{\delta_i} S(Y_i)$$

weights failures by their hazard and censored observations by their survival
probability, using the partial information without imputing the rest.

**Cox proportional hazards** is the primary model:

$$h_i(t \mid x_i) = h_0(t)\exp(\beta^\top x_i)$$

The baseline $h_0(t)$ is left unspecified, which matters because spacecraft
ageing is a bathtub shape no one can responsibly assume. Estimation by partial
likelihood,

$$L_p(\beta) = \prod_j \frac{\exp(\beta^\top x_{(j)})}{\sum_{i \in R(t_j)}\exp(\beta^\top x_i)}$$

cancels $h_0$ between numerator and denominator. Censored satellites contribute
through the risk-set denominator, recording that they were exposed and did not
fail.

**Time-varying covariates** are implemented in counting-process format, one row
per satellite per quarter as $(t_{\text{start}}, t_{\text{stop}}]$. This is
necessary because debris density around a satellite launched in 2012 is not
what it was at launch; freezing it to a single value discards the variable
under study.

**Weibull AFT** supports extrapolation, since Cox estimates the baseline only
where failures were observed and remaining-life estimates require projection
beyond the window.

**Logistic regression** on a fixed one-year window is the baseline to beat. It
discards timing and handles partial follow-up poorly — precisely the
information survival analysis retains.

### 3.9 Censoring rules

| Detector verdict | Panel treatment |
|---|---|
| `failed_abrupt` | `event = 1` on the final row |
| `maintenance_ended_gradual` | **Censored** at cessation — operational when maintenance stopped, unknown after |
| `active` | Censored at study end |
| `abstain` | Excluded |

Treating gradual wind-downs as failures would import the Terra error directly
into the model.

---

## 4. Validation

### 4.1 Detector against documented outcomes

Four satellites whose circumstances are matters of public record:

| Satellite | Expected | Detected | Baseline | Decline | Error |
|---|---|---|---|---|---|
| Envisat | `failed_abrupt` | `failed_abrupt` | 0.212 | 1 quarter | **−7 days** |
| Terra | not a failure | `maintenance_ended_gradual` | 0.089 | 8 quarters | — |
| Aura | not a failure | `maintenance_ended_gradual` | 0.072 | 6 quarters | — |
| GOCE | abstain | `abstain` (below floor) | — | — | — |

**4 of 4 correct.** Envisat's documented contact loss is 8 April 2012; the
detector places cessation at 1 April — the quarter boundary, and the finest
resolution a quarterly series admits.

Terra is the harder test, and the one that matters: an operational satellite
that stopped manoeuvring must not be labelled dead.

### 4.2 Synthetic ground truth

29 unit tests on synthetic traces with controlled failure times, calibrated to
magnitudes measured from real data rather than assumed. Detection of abrupt
failures achieves precision 0.96 and recall 0.88.

Two tests deliberately **document breakdowns** rather than assert success: one
confirms the statistic degrades when noise exceeds drag, another confirms that
abruptness is the only thing separating a drifting satellite from a dead one.

---

## 5. Results

### 5.1 Population

| | |
|---|---|
| Satellites classified | 535 |
| Entering the survival panel | 264 |
| Panel rows | 12,793 |
| Failure events | 83 |
| Events per covariate | 20.8 |
| Censoring rate | 68.6% |
| Median follow-up | 43 quarters |

### 5.2 Cox model

| Covariate | Coefficient | Hazard ratio | SE | p |
|---|---|---|---|---|
| density | +0.0026 | 1.003 | 0.0038 | 0.49 |
| f107 | +0.0016 | 1.002 | 0.0012 | 0.20 |
| age_years | −0.0019 | 0.998 | 0.0025 | 0.45 |
| altitude_km | −0.0001 | 1.000 | 0.0001 | 0.45 |

No covariate is significant. Concordance 0.676 in-sample, **0.562** on the
post-2020 test period — barely above chance. The proportional hazards
assumption is violated for solar flux (p = 0.001).

### 5.3 The null is robust

Sixteen configurations were tested across shell boundaries (coarse, fine,
shifted ±50 km), study window start (2004–2016), and population subsets
(launch era, altitude range, mass class, excluding gradual wind-downs).

| | |
|---|---|
| Configurations fitted | 16 of 16 |
| Hazard ratio range | 0.9976 – 1.0033 |
| Smallest p-value for density | **0.360** |
| Significant at p < 0.05 | **0 of 16** |

Collinearity was tested explicitly, since density and altitude correlate at
−0.68:

| Specification | HR(density) | p |
|---|---|---|
| density alone | 1.0022 | 0.49 |
| density + f107 | 1.0021 | 0.49 |
| density + age | 1.0021 | 0.50 |
| all four covariates | 1.0020 | 0.53 |

The hazard ratio does not move past the third decimal place in any
specification. This is a genuine null, not a masked effect.

### 5.4 Cox loses to the baseline

| Model | Concordance |
|---|---|
| Logistic baseline | **0.696** |
| Cox proportional hazards | 0.676 |

Scored on the same task — ranking satellites by risk — the simpler model ranks
better. The survival machinery does not buy ranking accuracy here. Its value is
confined to handling censoring correctly and making the time-varying covariate
expressible at all.

### 5.5 Pricing

Empirical hazard per shell: events divided by exposure, no model interposed.

| Shell | Satellites | Events | Exposure (yr) | Density | Rate/yr | Premium | vs market |
|---|---|---|---|---|---|---|---|
| 600–700 km | 43 | 19 | 362 | 13.8 | 5.25% | 7.34% | roughly fair |
| 500–600 km | 23 | 13 | 283 | 9.0 | 4.59% | 6.43% | overpriced |
| 1000–1200 km | 17 | 8 | 202 | 6.2 | 3.96% | 5.55% | overpriced |
| 800–900 km | 41 | 17 | 501 | 23.1 | 3.40% | 4.75% | overpriced |
| 400–500 km | 3 | 1 | 38 | 10.6 | 2.64% | 3.70% | overpriced |
| 700–800 km | 45 | 11 | 438 | 24.1 | 2.51% | 3.51% | overpriced |
| 900–1000 km | 33 | 7 | 343 | 16.2 | 2.04% | 2.85% | overpriced |
| 1200–1500 km | 37 | 7 | 608 | 5.7 | 1.15% | 1.61% | overpriced |
| 1500–2000 km | 22 | 0 | 434 | 1.7 | 0.00% | 0.00% | overpriced |

Premium = rate × 1.4. The loading exists because space losses are
**correlated**: one fragmentation event damages many satellites at once, so
insurer variance exceeds what independence implies. That correlation is why
capacity leaves the market after a bad year.

The ordering does not track density — the densest shell (700–800 km, 24.1
objects/km) prices near the bottom. This is the Cox null appearing directly in
the rates.

### 5.6 External validation

The whole-panel cessation rate is **2.59% per satellite-year**. Published
in-orbit insurance loss rates are of order 1–3% per year.

A detector constructed entirely from orbital geometry, with no insurance data
at any point in the pipeline, reproduces the market's own loss experience. This
is the strongest evidence the labelling method produces something real.

### 5.7 The Weibull model is not calibrated

| Shell | Empirical | Weibull | Ratio |
|---|---|---|---|
| 600–700 km | 0.0525 | 0.1218 | 2.3× |
| 800–900 km | 0.0340 | 0.1207 | 3.6× |
| 700–800 km | 0.0251 | 0.1251 | 5.0× |
| 1200–1500 km | 0.0115 | 0.0830 | 7.2× |

The Weibull sits 2–7× above empirical everywhere. Its duration axis starts at
first observation rather than at launch, so for satellites already old when the
window opens the fitted age is wrong, and with shape ρ = 2.48 the error
compounds. The empirical rates are the ones quoted; the Weibull is excluded
from the headline pricing.

---

## 6. Discussion

### 6.1 Why the hypothesis failed

The most plausible explanation is that the detector measures **end of orbit
maintenance**, which is dominated by propellant exhaustion and planned
retirement rather than by debris impacts. Collision-induced failures are rare
enough — the catalogue records a handful of destructive events across decades —
that they do not move an aggregate hazard model built on 83 events.

This is a limitation of what the labels *mean*, not a flaw in how they are
derived. The labels faithfully capture maintenance cessation; maintenance
cessation simply is not primarily a debris phenomenon.

Testing the debris hypothesis directly would require a rarer event class:
fragmentation and anomaly records rather than cessations. That trades a large
sample of the wrong events for a small sample of the right ones, and the
events-per-covariate constraint would bind hard.

### 6.2 What the project does establish

The method validates itself through an independent route. An event rate derived
from orbital geometry reproduces published insurance loss rates. That is a
non-trivial check: nothing in the pipeline was fitted to, tuned on, or informed
by insurance data.

It also inverts the project's premise. The market's flat rate was assumed to be
too coarse, under-charging crowded orbits. Measured against observed cessation
rates it is **conservative** — every shell prices below the 8.5% midpoint. The
coverage gap may reflect price exceeding measured risk rather than inability to
measure it.

### 6.3 A note on negative results

The hypothesis was not confirmed. The analysis was nonetheless designed to be
capable of confirming it: 20.8 events per covariate clears the conventional
threshold by a factor of two, the null was attacked across sixteen
configurations, and collinearity was tested explicitly rather than assumed
away.

A null that survives that treatment is informative. The alternative — reporting
a marginal effect found in one favourable specification — would have been less
honest and less useful.

---

## 7. Limitations

| Limitation | Treatment |
|---|---|
| Element sets carry km-scale positional error | Output is a relative hazard index, not collision probability. No claim about any trajectory. |
| Catalogue covers only objects > 10 cm | Tracked density is a proxy, assuming untracked debris scales with tracked. The particle that destroyed SpainSat NG-2 was likely smaller. |
| `APOGEE`/`PERIGEE` are a snapshot, not a series | Each object's altitude treated as fixed; biases decayed objects' shell assignment downward. |
| Cessation ≠ insurable loss | Many cessations are planned retirements. Rates are an upper bound on claims. |
| Weibull time origin is first observation | Breaks absolute parametric pricing. Highest-priority fix. |
| PH violated for solar flux | Needs stratification or a flux-by-time interaction. |
| Out-of-sample concordance 0.562 | The model barely generalises. |
| 400–500 km shell has 3 satellites | Its rate is not meaningful. |
| 1500–2000 km shell has 0 events | Zero rate reflects no observed failures, not demonstrated safety. |
| Wind-down separation imperfect | 6/15 on synthetic cases; real cases separate cleanly. |
| Observational data | Association only. Popular orbits attract both debris and well-monitored satellites. |
| Per-policy premiums are proprietary | Validation at market-aggregate level only. |

---

## 8. Conclusion

This project set out to test whether orbital debris density predicts satellite
failure, and to compare the resulting risk estimate against the insurance
market's flat rate.

It built a labelling method that does not exist in the literature in this
form — deriving failure events from manoeuvre-frequency changepoints in
orbital element histories — validated it against four documented satellites
with 4/4 accuracy, and applied it to 535 satellites to produce 93 events.

The hypothesis was not supported, robustly so. The method nonetheless
validated itself by reproducing published insurance loss rates from orbital
data alone, and inverted the project's premise by showing the market's flat
rate to be conservative rather than coarse.

The most useful next step is not a better model but a better event class:
fragmentation and anomaly records, which measure the phenomenon the hypothesis
is actually about.

---

## 9. Reproducibility

All inputs are public and all intermediate artefacts are committed.

```bash
pip install -r requirements.txt

python scripts/run_real_validation.py     # 4/4 detector validation
python scripts/run_full_analysis.py       # full pipeline, real data
python scripts/sensitivity_analysis.py    # 16-configuration robustness
python scripts/envisat_case_study.py      # single-satellite deep dive
python scripts/pipeline_smoke_test.py     # synthetic end-to-end check
python -m pytest tests/ -q                # 51 tests
```

Only `scripts/validate_detector.py` requires Space-Track credentials; every
other result reproduces from committed data.

---

## 10. References

1. Space-Track.org, US Space Force — orbital element catalogue and API
   documentation.
2. NOAA Space Weather Prediction Center — observed solar cycle indices
   (F10.7).
3. McDowell, J. — General Catalog of Artificial Space Objects (GCAT),
   planet4589.org.
4. ESA Space Debris Office — Annual Space Environment Report.
5. Cox, D. R. (1972). Regression Models and Life-Tables. *Journal of the Royal
   Statistical Society, Series B*, 34(2), 187–220.
6. Schoenfeld, D. (1982). Partial Residuals for the Proportional Hazards
   Regression Model. *Biometrika*, 69(1), 239–241.
7. Harrell, F. E. et al. (1982). Evaluating the Yield of Medical Tests.
   *JAMA*, 247(18), 2543–2546. (Concordance index.)
8. Aon / Gallagher — quarterly space insurance market reports.
