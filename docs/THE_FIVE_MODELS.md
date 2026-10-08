# The five models, one by one

For each model: what it is for, what it was trained on, and how it was built. Numbers
are from `models/ai/metrics.json`; the per-model input rankings come from the trees
themselves (`tests/feature_use.py`).

---

## What all five share

**Training data.** 18,348 harvested site-days across 12 Saudi sites (Aug 2022 to Oct
2026), which become 17,772 usable samples once the history windows are built.

**The 37 inputs.** Every model reads the same 37 numbers per site per day:

* where: latitude, longitude, elevation
* when: day-of-year as a sine and a cosine
* today's weather: max, min and mean temperature, humidity, max wind, max gust,
  rain, wind direction, sun energy
* today's dust: PM10 max and mean, dust max and mean, aerosol optical depth, PM2.5
* how long since: days since it rained, days since the last storm day
* history windows: PM10 max over 3, 7 and 30 days; dust mean over 7 and 30 days;
  gust max over 7 and 30 days; rain over 7 and 30 days; aerosol over 7 days
* lags: PM10 max 1, 2 and 3 days ago; dust mean yesterday
* already on the glass: an estimate of how much sunlight the current dirt blocks

**The rule.** A row dated today may only see days up to today. Every label is about
tomorrow or later.

**The split.** Train on everything before 1 Oct 2025 (13,344 samples), tune on Oct
2025 to Mar 2026 (2,184), then test on Apr to Oct 2026 (2,244) which we never looked
at. Plus leave-one-site-out: hide a whole site, train on the other 11, score on the
hidden one.

**The two model families, identical in all five.** We train each model twice, then
blend:
* **Gradient-boosted trees**, written from scratch in numpy. Histogram binning with 32
  buckets, depth 3 or 4, at least 25 samples per leaf, 85% of rows and 75% of features
  sampled per tree, L2 penalty 1.0, learning rate 0.05 to 0.07, 280 to 320 trees.
* **A neural network**, 37 inputs to 64 to 32 to 1 output, ReLU, Adam at learning rate
  0.003 for 120 passes, batches of 128. Its inputs are z-scored with statistics stored
  in the bundle.
* **The blend** uses inverse-error weights fitted on the last 15% of the training
  block, so the pair can never be worse than the weaker of the two.

**One honest note that applies to all five:** the trees lean heavily on one input,
`dust_factor_today`, which is the estimate of how much dust is already on the glass.
It takes about 54% of all splits in every model. This is physically sensible, because
dust is autocorrelated from one day to the next, and it is also exactly why the naive
"tomorrow looks like today" rule is strong at one day ahead. Everything else the
models use is the slower signal around it: how long since the last storm, wind
direction (a north-easterly is a shamal), seven-day gusts, humidity, season, days
since rain, and the 30-day dust average.

---

## 1. `storm_t1` — will a sandstorm arrive tomorrow?

**Purpose.** Warn the operator a day ahead, so a crew can be booked *before* the dust
lands rather than after. This is the difference between protecting generation and
explaining it.

**Trained on.** The 37 inputs, with a binary target: tomorrow's daily maximum PM10 is
at least **3 times that site's own median PM10**, and never below **300 µg/m³**. That
labels 10.0% of days as storms. Top inputs by use: `dust_factor_today` (54.5%),
`days_since_storm` (2.7%), `wind_dir_deg` (2.5%), `gust_max_7d` (1.9%),
`rh_mean_pct` (1.9%), `doy_cos` (1.8%).

**Methods.** Logistic-loss gradient boosting (320 trees, depth 3, learning rate 0.07,
min 25 per leaf) blended 27% with the neural network (73%). Because only 10% of days
are positive, the imbalance is handled by **tuning the decision threshold** on the
validation block to maximise F1 rather than by weighting the classes; the chosen
threshold is 0.373 and is stored in the bundle.

**Measured.** Recall 69%, precision 75%, **AUC 0.952**, Brier 0.062 against 0.132 for
always guessing the normal rate. The persistence baseline scores F1 0.743 against our
0.719 at this horizon, which we state rather than hide.

---

## 2. `storm_t2` — the same question, two days ahead

**Purpose.** The scheduling horizon. Cleaning takes about a day of mobilisation, so
"tomorrow" can be too late; two days is when a crew can actually be committed.

**Trained on.** The same 37 inputs, the same storm definition, targeting the day after
tomorrow. Top inputs: `dust_factor_today` (54.1%), `doy_cos` (2.6%),
`days_since_storm` (2.5%), `doy_sin` (2.2%), `wind_dir_deg` (2.0%),
`gust_max_7d` (1.9%), `aod_mean_7d` (1.9%).

