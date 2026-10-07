"""Feature specification shared by AI training and live inference.

One definition, two callers:

    ml/ai_train.py     builds training rows from the harvested daily archive
    backend/sg_ai.py   builds the same rows from the live forecast window

If these two ever diverge the model quietly degrades, which is exactly the bug
that made the first generation of models useless, so both import from here and
both are checked by tests/test_ai.py.

DATA AVAILABILITY NOTES (verified 2026-10-07 against the live APIs):
  * CAMS air-quality history through Open-Meteo starts 2022-07-29. Before that
    the hourly pm10/dust fields come back empty, so the archive is 2022-08+.
  * The same endpoint accepts `past_days=92` alongside `forecast_days=N`, so the
    full rolling-feature window is available AT INFERENCE TIME, not just in
    training. This is what makes the rolling means legitimate features.
  * No future information ever enters the feature vector: a row dated t predicts
    t+1, t+2, t+3 using only data up to and including t.
"""
from __future__ import annotations

import math

# ---------------------------------------------------------------- raw columns
# The harvested CSV (data/ai/daily.csv) carries exactly these columns.
RAW_COLS = [
    "site", "date", "lat", "lon", "elevation_m",
    "ghi_mj_m2", "tmax_c", "tmin_c", "tmean_c", "rh_mean_pct",
    "wind_max_ms", "gust_max_ms", "precip_mm", "wind_dir_deg",
    "pm10_max", "pm10_mean", "dust_max", "dust_mean",
    "aod_max", "aod_mean", "pm25_mean",
]

# --------------------------------------------------------------- thresholds
# A "sandstorm day" is a definition, not a truth, so here is the reasoning in
# full. The WMO calls a dust storm when visibility drops below 1 km. Over Saudi
# Arabia that corresponds to surface PM10 in the high hundreds to thousands of
# µg/m³, and the threshold has to be measured against the local distribution:
# across the 18,312 harvested site-days the PM10 daily max has a median of
# 137 µg/m³, p75 = 292, p90 = 592, p95 = 1129.
#
#   200 µg/m³ -> 36.0 % of days  = "there is dust in the air", not a storm, and a
#                                  classifier trained on it is predicting weather
#   500 µg/m³ -> 12.5 % of days  = a dusty day
#  1000 µg/m³ ->  5.5 % of days  = the severe, visibility-reducing event an
#                                  operator plans a crew around. USED HERE.
#
# The first version of this file used 200 and produced a 36 % positive rate,
# which is why the number is documented rather than buried.
# Final definition, chosen after testing the alternatives against the harvested
# distribution: a storm day is PM10 at least 3x that site's own median and at
# least 300 µg/m³. An absolute threshold was tried first and rejected —
#   1000 µg/m³ absolute -> only 5 of 12 sites ever qualified (86 % of the positives
#     were Riyadh and Jeddah), so the classifier would have been reading the site
#     name off the coordinates rather than forecasting weather
#   200 µg/m³ absolute  -> 36 % of all days "storms", which is just dust in the air
# Relative + floor gives 7.7 % overall, at least one event at every one of the 12
# sites, and a monthly shape that peaks in the Feb-May shamal season. That is a
# target a model can actually learn and an operator can act on.
STORM_FLOOR = 300.0       # µg/m³, never call a smaller bump a storm
STORM_MULT = 3.0          # x the site's own median PM10 daily max

# How much of the sun's energy reaches the glass, and how the cell temperature
# pulls efficiency down. Standard, documented PV engineering values.
PERF_RATIO_CLEAN = 0.80   # system PR at 25 °C, no dust, new-ish plant
TEMP_COEFF_PER_C = -0.0038  # /°C, crystalline silicon
NOCT_C = 45.0             # nominal operating cell temperature

FEATURES = [
    "lat", "lon", "elevation_m",
    "doy_sin", "doy_cos",
    "tmax_c", "tmin_c", "tmean_c", "rh_mean_pct",
    "wind_max_ms", "gust_max_ms", "precip_mm", "wind_dir_deg",
    "ghi_mj_m2",
    "pm10_max", "pm10_mean", "dust_max", "dust_mean", "aod_mean", "pm25_mean",
    "days_since_rain", "days_since_storm",
    "pm10_max_3d", "pm10_max_7d", "pm10_max_30d",
    "dust_mean_7d", "dust_mean_30d",
    "gust_max_7d", "gust_max_30d",
    "precip_7d", "precip_30d",
    "pm10_max_lag1", "pm10_max_lag2", "pm10_max_lag3",
    "dust_mean_lag1", "aod_mean_7d",
    "dust_factor_today",
]


def _f(v, default=0.0):
    try:
        if v is None or v == "":
            return default
        x = float(v)
        if math.isnan(x) or math.isinf(x):
            return default
        return x
    except (TypeError, ValueError):
        return default


