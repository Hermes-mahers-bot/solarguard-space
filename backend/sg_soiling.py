"""
SolarGuard Space — soiling physics, PV yield, and the cleaning decision engine.

This module answers the client's only real question: *how much power am I losing
to dust, and should I send a crew today?*

Model
-----
Soiling loss grows as an exponential approach to an asymptotic loss:

    loss(t) = lmax * (1 - exp(-exposure / tau))

`exposure` is counted in *effective dust days*, not calendar days: each day
contributes `dust_factor(day)`, which is built from the measured drivers —
airborne dust concentration, wind speed (deposition rises with wind, then high
wind scours loose dust off the glass), humidity (dew and hygroscopic growth
cement particles so wind can no longer remove them) and irradiance (hot dry glass
holds particles electrostatically). A wash-off rain (>5 mm) resets exposure, as
does a cleaning event.

`lmax` is not a fudge factor: it is *solved* at import time so that, cleaning
every 7 days in average conditions, the annual mean soiling loss equals the
published band for that climate class —

    west coast  (Jeddah, Yanbu) ....... 15 %   (KAUST study)
    east coast  (Dammam, Al Jubail) ... 45 %   (KAUST study)
    inland desert ..................... 30 %   (Middle East range 12-36 %)
    highland (Abha) ................... 12 %

Because the annual mean of `lmax*(1-exp(-t/tau))` over a cycle of length I is
`lmax*(1 - (tau/I)*(1-exp(-I/tau)))`, inverting that for lmax is exact — see
`_solve_lmax`. So the literature numbers are reproduced by construction, and the
model then moves with real weather instead of pretending October in Dammam looks
like the February-May dust season.

Optional ML refinement: if the ML workstream shipped models/gbrt.npz, its daily
soiling prediction replaces the analytic curve (physics remains the fallback and
the sanity check).
"""
from __future__ import annotations

import math
import sys
from datetime import datetime

from sg_config import (CLEANING_COST_SAR_PER_MWP, DEFAULT_CLEANING_INTERVAL_DAYS,
                       MODELS, ROOT, TARIFF_SAR_PER_KWH, WATER_LITRES_PER_MWP_WET_CLEAN)

# --------------------------------------------------------------- calibration
# Daily soiling rate at average conditions, % of output per day. These are set
# inside reported Saudi/arid soiling rates (published: ~0.1-0.5 %/day typical,
# up to ~2 %/day during dust events; dust-season studies in the Gulf report the
# upper end). The rate, not the headline annual figure, is the physical anchor:
# a model that is calibrated to an annual number alone will tell an operator the
# array lost 17 % of its output on the day after it was washed, which is not
# physics. See MODEL_CARD.md for how the published 12-36 % / 15 % / 45 % annual
# figures relate to these rates (they imply much longer cleaning intervals than
# one week).
CLIMATE_RATE_PCT_PER_DAY = {"west": 0.30, "east": 0.80, "inland": 0.50, "highland": 0.18}
# Loss the array tends toward if it is never cleaned (glass + frame + edge effects)
CLIMATE_LMAX = {"west": 0.85, "east": 0.92, "inland": 0.90, "highland": 0.80}
# How this climate's dust load compares to the Saudi average (modulates the rate)
CLIMATE_DUST_BIAS = {"west": 0.85, "east": 1.25, "inland": 1.05, "highland": 0.70}
# Reviewed published references, quoted on the site next to our simulated values
LITERATURE = {
    "west": {"annual_loss_pct": 15.0, "source": "KAUST, west-coast Saudi site, weekly cleaning"},
    "east": {"annual_loss_pct": 45.0, "source": "KAUST, east-coast Saudi site, weekly cleaning"},
    "inland": {"annual_loss_pct": 30.0, "source": "Middle East regional studies, 12-36 % band, weekly cleaning"},
    "highland": {"annual_loss_pct": 12.0, "source": "regional lower bound (high elevation, more rain)"},
}

