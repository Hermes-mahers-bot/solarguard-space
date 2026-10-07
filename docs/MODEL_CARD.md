# Model card — SolarGuard AI

Three models, trained here, in numpy, on a CPU, from open data. This card states
what they predict, how wrong they are, what the labels actually are, and where
they will fail. Nothing here is estimated: every number is produced by
`ml/ai_train.py` and written to `models/ai/metrics.json`.

```
python3 ml/ai_train.py          # retrains, ~16 min on 4 vCPU
python3 tests/test_ai.py        # 41 checks, incl. the train/serve divergence guard
GET /api/ai?site=dammam         # live predictions
GET /api/ai/models              # this card, machine-readable
```

## What is predicted

| Output | Question it answers | Horizon |
|---|---|---|
| `storm_t1/2/3` | Will a sandstorm come? (probability + level) | +1, +2, +3 days |
| `yield_t1` | How much will the panels make? (kWh, and kWh per kWp) | tomorrow |
| `soiling_t1` | How dirty will the glass be? (% optical loss) | tomorrow |

## Data and labels

* **17,772 samples**, 12 Saudi sites, 15 Sep 2022 – 4 Oct 2026 (CAMS dust history
  begins 29 Jul 2022, which is what sets the start).
* **Inputs (37 features)**, all from live, keyless sources and all rebuildable at
  prediction time from the last 92 days plus the forecast: meteorology and
  irradiation (ERA5/Open-Meteo), dust — PM10 daily max/mean, dust, AOD, PM2.5
  (CAMS via Open-Meteo), calendar encodings, and causal 3/7/30-day rolling
  statistics plus 1–3-day lags. **No future information enters the features**:
  a row dated *t* sees rows `[0..t]` only.
* **Splits**: train < 2025-10-01 (13,344) · validation 2025-10-01…2026-03-31
  (2,184) · **test** 2026-04-01…2026-10-07 (2,244). The threshold for each model is
  tuned on validation only; the test block is untouched.
* **Leave-one-site-out**: each site is held out entirely in turn.

### The "sandstorm" label is a definition, and it took three tries

```
a storm day  =  daily max PM10 >= max(3 x that site's own median, 300 ug/m3)
```

* Absolute ≥ 200 µg/m³ → **36 %** of all days qualified. That is "there is dust in
  the air" in Saudi Arabia, not a storm, and it trains a model that predicts nothing.
* Absolute ≥ 1000 µg/m³ → only **5 of 12 sites** ever qualified, and 86 % of the
  positives were Riyadh and Jeddah. The model would have been reading the site name
  off the coordinates.
* Relative + floor → **10.0 %** of days, at least one event at every one of the 12
  sites, peak in the Feb–May shamal season. This is the definition shipped.
* The CAMS `dust` column was also tried as a second trigger and removed: it runs
  2–5× PM10, so `dust >= 0.4 × threshold` labelled **62 %** of days as storms.

Labels for the other two outputs are **models on measured weather, not inverter
telemetry** — there is no public Saudi inverter dataset:
* `yield_t1` = measured irradiation (MJ/m² → kWh/m²) × a documented performance
  ratio (NOCT cell-temperature derate × soiling loss).
* `soiling_t1` = a deposition model over measured PM10/dust/gust/rain, accumulated
  since the last rain. **It assumes no cleaning** — rain is the only reset. It is
  therefore a different quantity from the physics engine's "loss since the
  operator's last clean", and the dashboard labels it as such.

## Measured error (test block, holed-out; n = 2,244)

**Sandstorm probability**

| Horizon | Recall | Precision | AUC | Brier | Climatology Brier | Persistence F1 | Model F1 |
|---|---|---|---|---|---|---|---|
| +1 day | 68.8 % | 75.4 % | **0.952** | **0.062** | 0.132 | 0.743 | 0.719 |
| +2 days | 60.6 % | 84.5 % | 0.929 | 0.066 | 0.132 | 0.660 | 0.706 |
| +3 days | 69.3 % | 74.0 % | 0.931 | 0.065 | 0.131 | 0.661 | 0.716 |

Honest reading: **at +1 day the "tomorrow looks like today" baseline is slightly
better on F1 (0.743 vs 0.719)** because dust episodes last several days. The model
earns its place at +2 and +3 days, where persistence decays and the model does not,
and it is far better calibrated at every horizon (Brier 0.06 vs 0.13 climatology).

**Panel output, tomorrow** (kWh per kWp per day)

| Model | MAE | R² |
|---|---|---|
| Gradient-boosted trees | 0.265 | 0.932 |
| Neural net (64-32) | 0.256 | 0.939 |
| **Blend (0.42 / 0.58 by measured skill)** | **0.234** | **0.949** |
| Baseline: yesterday's irradiation carried forward | 2.572 | — |

MAE is **7.7 % of the mean daily yield**. The baseline is 11× worse.

**Soiling loss, tomorrow** (% points): **MAE 3.17** (8.4 % of the mean), R² 0.974,
against a predict-the-mean baseline of MAE 26.1.

**Unseen sites (leave-one-site-out mean)**

| | Mean |
|---|---|
| Output MAE | 0.429 kWh/kWp (R² 0.513) |
| Soiling MAE | 9.3 points |
| Sandstorm AUC (+1 day) | 0.785 |

Per site the storm model generalises well (AUC 0.64–0.98); the regressions degrade
at the two climatological outliers — **Abha** (2,219 m highland, R² −0.18) and
**Jeddah** (soiling MAE 30.9, R² −0.68, extreme coastal dust). Reported rather than
averaged away.

## Failure modes

* **Dust episodes in a regime not in the record.** The models interpolate the
  twelve sites' experience; a new microclimate (a coastal industrial site, a
  highland plateau) can fall outside it — see Abha and Jeddah above.
* **The output label is a formula, not a meter.** It cannot capture a tracker
  fault, an inverter clipping, or a wiring loss. Predictions of *dust-driven*
  change are the trustworthy part.
* **Soiling assumes rain-only reset.** A plant that cleans on schedule will see
  far less loss than the card's number; use the physics engine for that.
* **A "storm" is a PM10 threshold.** A day can be miserable for a plant (heavy
  coarse dust) without crossing it, and vice versa.
* **CAMS is a reanalysis.** Its PM10 over the Empty Quarter is modelled, not
  measured; AERONET ground truth is available in the product to sanity-check it.

## What this replaced, and why it is written down

The first generation (`models/gbrt.npz`, `mlp.npz`, now deleted) was trained on
features — 3/7/30/90-day rolling dust means — that the serving path could not
build. Fed a short-horizon vector it silently fell back to training defaults and
returned 20–45 % soiling loss on the day *after* a clean. It was scored, shipped,
and wrong; nothing in the pipeline complained. Three things follow from that and
are kept in the code:

1. features are defined once, in `ml/ai_features.py`, and imported by both the
   trainer and the server;
2. `tests/test_ai.py` asserts that the served vector width equals the trained width
   for all five bundles, and that every prediction lands in physically sane bounds;
3. every prediction carries the error it made on held-out data, and the API refuses
   to serve without the metrics file.
