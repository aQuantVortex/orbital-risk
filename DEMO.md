# Live Demo Runbook

Everything runs in under 7 seconds. Total demo: about 20 seconds of compute,
so the time goes on explaining, not waiting.

**Setup once, before you present:**

```bash
git clone https://github.com/aQuantVortex/orbital-risk.git
cd orbital-risk
pip install -r requirements.txt
```

No credentials needed for anything below.

---

## Run order

### 1. Tests — 1 second

```bash
python -m pytest tests/ -q
```

**Output:** `29 passed`

**Say:** "29 unit tests. Most check the detector behaves correctly, but two
deliberately document where the method *breaks* — one confirms the statistic
degrades when observation noise exceeds atmospheric drag, the other confirms
that transition shape is the only thing separating a drifting satellite from
a dead one."

---

### 2. Detector validation — 1.4 seconds ← **lead with this**

```bash
python scripts/run_real_validation.py
```

**Output:** per-satellite verdicts, then

```
   name                    status                  expected  error_days  correct
Envisat             failed_abrupt             failed_abrupt        -7.0     True
  Terra maintenance_ended_gradual maintenance_ended_gradual         NaN     True
   Aura maintenance_ended_gradual                      None         NaN     True
   GOCE                   abstain                   abstain         NaN     True

Correct: 4/4
```

Also writes `data/figures/detector_validation.png`.

**Say:** "Four satellites whose outcomes are publicly documented. Envisat lost
contact on 8 April 2012 — the detector places it at 1 April, seven days early,
which is the quarter boundary and the finest resolution the method admits.
Terra is the harder test: it's still operational in 2026, but NASA stopped
funding its orbit maintenance around 2020, so on the raw signal it looks
identical to a dead satellite. It must not be labelled a failure, and it
isn't."

---

### 3. Envisat case study — 1.1 seconds

```bash
python scripts/envisat_case_study.py
```

**Output:** 29,574 element sets, manoeuvre frequency 0.244 alive vs 0.018
dead — a 13.6× separation. Writes `data/figures/envisat_case_study.png`.

**Open the figure.** Four panels: the altitude trace over 24 years, the
detection signal, a zoom on the transition quarter, and the before/after
distributions.

**Say:** "Panel 2 is the whole method in one picture. Manoeuvre frequency
sits around 0.21 for a decade, then falls off a cliff in exactly the quarter
the satellite died. The green line is Envisat's own baseline, computed from
its first eight quarters — not a global threshold, because Terra runs at 0.09
while perfectly healthy."

---

### 4. Full analysis — 3.4 seconds ← **the main result**

```bash
python scripts/run_full_analysis.py
```

**Output, in order:**
- Population: 535 satellites, verdict breakdown
- Survival panel: 12,793 rows, 264 satellites, 83 events, 20.8 events per covariate
- Cox table — all four covariates, none significant
- Concordance 0.676 fit, 0.562 test
- PH assumption violated for solar flux
- Weibull shape ρ = 2.48
- Logistic baseline, and the head-to-head: **Cox loses, 0.676 vs 0.696**
- Pricing table per shell
- Weibull calibration check, 2–7× off

**Say, when the Cox table appears:** "This is the headline and it's a null.
Debris density has a hazard ratio of 1.002 with p = 0.49. Nothing is
significant. The hypothesis this project was built to test is not supported."

**Say, at the baseline comparison:** "I report this rather than hide it. On
ranking, the simple logistic regression beats Cox. Survival analysis still
earns its place — it's what handles the 68.6% censoring and what makes a
time-varying covariate expressible — but on ranking alone the complexity
didn't pay."

**Say, at the pricing table:** "Every shell prices below the market's 8.5%
midpoint. I expected to find crowded orbits under-charged; the data says the
market is conservative. And notice the ordering doesn't track density — the
densest shell, 700–800 km at 24.1 objects per km, prices near the bottom.
That's the null showing up directly in the rates."

---

### 5. Sensitivity analysis — 5.8 seconds ← **the defence**

```bash
python scripts/sensitivity_analysis.py
```

**Output:** 16 configurations, then

```
  Hazard ratio range:         0.9976 to 1.0033
  Smallest p-value for density: 0.360
  Significant at p<0.05:      0 of 16
```

**Say:** "The obvious attack on a null is that I'd have found something with
different bins. So I tried sixteen ways — five shell binnings including ±50 km
shifts, four study windows, seven population subsets. The hazard ratio never
leaves the third decimal place and the smallest p-value anywhere is 0.360.
This is a real null, not low power."

---

### 6. Synthetic smoke test — 6.6 seconds *(only if asked about testing)*

```bash
python scripts/pipeline_smoke_test.py
```

**Say:** "Every number here is synthetic and the figure says so. It exists to
verify the chain before spending API quota — and it's where I caught two bugs
that would have produced believable but wrong results on real data."

---

## Figures to have open

| File | Shows |
|---|---|
| `data/figures/detector_validation.png` | 4/4 on documented satellites |
| `data/figures/envisat_case_study.png` | The method in four panels |
| `data/figures/real_results.png` | Density evolution, Cox coefficients, Kaplan-Meier, pricing |
| `data/figures/sensitivity_analysis.png` | 16 configurations, nothing significant |
| `data/figures/real_density_evolution.png` | Debris build-up and the solar cycle |

---

## If something goes wrong

**Import error** — `pip install -r requirements.txt`. The only non-obvious
dependency is `lifelines`.

**A figure won't open** — all scripts write to `data/figures/`; they're
committed, so the repo copies are already there even if a run fails.

**`validate_detector.py` fails** — that's the one script needing Space-Track
credentials. Use `run_real_validation.py` instead; it reproduces the same 4/4
from committed data.

**Asked to re-pull live data** — say the retrieval ran under a 30-request-per-
minute API cap and took about 50 minutes for 535 satellites, which is why the
aggregated outputs are committed. `validate_detector.py` demonstrates the live
path on four satellites if they want to see it.

---

## The closing line

> The hypothesis wasn't supported, and I tried sixteen ways to break that
> null. But the method validated itself a different way: the failure rate it
> produces, 2.59% per satellite-year, lands inside the 1–3% band of published
> insurance loss rates — and there is no insurance data anywhere in the
> pipeline. The honest finding is that the market's flat rate is conservative
> rather than coarse, which is the opposite of what I set out to show.