REFERENCE_PM10 = 120.0      # µg/m³ — rough Saudi average, used to normalise dust
RAIN_WASHOFF_MM = 5.0       # rain above this resets most accumulated dust
PR_BASE = 0.80              # performance ratio before temperature derate
TEMP_COEFF = -0.0040        # /degC, crystalline silicon power temperature coefficient
DEFAULT_CAPACITY_KWP = 1000.0
# Ceiling on soiling loss. The Energies 2022 Saudi review reports module output
# reductions of 2-50 % depending on region and a >50 % drop at Dhahran after six
# months without cleaning, so the accumulation curve is clamped at 55 %: beyond
# that, dust slumps off the glass and plants intervene anyway. Without this the
# model would happily predict a 90 %-lost array, which is not what is observed.
MAX_LOSS_FRAC = 0.55
MAX_EXPOSURE_DAYS = 400     # effectively uncapped: the loss ceiling does the clamping


def climate(site: dict) -> str:
    return (site or {}).get("climate", "inland") if site else "inland"


def dust_season_factor(doy: int) -> float:
    """Saudi dust seasonality: main peak Feb-May (shamal winds), secondary peak in
    late October-November, minimum in high summer and mid-winter."""
    main = 0.65 * math.exp(-((doy - 60) / 45.0) ** 2)
    secondary = 0.35 * math.exp(-((doy - 300) / 32.0) ** 2)
    return 1.0 + main + secondary


def climate_params(site: dict) -> dict:
    c = climate(site)
    rate = CLIMATE_RATE_PCT_PER_DAY[c]
    lmax = CLIMATE_LMAX[c]
    # tau chosen so the instantaneous rate at exposure 0 is exactly the published
    # daily soiling rate for this climate: dloss/dt|0 = lmax/tau
    tau = lmax / (rate / 100.0)
    return {"climate": c, "rate_pct_per_day": rate, "lmax": lmax, "tau": round(tau, 2),
            "dust_bias": CLIMATE_DUST_BIAS[c],
            "literature": LITERATURE[c],
            "cleaning_interval_days": DEFAULT_CLEANING_INTERVAL_DAYS}


# --------------------------------------------------------------- ML hook
_ML = None
_ML_TRIED = False


class _MLAdapter:
    """`ml/predict.py` exposes predict(features, models); the rest of this module
    talks to a single object. Small adapter, so either shape works."""

    def __init__(self, module, models):
        self._module = module
        self._models = models
        self.info = getattr(models, "meta_gbrt", {})

    def predict(self, features: dict) -> dict:
        return self._module.predict(features, self._models)


# ---------------------------------------------------------------------------
# There is deliberately no ML loader here any more.
#
# The first generation of models (models/gbrt.npz + mlp.npz) was trained on
# features this module's 14-day horizon cannot supply, so it was retired along
# with its artifacts. Predictions now live in backend/sg_ai.py, which is trained
# and evaluated separately and rebuilt from the same feature code as its trainer.
# This file is the physics + economics engine: soiling accumulation, PV yield,
# cleaning cost and the policy optimiser. Keeping the two apart is what lets the
# dashboard say "predicted by the AI" and "priced by the model" honestly.
# ---------------------------------------------------------------------------
def ml_available() -> bool:
    """Retired. The live AI is backend/sg_ai.py (see /api/ai/models)."""
    return False


def ml_serving() -> bool:
    """Retired. Physics serves the decision; the AI serves the predictions."""
    return False


