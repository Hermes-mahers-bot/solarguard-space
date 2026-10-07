#!/usr/bin/env python3
"""
predict.py -- SolarGuard Space
=============================
Pure-numpy inference API for the SolarGuard Space dust-soiling models.
No PyTorch / TensorFlow / sklearn / pandas.  Loads the from-scratch models saved by
`ml/train.py` (models/gbrt.npz, models/mlp.npz) plus models/feature_meta.json.

Public API
----------
    models = load_models("models")               # once, at process start
    out    = predict({"site": "Dammam", "pm10": 180, "humidity": 45,
                      "wind_speed": 22, "precip": 0.0, "days_since_clean": 6,
                      "temperature": 41}, models)
    # -> {'soiling_loss_pct', 'deposition_g_m2', 'cleaning_urgency',
    #     'days_until_clean_recommended', 'confidence', 'power_loss_pct',
    #     'energy_value_lost_sar_per_kwp', ... }

`load_models` does all file I/O once; `predict` is a handful of numpy ops on ONE row,
well inside a 200 ms budget (measured ~1 ms).

Assumptions (documented, override-able)
---------------------------------------
  * Saudi grid tariff .................. 0.18 SAR/kWh            (ECRA/SE residential+industrial avg)
  * waterless cleaning ................. 1.00 SAR/kWp/event      (published range 0.5-1.5)
  * specific yield KSA ................. 5.5 kWh/kWp/day         (~2000 kWh/kWp/yr, high-DNI desert)
  * soiling loss -> power loss ......... 1:1 first order (uniform dust attenuates irradiance;
                                         literature: transmission loss ~= power loss for
                                         uniform soiling below ~25 %; we cap the mapping at
                                         1.0 and document the simplification)
  * cleaning pays back when the energy recovered over the next cleaning interval
    exceeds the cleaning cost  ->  break-even average soiling loss
        = cost / (yield * tariff * interval)  ~= 1.0/(5.5*0.18*7) ~= 14.4 %
"""

import json
import math
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
DEFAULT_MODEL_DIR = os.path.join(ROOT, "models")

# ---------------------------------------------------------------- economic assumptions
TARIFF_SAR_PER_KWH = 0.18
CLEANING_COST_SAR_PER_KWP = 1.00
SPECIFIC_YIELD_KWH_PER_KWP_DAY = 5.5
DEFAULT_CLEANING_INTERVAL_DAYS = 7

# site table (lat, lon, elevation m, region) -- matches ml/build_dataset.py
SITE_TABLE = {
    "Riyadh":   (24.71, 46.67, 629, "central"),
    "Jeddah":   (21.49, 39.19, 13, "west"),
    "Dammam":   (26.43, 50.10, 9, "east"),
    "AlJubail": (27.00, 49.66, 3, "east"),
    "Yanbu":    (24.09, 38.06, 7, "west"),
    "NEOM":     (27.99, 35.25, 11, "west"),
    "AlUla":    (26.61, 37.92, 696, "northwest"),
    "Tabuk":    (28.38, 36.57, 767, "northwest"),
    "Abha":     (18.22, 42.50, 2219, "southwest_highland"),
    "Shaqra":   (25.25, 45.25, 710, "central"),
    "Sakaka":   (29.97, 40.20, 559, "north"),
    "Sudair":   (25.55, 45.55, 807, "central"),
}

