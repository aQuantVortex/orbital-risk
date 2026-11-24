# Code Walkthrough

Every file, what it does, and why it is written the way it is. Read this
before the viva — if you can explain each section here in your own words you
can answer anything asked about the implementation.

Total: ~2,900 lines of Python across 8 modules, 8 scripts and 51 tests.

---

## The shape of the project

```
raw orbital element sets
    │
    ├─ spacetrack_client.py ── fetches them, respecting rate limits
    ├─ ingest.py ───────────── samples and decimates
    │
    ▼
daily altitude series
    │
    ├─ failure_detection.py ── WHO FAILED AND WHEN  ← the core contribution
    │
    ▼
per-satellite verdicts
    │
    ├─ features.py ─────────── debris density per shell per quarter
    ├─ panel_summary.py ────── assembles the survival panel
    │
    ▼
counting-process panel
    │
    ├─ models.py ───────────── Cox, Weibull, logistic, pricing
    │
    ▼
hazard ratios, survival curves, premium rates
```

The intellectual weight is in `failure_detection.py`. Everything upstream
feeds it; everything downstream is standard survival analysis applied to what
it produces.

---

## src/spacetrack_client.py (~150 lines)

**Job:** talk to the Space-Track API without getting the account suspended.

### `RateLimiter`

A token-bucket limiter enforcing **both** published caps simultaneously —
30 requests/minute and 300/hour. It keeps two deques of timestamps, prunes
expired entries, and sleeps until a slot frees under whichever constraint
binds.

*Why not just `sleep(2)` between calls?* Because the per-hour cap is a
different constraint from the per-minute one. A fixed sleep that satisfies one
can violate the other over a long run.

### `SpaceTrackClient`

- `login()` — POSTs credentials once, reuses the session cookie
- `query()` — runs a query with **disk caching**, so re-runs cost no quota
- `get_satellite_history()` — full `gp_history` for one object
- `_clean()` — parses epochs, casts numeric columns

**Point worth making in a viva:** the caching is not an optimisation, it is
what makes the work reproducible. Without it every re-run would burn API
quota and the analysis could not be repeated.

---

## src/ingest.py (~110 lines)

**Job:** decide which satellites to pull and at what resolution.

### `stratified_object_sample()`

Samples a fixed number of objects per altitude shell rather than taking
catalogue order.

*Why:* catalogue order over-represents whichever constellation launched most
recently. Without stratification the population would be dominated by one
orbital regime and the shell comparison would be meaningless.

### `decimate_weekly()`

Resamples to one element set per week, taking the last in each week (the most
refined estimate for that period).

*Why it costs nothing:* orbital elements change slowly relative to the
transition being detected. This cuts volume by one to two orders of magnitude.

---

## src/features.py (~130 lines)

**Job:** turn orbital elements into modelling features.

### `altitude_from_sma()`

`altitude = a − R_earth`, with `R_earth = 6378.137 km`.

### `shell_from_altitude()`

Bins into 10 shells with edges at 200/400/500/600/700/800/900/1000/1200/1500/2000 km.

### `shell_density_kde()`

Kernel density estimation over the altitude distribution of all tracked
objects:

$$\hat f_h(a) = \frac{1}{nh}\sum_i K\!\left(\frac{a - a_i}{h}\right)$$

*Why KDE and not a histogram:* a histogram is discontinuous and its answer
depends on where you place the bin edges. That is a poor input to a
regression — the model would inherit an arbitrary choice.

*The parameter that matters:* bandwidth $h$. Bias scales as $O(h^2)$, variance
as $O(1/nh)$. Debris concentrates in narrow shells, so over-smoothing erases
exactly the structure being measured. Default is Scott's rule.

*Optional refinement:* objects can be weighted by cross-sectional area, since
a spent rocket body and a CubeSat are not equally hazardous targets.

### `build_density_panel()`

Produces density per shell per quarter across the population.

---

## src/failure_detection.py (~460 lines) ← **the core**

**Job:** decide, from an altitude trace alone, whether and when a satellite
stopped being maintained.

This is the file to know cold.

### `daily_series()`

Collapses multiple element sets per day to one **median** altitude.

*Why median not mean:* breakdown point. The median tolerates up to 50%
arbitrary corruption; the mean tolerates 0% — one bad fit moves it anywhere.
The signal involves changes of ~0.016 km while a bad fit can be off by
kilometres.

### `positive_delta_fraction()`

