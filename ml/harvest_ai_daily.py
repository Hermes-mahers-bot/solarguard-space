#!/usr/bin/env python3
"""Harvest the SolarGuard AI training archive: data/ai/daily.csv.

One row per Saudi solar site per day, 2022-08-01 .. 2026-10-07.

Sources (all keyless, verified 2026-10-07):
  1. Open-Meteo archive DAILY  -> weather (NASA/ERA5). One request per site for
     the whole range. wind_speed_unit=ms is mandatory or wind silently becomes km/h.
  2. Open-Meteo archive HOURLY -> relative_humidity_2m (the daily set has none),
     fetched in ~90-day windows and averaged per day.
  3. Open-Meteo air-quality HOURLY (CAMS) -> pm10, dust, aerosol_optical_depth,
     pm2_5, fetched in ~90-day windows and aggregated per day.

Rules:
  * RAW_COLS order/names come from ml/ai_features.py.
  * Retry each request up to 3 times with backoff on timeout/5xx.
  * A failed window NEVER yields fabricated zeros: the affected days are simply
    absent from the CSV and every missing window is listed in the report.
  * Every raw JSON response is kept under data/ai/raw/ (provenance).
"""
from __future__ import annotations

import csv
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

ROOT = "/home/hermes2/solarguard-space"
sys.path.insert(0, os.path.join(ROOT, "backend"))
sys.path.insert(0, os.path.join(ROOT, "ml"))

from sg_config import SITES          # noqa: E402  (12 sites)
from ai_features import RAW_COLS     # noqa: E402  exact header

from statistics import mean as _mean

START = "2022-08-01"
END = "2026-10-07"
WINDOW_DAYS = 90
RAW_DIR = os.path.join(ROOT, "data", "ai", "raw")
OUT_CSV = os.path.join(ROOT, "data", "ai", "daily.csv")
OUT_REPORT = os.path.join(ROOT, "data", "ai", "harvest_report.json")

WEATHER_DAILY_VARS = ("shortwave_radiation_sum,temperature_2m_max,temperature_2m_min,"
                      "temperature_2m_mean,wind_speed_10m_max,wind_gusts_10m_max,"
                      "precipitation_sum,wind_direction_10m_dominant")
AQ_VARS = "pm10,dust,aerosol_optical_depth,pm2_5"

WEATHER_URL = ("https://archive-api.open-meteo.com/v1/archive?latitude={lat}&longitude={lon}"
               "&start_date={s}&end_date={e}&daily=" + WEATHER_DAILY_VARS +
               "&timezone=UTC&wind_speed_unit=ms")
RH_URL = ("https://archive-api.open-meteo.com/v1/archive?latitude={lat}&longitude={lon}"
          "&start_date={s}&end_date={e}&hourly=relative_humidity_2m&timezone=UTC")
AQ_URL = ("https://air-quality-api.open-meteo.com/v1/air-quality?latitude={lat}&longitude={lon}"
          "&start_date={s}&end_date={e}&hourly=" + AQ_VARS + "&timezone=UTC")

os.makedirs(RAW_DIR, exist_ok=True)
MISSING_WINDOWS = []          # list of dicts
DROPPED_VARIABLES = []        # list of dicts
FETCH_COUNT = {"hit": 0, "cache": 0, "fail": 0}


def _get(url: str, cache_name: str, attempts: int = 3):
    """GET with cache + retry/backoff. Returns (json_dict_or_None, error_str_or_None)."""
    path = os.path.join(RAW_DIR, cache_name)
    if os.path.exists(path) and os.path.getsize(path) > 2:
        try:
            with open(path) as fh:
                return json.load(fh), None
        except Exception:
            pass  # corrupt cache -> refetch
    last = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "SolarGuardSpace/1.0 harvest"})
            with urllib.request.urlopen(req, timeout=60) as r:
                body = r.read()
            data = json.loads(body)
            if isinstance(data, dict) and data.get("error"):
                last = f"API error: {data.get('reason')}"
            else:
                with open(path, "wb") as fh:
                    fh.write(body)
                FETCH_COUNT["hit"] += 1
                return data, None
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
            if e.code < 500 and e.code not in (408, 429):
                break  # 4xx non-retryable (e.g. bad parameter)
        except Exception as e:  # noqa: BLE001
            last = f"{type(e).__name__}: {e}"
        if i < attempts - 1:
            time.sleep(2 ** (i + 1))
    FETCH_COUNT["fail"] += 1
    return None, last


def windows(start: str, end: str, step: int):
    d = datetime.strptime(start, "%Y-%m-%d").date()
    e = datetime.strptime(end, "%Y-%m-%d").date()
    out = []
    while d <= e:
        w_end = min(d + timedelta(days=step - 1), e)
        out.append((d.isoformat(), w_end.isoformat()))
        d = w_end + timedelta(days=1)
    return out


def _fnum(v):
    if v is None or v == "":
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x


