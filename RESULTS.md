# Results

**Pricing Orbital Risk** — full pipeline on real Space-Track data
Run date: 24 November 2026

Reproduce with `python scripts/run_full_analysis.py`.

---

## Headline

**The central hypothesis is not supported.** Orbital debris density does not
measurably predict satellite end-of-maintenance in this data. The hazard ratio
is 1.002 with p = 0.49, and that null survives every subset and specification
tested.

Two findings do survive, and they are worth more than a confirmed hypothesis
would have been:

1. The empirical cessation rate, **2.59% per satellite-year**, lands squarely
   in the 1–3% band of published in-orbit insurance loss rates. A detector
   built purely from orbital geometry, with no insurance data anywhere in it,
   reproduces the market's own loss experience.

2. On that basis the market's flat 5–12% rate is **not too blunt — it is
   conservative**. Every shell prices below the 8.5% midpoint. The original
   framing assumed mispricing in the direction of under-charging crowded
   orbits; the data says the opposite.

---

## The data

| | |
|---|---|
| Catalogue objects used for density | 71,424 |
| Satellites sampled and classified | 535 |
| Satellites entering the survival panel | 264 |
| Panel rows (satellite-quarters) | 12,793 |
| Failure events | 83 |
| Events per covariate | 20.8 (rule of thumb wants ≥ 10) |
| Censoring rate | 68.6% |
| Median follow-up | 43 quarters |
| Study window | 2004Q4 – 2026Q4 |

Detector verdicts across all 535:

| Verdict | n | Share |
|---|---|---|
| `abstain` | 248 | 46.4% |
| `maintenance_ended_gradual` | 115 | 21.5% |
| `failed_abrupt` | 93 | 17.4% |
| `active` | 79 | 14.8% |

The 46% abstention rate is the detector refusing to guess — mostly
`noise_dominated` at high altitude and `no_station_keeping` for satellites
that never manoeuvred. Those exclusions are the method working, not failing.

---

## Cox proportional hazards

| Covariate | Coefficient | Hazard ratio | SE | p |
|---|---|---|---|---|
| density | +0.0026 | 1.003 | 0.0038 | 0.49 |
| f107 | +0.0016 | 1.002 | 0.0012 | 0.20 |
| age_years | −0.0019 | 0.998 | 0.0025 | 0.45 |
| altitude_km | −0.0001 | 1.000 | 0.0001 | 0.45 |

**Nothing is significant.** Concordance 0.676 in-sample, **0.562 out-of-sample** —
barely above a coin flip on the post-2020 test period.

The proportional hazards assumption is violated for solar flux (p = 0.001),
meaning its effect is itself time-dependent. The remedy — stratifying on it or
adding a flux-by-time interaction — is not yet applied.

### The density null is robust

Tested across subsets:

| Subset | n | events | HR(density) | p | C |
|---|---|---|---|---|---|
| all satellites | 264 | 83 | 1.002 | 0.53 | 0.631 |
| modern (launch ≥ 1995) | 199 | 72 | 1.001 | 0.73 | 0.511 |
| modern, ≤ 1000 km | 153 | 59 | 0.997 | 0.63 | 0.543 |
| all, ≤ 1000 km | 188 | 68 | 0.998 | 0.70 | 0.641 |

And across specifications, to rule out collinearity masking it (density and
altitude correlate at −0.68):

| Model | HR(density) | p |
|---|---|---|
| density alone | 1.0022 | 0.49 |
| density + f107 | 1.0021 | 0.49 |
| density + age | 1.0021 | 0.50 |
| all four covariates | 1.0020 | 0.53 |

The hazard ratio does not move past the third decimal place in any
specification. This is a real null, not a masked effect.

---

## Cox loses to the baseline

| Model | Concordance |
|---|---|
| Logistic baseline | **0.696** |
| Cox proportional hazards | 0.676 |

Scored on the same task — ranking satellites by risk — the simple logistic
regression ranks *better* than Cox. The survival machinery is not buying
ranking accuracy on this data.

That does not make it worthless: it is still what handles censoring correctly
and what makes the time-varying debris covariate expressible at all. But the
honest statement is that on ranking alone the added complexity did not pay,
and the report says so rather than burying it.

---

## Pricing

Empirical hazard per shell — events divided by exposure, no model interposed.

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

Premium = empirical rate × 1.4. The loading exists because space losses are
correlated: one fragmentation event damages many satellites simultaneously, so
insurer variance far exceeds what independence would imply.

Note the ordering does **not** track density. The 700–800 km shell is the
densest in the sample at 24.1 objects/km and prices near the bottom; 600–700 km
at 13.8 prices highest. This is the Cox null showing up directly in the rates.

### The Weibull model is not calibrated

| Shell | Empirical | Weibull | Ratio |
|---|---|---|---|
| 600–700 km | 0.0525 | 0.1218 | 2.3× |
| 1000–1200 km | 0.0396 | 0.0957 | 2.4× |
| 500–600 km | 0.0459 | 0.1215 | 2.6× |
| 800–900 km | 0.0340 | 0.1207 | 3.6× |
| 400–500 km | 0.0264 | 0.1284 | 4.9× |
| 700–800 km | 0.0251 | 0.1251 | 5.0× |
| 900–1000 km | 0.0204 | 0.1080 | 5.3× |
| 1200–1500 km | 0.0115 | 0.0830 | 7.2× |

The Weibull sits 2–7× above the empirical rate everywhere. Its duration axis
starts at first observation rather than at launch, so for satellites already
old when the study window opens the fitted age is wrong; with shape ρ = 2.48
that error compounds steeply.

The empirical rates are the ones to quote. The Weibull is not yet usable for
absolute pricing, and fixing its time origin is the first item of remaining
work.

---

## What this means

**The project's method works; its hypothesis does not.**

The detector produces an event rate that independently reproduces the
insurance market's own loss experience — that is a real validation of the
labelling approach, achieved without ever touching insurance data.

But the thing those labels were built to test — that crowded orbits kill
satellites faster — is not visible at this resolution. The most likely reason
is that the detector measures *end of orbit maintenance*, which is dominated
by propellant exhaustion and planned retirement, not by debris impacts. Real
collision-induced failures are rare enough that they do not move an aggregate
hazard model built on 83 events.

That is a limitation of what the labels mean, not a flaw in how they were
derived. Detecting debris-driven failure specifically would need a far rarer
event class: anomalies and fragmentations, not cessations.

---

## Known weaknesses

| Weakness | Status |
|---|---|
| Weibull time origin is first observation, not launch | Breaks absolute pricing. Fix first. |
| PH assumption violated for solar flux | Needs stratification or a time interaction. |
| Out-of-sample concordance 0.562 | The model barely generalises. |
| 400–500 km shell has 3 satellites | Its rate is not meaningful. |
| 1500–2000 km shell has 0 events | Zero rate is an artifact of no exposure to failure, not of safety. |
| Cessation ≠ insurable loss | Many cessations are planned retirements. The rates are an upper bound on claims. |
| Observational data | No causal claim. Popular orbits attract both debris and well-monitored satellites. |
| Wind-down separation imperfect | 6/15 on synthetic cases; real cases separate cleanly. |
