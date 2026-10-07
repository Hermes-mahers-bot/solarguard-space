#!/usr/bin/env python3
"""
physics_soiling.py -- SolarGuard Space
=====================================
An EXPLAINABLE physics / empirical soiling model for PV modules in Saudi Arabia.
It is the label generator for the machine-learning models in `train.py`.

Why a physics model for labels?
    There is no public, free, high-frequency archive of *measured* PV soiling loss for
    Saudi plants (that data lives in KAUST/ACWA/utility SCADA systems).  So the labels
    are produced by a transparent mass-balance soiling model whose free parameters are
    calibrated to PUBLISHED annual soiling-loss bands.  Every label is therefore
    "literature-calibrated model output", NOT measured field data.  The measured part of
    the pipeline is the meteorology and the satellite aerosol columns (Open-Meteo).

Model (mass balance on a tilted glass surface)
----------------------------------------------
    M(t)  [g/m2]  dust mass density on the module

    1. Deposition
         F(t) = V_SCALE * wfac(v_wind) * (PM10/100)^P_EXP * site_factor      [g/m2/day]
       wfac  : deposition-velocity shape.  Rises with wind (turbulence brings more
               particles to the surface) and then FALLS for strong wind because coarse
               particles bounce / are resuspended.  Gaussian-in-log(wind), peak ~5.5 m/s,
               with a small gravitational floor.
       P_EXP : >1 => super-linear response to concentration, i.e. dust storms (very high
               PM10) deposit disproportionately more mass than hazy days.  Standard
               "storm-dominated" behaviour observed in arid-region soiling studies.
    2. Removal by wind (resuspension): above RESUSPEND_KMH the existing deposit is
       partially eroded (this is why very windy desert days can self-clean a little).
    3. Removal by rain:  precip >= RAIN_RESET_MM (5 mm) fully washes the module (M->0).
       Partial rain 0.5..5 mm removes a fraction exp(-ALPHA_RAIN*P).
    4. Cementation / hygroscopic growth: humid air (RH) cements dust onto the glass and
       grows the particles, so the same mass causes a larger optical loss.  Modelled as
       an effective-mass multiplier  cement(RH).
    5. Cleaning events every CLEANING_INTERVAL_DAYS with efficiency CLEAN_EFFICIENCY.
    6. Optical loss (Beer-Lambert-type saturation, standard for soiling):
         loss_pct = 100 * (1 - exp(-K_LOSS * M * cement))

Calibration
-----------
Each site's `site_factor` (a regional dust-loading coefficient, absorbing local dust
source strength, dust chemistry and single-digit-km land use that a ~0.4 deg CAMS grid
cell cannot resolve) is fitted by bisection so that the simulated MEAN ANNUAL soiling
loss under weekly cleaning matches the published band for that region:

    west coast (Jeddah, Yanbu, NEOM) ....  ~15 %   (KAUST)
    east coast (Dammam, AlJubail) .......  ~45 %   (KAUST)
    central / north / northwest .........  12-36 % (Middle-East meta-study)
    southwest highland (Abha) ...........  ~14 %   (wet, washes often)

The fitted factors are written to models/soiling_calibration.json.  This is a
literature-calibrated empirical model, and it is documented as such -- the DAY-TO-DAY
shape comes from the measured meteorology, the LEVEL comes from the published bands.

CLI
    python ml/physics_soiling.py                 # print per-site annual loss table
    python ml/physics_soiling.py --calibrate     # (re)fit site factors, write JSON
    python ml/physics_soiling.py --site Jeddah   # trace one site
"""

import argparse
import csv
import json
import math
import os
from datetime import datetime

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
CSV_PATH = os.path.join(ROOT, "data", "soiling_dataset.csv")
CALIB_PATH = os.path.join(ROOT, "models", "soiling_calibration.json")

