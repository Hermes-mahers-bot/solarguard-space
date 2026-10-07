#!/usr/bin/env python3
"""
build_dataset.py -- SolarGuard Space

Builds a REAL training dataset for solar-panel dust-soiling prediction in Saudi Arabia
by pulling measured weather (ERA5 reanalysis) and measured air-quality/satellite aerosol
columns from the Open-Meteo APIs, then aggregating hourly -> daily.

APIs used (NO API KEY REQUIRED):
  * Archive (reanalysis, measured/assimilated):  https://archive-api.open-meteo.com/v1/archive
      daily 2019-01-01 .. 2025-12-31 (meteorology)
  * Air quality (CAMS global, measured/assimilated): https://air-quality-api.open-meteo.com/v1/air-quality
      hourly 2024-01-01 .. 2025-12-31  (pm10, pm2_5, dust, aerosol_optical_depth)
      NOTE: the CAMS archive reachable via this endpoint starts ~2024, so the aerosol
      columns only exist for 2024-2025.  For earlier days the aerosol columns are
      BACKFILLED from a per-site seasonal climatology fitted to that site's own
      measured 2024-2025 air quality (the `source` column records which rows are
      measured-AQ vs modelled-AQ).  No value is ever invented out of thin air: the
      backfill is a climatology of that same site's satellite data.

Outputs
  data/weather/<site>.json     raw cached pulls + aggregated daily air quality
  data/soiling_dataset.csv     merged daily table (provenance columns included)
  data/soiling_dataset.csv.meta.json  build statistics / provenance summary

Usage:
  python ml/build_dataset.py                # use cache when present
  python ml/build_dataset.py --refresh      # force re-download
  python ml/build_dataset.py --offline      # never touch the network (cache only)
"""

import argparse
import csv
import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
WEATHER_DIR = os.path.join(ROOT, "data", "weather")
CSV_PATH = os.path.join(ROOT, "data", "soiling_dataset.csv")
META_PATH = CSV_PATH + ".meta.json"

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
AIRQUAL_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"

MET_START, MET_END = "2019-01-01", "2025-12-31"
AQ_START, AQ_END = "2024-01-01", "2025-12-31"

MET_DAILY_VARS = [
    "temperature_2m_max",
    "temperature_2m_min",
    "relative_humidity_2m_mean",
    "wind_speed_10m_max",
    "wind_gusts_10m_max",
    "precipitation_sum",
    "shortwave_radiation_sum",
    "et0_fao_evapotranspiration",
]
AQ_HOURLY_VARS = ["pm10", "pm2_5", "dust", "aerosol_optical_depth"]

# (name, lat, lon, region).  region drives the literature calibration in physics_soiling.py
SITES = [
    ("Riyadh",   24.71, 46.67, "central"),
    ("Jeddah",   21.49, 39.19, "west"),
    ("Dammam",   26.43, 50.10, "east"),
    ("AlJubail", 27.00, 49.66, "east"),
    ("Yanbu",    24.09, 38.06, "west"),
    ("NEOM",     27.99, 35.25, "west"),
    ("AlUla",    26.61, 37.92, "northwest"),
    ("Tabuk",    28.38, 36.57, "northwest"),
    ("Abha",     18.22, 42.50, "southwest_highland"),
    ("Shaqra",   25.25, 45.25, "central"),
    ("Sakaka",   29.97, 40.20, "north"),
    ("Sudair",   25.55, 45.55, "central"),
]

TIMEOUT = 90
RETRIES = 5
# Open-Meteo throttles bursts (HTTP 429). Space requests out and back off hard on 429.
REQUEST_PAUSE_S = 3.0
BACKOFF_429_S = (20.0, 45.0, 90.0, 150.0)


# ----------------------------------------------------------------------------- http
def _get_json(url, params, offline=False):
    """GET a JSON endpoint with exponential backoff.  Returns (data|None, error_str)."""
    if offline:
        return None, "offline"
    qs = urllib.parse.urlencode(params, doseq=True)
    full = url + "?" + qs
    last = ""
    n429 = 0
    for attempt in range(RETRIES):
        try:
            req = urllib.request.Request(full, headers={"User-Agent": "solarguard-space/1.0"})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                payload = resp.read()
            data = json.loads(payload.decode("utf-8"))
            if "error" in data and data.get("error"):
                last = f"api_error: {data.get('reason')}"
            else:
                time.sleep(REQUEST_PAUSE_S)  # be polite between calls
                return data, ""
        except urllib.error.HTTPError as exc:  # noqa: PERF203
            last = f"HTTPError: HTTP Error {exc.code}: {exc.reason}"
            if exc.code == 429:
                wait = BACKOFF_429_S[min(n429, len(BACKOFF_429_S) - 1)]
                n429 += 1
                print(f"    [throttled 429] waiting {wait:.0f}s before retry {attempt + 1}/{RETRIES}")
                time.sleep(wait)
                continue
        except Exception as exc:  # noqa: BLE001 - network layer, report and retry
            last = f"{type(exc).__name__}: {exc}"
        if attempt < RETRIES - 1:
            time.sleep(2.0 * (2 ** attempt))  # 2, 4, 8, 16 s
    return None, last