**Methods.** Identical pipeline: 320-tree logistic GBRT blended 27% with the neural
network at 73%, threshold 0.510.

**Measured.** Recall 61%, precision 85%, **AUC 0.929**, Brier 0.066. Here the model
**beats** the persistence baseline: F1 0.706 against 0.660.

---

## 3. `storm_t3` — three days ahead

**Purpose.** The planning horizon: for a multi-site fleet, this is what makes it
possible to route one crew across several plants in a week.

**Trained on.** Same 37 inputs, same definition, three days out. Top inputs:
`dust_factor_today` (54.1%), `doy_cos` (3.1%), `days_since_storm` (2.3%),
`wind_max_ms` (2.3%), `doy_sin` (2.1%), `rh_mean_pct` (1.9%), `gust_max_7d` (1.7%).

**Methods.** Same again: 320 trees depth 3 blended 26% with the network at 74%,
threshold 0.385.

**Measured.** Recall 69%, precision 74%, **AUC 0.931**, Brier 0.065. Beats
persistence: F1 0.716 against 0.661.

---

## 4. `yield_t1` — how much will the panels make tomorrow?

**Purpose.** This is the model that turns dust into money. It produces the kWh figure
the operator already cares about, and it is the denominator for the whole cleaning
decision: what the dirt costs, versus what a crew costs.

**Trained on.** The 37 inputs, with a continuous target: tomorrow's specific yield in
kWh per kWp per day, computed as the measured sun energy in kWh per m² multiplied by a
documented performance ratio (0.80 base, minus 0.38% per degree the cell runs above
25 °C, minus the soiling loss). Cell temperature is estimated from air temperature and
irradiance. Said plainly: **the target is a formula fed with measured weather, not a
meter reading** — no public Saudi inverter data exists, and we say so rather than imply
otherwise. Top inputs: `dust_factor_today` (53.9%), `days_since_rain` (3.7%),
`ghi_mj_m2` (3.4%), `doy_cos` (3.3%), `dust_mean_30d` (3.1%), `doy_sin` (2.9%),
`days_since_storm` (2.3%).

**Methods.** Squared-error gradient boosting (300 trees, depth 4, learning rate 0.05,
min 25 per leaf) blended 42% with the neural network (58%).

**Measured.** Trees alone: MAE 0.265, R² 0.932. Network alone: 0.256, R² 0.939.
**Ensemble: MAE 0.234 kWh/kWp, which is 7.7% of the average day, RMSE 0.336, R²
0.949** — against a naive baseline of 2.572, so 11 times better. On a site it has
never seen: MAE 0.429 (R² 0.513), best at NEOM 0.202, worst at Jeddah 1.182.

---

## 5. `soiling_t1` — how dirty will the glass be tomorrow?

**Purpose.** The core physical number: the share of tomorrow's output the dust will
steal. It feeds the clean-or-wait verdict, the water saving, and the warning that dust
left on glass hardens into cement.

**Trained on.** The 37 inputs, with a continuous target in percent optical loss:
100 × (1 − e^(−mass ÷ 30)) × 0.98, where mass is how many grams of dust per m² have
landed since the last rain, and the daily landing rate is a function of dust, PM10,
gust and rain. The 30 is calibrated so a dry month equals 10 to 35% loss and a dry day
equals 0.2 to 0.8% per day, which is the published Saudi range. Top inputs:
`dust_factor_today` (55.2%), `days_since_rain` (5.1%), `dust_mean_30d` (4.5%),
`days_since_storm` (2.8%), `doy_cos` (2.4%), `pm10_max_30d` (2.2%), `doy_sin` (2.1%).

**Methods.** Squared-error gradient boosting (280 trees, depth 4, learning rate 0.05)
blended 40% with the neural network (60%).

**Measured.** **Ensemble MAE 3.17 percentage points, 8.4% of the mean, R² 0.974**,
against a baseline of 26.108 for predicting the average. On a site never seen: MAE
9.3, best at NEOM 2.5, worst at Jeddah 30.9.

---

## What none of the five can see

No inverter data, no SCADA, no sensors on the panels, no photographs of the glass.
Only satellite, weather and dust feeds, plus the physics in the label definitions. Two
of the three targets are therefore *documented formulas applied to measured weather*,
and the storm target is a *measured threshold*, not a human annotation. That is the
honest boundary of what we built, and it is written on the model card.