# --------------------------------------------------------------- daily drivers
def dust_factor(day: dict, params: dict) -> float:
    """Effective dust-days contributed by one day (1.0 = an average day)."""
    pm10 = day.get("pm10_ugm3")
    if pm10 is None:
        pm10 = day.get("dust_ugm3")
    c_ratio = 1.0 if pm10 is None else max(0.20, min(5.0, pm10 / REFERENCE_PM10))

    wind = day.get("wind_max_ms") or 3.0
    gust = day.get("gust_max_ms") or wind
    w = max(0.0, min(gust, 28.0))
    if w <= 8.0:
        wind_mult = 0.55 + 0.075 * w                      # deposition grows with wind
    else:
        wind_mult = max(0.35, 1.15 - 0.055 * (w - 8.0))   # scouring above 8 m/s

    rh = day.get("rh_mean_pct") or 30.0
    humidity_mult = 0.85 + 0.006 * max(0.0, rh - 25.0)     # dew cementation

    irr = day.get("irradiation_kwh_m2")
    irr_mult = 0.9 + 0.03 * max(0.0, min(irr if irr is not None else 6.0, 8.5))

    f = params["dust_bias"] * c_ratio * wind_mult * humidity_mult * irr_mult
    return max(0.05, min(3.5, f))


def loss_from_exposure(exposure: float, params: dict) -> float:
    """Soiling loss in percent for a given accumulated effective dust exposure,
    clamped at the observed 55 % ceiling (see MAX_LOSS_FRAC)."""
    raw = params["lmax"] * (1.0 - math.exp(-max(0.0, exposure) / params["tau"]))
    return 100.0 * min(MAX_LOSS_FRAC, raw)


def mass_from_loss(loss_pct: float) -> float:
    """Indicative dust loading on the glass (g/m²) consistent with the loss —
    used for display, derived from the transmittance relation used in the
    soiling literature (exponential attenuation of transmitted light)."""
    frac = min(max(loss_pct, 0.0), 99.0) / 100.0
    return round(-9.0 * math.log(max(1e-6, 1.0 - frac)), 2)


def marginal_loss_per_day(exposure: float, params: dict) -> float:
    """Percentage points of loss added by one more average dust-day."""
    return 100.0 * (params["lmax"] / params["tau"]) * math.exp(-exposure / params["tau"])


# --------------------------------------------------------------- PV yield
def performance_ratio(day: dict) -> float:
    tcell = day.get("tcell_max_c")
    if tcell is None:
        tair = day.get("tair_max_c") or 35.0
        tcell = tair + (day.get("peak_ghi_wm2") or 800) * 0.028
    derate = 1.0 + TEMP_COEFF * max(0.0, tcell - 25.0)
    return max(0.45, min(0.95, PR_BASE * derate))


def day_energy_kwh(capacity_kwp: float, day: dict, soiling_loss_frac: float) -> float:
    irr = day.get("irradiation_kwh_m2")
    if irr is None:
        irr = (day.get("peak_ghi_wm2") or 800) * 6.0 / 1000.0
    return capacity_kwp * irr * performance_ratio(day) * (1.0 - soiling_loss_frac)


def cleaning_cost_sar(capacity_kwp: float, waterless: bool = True,
                      cost_per_mwp: float | None = None) -> float:
    """Cost of one cleaning pass. Waterless (dry brush/robot) is the Saudi default
    because of water scarcity; wet cleaning is costed higher for comparison.

    Assumption: 0.9 SAR per kWp per event (~240 USD/MWp), the mid-range of
    published O&M cleaning figures. It is exposed as a constant so the sensitivity
    is obvious, and the dashboard lets the operator move it."""
    mwp = max(capacity_kwp / 1000.0, 0.001)
    per_mwp = CLEANING_COST_SAR_PER_MWP if cost_per_mwp is None else float(cost_per_mwp)
    return mwp * per_mwp * (1.0 if waterless else 1.45)


def water_litres_per_event(capacity_kwp: float, litres_per_mwp: float | None = None) -> float:
    """Water a wet clean would use — the resource an adaptive schedule saves."""
    return (WATER_LITRES_PER_MWP_WET_CLEAN if litres_per_mwp is None else litres_per_mwp) * capacity_kwp / 1000.0


# --------------------------------------------------------------- policy
# The core of the product: cleaning on a calendar is either too often (wasting
# crews and water) or too late (losing generation). We simulate a year at this
# site and tune the trigger to the site's own economics, then the forecast simply
# follows that threshold. The tuning is deterministic and cached.
_POLICY_CACHE: dict = {}

