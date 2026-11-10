# Pricing Orbital Risk

**A data-driven model of satellite failure hazard in low Earth orbit**

Foundations of Data Science — course project
BITS Pilani Dubai Campus

---

## The problem

Satellite insurance prices risk as a flat 5–12% of asset value, with almost no adjustment for where a satellite actually orbits. Debris density in LEO varies by more than an order of magnitude between altitude bands and has shifted sharply over the past decade.

The consequence is a market that cannot measure the risk it underwrites. Fewer than 1% of active LEO satellites carry in-orbit insurance — roughly 300 out of 10,000 — and in 2023 insurers paid $995M in claims against $557M in premiums, a loss ratio near 180%.

**This project asks whether that risk can be measured from public data alone, and how far the market's flat rate sits from what the orbital environment implies.**

---

## Approach

### Failure labels are derived, not inherited

The central methodological choice. Public failure registries cover mostly large, insured, Western spacecraft, which would bias any model trained on them and leave too few events to fit anything.

Instead, failures are detected from orbital behaviour. An operational satellite fights atmospheric drag by periodically raising its orbit, producing a sawtooth altitude trace. When control ends, the burns stop and the trace becomes monotonic decay. That transition is detectable, applies uniformly to every object, and yields far more events.

Two signals are combined, with a third for corroboration:

1. Cessation of station-keeping manoeuvres (positive jumps in semi-major axis)
2. Sustained negative altitude slope afterwards
3. A jump in the `BSTAR` drag term — a satellite that loses attitude control tumbles, changing its effective cross-section

Curated failure records then serve as the **validation set** rather than the training target.

### Survival analysis, because most satellites have not failed

Most of the population is still flying, so their failure times are unknown. Dropping them trains the model on failures only; labelling them as successes asserts something unknowable. Both are wrong, in opposite directions.

This is right-censoring, and survival analysis handles it by treating a working satellite as a partial observation: survived at least this long, unknown after that.

| Model | Role |
|---|---|
| Cox proportional hazards | Primary. Leaves the baseline hazard unspecified, since spacecraft ageing is not a shape we can responsibly assume. Supports time-varying covariates. |
| Weibull AFT | Forecasting. Cox cannot extrapolate past the study window; remaining-life estimates need a parametric survival function. |
| Logistic regression | The baseline to beat. If Cox does not beat it, the complexity is not earning its place. |

Debris density enters as a **time-varying covariate**: a satellite launched in 2012 did not experience the same orbital environment in 2024 that it did at launch.

---

## Repository layout

```
src/
  spacetrack_client.py   Rate-limited API client (30/min, 300/hr) with disk caching
  ingest.py              Stratified sampling by shell, weekly epoch decimation
  features.py            Altitude derivation, KDE debris density per shell per epoch
  failure_detection.py   Changepoint detection for end-of-life labelling
  panel.py               Counting-process panel assembly (one row per satellite-period)
  models.py              Cox, Weibull, logistic baseline, and the pricing layer

scripts/
  validate_detector.py   Runs the detector against satellites with documented outcomes

tests/
  test_detection.py      Unit tests on synthetic traces with known ground truth

docs/
  methodology.md         Method, assumptions, and limitations in detail
```

---

## Data sources

| Source | Content | Scale | Access |
|---|---|---|---|
| Space-Track.org `gp_history` | Historical orbital element sets | 138M+ records | Free account, REST API |
| CelesTrak | Catalog metadata | ~30,000 objects | Open |
| GCAT (planet4589.org) | Launch, decay, anomaly records | Full history | Open |
| ESA Space Environment Report | Debris counts by shell | Annual | Open PDF |
| NOAA SWPC | F10.7 solar flux index | Daily since 1947 | Open |
| Aon / Gallagher market reports | Market loss ratios | Quarterly | Open PDF |

The legacy `tle` and `tle_latest` API classes were deprecated and return 404 as of January 2026. This project uses `gp` and `gp_history`, which also expose `SEMIMAJOR_AXIS` and `BSTAR` directly.

---

## Setup

```bash
pip install -r requirements.txt
cp config.example.ini config.ini     # add Space-Track credentials
python scripts/validate_detector.py
```

Register for free API access at [space-track.org](https://www.space-track.org/auth/createAccount).

---

## Status

**Complete**
- API access established and verified
- Rate-limited client with disk caching
- Stratified sampling and weekly decimation
- KDE debris density estimation per shell per epoch
- Failure detection via manoeuvre-cessation changepoint
- Counting-process panel assembly
- Cox, Weibull and logistic model layer with PH assumption testing
- Unit tests on synthetic traces

**In progress**
- Detector validation against documented failures (Envisat, GOCE, with Terra and Aura as controls)
- Full population ingestion

**Remaining**
- Model fitting on the complete panel
- Bandwidth and shell-boundary sensitivity analysis
- Market-aggregate validation against published loss ratios
- Pricing comparison and written report

---

## Known limitations

Stated here rather than discovered later.

| Limitation | Handling |
|---|---|
| Element sets carry kilometre-scale positional error | Output is a relative hazard index, not a collision probability. No claim is made about any specific trajectory. |
| Failure disclosure favours large, insured spacecraft | Largely addressed by deriving labels from orbital behaviour; residual bias stated and scoped. |
| Solar activity drives drag and decay | F10.7 flux included as a covariate, so solar-cycle effects are not misattributed to debris density. |
| Objects below ~400 km decay regardless of health | Detector abstains below that altitude rather than producing false positives. |
| Starlink dominates the recent population | Stratified out and analysed separately. |
| Per-policy premium data is proprietary (Seradata) | Validation performed at market aggregate level only. |
| Most debris is untracked (catalog covers >10 cm) | Tracked density is a proxy, assuming untracked debris scales with tracked. Stated explicitly. |

---

## A note on causality

This is observational data. Popular orbits attract both debris and expensive, well-monitored satellites. Nothing here establishes that debris density *causes* failures — the claim is association, conditional on the included covariates.