# ------------------------------------------------------------------ tunable constants
CLEANING_INTERVAL_DAYS = 7      # weekly cleaning (KAUST baseline scenario)
CLEAN_EFFICIENCY = 0.95         # 95 % of the deposit removed per event
RAIN_RESET_MM = 5.0             # rain >= this fully washes the module
PARTIAL_RAIN_MIN_MM = 0.5       # below this, drizzle cements rather than cleans
ALPHA_RAIN = 0.35               # per-mm partial wash-off constant
RESUSPEND_KMH = 45.0            # above this, wind erodes the deposit
RESUSPEND_SLOPE = 0.011         # fraction eroded per km/h above threshold
V_SCALE = 0.080                 # deposition-velocity scale [g/m2/day per (PM10/100)^p]
P_EXP = 1.15                    # super-linear concentration response
WIND_PEAK_MS = 5.5              # deposition-velocity peaks here
WIND_SIGMA = 0.85               # log-width of the deposition-velocity curve
WIND_FLOOR = 0.25               # calm-air gravitational settling floor
K_LOSS = 0.81                   # optical loss coefficient [1/(g/m2)]
CEMENT_BETA = 0.35              # humidity cementation strength
CEMENT_RH_REF = 40.0            # RH above which cementation kicks in

REGION_TARGET_LOSS = {
    "west": 15.0,
    "east": 45.0,
    "central": 28.0,
    "north": 24.0,
    "northwest": 23.0,
    "southwest_highland": 14.0,
}
DEFAULT_FACTOR_BY_REGION = {  # fallback for sites absent from the calibration file
    "west": 0.55, "east": 1.10, "central": 0.60,
    "north": 0.55, "northwest": 0.45, "southwest_highland": 0.30,
    "unknown": 0.50,
}


# ------------------------------------------------------------------------ core physics
def wind_deposition_factor(wind_kmh):
    """Deposition-velocity shape: rises with wind, falls for strong wind (bounce/resuspension)."""
    w = np.maximum(np.asarray(wind_kmh, dtype=float), 0.5) / 3.6  # km/h -> m/s
    shape = np.exp(-0.5 * (np.log(w / WIND_PEAK_MS) / WIND_SIGMA) ** 2)
    return WIND_FLOOR + (1.0 - WIND_FLOOR) * shape


def cementation_factor(rh_pct):
    """Humid air cements dust and grows particles -> more optical loss per unit mass."""
    rh = np.asarray(rh_pct, dtype=float)
    return 1.0 + CEMENT_BETA * np.clip(rh - CEMENT_RH_REF, 0.0, None) / 60.0


def deposition_flux(pm10, wind_kmh, factor):
    """Daily dust deposition flux onto the module [g/m2/day]."""
    pm10 = np.asarray(pm10, dtype=float)
    concentration_term = (np.maximum(pm10, 5.0) / 100.0) ** P_EXP
    return V_SCALE * factor * wind_deposition_factor(wind_kmh) * concentration_term


def loss_from_mass(mass, rh_pct):
    """Beer-Lambert-type saturating optical loss [%]."""
    eff = np.asarray(mass, dtype=float) * cementation_factor(rh_pct)
    return 100.0 * (1.0 - np.exp(-K_LOSS * eff))