def agg_hourly_to_daily(times, series_map):
    """Aggregate hourly series to per-day stats.

    series_map: {"pm10": [...], "dust": [...], ...}
    Returns {date: {"<key>_max":.., "<key>_mean":.., "<key>_n":int}}.
    Only days with at least one non-null value are returned.
    """
    days = {}
    for i, ts in enumerate(times):
        d = ts[:10]
        slot = days.setdefault(d, {})
        for key, arr in series_map.items():
            val = arr[i] if i < len(arr) else None
            v = _fnum(val)
            if v is None:
                continue
            slot.setdefault(f"{key}__vals", []).append(v)
    out = {}
    for d, slot in days.items():
        rec = {}
        for key in series_map:
            vals = slot.get(f"{key}__vals", [])
            if not vals:
                continue
            rec[f"{key}_max"] = max(vals)
            rec[f"{key}_mean"] = _mean(vals)
            rec[f"{key}_n"] = len(vals)
        if rec:
            out[d] = rec
    return out


def run(site_filter=None):
    sites = [s for s in SITES if not site_filter or s["id"] in site_filter]
    rows = []
    site_meta = {}

    for si, s in enumerate(sites, 1):
        sid, lat, lon = s["id"], s["lat"], s["lon"]
        print(f"[{si}/{len(sites)}] {sid} ({lat},{lon})", flush=True)

        # ---- 1. weather daily: one request for the whole range
        url = WEATHER_URL.format(lat=lat, lon=lon, s=START, e=END)
        cname = f"met_{sid}_{START}_{END}.json"
        w, err = _get(url, cname)
        elev = None
        weather = {}          # date -> dict of RAW columns
        if w and "daily" in w:
            elev = _fnum(w.get("elevation"))
            dly = w["daily"]
            t = dly["time"]
            cols = {
                "ghi_mj_m2": dly.get("shortwave_radiation_sum"),
                "tmax_c": dly.get("temperature_2m_max"),
                "tmin_c": dly.get("temperature_2m_min"),
                "tmean_c": dly.get("temperature_2m_mean"),
                "wind_max_ms": dly.get("wind_speed_10m_max"),
                "gust_max_ms": dly.get("wind_gusts_10m_max"),
                "precip_mm": dly.get("precipitation_sum"),
                "wind_dir_deg": dly.get("wind_direction_10m_dominant"),
            }
            for i, d in enumerate(t):
                weather[d] = {k: _fnum(v[i] if i < len(v) else None) for k, v in cols.items()}
        else:
            MISSING_WINDOWS.append({"site": sid, "kind": "weather_daily",
                                    "start": START, "end": END, "error": err})

        # ---- 2. relative humidity, hourly in windows
        rh = {}               # date -> mean
        for (ws, we) in windows(START, END, WINDOW_DAYS):
            u = RH_URL.format(lat=lat, lon=lon, s=ws, e=we)
            data, err = _get(u, f"rh_{sid}_{ws}_{we}.json")
            if not data or "hourly" not in data:
                MISSING_WINDOWS.append({"site": sid, "kind": "rh_hourly",
                                        "start": ws, "end": we, "error": err})
                continue
            daily = agg_hourly_to_daily(data["hourly"]["time"],
                                        {"relative_humidity_2m": data["hourly"]["relative_humidity_2m"]})
            for d, rec in daily.items():
                if "relative_humidity_2m_mean" in rec:
                    rh[d] = rec["relative_humidity_2m_mean"]
        print(f"    humidity windows done; rh days={len(rh)}", flush=True)

        # ---- 3. CAMS air quality, hourly in windows
        aq = {}               # date -> dict with pm10_max/pm10_mean/...
        for (ws, we) in windows(START, END, WINDOW_DAYS):
            u = AQ_URL.format(lat=lat, lon=lon, s=ws, e=we)
            data, err = _get(u, f"aq_{sid}_{ws}_{we}.json")
            if not data or "hourly" not in data:
                MISSING_WINDOWS.append({"site": sid, "kind": "aq_hourly",
                                        "start": ws, "end": we, "error": err})
                continue
            h = data["hourly"]
            daily = agg_hourly_to_daily(h["time"], {
                "pm10": h.get("pm10", []),
                "dust": h.get("dust", []),
                "aod": h.get("aerosol_optical_depth", []),
                "pm25": h.get("pm2_5", []),
            })
            aq.update(daily)
        print(f"    air-quality windows done; aq days={len(aq)}", flush=True)

        # ---- assemble one row per weather day (the spine), sorted by date
        nrows = 0
        for d in sorted(weather.keys()):
            wd = weather[d]
            a = aq.get(d, {})
            row = {
                "site": sid, "date": d, "lat": lat, "lon": lon, "elevation_m": elev,
                "ghi_mj_m2": wd.get("ghi_mj_m2"), "tmax_c": wd.get("tmax_c"),
                "tmin_c": wd.get("tmin_c"), "tmean_c": wd.get("tmean_c"),
                "rh_mean_pct": rh.get(d),
                "wind_max_ms": wd.get("wind_max_ms"), "gust_max_ms": wd.get("gust_max_ms"),
                "precip_mm": wd.get("precip_mm"), "wind_dir_deg": wd.get("wind_dir_deg"),
                "pm10_max": a.get("pm10_max"), "pm10_mean": a.get("pm10_mean"),
                "dust_max": a.get("dust_max"), "dust_mean": a.get("dust_mean"),
                "aod_max": a.get("aod_max"), "aod_mean": a.get("aod_mean"),
                "pm25_mean": a.get("pm25_mean"),
            }
            rows.append(row)
            nrows += 1
        site_meta[sid] = {"id": sid, "name": s["name"], "lat": lat, "lon": lon,
                          "elevation_m": elev, "weather_days": len(weather),
                          "rh_days": len(rh), "aq_days": len(aq),
                          "rows": nrows,
                          "first_date": min(weather) if weather else None,
                          "last_date": max(weather) if weather else None}

    rows.sort(key=lambda r: (r["site"], r["date"]))
    return rows, site_meta


