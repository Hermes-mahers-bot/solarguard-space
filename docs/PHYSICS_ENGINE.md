# The physics engine

`backend/sg_soiling.py` (611 lines). Hand-written equations, no machine learning. It
takes the weather and dust forecast and answers two questions: how much output the
dust will steal, and whether cleaning today is worth the money.

## Why it exists next to the AI

The deck says "the AI predicts, the physics engine decides." That split is deliberate:

1. **A decision must be bounded and monotone.** An ML model can output a 32% loss the
   day after a wash. The engine cannot: loss starts at zero when the glass is clean,
   rises with dust, and is clamped at an observed ceiling.
2. **The money needs auditable assumptions.** The cost of a cleaning pass is a number
   the operator can see and change, not a weight inside a network.
3. **A verdict must be explainable in one sentence**, and identical for identical input.
4. If the AI is unavailable, the engine still answers from the live feed numbers.

## The chain, with the actual formulas

**1. How much dust lands in a day** — `dust_factor()`, in "effective dust-days"
(1.0 = an average day):

```
ratio     = PM10 / 120 µg/m³                      clamped 0.2 – 5.0
wind      = 0.55 + 0.075·w                        up to 8 m/s (more dust lifted)
            max(0.35, 1.15 − 0.055·(w − 8))       above 8 m/s (strong wind scours the glass)
humidity  = 0.85 + 0.006·(RH − 25)                dew cements dust onto the surface
sun       = 0.9 + 0.03·min(irradiance, 8.5)       solar load
seasonal  = Feb–May peak, secondary Oct–Nov        shamal dust season
dust_bias = east 1.25 · inland 1.05 · west 0.85 · highland 0.70
```

**2. Accumulation.** Exposure = the sum of those dust-days since the last cleaning.
Rain of 5 mm or more resets it, because that is what actually washes a panel.

**3. Soiling loss** — `loss_from_exposure()`:

```
loss% = 100 · min(0.55, lmax · (1 − e^(−exposure / tau)))
```

A saturating curve: dust costs the most in its first days on the glass, then the curve
flattens. `tau` is chosen so the instantaneous rate at exposure 0 equals the published
daily soiling rate for that climate:

| Climate | Daily rate | Ceiling `lmax` |
|---|---|---|
| east (Dammam, Jubail) | **0.80 %/day** | 0.92 |
| inland (Riyadh, Sakaka) | 0.50 %/day | 0.90 |
| west (Yanbu, Jeddah) | 0.30 %/day | 0.85 |
| highland (Abha, AlUla) | 0.18 %/day | 0.80 |

The 0.2–0.8 %/day band is the published Saudi range (IEA-PVPS 2022, KAUST). The **55 %**
ceiling comes from the Energies 2022 Saudi review, which reports 2–50 % depending on
region and more than 50 % at Dhahran after six months uncleaned. Without the ceiling the
model would happily predict a 90 %-lost array, which is not observed.

Two derived helpers: `mass_from_loss()` converts a loss into grams per m² on the glass
for display, and `marginal_loss_per_day()` gives the percentage points the *next* day
adds, which is what makes "clean now or later" a real comparison rather than a guess.

**4. Panel output** — `day_energy_kwh()`:

```
energy = capacity_kWp × irradiance (kWh/m²) × PR × (1 − soiling loss)
PR     = 0.80 × (1 + (−0.0040) × max(0, cell temp − 25 °C))     clamped 0.45 – 0.95
cell temp = air temp + peak irradiance × 0.028
```

The −0.40 %/°C coefficient is the standard crystalline-silicon temperature response.

**5. Money** — `cleaning_cost_sar()`: **1,800 SAR per MWp per pass** (0.9 SAR per kWp,
about 240 USD/MWp, the mid-range of published O&M figures), and 45 % more for wet
cleaning, which is why dry cleaning is the Saudi default. Lost energy is priced at the
tariff to give a daily `lost_sar` figure.

**6. The verdict** — `verdict()`:

```
money at risk = sum of lost_sar over the next 7 days
clean_now     = money at risk > 0.9 × cost of one pass
```

It returns the decision, an urgency score 0–100, the money at risk, the crew cost, the
**payback in days** (cost ÷ average daily risk), and a one-sentence reason. Dammam today:
0.73 % loss, about 12,030 SAR at risk this week against a 180,000 SAR crew, so **WAIT**.

## The policy optimiser

`policy()` simulates a full year at the site — real weather from the harvest, the
accumulation model above, and the economics — across **12 loss thresholds × 8 fixed
intervals**, plus never-clean and fixed-calendar baselines. It returns the trigger that
costs the least net at that site. For a 100 MWp plant in Dammam:

| Policy | Cleans a year | Mean loss | Net cost a year |
|---|---|---|---|
| never clean | 0 | 50.9 % | 16.13M SAR |
| weekly | 52 | 4.6 % | 10.78M SAR |
| every 10 days (the habit) | 36 | 6.2 % | 8.41M SAR |
| **tuned (clean at 20 % loss)** | **18** | **11.1 %** | **6.71M SAR** |

The counter-intuitive result worth saying out loud: at an east-coast site the tuned
policy **cleans less often than the industry habit and still costs less**, because the
cleaning itself is the expensive part. That is the finding, not a rounding error.

**The honest caveat the engine hands us.** It also scores the *best possible* fixed
calendar, and at Dammam that is a 21-day interval: 17 cleans, 6.73M SAR net. Our tuned
policy returns 6.71M. So against a hypothetical perfectly-tuned calendar we are ahead by
only about 18,000 SAR a year; the large saving (1.7M SAR) is against the *industry habit*
of roughly 10 days. `policy()` returns `beats_calendar` and
`saving_vs_best_calendar_sar` precisely so this is never hidden — if a site's weather
were flat enough that a fixed calendar matched us, the engine would say so.

## What the engine does not model

No inverter or SCADA data (none is public for Saudi plants). No snow, no coastal fog.
Soiling is assumed uniform across the array rather than patchy. Rain above 5 mm is
treated as a full reset. The cleaning cost is one stated constant, exposed so the
operator can move it — and the dashboard lets them.