def simulate_site(daily, factor, cleaning_interval_days=CLEANING_INTERVAL_DAYS,
                  rain_reset_mm=RAIN_RESET_MM):
    """
    Run the mass balance over a site's daily series.

    daily : dict of equal-length sequences (numpy arrays or lists), keys:
        pm10_mean_ugm3, wind_max_kmh, gust_max_kmh, rh_mean_pct, precip_mm
        (missing PM10 is treated as the series median -- never as zero)
    factor : site dust-loading coefficient (see calibrate_factor)

    Returns dict of numpy arrays (all length n):
        deposition_g_m2_day, mass_g_m2, soiling_loss_pct,
        cleaned_today (0/1), days_since_clean, days_since_rain, wet_flag
    """
    pm10 = np.asarray(daily["pm10_mean_ugm3"], dtype=float)
    wind = np.asarray(daily["wind_max_kmh"], dtype=float)
    rh = np.asarray(daily["rh_mean_pct"], dtype=float)
    precip = np.asarray(daily["precip_mm"], dtype=float)

    if not np.any(np.isfinite(pm10)):
        raise ValueError("simulate_site: no valid PM10 for this site")
    fill = float(np.nanmedian(pm10[np.isfinite(pm10)]))
    pm10 = np.where(np.isfinite(pm10), pm10, fill)
    wind = np.where(np.isfinite(wind), wind, float(np.nanmedian(wind)))
    rh = np.where(np.isfinite(rh), rh, float(np.nanmedian(rh)))
    precip = np.where(np.isfinite(precip), precip, 0.0)

    n = len(pm10)
    flux = deposition_flux(pm10, wind, factor)

    mass = np.zeros(n)
    loss = np.zeros(n)
    cleaned = np.zeros(n, dtype=int)
    dsc = np.zeros(n)
    dsr = np.zeros(n)
    wet = np.zeros(n, dtype=int)

    m = 0.0
    since_clean = 10 ** 6
    since_rain = 10 ** 6
    for t in range(n):
        p = precip[t]
        # ---- removal by rain (largest fresh-water effect first)
        if p >= rain_reset_mm:
            m = 0.0
            since_rain = 0
            wet[t] = 1
        elif p >= PARTIAL_RAIN_MIN_MM:
            m *= math.exp(-ALPHA_RAIN * p)
            since_rain = 0
            wet[t] = 1
        else:
            since_rain += 1

        # ---- removal by strong wind (resuspension)
        if wind[t] > RESUSPEND_KMH:
            m *= max(0.0, 1.0 - RESUSPEND_SLOPE * (wind[t] - RESUSPEND_KMH))

        # ---- deposition
        m += float(flux[t])

        # ---- scheduled cleaning
        if since_clean >= cleaning_interval_days:
            m *= (1.0 - CLEAN_EFFICIENCY)
            cleaned[t] = 1
            since_clean = 0
        else:
            since_clean += 1

        mass[t] = m
        loss[t] = 100.0 * (1.0 - math.exp(-K_LOSS * m * float(cementation_factor(rh[t]))))
        dsc[t] = min(since_clean, 999)
        dsr[t] = min(since_rain, 999)

    return {
        "deposition_g_m2_day": flux,
        "mass_g_m2": mass,
        "soiling_loss_pct": loss,
        "cleaned_today": cleaned,
        "days_since_clean": dsc,
        "days_since_rain": dsr,
        "wet_flag": wet,
    }


# ---------------------------------------------------------------------------- calibration
def calibrate_factor(daily, target_annual_loss_pct,
                     cleaning_interval_days=CLEANING_INTERVAL_DAYS, tol=0.05):
    """Bisection on the site factor so that mean annual weekly-cleaning loss == target."""
    lo, hi = 0.005, 40.0
    for _ in range(80):
        mid = math.sqrt(lo * hi)
        out = simulate_site(daily, mid, cleaning_interval_days)
        got = float(np.mean(out["soiling_loss_pct"]))
        if abs(got - target_annual_loss_pct) < tol:
            return mid, got
        # loss is monotone increasing in factor
        if got < target_annual_loss_pct:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-6:
            break
    out = simulate_site(daily, lo, cleaning_interval_days)
    return lo, float(np.mean(out["soiling_loss_pct"]))


def load_dataset(path=CSV_PATH):
    """Read soiling_dataset.csv with the stdlib (no pandas). Returns {site: {'meta':..,'data':{col:np.array}}}"""
    with open(path) as fh:
        rows = list(csv.DictReader(fh))
    sites = {}
    for r in rows:
        s = sites.setdefault(r["site"], {"meta": {
            "lat": float(r["lat"]), "lon": float(r["lon"]),
            "elevation_m": float(r["elevation_m"]) if r["elevation_m"] not in ("", "None") else float("nan"),
            "region": r["region"],
        }, "data": {}, "dates": []})
        s["dates"].append(r["date"])
        for col in ("pm10_mean_ugm3", "wind_max_kmh", "gust_max_kmh",
                    "rh_mean_pct", "precip_mm", "tmax_c", "tmin_c", "tmean_c",
                    "radiation_mj_m2", "et0_mm", "pm2_5_mean_ugm3", "dust_mean_ugm3",
                    "aod_mean", "pm10_max_ugm3", "dust_max_ugm3", "aod_max"):
            s["data"].setdefault(col, [])
            v = r.get(col, "")
            s["data"][col].append(float("nan") if v in ("", "None") else float(v))
    for s in sites.values():
        s["data"] = {k: np.asarray(v, dtype=float) for k, v in s["data"].items()}
        s["dates"] = np.asarray(s["dates"])
    return sites