def write_csv(rows):
    os.makedirs(os.path.dirname(OUT_CSV), exist_ok=True)
    with open(OUT_CSV, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=RAW_COLS)
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in RAW_COLS})


def build_report(rows, site_meta):
    n = len(rows)
    seen = set()
    dups = 0
    for r in rows:
        key = (r["site"], r["date"])
        if key in seen:
            dups += 1
        seen.add(key)

    def col_vals(col):
        return [r[col] for r in rows if r.get(col) is not None]

    def stats(col):
        v = col_vals(col)
        if not v:
            return None
        return {"min": min(v), "mean": sum(v) / len(v), "max": max(v), "nonnull": len(v)}

    col_pct = {}
    for c in RAW_COLS:
        nn = sum(1 for r in rows if r.get(c) is not None and r.get(c) != "")
        col_pct[c] = round(100.0 * nn / n, 3) if n else 0.0

    per_site = {}
    for sid, m in site_meta.items():
        srows = [r for r in rows if r["site"] == sid]
        p10 = [r["pm10_max"] for r in srows if r.get("pm10_max") is not None]
        storm_pm10 = sum(1 for v in p10 if v >= 200.0)
        storm_label = sum(1 for r in srows
                          if (r.get("pm10_max") or 0) >= 200.0 or (r.get("dust_max") or 0) >= 100.0)
        per_site[sid] = {
            **{k: m[k] for k in ("name", "lat", "lon", "elevation_m")},
            "rows": len(srows),
            "first_date": srows[0]["date"] if srows else None,
            "last_date": srows[-1]["date"] if srows else None,
            "pm10_max_days": len(p10),
            "storm_days_pm10_ge200": storm_pm10,
            "storm_days_label_pm10ge200_or_dustge100": storm_label,
        }

    all_p10 = col_vals("pm10_max")
    report = {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "requested_range": {"start": START, "end": END},
        "sites_requested": len(SITES),
        "rows": n,
        "unique_site_date": len(seen),
        "duplicate_site_date": dups,
        "overall": {
            "storm_days_pm10_ge200": sum(1 for v in all_p10 if v >= 200.0),
            "storm_days_label_pm10ge200_or_dustge100": sum(
                1 for r in rows
                if (r.get("pm10_max") or 0) >= 200.0 or (r.get("dust_max") or 0) >= 100.0),
            "pm10_max": stats("pm10_max"),
            "ghi_mj_m2": stats("ghi_mj_m2"),
            "gust_max_ms": stats("gust_max_ms"),
        },
        "column_nonnull_pct": col_pct,
        "per_site": per_site,
        "dropped_variables": DROPPED_VARIABLES,
        "missing_windows": MISSING_WINDOWS,
        "fetch_counts": FETCH_COUNT,
        "api": {
            "weather_daily": WEATHER_URL,
            "rh_hourly": RH_URL,
            "air_quality_hourly": AQ_URL,
            "window_days": WINDOW_DAYS,
            "air_quality_vars_requested": AQ_VARS,
            "weather_daily_vars_requested": WEATHER_DAILY_VARS,
        },
        "notes": [
            "site key = sg_config.SITES 'id'; sg_config has no elevation_m field, so "
            "elevation_m is the grid elevation returned by the Open-Meteo weather request.",
            "CAMS air-quality history was observed to begin ~2022-08-04 (2022-08-01..03 "
            "came back all-null), so the first few days of the requested range have no dust data.",
        ],
    }
    with open(OUT_REPORT, "w") as fh:
        json.dump(report, fh, indent=2)
    return report


if __name__ == "__main__":
    flt = None
    if "--sites" in sys.argv:
        flt = set(sys.argv[sys.argv.index("--sites") + 1].split(","))
    t0 = time.time()
    rows, meta = run(site_filter=flt)
    write_csv(rows)
    rep = build_report(rows, meta)
    print(f"\nDONE rows={len(rows)} in {time.time()-t0:.0f}s "
          f"fetch={FETCH_COUNT} missing_windows={len(MISSING_WINDOWS)}")
    print(f"CSV  -> {OUT_CSV} ({os.path.getsize(OUT_CSV)} bytes)")
    print(f"REP  -> {OUT_REPORT} ({os.path.getsize(OUT_REPORT)} bytes)")