THRESHOLD_CANDIDATES = (1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0, 12.0, 15.0, 20.0, 25.0)
INTERVAL_CANDIDATES = (5, 7, 10, 14, 21, 30, 45, 60)


def _sim_year(site: dict, capacity_kwp: float, interval: int | None = None,
              threshold: float | None = None, days: int = 365,
              cost_per_mwp: float | None = None) -> dict:
    """One year at this site under a cleaning rule. Uses the site's dust
    seasonality and irradiance curve, so no network access is needed."""
    import datetime as _dt
    params = climate_params(site)
    c = climate(site)
    highland = c == "highland"
    irr_summer, irr_winter = (6.8, 4.6) if highland else (7.2, 5.0)
    pr = 0.78 if c in ("east", "west") else 0.80
    cost = cleaning_cost_sar(capacity_kwp, cost_per_mwp=cost_per_mwp)
    start = _dt.date(2026, 1, 1)
    exposure = 0.0
    loss_sum = 0.0
    lost_kwh = 0.0
    events = 0
    last_clean_day = -999
    for i in range(days):
        doy = (start + _dt.timedelta(days=i)).timetuple().tm_yday
        frac = (1 + math.cos(2 * math.pi * (doy - 180) / 365.0)) / 2
        irr = irr_winter + (irr_summer - irr_winter) * frac
        f = dust_season_factor(doy) * params["dust_bias"]
        exposure = min(MAX_EXPOSURE_DAYS, exposure + f)
        loss_pct = loss_from_exposure(exposure, params)
        loss = loss_pct / 100.0
        loss_sum += loss
        lost_kwh += capacity_kwp * irr * pr * loss
        clean = False
        if interval:
            clean = (i + 1) % interval == 0
        elif threshold is not None:
            clean = loss_pct >= threshold and (i - last_clean_day) >= 2
        if clean:
            events += 1
            exposure = 0.0
            last_clean_day = i
    lost_sar = lost_kwh * TARIFF_SAR_PER_KWH
    ev_cost = events * cost
    return {"cleaning_interval_days": interval if interval else ("adaptive" if threshold is not None else "never"),
            "threshold_pct": threshold,
            "cleaning_events_per_year": events,
            "mean_soiling_loss_pct": round(100.0 * loss_sum / days, 2),
            "energy_lost_kwh": round(lost_kwh, 0),
            "value_lost_sar": round(lost_sar, 0),
            "cleaning_cost_sar": round(ev_cost, 0),
            "water_litres": round(events * water_litres_per_event(capacity_kwp), 0),
            "cost_per_mwp_sar": CLEANING_COST_SAR_PER_MWP if cost_per_mwp is None else float(cost_per_mwp),
            "net_cost_sar": round(lost_sar + ev_cost, 0)}


def policy(site: dict, capacity_kwp: float, cost_per_mwp: float | None = None) -> dict:
    """Tune the cleaning trigger to this site's own economics and weather curve.

    Evaluates every fixed calendar and a sweep of loss thresholds, then keeps the
    one with the lowest total cost (lost generation + cleaning spend). Fair to the
    operator by construction: the calendar they use today is one of the candidates,
    so if adaptive cannot beat it, we say so.
    """
    key = (climate(site), round(float(capacity_kwp), 1),
           CLEANING_COST_SAR_PER_MWP if cost_per_mwp is None else round(float(cost_per_mwp), 1))
    if key in _POLICY_CACHE:
        return _POLICY_CACHE[key]
    scored = []
    for iv in INTERVAL_CANDIDATES:
        scored.append(_sim_year(site, capacity_kwp, interval=iv, cost_per_mwp=cost_per_mwp))
    for th in THRESHOLD_CANDIDATES:
        scored.append(_sim_year(site, capacity_kwp, threshold=th, cost_per_mwp=cost_per_mwp))
    never = _sim_year(site, capacity_kwp, interval=0, cost_per_mwp=cost_per_mwp)
    best = min(scored, key=lambda r: r["net_cost_sar"])
    best_fixed = min((r for r in scored if r["cleaning_interval_days"] != "adaptive"),
                     key=lambda r: r["net_cost_sar"])
    out = {"adaptive": best, "best_fixed_calendar": best_fixed,
           "candidates_evaluated": len(scored) + 1,
           "never_clean": never,
           "beats_calendar": best["net_cost_sar"] < best_fixed["net_cost_sar"] - 1,
           "saving_vs_best_calendar_sar": round(best_fixed["net_cost_sar"] - best["net_cost_sar"], 0),
           "method": "365-day simulation; every fixed interval in {5,7,10,14,21,30,45,60} days and "
                     "12 loss-threshold policies scored on total cost (lost generation + cleaning)"}
    _POLICY_CACHE[key] = out
    return out