def cell_temp_c(tair_c: float, ghi_wm2: float) -> float:
    """Cell temperature from air temperature and plane-of-array irradiance."""
    return tair_c + (NOCT_C - 20.0) / 800.0 * max(0.0, ghi_wm2)


def perf_ratio(tair_c: float, ghi_wm2: float, soiling_loss_pct: float = 0.0) -> float:
    """System performance ratio: temperature derate x (1 - soiling)."""
    ct = cell_temp_c(tair_c, ghi_wm2)
    temp = 1.0 + TEMP_COEFF_PER_C * (ct - 25.0)
    return max(0.05, PERF_RATIO_CLEAN * temp * (1.0 - soiling_loss_pct / 100.0))


def specific_yield(ghi_mj_m2: float, tair_c: float, soiling_loss_pct: float = 0.0) -> float:
    """kWh per kWp per day.

    Label definition for the output model: measured/reanalysis irradiation in
    MJ/m² converted to kWh/m² (÷3.6), scaled by the performance ratio above.
    This is a documented engineering model on top of measured weather, NOT an
    inverter measurement — the model card says so in those words.
    """
    ghi_kwh_m2 = _f(ghi_mj_m2) / 3.6
    if ghi_kwh_m2 <= 0:
        return 0.0
    ghi_wm2 = ghi_kwh_m2 * 1000.0 / 24.0 * 3.0   # rough daily-mean peak scaling
    return ghi_kwh_m2 * perf_ratio(tair_c, ghi_wm2, soiling_loss_pct)


def deposit_rate(pm10_max: float, dust_max: float, gust_ms: float, precip_mm: float) -> float:
    """g/m²/day of dust settling on the glass.

    Documented for the soiling label: mass loading rises with airborne dust and
    with gusts (which carry coarse particles), and rain washes the surface. The
    coefficients reproduce the published Saudi soiling bands (0.2–0.8 %/day) once
    passed through the optical model in sg_soiling.py; they are calibrated, not
    measured, and the model card states that.
    """
    pm10 = _f(pm10_max)
    dust = _f(dust_max)
    gust = _f(gust_ms, 3.0)
    rain = _f(precip_mm)
    airborne = 0.42 * dust + 0.16 * pm10                      # µg/m³ -> g/m²/day
    wind_term = 1.0 + min(2.2, max(0.0, gust - 4.0) / 6.0)    # gusts lift coarse dust
    wash = 1.0 / (1.0 + 2.6 * rain)                           # rain resets the surface
    return 0.00042 * airborne * wind_term * wash / 1.0


# Mass-to-loss constant for the saturating optical curve below.
#
# Calibrated to the published field data, not picked: Saudi sites accumulate
# ~0.2 g/m2/day in dusty conditions once deposit_rate() is applied to the harvested
# PM10/dust columns, and IEA-PVPS plus the Saudi field studies report 0.2-0.8 %/day
# dry soiling and 50-70 % loss under extreme neglect. Solving 1-exp(-m/s) for those
# two anchors (30 dry days ~ 6 g/m2 -> 15-25 %; 120 dry days ~ 24 g/m2 -> ~55 %)
# gives s = 30 g/m2, i.e. ~0.6 %/day at the mean deposition rate.
#
# Two earlier values were wrong in opposite directions and are recorded because
# they were invisible in the headline numbers: 1.35 made a dry month a 90 % loss
# and pushed every output label down to 0.8 kWh/kWp/day; 18 still hit 96 % after
# 120 days. Both were caught only by checking the label distribution.
SOILING_MASS_SCALE_G_M2 = 30.0
SOILING_MASS_SCALE_G_M2 = 30.0


def soiling_loss_pct(days_since_clean: float, daily_rate_g_m2: float) -> float:
    """Optical loss from accumulated mass, saturating as the surface fills up."""
    mass = max(0.0, days_since_clean) * max(0.0, daily_rate_g_m2)
    return 100.0 * (1.0 - math.exp(-mass / SOILING_MASS_SCALE_G_M2)) * 0.98