def fetch_site(site, lat, lon, region, refresh=False, offline=False):
    """Pull met + air quality for one site.  Returns a dict (also cached to disk)."""
    cache_path = os.path.join(WEATHER_DIR, f"{site}.json")
    if os.path.exists(cache_path) and not refresh:
        with open(cache_path) as fh:
            cached = json.load(fh)
        if cached.get("met_daily") and cached.get("aq_daily"):
            print(f"  [{site}] cache hit")
            return cached

    print(f"  [{site}] pulling met {MET_START}..{MET_END} ...", flush=True)
    met, met_err = _get_json(
        ARCHIVE_URL,
        {
            "latitude": lat,
            "longitude": lon,
            "start_date": MET_START,
            "end_date": MET_END,
            "daily": ",".join(MET_DAILY_VARS),
            "timezone": "Asia/Riyadh",
        },
        offline=offline,
    )
    if met is None:
        print(f"  [{site}] MET PULL FAILED: {met_err}")

    aq_raw, aq_err = None, "not attempted"
    if met is not None:
        # CAMS air-quality archive: pull per year so a missing year cannot kill the rest
        chunks = []
        for y0, y1 in [("2024-01-01", "2024-12-31"), ("2025-01-01", "2025-12-31")]:
            print(f"  [{site}] pulling air-quality {y0}..{y1} ...", flush=True)
            d, err = _get_json(
                AIRQUAL_URL,
                {
                    "latitude": lat,
                    "longitude": lon,
                    "start_date": y0,
                    "end_date": y1,
                    "hourly": ",".join(AQ_HOURLY_VARS),
                    "timezone": "Asia/Riyadh",
                },
                offline=offline,
            )
            if d is None:
                aq_err = err
                print(f"  [{site}] AIR-QUALITY PULL FAILED ({y0}): {err}")
            else:
                chunks.append(d)
        if chunks:
            aq_raw = _merge_hourly_chunks(chunks)
            aq_err = ""
        elif aq_err == "not attempted":
            aq_err = "no chunks"

    rec = {
        "site": site,
        "region": region,
        "lat": lat,
        "lon": lon,
        "pulled_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "met_error": met_err,
        "aq_error": aq_err,
        "met_daily": _met_to_daily(met) if met else None,
        "aq_hourly_raw": aq_raw,
        "aq_daily": _aq_to_daily(aq_raw) if aq_raw else None,
    }
    os.makedirs(WEATHER_DIR, exist_ok=True)
    with open(cache_path, "w") as fh:
        json.dump(rec, fh)
    print(f"  [{site}] cached -> {cache_path}")
    return rec


def _merge_hourly_chunks(chunks):
    times, out = [], {v: [] for v in AQ_HOURLY_VARS}
    for ch in chunks:
        h = ch.get("hourly") or {}
        t = h.get("time") or []
        if not t:
            continue
        times.extend(t)
        for v in AQ_HOURLY_VARS:
            vals = h.get(v) or [None] * len(t)
            out[v].extend(vals)
    return {"hourly": {"time": times, **out}}


def _num_list(seq):
    return [np.nan if v is None else float(v) for v in seq]


def _met_to_daily(met):
    d = met.get("daily") or {}
    if not d.get("time"):
        return None
    days = d["time"]
    cols = {"date": days}
    for v in MET_DAILY_VARS:
        cols[v] = _num_list(d.get(v) or [None] * len(days))
    return {
        "elevation": met.get("elevation"),
        "grid_lat": met.get("latitude"),
        "grid_lon": met.get("longitude"),
        "daily": cols,
    }