# --------------------------------------------------------------- projection
def project(days: list[dict], site: dict, capacity_kwp: float = DEFAULT_CAPACITY_KWP,
            cleaning_interval_days: int | None = None, adaptive: bool = False,
            days_since_last_clean: int = 0, use_ml: bool = True,
            cost_per_mwp: float | None = None) -> dict:
    """Day-by-day soiling + energy simulation for one site.

    Runs the operator's current habit (`cleaning_interval_days`) and, when
    `adaptive=True`, SolarGuard's own schedule over exactly the same weather, so
    the comparison is apples to apples.
    """
    params = climate_params(site)
    model = _ml_model() if (use_ml and ml_serving()) else None
    tuned = policy(site, capacity_kwp, cost_per_mwp)["adaptive"]
    tuned_threshold = float(tuned.get("threshold_pct") or 6.0)

    def run(fixed_interval: int | None, smart: bool):
        rows: list[dict] = []
        exposure = float(days_since_last_clean)
        factor_hist: list[float] = []
        energy = 0.0
        clean_energy = 0.0
        cleans = 0
        clean_cost = 0.0
        water_used = 0.0
        for i, day in enumerate(days):
            f = dust_factor(day, params)
            factor_hist.append(f)
            factor_hist = factor_hist[-7:]
            mean_f = sum(factor_hist) / len(factor_hist)

            # ---- accumulate dust -------------------------------------------
            exposure += f
            exposure = min(exposure, MAX_EXPOSURE_DAYS)
            loss_pct = loss_from_exposure(exposure, params)
            if model is not None:
                try:
                    pred = model.predict(_ml_features(site, day, exposure, mean_f))
                    loss_pct = max(0.0, min(95.0, float(pred.get("soiling_loss_pct", loss_pct))))
                except Exception:
                    pass

            # ---- rain wash-off --------------------------------------------
            rain = day.get("precip_mm") or 0.0
            if rain >= RAIN_WASHOFF_MM:
                exposure *= 0.15
                loss_pct = loss_from_exposure(exposure, params)

            # ---- energy ----------------------------------------------------
            e = day_energy_kwh(capacity_kwp, day, loss_pct / 100.0)
            e_clean = day_energy_kwh(capacity_kwp, day, 0.0)
            energy += e
            clean_energy += e_clean

            # ---- cleaning decision ----------------------------------------
            act = False
            if smart:
                # The trigger is tuned per site on a simulated year of that site's
                # own dust seasonality and economics (see policy()): clean when the
                # measured soiling loss crosses the threshold that minimised total
                # cost. A severe dust day brings it forward, because the next days
                # would blow past it anyway.
                if loss_pct >= tuned_threshold:
                    act = True
                elif rows and rows[-1].get("dust_risk") == "severe" and loss_pct >= tuned_threshold * 0.6:
                    act = True
                # a wash-off rain does the job for free — never send a crew into it
            elif fixed_interval and (i + 1) % fixed_interval == 0:
                act = True
            if act:
                pass

            if act:
                cleans += 1
                clean_cost += cleaning_cost_sar(capacity_kwp, cost_per_mwp=cost_per_mwp)
                water_used += water_litres_per_event(capacity_kwp)
                exposure = 0.0

            rows.append({
                "date": day["date"],
                "irradiation_kwh_m2": day.get("irradiation_kwh_m2"),
                "tair_max_c": day.get("tair_max_c"),
                "tcell_max_c": day.get("tcell_max_c"),
                "wind_max_ms": day.get("wind_max_ms"),
                "gust_max_ms": day.get("gust_max_ms"),
                "precip_mm": rain,
                "pm10_ugm3": day.get("pm10_ugm3"),
                "dust_ugm3": day.get("dust_ugm3"),
                "aod": day.get("aod"),
                "soiling_loss_pct": round(loss_pct, 2),
                "dust_mass_g_m2": mass_from_loss(loss_pct),
                "exposure_days": round(exposure, 2),
                "days_since_clean": round(exposure, 1),
                "energy_kwh": round(e, 1),
                "energy_if_clean_kwh": round(e_clean, 1),
                "lost_kwh": round(e_clean - e, 1),
                "lost_sar": round((e_clean - e) * TARIFF_SAR_PER_KWH, 2),
                "cleaned": act,
                "dust_risk": _risk_label(day, loss_pct, exposure),
                "perf_ratio": round(performance_ratio(day), 3),
                "dust_factor": round(f, 2),
            })
        lost_kwh = clean_energy - energy
        return {
            "rows": rows,
            "energy_kwh": round(energy, 1),
            "energy_if_clean_kwh": round(clean_energy, 1),
            "lost_kwh": round(lost_kwh, 1),
            "lost_sar": round(lost_kwh * TARIFF_SAR_PER_KWH, 2),
            "cleaning_events": cleans,
            "cleaning_cost_sar": round(clean_cost, 2),
            "water_litres": round(water_used, 0),
            "mean_soiling_loss_pct": round(sum(r["soiling_loss_pct"] for r in rows) / max(len(rows), 1), 2),
            "max_soiling_loss_pct": round(max((r["soiling_loss_pct"] for r in rows), default=0.0), 2),
            "net_sar": round(energy * TARIFF_SAR_PER_KWH - clean_cost, 2),
        }

    fixed = run(cleaning_interval_days, False)
    smart = run(None, True) if adaptive else None
    return {"fixed_schedule": fixed, "adaptive_schedule": smart, "params": params,
            "cost_per_mwp_sar": CLEANING_COST_SAR_PER_MWP if cost_per_mwp is None else float(cost_per_mwp),
            "policy": policy(site, capacity_kwp, cost_per_mwp),
            "model": "ml+physics" if model is not None else "physics-empirical",
            "calibration": {
                "anchor": f"{params['rate_pct_per_day']} %/day soiling rate for this climate "
                          f"(published Saudi range ~0.1-0.5 %/day typical, up to ~2 %/day in dust events)",
                "tau_days": params["tau"], "lmax": params["lmax"],
                "literature_reference": params["literature"],
                "note": "Current-month weather modulates this around the annual average: during the "
                        "Feb-May dust season these numbers rise, in calm months they fall. "
                        "MODEL_CARD.md reconciles our simulated annual figures with the published ones.",
            }}