The central statistic. Counts the fraction of consecutive days on which
altitude rose, skipping gaps longer than 3 days.

**Be ready to derive this.** Each day:

```
Δaᵢ = −d + bᵢ + εᵢ
```

- `d ≈ 0.001 km/day` — drag, always negative, relentless
- `bᵢ` — manoeuvre: 0 most days, ~0.016 km when a burn fires
- `εᵢ` — observation noise

No burn → `Δa < 0`. Burn → `Δa > 0`. **So the sign is a burn detector**, and
counting positive days counts burns.

The key property: it does not care how *big* burns are, only that they exceed
drag. A magnitude threshold needs the scale known in advance; this does not.
That distinction is why the first implementation failed and this one works.

### `quarterly_activity()`

Aggregates daily deltas into quarterly `pos_frac`, median altitude and day
count. Quarters with fewer than 8 usable comparisons are dropped.

*Why quarterly:* long enough for the fraction to be stable, short enough to
date a transition usefully.

### `classify_activity()` — the decision logic

Deliberately separated from aggregation so it can run on an activity table
computed anywhere (see "Running detection at the source").

The rules, in order:

1. **Altitude floor.** Below 400 km, drag decay is rapid regardless of health
   and some craft use continuous low thrust → `abstain`.
2. **Minimum history.** Fewer than 16 quarters → `abstain`.
3. **Baseline.** Median `pos_frac` over the first 8 quarters.
4. **Lower guard.** Baseline < 0.04 → never station-kept → `abstain`.
5. **Upper guard.** Baseline > 0.45 → `noise_dominated` → `abstain`.
6. **Cessation search.** Earliest quarter from which `pos_frac` stays below
   35% of baseline for 4 consecutive quarters *and* stays below for >80% of
   all remaining quarters.
7. **Abruptness.** Transition length measured on a 3-quarter rolling median.
   ≤4 quarters → `failed_abrupt`; longer → `maintenance_ended_gradual`.

**Why rule 5 exists** (likely viva question): the statistic assumes drag
exceeds noise. Above ~1000 km drag is ~0.0001 km/day, below element-set noise,
so ~half of all days read positive whether the satellite is alive or dead.
Real 1960s–80s payloads in those shells returned baselines of 0.46–0.61 —
they look like vigorous station-keepers and are in fact long dead.

**Why rule 7 exists:** Terra. Operational in 2026, but NASA stopped funding
its orbit maintenance around 2020. On the frequency statistic alone it is
indistinguishable from a dead satellite. Only the *shape* of the decline
separates them — Envisat fell in 1 quarter, Terra over 8.

**Why the rolling median in rule 7:** quarterly `pos_frac` is noisy enough
that one high quarter part way down a multi-year ramp would make a wind-down
look abrupt.

### `detect_failure()`

Convenience wrapper: `daily_series` → `quarterly_activity` →
`classify_activity`.

---

## src/panel.py and src/panel_summary.py (~180 lines each)

**Job:** build the counting-process panel the survival models consume.

Two entry points for the same output:

- `panel.build_panel()` — from raw element-set histories
- `panel_summary.build_panel_from_summary()` — from per-satellite verdicts

*Why two:* classifying hundreds of satellites from raw element sets means
moving tens of millions of records to derive a few hundred summary rows. The
second path lets aggregation happen at the data source.

### The output format

One row per satellite per quarter as `(t_start, t_stop]`:

```
norad_id | t_start | t_stop | event | density | f107 | age_years | altitude_km | shell
```

*Why this format:* it is what makes **time-varying covariates** possible.
Debris density around a 2012-launched satellite is not what it was at launch.
One row per satellite would force a single frozen value and discard the
variable under study.

### Censoring rules — the substantive decision

| Verdict | Treatment | Reasoning |
|---|---|---|
| `failed_abrupt` | `event = 1` on final row | A genuine failure |
| `maintenance_ended_gradual` | **Censored** at cessation | Operational when maintenance stopped; unknown after. Counting it as failure imports the Terra error into the model |
| `active` | Censored at study end | Still maintaining |
| `abstain` | Excluded | No view formed; inventing one is worse than dropping |

### Why the window starts 2004Q4

NOAA reports F10.7 as `-1` before October 2004. Rather than impute a covariate
across 11 quarters, the modelling window is clipped. Detection baselines still
use full history.

---

## src/models.py (~420 lines)

**Job:** fit, evaluate, and convert hazard into price.

### `temporal_split()`