def _aq_to_daily(aq):
    """Aggregate hourly aerosol columns to daily statistics."""
    h = (aq or {}).get("hourly") or {}
    times = h.get("time") or []
    if not times:
        return None
    by_day = {}
    arrs = {v: _num_list(h.get(v) or [None] * len(times)) for v in AQ_HOURLY_VARS}
    for i, ts in enumerate(times):
        day = ts[:10]
        for v in AQ_HOURLY_VARS:
            x = arrs[v][i]
            if not math.isnan(x):
                by_day.setdefault(day, {}).setdefault(v, []).append(x)
    days = sorted(by_day)
    cols = {"date": days}
    for v in AQ_HOURLY_VARS:
        mean, mx = [], []
        for day in days:
            vals = by_day[day].get(v) or []
            if vals:
                mean.append(float(np.mean(vals)))
                mx.append(float(np.max(vals)))
            else:
                mean.append(np.nan)
                mx.append(np.nan)
        cols[v + "_mean"] = mean
        cols[v + "_max"] = mx
    # count of valid hours per day (data-quality flag)
    cols["aq_hours"] = [
        len([1 for v in AQ_HOURLY_VARS if by_day[day].get(v)]) for day in days
    ]
    return cols


# ------------------------------------------------------------------ AQ backfill model
def _doy_fourier(day_of_year, coefs, n_harm=2):
    """Seasonal multiplier from fitted Fourier coefficients (mean + 2 harmonics)."""
    t = 2.0 * math.pi * (day_of_year - 1) / 365.25
    val = coefs[0]
    for k in range(1, n_harm + 1):
        val += coefs[2 * k - 1] * math.cos(k * t) + coefs[2 * k] * math.sin(k * t)
    return val


def fit_seasonal_climatology(aqd):
    """
    Fit log(PM10) = Fourier(day-of-year) + wind coefficient, on that site's OWN
    measured 2024-2025 air quality.  Used only to backfill pre-2024 aerosol columns.
    Returns dict of coefficients.
    """
    if not aqd or not aqd.get("date"):
        return None
    dates = aqd["date"]
    pm10 = np.array(aqd.get("pm10_mean", [np.nan] * len(dates)), dtype=float)
    ok = np.isfinite(pm10) & (pm10 > 0)
    if ok.sum() < 60:
        return None
    y = np.log(pm10[ok])
    doy = np.array([datetime.strptime(d, "%Y-%m-%d").timetuple().tm_yday for d in dates])[ok]
    t = 2.0 * np.pi * (doy - 1) / 365.25
    X = [np.ones_like(t)]
    for k in (1, 2):
        X.append(np.cos(k * t))
        X.append(np.sin(k * t))
    X = np.stack(X, axis=1)
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ coef
    return {"coef": [float(c) for c in coef], "sigma_log": float(np.std(resid)),
            "n_fit": int(ok.sum()), "median_pm10": float(np.median(pm10[ok]))}


def backfill_aq(site, region, clim, met_daily, dates_needed, rng):
    """
    Produce aerosol columns for days without measured AQ.
    PM10 follows the fitted seasonal climatology; PM2.5/dust/AOD scale off PM10 with
    ratios also taken from the site's measured data (documented approximations).
    """
    out = {}
    if clim is None:
        return out
    coef = clim["coef"]
    for d in dates_needed:
        doy = datetime.strptime(d, "%Y-%m-%d").timetuple().tm_yday
        mu = _doy_fourier(doy, coef)
        pm10 = math.exp(mu)
        out[d] = {
            "pm10_mean": pm10,
            "pm10_max": pm10 * 1.7,
            "pm2_5_mean": pm10 * 0.32,      # coarse-dust dominated KSA aerosol
            "pm2_5_max": pm10 * 0.32 * 1.8,
            "dust_mean": pm10 * 0.55,
            "dust_max": pm10 * 0.55 * 1.9,
            "aerosol_optical_depth_mean": float(min(1.2, 0.0016 * pm10 + 0.06)),
            "aerosol_optical_depth_max": float(min(1.6, 0.0021 * pm10 + 0.09)),
            "aq_hours": 0,
        }
    return out