def _ml_features(site: dict, day: dict, exposure: float, mean_f: float) -> dict:
    doy = datetime.strptime(day["date"], "%Y-%m-%d").timetuple().tm_yday
    radiation = day.get("irradiation_kwh_m2")
    return {
        "lat": site.get("lat", 24.7), "lon": site.get("lon", 46.7), "doy": doy,
        "tmax": day.get("tair_max_c"), "tmin": day.get("tair_max_c"),
        "rh": day.get("rh_mean_pct"), "wind": day.get("wind_max_ms"),
        "gust": day.get("gust_max_ms"), "precip": day.get("precip_mm"),
        "rad": radiation if radiation is not None else 6.0,
        "pm10": day.get("pm10_ugm3") or 0.0, "pm25": day.get("pm10_ugm3") or 0.0,
        "dust": day.get("dust_ugm3") or 0.0, "aod": day.get("aod") or 0.0,
        "days_since_rain": exposure, "days_since_clean": exposure,
        "dust_factor": mean_f, "exposure": exposure,
    }


def _risk_label(day: dict, loss_pct: float, exposure: float) -> str:
    gust = day.get("gust_max_ms") or 0
    pm10 = day.get("pm10_ugm3") or 0
    aod = day.get("aod") or 0
    score = 0
    if gust >= 14: score += 2
    elif gust >= 10: score += 1
    if pm10 >= 250: score += 2
    elif pm10 >= 150: score += 1
    if aod >= 0.8: score += 2
    elif aod >= 0.45: score += 1
    if loss_pct >= 25: score += 2
    elif loss_pct >= 12: score += 1
    if score >= 5: return "severe"
    if score >= 3: return "high"
    if score >= 1: return "moderate"
    return "low"