Train pre-2020, test post-2020. **Never random.**

*Why:* random splitting puts the same satellite's quarters on both sides →
leakage. Time splitting also matches intended use: fit on history, predict
forward.

### `fit_cox()`

Uses `CoxTimeVaryingFitter`, not `CoxPHFitter`.

*Why that matters:* the plain fitter takes one row per subject and cannot
express a covariate that changes during observation. The time-varying fitter
accepts counting-process format.

Ridge penalisation (0.1) because the event count is modest relative to
covariates. Warns when events-per-covariate falls below 10.

### `check_proportional_hazards()`

Cox's one real assumption: the hazard ratio between two satellites is
**constant over time**. Scaled Schoenfeld residuals regressed on time reveal
violations.

*Remedies if violated:* stratify on the offending covariate (each stratum gets
its own baseline), or add an explicit covariate-by-time interaction.

*In our results:* violated for solar flux, p = 0.001. Not yet remedied —
stated as a limitation.

### `fit_weibull()` and `WeibullPricer`

Parametric model for extrapolation, since Cox cannot predict past the observed
window.

Covariates are **standardised** before fitting: raw values span very different
magnitudes (altitude ~800, density ~2, age ~5), which conditions the optimiser
badly.

**Critical detail found during testing:** fit on the *full* panel, not the
temporal training split. A temporal split censors every survivor at the same
calendar instant, piling most durations onto one value; the shape parameter
then describes the split rather than how satellites age.

### `fit_logistic_baseline()`

The model to beat. Fixed one-year window, failed or not.

**Second bug found during testing:** the label must be built **per observation
row** — for each satellite-quarter, did it fail within the next 52 weeks?
Labelling on total lifetime makes every long-observed satellite a negative and
collapses the target to a single class.

### `evaluate_cox()` / `evaluate_logistic()`

Both score **concordance**: of all pairs where you know which failed first,
what fraction did the model rank correctly?

*Why both on the same metric:* Cox and logistic answer different questions
natively, so comparing their outputs is meaningless. What *is* comparable is
how well each **ranks** satellites by risk.

*What concordance measures:* discrimination, not calibration. A model can rank
perfectly while being numerically wrong about absolute probabilities — which
is exactly why the external market-rate check exists separately.

### `kaplan_meier_by_group()`

Empirical survival curves per shell, with no model interposed. These show what
the data did; the Weibull curves show what the fitted model believes.

### Pricing: `annual_failure_probability()` and `premium_rate()`

$$P(\text{fail in next year} \mid \text{survived to } t) = 1 - \frac{S(t+52)}{S(t)}$$

*Why the conditioning:* you are pricing a policy on a satellite that has
already survived to age *t*, not one at launch.

$$\text{Premium} = \mathbb{E}[\text{loss}] \times (1 + \text{loading})$$

*Why a loading:* space losses are **correlated** — one fragmentation event
damages many satellites simultaneously, so insurer variance far exceeds what
independence implies. That correlation is why capacity flees after a bad year.

---

## Scripts

| Script | What it does | Credentials? |
|---|---|---|
| `run_full_analysis.py` | Full pipeline on real data → results + figures | No |
| `run_real_validation.py` | Detector vs 4 documented satellites → 4/4 | No |
| `sensitivity_analysis.py` | 16 configurations testing robustness | No |
| `envisat_case_study.py` | Single-satellite deep dive | No |
| `pipeline_smoke_test.py` | End-to-end on synthetic data with known truth | No |
| `decode_population.py` | Decodes source-side detection results | No |
| `validate_detector.py` | Full end-to-end from the API | **Yes** |

### Why `pipeline_smoke_test.py` exists

It verifies the whole chain on synthetic satellites with known failure times
**before** spending API quota. It is also where both modelling bugs above were
caught — on real data they would have produced plausible but wrong results.

---

## The live path: one satellite, any NORAD ID

### src/celestrak.py

A small client for CelesTrak's two public endpoints: the catalogue record
(`satcat`) and the current element set (`gp`). No account needed.

- `altitude_from_mean_motion()` — CelesTrak's element sets give mean motion
  (revolutions per day), not semi-major axis. Kepler's third law converts it:
  n in rad/s, then a = (μ / n²)^(1/3) with μ = 398600.4418 km³/s², minus
  Earth's radius 6378.137 km. Tested against CelesTrak's own apogee/perigee to
  within 2 km for Envisat, Terra, the ISS and GOES 16.