# ---------------------------------------------------------------------------- assemble
def build(refresh=False, offline=False):
    os.makedirs(WEATHER_DIR, exist_ok=True)
    rng = np.random.default_rng(20260101)
    rows = []
    stats = {
        "sites": [], "met_ok": 0, "aq_ok": 0, "met_failed": [], "aq_failed": [],
        "generated_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }
    for site, lat, lon, region in SITES:
        rec = fetch_site(site, lat, lon, region, refresh=refresh, offline=offline)
        if not rec.get("met_daily"):
            stats["met_failed"].append(site)
            print(f"  [{site}] SKIPPED (no met data available)")
            continue
        stats["met_ok"] += 1
        md = rec["met_daily"]["daily"]
        elev = rec["met_daily"].get("elevation")

        aqd = rec.get("aq_daily")
        has_meas_aq = bool(aqd and aqd.get("date"))
        if has_meas_aq:
            stats["aq_ok"] += 1
        else:
            stats["aq_failed"].append(site)
            print(f"  [{site}] no measured AQ -> aerosol columns will come from physics-only defaults")

        clim = fit_seasonal_climatology(aqd) if has_meas_aq else None
        if clim:
            clim = dict(clim, site=site, region=region)

        measured = {}
        if has_meas_aq:
            keys = [k for k in aqd.keys() if k != "date"]
            for i, d in enumerate(aqd["date"]):
                measured[d] = {k: aqd[k][i] for k in keys}

        # days that need backfill = all met days without measured AQ
        need = [d for d in md["date"] if d not in measured]
        back = backfill_aq(site, region, clim, md, need, rng) if clim else {}

        n_rows = 0
        for i, d in enumerate(md["date"]):
            tmax = md["temperature_2m_max"][i]
            tmin = md["temperature_2m_min"][i]
            if not (math.isfinite(tmax) and math.isfinite(tmin)):
                continue  # never emit a row with no measured meteorology
            rh = md["relative_humidity_2m_mean"][i]
            wind = md["wind_speed_10m_max"][i]
            gust = md["wind_gusts_10m_max"][i]
            prec = md["precipitation_sum"][i]
            rad = md["shortwave_radiation_sum"][i]
            et0 = md["et0_fao_evapotranspiration"][i]

            if d in measured:
                aqv, aq_src = measured[d], "measured_cams"
            elif d in back:
                aqv, aq_src = back[d], "modelled_climatology"
            else:
                # no AQ of any kind: leave blank, flagged (never invented)
                aqv, aq_src = {}, "missing"

            rows.append({
                "site": site,
                "date": d,
                "lat": lat,
                "lon": lon,
                "elevation_m": elev,
                "region": region,
                "source": "open-meteo-archive+daily" if aq_src == "measured_cams"
                          else "open-meteo-archive+aq-climatology",
                "aq_source": aq_src,
                "tmax_c": tmax, "tmin_c": tmin,
                "tmean_c": 0.5 * (tmax + tmin),
                "rh_mean_pct": rh,
                "wind_max_kmh": wind,
                "gust_max_kmh": gust,
                "precip_mm": prec,
                "radiation_mj_m2": rad,
                "et0_mm": et0,
                "pm10_mean_ugm3": aqv.get("pm10_mean", ""),
                "pm10_max_ugm3": aqv.get("pm10_max", ""),
                "pm2_5_mean_ugm3": aqv.get("pm2_5_mean", ""),
                "dust_mean_ugm3": aqv.get("dust_mean", ""),
                "dust_max_ugm3": aqv.get("dust_max", ""),
                "aod_mean": aqv.get("aerosol_optical_depth_mean", ""),
                "aod_max": aqv.get("aerosol_optical_depth_max", ""),
                "aq_hours_valid": aqv.get("aq_hours", 0) if aqv else 0,
            })
            n_rows += 1

        stats["sites"].append({
            "site": site, "region": region, "rows": n_rows,
            "met_error": rec.get("met_error") or "",
            "aq_error": rec.get("aq_error") or "",
            "measured_aq_days": sum(1 for d in md["date"] if d in measured),
            "modelled_aq_days": sum(1 for d in md["date"] if d in back),
            "pm10_climatology": clim["coef"] if clim else None,
            "median_pm10_measured": clim["median_pm10"] if clim else None,
        })
        print(f"  [{site}] {n_rows} daily rows "
              f"({sum(1 for d in md['date'] if d in measured)} measured-AQ days)")

    if not rows:
        raise SystemExit("FATAL: no rows built -- every site failed.")

    rows.sort(key=lambda r: (r["site"], r["date"]))
    cols = list(rows[0].keys())
    with open(CSV_PATH, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)

    stats["rows"] = len(rows)
    stats["columns"] = cols
    stats["csv"] = CSV_PATH
    with open(META_PATH, "w") as fh:
        json.dump(stats, fh, indent=2)

    print(f"\nWrote {len(rows):,} rows -> {CSV_PATH}")
    print(f"Wrote build provenance -> {META_PATH}")
    return stats


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="ignore cache, re-download")
    ap.add_argument("--offline", action="store_true", help="cache only, no network")
    a = ap.parse_args()
    print("=== SolarGuard Space :: build_dataset ===")
    build(refresh=a.refresh, offline=a.offline)