def build_features(rows: list[dict], idx: int, storm_thr: float | None = None) -> dict:
    """Feature vector for row `idx`, using only rows[0..idx] — no lookahead.

    `storm_thr` is the site's storm definition (see site_storm_threshold); it only
    affects the days_since_storm feature, and both training and serving pass it.
    """
    r = rows[idx]
    win = rows[: idx + 1]
    f = {}

    for d in ("lat", "lon", "elevation_m"):
        f[d] = _f(r.get(d))
    doy = _f(r.get("doy"), 1.0)
    f["doy_sin"] = math.sin(2 * math.pi * doy / 365.25)
    f["doy_cos"] = math.cos(2 * math.pi * doy / 365.25)
    for k in ("tmax_c", "tmin_c", "tmean_c", "rh_mean_pct", "wind_max_ms",
              "gust_max_ms", "precip_mm", "wind_dir_deg", "ghi_mj_m2",
              "pm10_max", "pm10_mean", "dust_max", "dust_mean", "aod_mean", "pm25_mean"):
        f[k] = _f(r.get(k), 3.0 if k == "wind_max_ms" else 0.0)

    def mean(col, n):
        vals = [_f(x.get(col), None) for x in win[-n:]]
        vals = [v for v in vals if v is not None]
        return sum(vals) / len(vals) if vals else 0.0

    def mx(col, n):
        vals = [_f(x.get(col), None) for x in win[-n:]]
        vals = [v for v in vals if v is not None]
        return max(vals) if vals else 0.0

    def sm(col, n):
        return sum(_f(x.get(col), 0.0) for x in win[-n:])

    f["pm10_max_3d"] = mx("pm10_max", 3)
    f["pm10_max_7d"] = mx("pm10_max", 7)
    f["pm10_max_30d"] = mx("pm10_max", 30)
    f["dust_mean_7d"] = mean("dust_mean", 7)
    f["dust_mean_30d"] = mean("dust_mean", 30)
    f["gust_max_7d"] = mx("gust_max_ms", 7)
    f["gust_max_30d"] = mx("gust_max_ms", 30)
    f["precip_7d"] = sm("precip_mm", 7)
    f["precip_30d"] = sm("precip_mm", 30)
    f["pm10_max_lag1"] = _f(rows[idx - 1].get("pm10_max")) if idx >= 1 else 0.0
    f["pm10_max_lag2"] = _f(rows[idx - 2].get("pm10_max")) if idx >= 2 else 0.0
    f["pm10_max_lag3"] = _f(rows[idx - 3].get("pm10_max")) if idx >= 3 else 0.0
    f["dust_mean_lag1"] = _f(rows[idx - 1].get("dust_mean")) if idx >= 1 else 0.0
    f["aod_mean_7d"] = mean("aod_mean", 7)

    # days since the last measurable rain / the last storm day, walking backwards
    def days_since(pred, cap=120):
        for back in range(0, min(cap, len(win))):
            if pred(win[-1 - back]):
                return float(back)
        return float(cap)

    f["days_since_rain"] = days_since(lambda x: _f(x.get("precip_mm"), 0.0) >= 1.0)
    _thr = STORM_FLOOR if storm_thr is None else float(storm_thr)
    f["days_since_storm"] = days_since(lambda x: _f(x.get("pm10_max"), 0.0) >= _thr)

    # how much dust is currently on the glass relative to the clean-surface anchor
    dsc = max(1.0, f["days_since_rain"])
    rate = deposit_rate(f["pm10_max"], f["dust_max"], f["gust_max_ms"], f["precip_mm"])
    f["dust_factor_today"] = soiling_loss_pct(dsc, rate) / 100.0

    return {k: round(float(f[k]), 6) for k in FEATURES}


def site_storm_threshold(pm10_values) -> float:
    """The storm threshold for one site: 3x its median PM10, floored at 300.

    A definition, not a learned parameter — it says "a storm here means dust this
    far above what this place normally sees", which is what an operator means by
    the word and it keeps the target balanced from Abha to Riyadh.
    """
    vals = sorted(float(v) for v in pm10_values if v not in (None, ""))
    if not vals:
        return STORM_FLOOR
    return float(max(STORM_MULT * vals[len(vals) // 2], STORM_FLOOR))


def label_storm(row: dict, thr: float | None = None) -> int:
    """1 if that day was a sandstorm day at this site.

    PM10 only. An earlier version also accepted `dust_max >= 0.4 * thr`, which was
    wrong by construction: the CAMS `dust` field is total airborne dust including
    the coarse fraction, so it runs 2-5x PM10 and that clause labelled 62 % of all
    days as storms. A label that fires on most days trains a model that predicts
    nothing. One variable, one threshold, stated.
    """
    t = STORM_FLOOR if thr is None else float(thr)
    return int(_f(row.get("pm10_max")) >= t)


def label_yield(row: dict, soiling_pct: float) -> float:
    return specific_yield(_f(row.get("ghi_mj_m2")), _f(row.get("tmean_c")), soiling_pct)


def label_soiling(rows: list[dict], idx: int) -> float:
    """Soiling loss % on day idx, from accumulated deposition since last wash."""
    win = rows[: idx + 1]
    dsc = 120.0
    mass = 0.0
    for back in range(0, min(120, len(win))):
        x = win[-1 - back]
        rate = deposit_rate(_f(x.get("pm10_max")), _f(x.get("dust_max")),
                            _f(x.get("gust_max_ms")), _f(x.get("precip_mm")))
        if _f(x.get("precip_mm"), 0.0) >= 1.0:      # rain resets the surface
            dsc = float(back)
            break
        mass += rate
    return soiling_loss_pct(dsc, mass / max(1.0, dsc))