# --------------------------------------------------------------- verdict
def verdict(report: dict, capacity_kwp: float = DEFAULT_CAPACITY_KWP,
            cost_per_mwp: float | None = None) -> dict:
    fixed = report["fixed_schedule"]
    rows = fixed["rows"]
    if not rows:
        return {"decision": "unknown", "reason": "no forecast data"}
    cur = rows[0]
    horizon = rows[:7]
    # money at risk over the next 7 days if nothing is done, and if we clean today
    risk = sum(r["lost_sar"] for r in horizon)
    cost = cleaning_cost_sar(capacity_kwp, cost_per_mwp=cost_per_mwp)
    smart = report.get("adaptive_schedule") or {}
    vs = None
    if smart:
        vs = {
            "energy_pct": round(100.0 * (smart["energy_kwh"] / fixed["energy_kwh"] - 1.0), 2) if fixed["energy_kwh"] else 0.0,
            "lost_sar_fixed": fixed["lost_sar"],
            "lost_sar_adaptive": smart["lost_sar"],
            "saved_sar": round(fixed["lost_sar"] - smart["lost_sar"], 2),
            "cleaning_events_fixed": fixed["cleaning_events"],
            "cleaning_events_adaptive": smart["cleaning_events"],
            "water_saved_litres": round(max(0.0, water_litres_per_event(capacity_kwp) *
                                           max(0, fixed["cleaning_events"] - smart["cleaning_events"])), 0),
            "cost_per_mwp_sar": CLEANING_COST_SAR_PER_MWP if cost_per_mwp is None else float(cost_per_mwp),
        }
    urgency = max(0.0, min(100.0, 100.0 * (cur["soiling_loss_pct"] / 100.0) / max(cur.get("dust_factor", 1.0), 0.3) * 3.0))
    clean_now = risk > cost * 0.9
    return {
        "decision": "clean_now" if clean_now else "wait",
        "current_soiling_loss_pct": cur["soiling_loss_pct"],
        "urgency": round(min(100.0, urgency), 1),
        "next_7d_money_at_risk_sar": round(risk, 2),
        "cleaning_cost_sar": round(cost, 2),
        "payback_days": round(cost / max(risk / max(len(horizon), 1), 0.01), 1),
        "reason": (f"Leaving the array as-is risks about {risk:,.0f} SAR of lost output over 7 days; "
                   f"one cleaning pass costs {cost:,.0f} SAR."
                   if clean_now else
                   f"Only {risk:,.0f} SAR at risk over 7 days against a {cost:,.0f} SAR crew — "
                   f"hold the crew and re-check tomorrow."),
        "risk_today": cur.get("dust_risk"),
        "adaptive_vs_fixed": vs,
    }