# accepted aliases in the caller's feature dict
ALIASES = {
    "latitude": "lat", "longitude": "lon", "elevation": "elevation_m", "elev": "elevation_m",
    "temperature": "tmean_c", "temp": "tmean_c", "temp_mean": "tmean_c", "t2m": "tmean_c",
    "temperature_2m": "tmean_c", "temperature_2c": "tmean_c", "air_temp": "tmean_c",
    "tmax": "tmax_c", "temperature_max": "tmax_c", "tmin": "tmin_c", "temperature_min": "tmin_c",
    "humidity": "rh_mean_pct", "rh": "rh_mean_pct", "relative_humidity": "rh_mean_pct",
    "relative_humidity_2m": "rh_mean_pct", "rh2m": "rh_mean_pct",
    "wind": "wind_max_kmh", "wind_speed": "wind_max_kmh", "wind_max": "wind_max_kmh",
    "windspeed_10m_max": "wind_max_kmh", "wind_speed_10m_max": "wind_max_kmh",
    "gust": "gust_max_kmh", "gusts": "gust_max_kmh", "wind_gusts_10m_max": "gust_max_kmh",
    "gusts_max_kmh": "gust_max_kmh",
    "precip": "precip_mm", "rain": "precip_mm", "precipitation": "precip_mm",
    "precipitation_sum": "precip_mm",
    "radiation": "radiation_mj_m2", "shortwave_radiation_sum": "radiation_mj_m2",
    "ghi": "radiation_mj_m2",
    "et0": "et0_mm", "evapotranspiration": "et0_mm",
    "pm10": "pm10_mean_ugm3", "pm10_mean": "pm10_mean_ugm3",
    "pm25": "pm2_5_mean_ugm3", "pm2_5": "pm2_5_mean_ugm3", "pm2.5": "pm2_5_mean_ugm3",
    "dust": "dust_mean_ugm3", "dust_concentration": "dust_mean_ugm3",
    "aod": "aod_mean", "aerosol_optical_depth": "aod_mean",
    "aerosol_optical_depth_mean": "aod_mean",
    "days_since_rain": "days_since_rain", "days_since_clean": "days_since_clean",
    "day_of_year": "doy", "doy": "doy", "date": "date",
}
# if the caller gives an instantaneous aerosol value we treat it as representative of the
# recent window -- documented simplification, keeps predict() to a single dict.
ROLL_SOURCE = {
    "pm10_mean_ugm3": ["pm10_mean_ugm3_3d_mean", "pm10_mean_ugm3_7d_mean",
                       "pm10_mean_ugm3_30d_mean", "pm10_mean_ugm3_90d_mean"],
    "dust_mean_ugm3": ["dust_mean_ugm3_7d_mean", "dust_mean_ugm3_30d_mean"],
    "aod_mean": ["aod_mean_7d_mean"],
    "wind_max_kmh": ["wind_max_kmh_7d_mean", "wind_max_kmh_30d_mean"],
    "gust_max_kmh": ["gust_max_kmh_7d_mean"],
    "rh_mean_pct": ["rh_mean_pct_7d_mean"],
    "precip_mm": ["precip_mm_7d_sum", "precip_mm_30d_sum"],
    "pm10_max_ugm3": ["pm10_max_ugm3_7d_max"],
}
EXPANDING = ["pm10_mean_ugm3", "dust_mean_ugm3", "aod_mean"]


# ---------------------------------------------------------------------------- model load
class SoilingModels:
    """Container holding both trained models + feature metadata."""

    def __init__(self, gbrt_loss, gbrt_dep, mlp, feat_meta, meta_gbrt, meta_mlp):
        self.gbrt_loss = gbrt_loss
        self.gbrt_dep = gbrt_dep
        self.mlp = mlp
        self.feat_meta = feat_meta
        self.meta_gbrt = meta_gbrt
        self.meta_mlp = meta_mlp
        self.features = feat_meta["features"]
        self.defaults = feat_meta["defaults"]
        self.ranges = feat_meta.get("ranges", {})
        tt = meta_gbrt.get("target_transforms") or feat_meta.get("target_transforms") or ["none", "none"]
        self.target_transforms = tt
        self.dep_transform = tt[1]
        self.loss_transform = tt[0]


def load_models(model_dir=DEFAULT_MODEL_DIR):
    """Load gbrt.npz + mlp.npz + feature_meta.json.  Call once per process."""
    import sys
    if HERE not in sys.path:
        sys.path.insert(0, HERE)
    from train import GBRT, MLP  # local import: only needed for reconstruction

    gz = np.load(os.path.join(model_dir, "gbrt.npz"), allow_pickle=False)
    mz = np.load(os.path.join(model_dir, "mlp.npz"), allow_pickle=False)
    meta_gbrt = json.loads(str(gz["meta_json"][0]))
    meta_mlp = json.loads(str(mz["meta_json"][0]))
    feat_meta = json.load(open(os.path.join(model_dir, "feature_meta.json")))

    gbrt_loss = GBRT.from_npz(gz, meta_gbrt.get("targets_prefix", {}).get("soiling_loss_pct", "loss_"))
    gbrt_dep = GBRT.from_npz(gz, meta_gbrt.get("targets_prefix", {}).get("deposition_g_m2_day", "dep_"))
    mlp = MLP.from_npz(mz, "")
    return SoilingModels(gbrt_loss, gbrt_dep, mlp, feat_meta, meta_gbrt, meta_mlp)


