# Viva Preparation

Questions you are likely to be asked, grouped by assessment component, with
answers. Where a question is a trap, that is flagged.

**The single most important rule:** the hypothesis was not confirmed. Do not
present it as confirmed. The result is the null plus two surviving findings,
and that is a stronger position than a marginal effect would have been — but
only if you own it rather than get caught.

---

## The 60-second summary

> Satellite insurance prices risk as a flat 5–12% of asset value, almost
> regardless of orbit, while debris density varies by more than an order of
> magnitude across altitude shells. I tested whether that environment predicts
> failure, using only public data.
>
> The hard part was labels — there is no usable list of satellite failures. So
> I derived them from orbital behaviour: a working satellite raises its orbit
> against drag, a dead one stops, and that transition is detectable. I
> validated the detector against four satellites with documented outcomes and
> got all four right, dating Envisat's 2012 failure to within seven days.
>
> Applied to 535 satellites it gave 93 failure events. I fitted a Cox
> proportional hazards model with time-varying covariates.
>
> The hypothesis failed. Debris density does not predict failure — hazard
> ratio 1.002, p = 0.49, and that null survives all sixteen configurations I
> tested. But two things did survive: the detector's empirical failure rate,
> 2.59% per satellite-year, lands inside the 1–3% band of published insurance
> loss rates despite no insurance data being in the pipeline. And on that
> basis the market's flat rate is conservative, not coarse — every shell
> prices below the midpoint, which is the opposite of what I expected to find.

---

## Component 1 — Technical Implementation

**Q: Walk me through your pipeline.**

Six stages. Ingest from Space-Track under a 30-request-per-minute cap, using
stratified sampling by altitude shell. Clean by collapsing to daily medians.
Engineer features — altitude from semi-major axis, debris density per shell
per quarter via kernel density estimation. Detect failures as changepoints in
manoeuvre frequency. Assemble a counting-process panel. Fit Cox, Weibull and a
logistic baseline, then convert hazard into premium.

**Q: Why median rather than mean for the daily collapse?**

Breakdown point. The median tolerates up to 50% arbitrary corruption before
failing; the mean tolerates zero — a single bad orbit fit moves it anywhere.
My signal involves altitude changes of about 0.016 km, and a bad fit can be
off by kilometres. The cost is efficiency: the median's variance is about 1.57×
the mean's on clean normal data. That trade is clearly right here.

**Q: Why KDE instead of a histogram for density?**