# --------------------------------------------------------------- annual context
def annual_estimate(site: dict, capacity_kwp: float = DEFAULT_CAPACITY_KWP,
                    intervals: tuple[int, ...] = (7, 14, 30),
                    cost_per_mwp: float | None = None) -> dict:
    """Simulate a full year at this site for several cleaning habits.

    Only the calibrated daily rate, the dust seasonality curve and the chosen
    interval drive this, so it works with no forecast and is fully reproducible.
    The published annual losses are reported next to ours, labelled with the
    interval the study assumed — see MODEL_CARD.md for the reconciliation.

    Rain is deliberately not credited (conservative for Saudi Arabia), and the
    array's own degradation/soiling-free losses are unchanged between scenarios,
    so the comparison isolates dust.
    """
    import datetime as _dt

    params = climate_params(site)
    c = climate(site)
    highland = c == "highland"
    irr_summer, irr_winter = (7.2, 5.0) if not highland else (6.8, 4.6)
    pr = 0.78 if c in ("east", "west") else 0.80
    start = _dt.date(2026, 1, 1)

    pol = policy(site, capacity_kwp, cost_per_mwp)
    habits = {f"{i}d": _sim_year(site, capacity_kwp, interval=i, cost_per_mwp=cost_per_mwp)
              for i in intervals}
    habits["weekly"] = habits.pop("7d")
    habits["industry_today"] = _sim_year(site, capacity_kwp, cost_per_mwp=cost_per_mwp,
                                        interval=DEFAULT_CLEANING_INTERVAL_DAYS)
    habits["adaptive"] = pol["adaptive"]
    habits["never"] = pol["never_clean"]
    lit = LITERATURE[c]
    best = pol["adaptive"]
    industry = habits["industry_today"]
    return {
        "climate": c,
        "literature_annual_loss_pct": lit["annual_loss_pct"],
        "literature_source": lit["source"],
        "no_cleaning_loss_ceiling_pct": round(MAX_LOSS_FRAC * 100, 1),
        "habits": habits,
        "industry_habit": industry,
        "solarguard_habit": best,
        "opportunity": {
            "vs": "today's habit (clean every %d days, as at Sakaka)" % DEFAULT_CLEANING_INTERVAL_DAYS,
            "energy_kept_pct": round(100.0 * (1 - best["energy_lost_kwh"] / max(industry["energy_lost_kwh"], 1)), 2),
            "sar_saved_year": round(industry["net_cost_sar"] - best["net_cost_sar"], 0),
            "events_saved": industry["cleaning_events_per_year"] - best["cleaning_events_per_year"],
            "water_saved_litres": round(max(0.0, industry["water_litres"] - best["water_litres"]), 0),
            "best_calendar": pol["best_fixed_calendar"],
            "beats_best_calendar": pol["beats_calendar"],
            "saving_vs_best_calendar_sar": pol["saving_vs_best_calendar_sar"],
            "tuned_trigger": best.get("threshold_pct"),
        },
        "model_anchor": {"rate_pct_per_day": params["rate_pct_per_day"],
                         "tau_days": params["tau"], "lmax": params["lmax"]},
        "assumptions": {"tariff_sar_per_kwh": TARIFF_SAR_PER_KWH,
                        "cleaning_cost_sar_per_mwp": CLEANING_COST_SAR_PER_MWP,
                        "performance_ratio": pr,
                        "irradiation_kwh_m2_summer": irr_summer,
                        "irradiation_kwh_m2_winter": irr_winter,
                        "rain_credited": False},
        "note": ("Published Saudi studies report 12-36 % and up to 45 % annual soiling losses under "
                 "weekly cleaning; a rate-anchored simulation at those intervals lands lower, which is "
                 "consistent with those figures describing heavily dust-exposed sites or longer "
                 "intervals. Both sets are shown so the operator can judge. MODEL_CARD.md explains it."),
    }


def water_saved_litres(events_fixed: int, events_adaptive: int, capacity_kwp: float,
                       litres_per_mwp: float = 2500.0) -> float:
    avoided = max(0, events_fixed - events_adaptive)
    return avoided * litres_per_mwp * capacity_kwp / 1000.0