# ------------------------------------------------------------------------ input handling
def _coerce_features(features, feat_meta):
    """dict -> (row np.array in canonical feature order, aq_supplied, out_of_range_frac)."""
    features = dict(features or {})
    # resolve aliases to canonical names
    canon = {}
    for k, v in features.items():
        if k is None:
            continue
        key = ALIASES.get(str(k).strip().lower(), str(k).strip())
        canon[key] = v

    # site expansion
    site = canon.pop("site", None)
    if site is not None:
        row = SITE_TABLE.get(str(site)) or SITE_TABLE.get(str(site).replace(" ", ""))
        if row is None:
            for name, r in SITE_TABLE.items():
                if name.lower() == str(site).lower():
                    row = r
                    break
        if row:
            canon.setdefault("lat", row[0])
            canon.setdefault("lon", row[1])
            canon.setdefault("elevation_m", row[2])
            canon.setdefault("region", row[3])

    # day of year
    if "doy" in canon and "doy_sin" not in canon:
        doy = canon.pop("doy")
        try:
            doy = int(doy)
        except (TypeError, ValueError):
            doy = 180
        canon["doy_sin"] = math.sin(2 * math.pi * (doy - 1) / 365.25)
        canon["doy_cos"] = math.cos(2 * math.pi * (doy - 1) / 365.25)
    elif "date" in canon and "doy_sin" not in canon:
        d = str(canon.pop("date"))
        try:
            from datetime import datetime as _dt
            doy = _dt.strptime(d[:10], "%Y-%m-%d").timetuple().tm_yday
        except Exception:  # noqa: BLE001
            doy = 180
        canon["doy_sin"] = math.sin(2 * math.pi * (doy - 1) / 365.25)
        canon["doy_cos"] = math.cos(2 * math.pi * (doy - 1) / 365.25)

    # tmean from tmax/tmin
    if "tmean_c" not in canon and "tmax_c" in canon and "tmin_c" in canon:
        canon["tmean_c"] = 0.5 * (float(canon["tmax_c"]) + float(canon["tmin_c"]))

    defaults = feat_meta["defaults"]
    aq_keys = ["pm10_mean_ugm3", "dust_mean_ugm3", "aod_mean", "pm2_5_mean_ugm3"]
    aq_supplied = any(k in canon for k in aq_keys)

    # expand rolls / expanding means from supplied values
    for src, targets in ROLL_SOURCE.items():
        if src in canon:
            for t in targets:
                canon.setdefault(t, canon[src])
    for src in EXPANDING:
        if src in canon:
            canon.setdefault(f"{src}_expmean", canon[src])
    if "precip_mm" in canon:
        canon.setdefault("pm10_max_ugm3", canon.get("pm10_mean_ugm3", defaults.get("pm10_max_ugm3", 100.0)))

    row = np.array([float(canon.get(f, defaults[f])) for f in feat_meta["features"]], dtype=float)
    row = np.nan_to_num(row, nan=0.0)

    oor = 0
    for i, f in enumerate(feat_meta["features"]):
        lo, hi = feat_meta.get("ranges", {}).get(f, [None, None])
        if lo is None:
            continue
        if row[i] < lo - 1e-9 or row[i] > hi + 1e-9:
            oor += 1
    return row, aq_supplied, oor / max(1, len(feat_meta["features"]))