- `rcs_to_mass_class()` — radar cross-section to the same SMALL / MEDIUM /
  LARGE buckets the population study used.
- Every response is cached to `data/raw/celestrak/`, so the script still runs
  with `--offline` if the network fails in class.

**Why CelesTrak alone is not enough:** it publishes only the *current* orbit.
The detector needs years of history to see station-keeping stop, so step 3
goes to Space-Track `gp_history` — the same US Space Force catalogue that
CelesTrak redistributes.

### scripts/analyse_satellite.py

Seven printed steps: catalogue → current orbit → history → detector →
cross-check → risk and price → figure and JSON.

- `load_history_file()` — the fallback when the login fails: accepts a
  Space-Track Query Builder export (CSV or JSON), upper- or lower-case columns,
  converts mean motion to semi-major axis if SMA is missing, and filters out
  any other objects in the file.
- `cross_check()` — compares the detector's verdict with CelesTrak's status
  code. They answer different questions (*is the orbit maintained* versus
  *is the spacecraft operating*), so agreement is defined by what each implies:
  `failed_abrupt` agrees with `-` (non-operational); `maintenance_ended_gradual`
  agrees with an operating code like `X` (extended mission) — the Terra case.
- `score()` — places the satellite in its shell, reads the empirical cessation
  rate for that shell from `real_pricing_comparison.csv`, loads it ×1.4 into a
  premium, compares against the 8.5% market midpoint, and computes the Cox
  relative hazard from the fitted coefficients. It refuses to price debris or
  rocket bodies, gives no comparison below 400 km, and prints a **thin data**
  warning when the shell had fewer than 10 satellites or 5 events.

Out-of-scope cases stop with a reason rather than a number: above 2,000 km
(no drag, so no signal), fewer than 16 quarters of history, no
station-keeping ever seen.

---

## tests/test_live_pipeline.py (22 tests)

Uses real CelesTrak responses captured on 24 November 2026 for deliberately
awkward objects — a failed satellite, a decayed one, a geostationary one, a
piece of debris. Checks the Kepler conversion against the catalogue, RCS
bucketing, parsing, history-file loading, and every branch of the cross-check.

---

## tests/test_detection.py (29 tests)

Three groups:

**Behaviour tests** — detector finds abrupt failures, ignores maintained
satellites, separates gradual wind-downs, abstains in each documented case.

**Calibration tests** — synthetic magnitudes pinned to *measured* values
(0.016 km burns, 0.001 km/day decay, pos_frac 0.07–0.25) rather than assumed
ones. One test exists specifically to prevent regressing to the wrong order of
magnitude.

**Limitation tests** — these *document breakdowns* rather than assert success:

- `test_breaks_when_noise_exceeds_decay` — confirms the statistic degrades
  where drag is too weak, and that the detector refuses to claim a failure it
  cannot see
- `test_cannot_distinguish_drift_from_death_without_abruptness` — confirms
  final activity levels are indistinguishable and only transition shape
  separates them

*Worth saying aloud:* tests that document failure modes are more valuable than
tests that only confirm success, because they stop a future change from
silently removing a guard.

---

## The two bugs — know these

Both were found by the synthetic smoke test, and both would have produced
believable but wrong numbers.

### 1. The Weibull was fitting the censoring boundary

A temporal split censors every surviving satellite at the same calendar
instant. Most durations piled onto one value, so the shape parameter described
*where the split was drawn* rather than how satellites age.

**Fix:** fit Weibull on the full panel; reserve the temporal split for
evaluating Cox's ranking.

### 2. The logistic baseline had a degenerate label

Labelling on total observed lifetime made every satellite observed longer than
the one-year horizon a negative. The target collapsed to a single class and
the model could not be fitted.

**Fix:** label per observation row.

---

## The three findings from real data

### 1. The threshold was wrong by ~20×

Assumed 0.3 km manoeuvres; real ones are 0.016 km/day at p99. The original
detector found zero manoeuvres across Envisat's entire operational life.

**Lesson:** an assumption that feels obviously reasonable can be off by orders
of magnitude. Only contact with real data reveals it.

### 2. Construct validity — Terra

The detector measures "is this maintained", not "is this functional". No
accuracy metric catches this, because the model is confidently right about the
wrong quantity.

### 3. The noise-dominated regime

Predicted by a limitation test, then found in real data above 1000 km. The
test existed *before* the finding, which is why the finding was recognised
rather than absorbed as signal.