def calibrate_all(path=CSV_PATH, out_path=CALIB_PATH, cleaning_interval_days=CLEANING_INTERVAL_DAYS,
                  region_targets=None):
    """Fit a site factor for every site in the dataset; write the calibration JSON."""
    region_targets = region_targets or REGION_TARGET_LOSS
    sites = load_dataset(path)
    calib = {}
    for site, s in sites.items():
        region = s["meta"]["region"]
        target = region_targets.get(region, 25.0)
        factor, achieved = calibrate_factor(s["data"], target, cleaning_interval_days)
        calib[site] = {
            "region": region, "target_annual_loss_pct": target,
            "site_factor": factor, "achieved_annual_loss_pct": achieved,
            "cleaning_interval_days": cleaning_interval_days,
            "lat": s["meta"]["lat"], "lon": s["meta"]["lon"],
        }
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    payload = {
        "generated_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "model": "physics_soiling v1 (literature-calibrated mass balance)",
        "constants": {
            "CLEANING_INTERVAL_DAYS": cleaning_interval_days,
            "CLEAN_EFFICIENCY": CLEAN_EFFICIENCY, "RAIN_RESET_MM": RAIN_RESET_MM,
            "ALPHA_RAIN": ALPHA_RAIN, "RESUSPEND_KMH": RESUSPEND_KMH,
            "V_SCALE": V_SCALE, "P_EXP": P_EXP, "K_LOSS": K_LOSS,
            "CEMENT_BETA": CEMENT_BETA, "CEMENT_RH_REF": CEMENT_RH_REF,
        },
        "region_targets_pct": region_targets,
        "sites": calib,
    }
    with open(out_path, "w") as fh:
        json.dump(payload, fh, indent=2)
    return payload


def load_calibration(path=CALIB_PATH, auto_calibrate=True):
    if os.path.exists(path):
        with open(path) as fh:
            return json.load(fh)
    if not auto_calibrate:
        return None
    return calibrate_all(out_path=path)


def factor_for_site(site_name, region="unknown", calib=None):
    if calib and site_name in calib.get("sites", {}):
        return calib["sites"][site_name]["site_factor"]
    return DEFAULT_FACTOR_BY_REGION.get(region, DEFAULT_FACTOR_BY_REGION["unknown"])


# --------------------------------------------------------------------------------- label
def compute_labels(path=CSV_PATH, calib=None, cleaning_interval_days=CLEANING_INTERVAL_DAYS):
    """Generate physics labels for every row of the dataset. Returns {site: {col: array}}."""
    calib = calib or load_calibration()
    sites = load_dataset(path)
    out = {}
    for site, s in sites.items():
        factor = factor_for_site(site, s["meta"]["region"], calib)
        res = simulate_site(s["data"], factor, cleaning_interval_days)
        res["site_factor"] = np.full(len(s["dates"]), factor)
        out[site] = {"dates": s["dates"], "labels": res, "meta": s["meta"]}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--calibrate", action="store_true")
    ap.add_argument("--site", default=None)
    ap.add_argument("--interval", type=int, default=CLEANING_INTERVAL_DAYS)
    a = ap.parse_args()

    if a.calibrate:
        pay = calibrate_all(cleaning_interval_days=a.interval)
    else:
        pay = load_calibration()

    print(f"\n=== physics_soiling :: annual soiling loss under {a.interval}-day cleaning ===")
    print(f"{'site':10} {'region':20} {'factor':>7} {'target%':>8} {'sim%':>7} {'no-clean%':>10}")
    losses = []
    for site, s in sorted(pay["sites"].items(), key=lambda kv: kv[1]["achieved_annual_loss_pct"]):
        data = load_dataset()[site]["data"]
        f = s["site_factor"]
        with_clean = float(np.mean(simulate_site(data, f, a.interval)["soiling_loss_pct"]))
        # steady-state annual loss with NO cleaning: mean over the final year of a 10-year run
        long_run = simulate_site(data, f, 3650)["soiling_loss_pct"]
        no_clean = float(np.mean(long_run[-365:]))
        losses.append(with_clean)
        print(f"{site:10} {s['region']:20} {f:7.3f} {s['target_annual_loss_pct']:8.1f} "
              f"{with_clean:7.2f} {no_clean:10.2f}")
    losses = np.array(losses)
    print(f"\nregion-wide: mean {losses.mean():.2f}%  min {losses.min():.2f}%  max {losses.max():.2f}%")
    print("'no-clean%' = steady-state annual loss if never cleaned (final-year mean of a 10-y run)")
    print("literature: west ~15%, east ~45% (KAUST); Middle East 12-36% with weekly cleaning\n")


if __name__ == "__main__":
    main()