# ------------------------------------------------------------------------------ inference
def predict(features, models, tariff=TARIFF_SAR_PER_KWH,
            cleaning_cost=CLEANING_COST_SAR_PER_KWP,
            cleaning_interval_days=DEFAULT_CLEANING_INTERVAL_DAYS):
    """
    Single-dict inference.  Returns a plain dict of floats/ints.

    `features` keys (all optional; missing values fall back to the site's/global median):
        site | lat | lon | elevation_m | date | day_of_year
        temperature (tmean_c) | tmax_c | tmin_c | humidity (rh_mean_pct)
        wind_speed (wind_max_kmh) | gust (gust_max_kmh) | precip (precip_mm)
        radiation (radiation_mj_m2) | et0 | pm10 | pm2_5 | dust | aod
        days_since_rain | days_since_clean
    """
    row, aq_supplied, oor = _coerce_features(features, models.feat_meta)
    X = row.reshape(1, -1)

    loss_g = float(models.gbrt_loss.predict(X)[0])
    dep_raw = float(models.gbrt_dep.predict(X)[0])
    dep_g = math.exp(dep_raw) if models.dep_transform == "log" else dep_raw

    xm = np.asarray(models.feat_meta["scaler_mean"])
    xs = np.asarray(models.feat_meta["scaler_std"])
    xs = np.where(np.asarray(xs) == 0, 1.0, xs)
    z = (X - xm) / xs
    mlp_out = np.asarray(models.mlp.predict(z)[0], dtype=float)
    ymean = np.asarray(models.meta_mlp.get("ymean", [0.0, 0.0]), dtype=float)
    ystd = np.asarray(models.meta_mlp.get("ystd", [1.0, 1.0]), dtype=float)
    ystd = np.where(ystd == 0, 1.0, ystd)
    mlp_native = mlp_out * ystd + ymean                      # undo standardisation
    transforms = models.meta_mlp.get("target_transforms", ["none", "none"])
    if transforms[1] == "log":
        mlp_native[1] = math.exp(float(np.clip(mlp_native[1], -50, 50)))
    loss_m = float(mlp_native[0])
    dep_m = float(mlp_native[1])

    loss = 0.5 * (loss_g + loss_m)
    dep = 0.5 * (dep_g + dep_m)
    loss = float(min(max(loss, 0.0), 100.0))
    dep = float(max(dep, 0.0))

    # ---- economics -----------------------------------------------------------------
    daily_value_per_kwp = SPECIFIC_YIELD_KWH_PER_KWP_DAY * tariff          # SAR/kWp/day
    power_loss_pct = float(min(max(loss, 0.0), 100.0))   # 1:1 below saturation (documented)
    value_lost_day = daily_value_per_kwp * (power_loss_pct / 100.0)
    value_lost_year = value_lost_day * 365.0
    # cleaning pays back if the energy recovered across the next cleaning interval beats cost
    break_even_loss_pct = cleaning_cost / (daily_value_per_kwp * max(cleaning_interval_days, 1)) * 100.0
    # expected average loss across the next interval (approximate: linear accrual from now)
    dsc = float(features.get("days_since_clean", models.feat_meta["defaults"].get("days_since_clean", 3))
                if isinstance(features, dict) else 3)
    dsc = max(dsc, 1.0)
    rate = max(loss / dsc, 0.05)                       # %/day accrual from observed state
    projected = min(100.0, loss + rate * cleaning_interval_days * 0.5)
    urgency = float(min(max(projected / max(break_even_loss_pct, 1e-6), 0.0), 1.0))
    if loss >= break_even_loss_pct:
        days_until = 0
    else:
        days_until = int(math.ceil((break_even_loss_pct - loss) / max(rate, 1e-6)))
        days_until = int(min(max(days_until, 0), 365))

    # ---- confidence ---------------------------------------------------------------
    denom = max(abs(loss), 1.0)
    disagree = abs(loss_g - loss_m) / denom
    conf_agree = math.exp(-disagree / 0.35)
    conf = 0.30 + (0.30 if aq_supplied else 0.0) + 0.40 * conf_agree
    conf *= (1.0 - 0.30 * min(oor, 1.0))
    confidence = float(min(max(conf, 0.05), 0.99))

    return {
        "soiling_loss_pct": round(loss, 2),
        "deposition_g_m2": round(dep, 4),
        "cleaning_urgency": round(urgency, 3),
        "days_until_clean_recommended": days_until,
        "confidence": round(confidence, 3),
        # ---- energy / economics
        "power_loss_pct": round(power_loss_pct, 2),
        "energy_value_lost_sar_per_kwp": round(value_lost_day, 4),
        "energy_value_lost_sar_per_kwp_annual": round(value_lost_year, 2),
        "cleaning_break_even_loss_pct": round(break_even_loss_pct, 2),
        "cleaning_cost_sar_per_kwp": cleaning_cost,
        "tariff_sar_per_kwh": tariff,
        "assumed_yield_kwh_per_kwp_day": SPECIFIC_YIELD_KWH_PER_KWP_DAY,
        "soiling_rate_pct_per_day": round(rate, 3),
        # ---- transparency
        "model_prediction_detail": {
            "gbrt": {"soiling_loss_pct": round(loss_g, 3), "deposition_g_m2": round(dep_g, 4)},
            "mlp": {"soiling_loss_pct": round(loss_m, 3), "deposition_g_m2": round(dep_m, 4)},
            "ensemble": "mean of GBRT and MLP",
            "used_measured_aerosol": bool(aq_supplied),
            "out_of_training_range_fraction": round(oor, 3),
        },
    }


def predict_batch(rows, models, **kw):
    return [predict(r, models, **kw) for r in rows]


# --------------------------------------------------------------------------------- demo
def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default=DEFAULT_MODEL_DIR)
    ap.add_argument("--site", default="Dammam")
    ap.add_argument("--pm10", type=float, default=None)
    ap.add_argument("--days-since-clean", type=float, default=6)
    ap.add_argument("--bench", type=int, default=0)
    a = ap.parse_args()

    import time
    models = load_models(a.models)
    feat = {"site": a.site, "days_since_clean": a.days_since_clean}
    if a.pm10 is not None:
        feat["pm10"] = a.pm10
    if a.bench:
        for _ in range(5):
            predict(feat, models)
        t0 = time.perf_counter()
        for _ in range(a.bench):
            predict(feat, models)
        dt = (time.perf_counter() - t0) / a.bench * 1000
        print(f"predict() latency: {dt:.2f} ms/call over {a.bench} calls")
    out = predict(feat, models)
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