A histogram is discontinuous and its answer depends on where you place the bin
edges. Feeding that into a regression means the model inherits an arbitrary
choice. KDE gives a smooth estimate. The parameter that matters is bandwidth —
bias goes as *h*², variance as 1/*nh* — and I tested sensitivity to it.

**Q: Why `CoxTimeVaryingFitter` rather than `CoxPHFitter`?**

The plain fitter takes one row per subject and cannot express a covariate that
changes during observation. Debris density around a satellite launched in 2012
is not what it was at launch — that change is the variable I am studying.
Freezing it to one value discards the thing under test. The time-varying
fitter accepts counting-process format, one row per satellite per quarter.

**Q: How did you test this?**

29 unit tests. Behaviour tests on synthetic traces with known failure times;
calibration tests pinning synthetic magnitudes to values measured from real
data; and two tests that deliberately *document breakdowns* rather than assert
success — one confirms the statistic degrades when noise exceeds drag, another
confirms that abruptness is the only thing separating a drifting satellite
from a dead one.

**Q: Did you find any bugs?**

Two, both caught by a synthetic smoke test before touching real data, and both
would have produced believable but wrong numbers.

The Weibull was fitting the censoring boundary — a temporal split censors
every survivor at the same instant, so most durations piled onto one value and
the shape parameter described the split rather than satellite ageing. Fixed by
fitting on the full panel.

The logistic baseline had a degenerate label — labelling on total lifetime
made every long-observed satellite a negative, collapsing the target to one
class. Fixed by labelling per observation row.

---

## Component 2 — Results and Analysis

**Q: What did you find?**

The central hypothesis was not supported. Debris density does not measurably
predict end-of-maintenance: hazard ratio 1.002, p = 0.49. No covariate reached
significance. In-sample concordance was 0.676 and out-of-sample 0.562 — barely
above chance.

**Q: How confident are you that this is a real null and not just low power?**

Three reasons.

First, power: 83 events for 4 covariates is 20.8 events per covariate, double
the conventional rule of thumb of 10.

Second, robustness: I ran sixteen configurations varying shell boundaries
(coarse, fine, shifted ±50 km), study window start, and population subsets.
The hazard ratio ranged 0.9976 to 1.0033, and the smallest p-value for density
in any configuration was 0.360. Nothing approached significance.

Third, collinearity: density and altitude correlate at −0.68, so I tested
density alone, with each other covariate, and in the full model. The hazard
ratio does not move past the third decimal place in any specification. It is
not a masked effect.

**Q: So why did the hypothesis fail?**

Most likely because the detector measures *end of orbit maintenance*, which is
dominated by propellant exhaustion and planned retirement, not debris impacts.
Destructive collisions are rare enough — a handful across decades — that they
do not move an aggregate hazard model built on 83 events.

That is a limitation of what my labels mean, not of how they were derived. The
labels faithfully capture maintenance cessation; maintenance cessation simply
is not primarily a debris phenomenon.

**Q: Then what, if anything, did the project establish?**

Two things.

The method validated itself independently. The empirical cessation rate is
2.59% per satellite-year; published in-orbit insurance loss rates are 1–3%.
A detector built entirely from orbital geometry reproduces the market's own
loss experience, with no insurance data anywhere in the pipeline.

And it inverted the premise. I assumed the market's flat rate under-charged
crowded orbits. Measured against observed rates it is *conservative* — every
shell prices below the 8.5% midpoint.

**Q: Your Cox model lost to a logistic regression. Doesn't that undermine the
whole approach?**

It undermines the claim that Cox improves *ranking*, which is why I report it
rather than hide it — 0.676 against 0.696 on the same metric.

It does not undermine using survival analysis. Cox is what handles censoring
correctly — 68.6% of my satellites never failed — and what makes a
time-varying covariate expressible at all. Logistic regression cannot do
either; it throws away timing and handles partial follow-up badly. The honest
statement is that on ranking alone the complexity did not pay here.

**Q: Your Weibull numbers are 2–7× the empirical rates. Explain.**

That is a calibration failure and I excluded the Weibull from the headline
pricing because of it. The cause is the duration axis: it starts at first
observation rather than at launch, so for satellites already old when my
window opens the fitted age is wrong. With shape ρ = 2.48 that error compounds
steeply. Fixing the time origin is the first item of remaining work. The
quoted rates are model-free — events divided by exposure.

**Q: One of your shells shows a 0% failure rate. Is it safe?**

No — that is 1500–2000 km with 22 satellites, 434 exposure-years and zero
observed events. Zero observed failures is not demonstrated safety, it is an
absence of evidence. With that exposure the upper confidence bound on the
true rate is still appreciable. I flag it as not meaningful, the same as the
400–500 km shell which has only 3 satellites.

**Q: Does debris density *cause* failures?**

No causal claim. This is observational data and popular orbits attract both
debris and expensive, well-monitored satellites. Everything here is
association, conditional on the covariates included.

---

## Component 3 — Report and Documentation

**Q: What is the contribution here?**

Not the model — Cox regression is standard. The contribution is the
construction of labels where none existed in usable form, and validating that
construction against independent ground truth.

**Q: Why not just use published failure lists?**

Two reasons. They cover predominantly large, insured, Western spacecraft, so a
model trained on them learns the disclosure process as much as the physics.
And they yield too few events — survival models are limited by event count,
not row count, and the rule of thumb wants ten events per covariate.

My method produced 93 events on a uniform definition that does not depend on
anyone choosing to disclose.

**Q: How did you validate the detector?**

Four satellites with publicly documented circumstances. Envisat — abrupt
contact loss, 8 April 2012 — detected as `failed_abrupt`, dated to 1 April,
seven days early, which is the quarter boundary and the finest resolution a
quarterly series admits. Terra and Aura — both operational but with
maintenance ended — correctly classified as gradual wind-downs, not failures.
GOCE — at 255 km with continuous ion thrust — correctly abstained.

4 of 4.

**Q: Terra is the interesting one. Why?**

Because it is the harder test. Terra is operational in 2026 but NASA stopped
funding its orbit maintenance around 2020, so on the frequency statistic alone
it looks exactly like a dead satellite. That is a construct validity problem —
I was measuring "is this maintained", not "is this functional", and no accuracy
metric detects that because the model is confidently right about the wrong
quantity.

The fix was abruptness. Envisat declined over 1 quarter, Terra over 8. A
failure is a step; a planned shutdown is a ramp.

---

## Component 4 — Presentation and Viva

### Concepts you must be able to explain without notes

**Right censoring.** Most satellites have not failed, so their failure time is
unknown — you only know they lasted at least this long. Dropping them trains
only on failures; calling them survivors asserts something unknowable.
Survival analysis treats them as partial observations.

**Hazard rate.** The instantaneous failure rate *given survival to this point*.
That conditioning is what makes censored data usable.

**Cox model.** Risk = baseline curve × per-satellite multiplier. The baseline
is left unspecified, which matters because spacecraft ageing is a bathtub shape
nobody can responsibly assume. Estimation is by partial likelihood, where the
baseline cancels between numerator and denominator.

**Partial likelihood, in words.** At each failure, ask: given that exactly one
satellite failed at this instant, what is the probability it was this one
rather than any other still at risk? The baseline appears in every term and
cancels. Censored satellites live in the denominator — they record who else
was exposed and did not fail.

**Proportional hazards assumption.** The hazard ratio between two satellites
is constant over time. Tested with scaled Schoenfeld residuals. Violated for
solar flux in my results (p = 0.001); remedies are stratification or a
covariate-by-time interaction.

**Concordance index.** Of all pairs where you know which failed first, the
fraction the model ranked correctly. 0.5 is a coin flip. Measures
discrimination, not calibration — a model can rank perfectly while being
numerically wrong about absolute probabilities.

### Derive this on a whiteboard if asked

Why frequency beats magnitude:

```
Δaᵢ = −d + bᵢ + εᵢ

d ≈ 0.001 km/day   drag, always negative
bᵢ ≈ 0.016 km      manoeuvre, zero on most days
εᵢ                 noise
```

No burn → negative. Burn → positive. The **sign** is a burn detector, so
counting positive days counts burns. It needs burns to exceed drag, not to
exceed a threshold you guessed in advance. My first detector used a 0.3 km
magnitude threshold — twenty times too large — and found zero manoeuvres
across Envisat's entire operational life.

### Likely traps

**"So your project failed?"**
No. The hypothesis was not supported; the method was validated. I built a
labelling technique that reproduces published insurance loss rates from
orbital data alone, and I established that the market's pricing is
conservative rather than coarse. A null that survives sixteen robustness
configurations is a result.

**"Couldn't you have gotten a significant result with different bins?"**
I tested that explicitly — five binning schemes including ±50 km shifts, four
study windows, seven population subsets. Sixteen configurations, zero
significant. The smallest p-value anywhere was 0.360.

**"Why should I believe your labels are right at all?"**
Two independent checks. Four documented satellites, 4/4 correct, with Envisat
dated to within seven days. And the aggregate event rate reproduces published
insurance loss rates without any insurance data in the pipeline.

**"What would you do differently?"**
Use a rarer but more appropriate event class — fragmentation and anomaly
records rather than maintenance cessations. That measures the phenomenon the
hypothesis is actually about. The trade is a much smaller sample, and the
events-per-covariate constraint would bind hard.

**"Show me the code that produced those 93 events."**
`src/failure_detection.py` holds the rules. For the population run the
retrieval and classification executed at the data source under the API's
rate limit, in an implementation mirroring that module, and what came back
was one summary row per satellite — that is `real_population_summary.csv`,
decoded by `scripts/decode_population.py`.

Everything downstream of that file is the committed Python on committed data
and reproduces from a clean clone. And the Python detector is verified
independently, not assumed equivalent: `run_real_validation.py` runs
`classify_activity` on the real quarterly series for four documented
satellites and reproduces 4/4, Envisat to within seven days.

If you want the whole chain run locally, `validate_detector.py` does that
from the API with credentials — it is slower, which is exactly why the split
exists.

**"Did you use AI to build this?"**
Answer honestly, however you did it. What you must be able to do is explain
every design decision in this document — why median not mean, why frequency
not magnitude, why Terra forced the abruptness test, why the Weibull is
excluded from pricing. That is what the viva tests.

---

## Numbers to have memorised

| Quantity | Value |
|---|---|
| Satellites classified | 535 |
| In the survival panel | 264 |
| Failure events | 83 |
| Events per covariate | 20.8 |
| Censoring rate | 68.6% |
| Hazard ratio, density | 1.002 (p = 0.49) |
| Concordance, in / out of sample | 0.676 / 0.562 |
| Concordance, logistic baseline | 0.696 |
| Sensitivity configurations | 16, none significant |
| Smallest p-value for density anywhere | 0.360 |
| Empirical cessation rate | 2.59% per satellite-year |
| Published insurance loss rates | 1–3% per year |
| Market flat rate | 5–12%, midpoint 8.5% |
| Envisat pos_frac before / after failure | 0.251 / 0.018 |
| Envisat detection error | −7 days |
| Detector validation | 4/4 |
| Unit tests | 29 |
| Real manoeuvre magnitude | 0.016 km/day at p99 |
| Original (wrong) threshold | 0.3 km — 20× too large |
