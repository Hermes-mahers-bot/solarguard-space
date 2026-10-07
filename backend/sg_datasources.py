"""
SolarGuard Space — live data layer.

Every number the dashboard and the AI assistant show comes through here. All
sources are either openly licensed or read from a key held in backend/.env;
nothing is mocked, and every pull is cached on disk with a TTL so the site stays
fast and the upstream APIs stay polite.

Sources actually used
---------------------
Open-Meteo        forecast + air-quality + satellite radiation   (open, no key)
NASA POWER        hourly/daily satellite meteorology             (open, no key)
NASA GIBS         MODIS/MAIAC/AIRS/MERRA-2 raster tiles (WMTS)   (open, no key)
NOAA S3           Himawari-9 + GFS bucket listings               (open, no key)
ECMWF open data   forecast index listing                         (open, no key)
AERONET           station list for ground-truth AOD              (open, no key)
Key-gated ones (Copernicus CAMS/ADS, Sentinel-5P, MERRA-2 GES DISC, NREL NSRDB,
JAXA P-Tree, Copernicus EMS) are recorded with their required env var in
docs/DATA_SOURCES.md and probed so their status is visible, never faked.
"""
from __future__ import annotations

import asyncio
import io
import json
import math
import time
from datetime import date, datetime, timedelta, timezone

import httpx

from sg_config import (CACHE, DATA, DEEPSEEK_BASE, DEEPSEEK_KEY, GIBS_BASE,
                       GIBS_LAYERS, HTTP_TIMEOUT, HTTP_USER_AGENT, KSA_BBOX,
                       SITES)

RIYADH = timezone(timedelta(hours=3))

# ------------------------------------------------------------------ cache
_mem: dict[str, tuple[float, object]] = {}


def _cache_path(key: str):
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in key)[:120]
    return CACHE / f"{safe}.json"


def cache_get(key: str, ttl: float):
    now = time.time()
    hit = _mem.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    p = _cache_path(key)
    try:
        blob = json.loads(p.read_text())
        if now - blob["ts"] < ttl:
            _mem[key] = (blob["ts"], blob["value"])
            return blob["value"]
    except Exception:
        pass
    return None


def cache_set(key: str, value):
    ts = time.time()
    _mem[key] = (ts, value)
    try:
        _cache_path(key).write_text(json.dumps({"ts": ts, "value": value}))
    except Exception:
        pass


async def _get_json(url: str, params: dict | None = None, headers: dict | None = None):
    h = {"User-Agent": HTTP_USER_AGENT}
    if headers:
        h.update(headers)
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True) as c:
        r = await c.get(url, params=params, headers=h)
        r.raise_for_status()
        return r.json()


# ------------------------------------------------------------------ open-meteo
FORECAST_HOURLY = (
    "temperature_2m,relative_humidity_2m,dew_point_2m,wind_speed_10m,wind_gusts_10m,"
    "wind_direction_10m,precipitation,shortwave_radiation,direct_normal_irradiance,"
    "diffuse_radiation,cloud_cover,apparent_temperature"
)
AIR_HOURLY = "pm10,pm2_5,dust,aerosol_optical_depth,uv_index"
FORECAST_DAILY = (
    "temperature_2m_max,temperature_2m_min,relative_humidity_2m_mean,wind_speed_10m_max,"
    "wind_gusts_10m_max,precipitation_sum,shortwave_radiation_sum,"
    "et0_fao_evapotranspiration,sunshine_duration"
)


async def openmeteo_forecast(lat: float, lon: float, days: int = 7, ttl: float = 900):
    """Weather + sun + dust forecast for one point, hourly, Riyadh local time."""
    days = max(1, min(int(days), 16))
    key = f"om_fc_{lat:.3f}_{lon:.3f}_{days}"
    if (v := cache_get(key, ttl)) is not None:
        return v
    # the air-quality endpoint caps its forecast at 7 days, and is allowed to
    # fail without taking the weather down with it
    aq_days = max(1, min(days, 7))
    w_res, a_res = await asyncio.gather(
        _get_json("https://api.open-meteo.com/v1/forecast", {
            "latitude": lat, "longitude": lon, "hourly": FORECAST_HOURLY,
            "daily": FORECAST_DAILY, "forecast_days": days,
            "timezone": "Asia/Riyadh", "wind_speed_unit": "ms"}),
        _get_json("https://air-quality-api.open-meteo.com/v1/air-quality", {
            "latitude": lat, "longitude": lon, "hourly": AIR_HOURLY,
            "forecast_days": aq_days, "timezone": "Asia/Riyadh"}),
        return_exceptions=True,
    )
    if isinstance(w_res, Exception):
        raise w_res
    w = w_res
    a = a_res if isinstance(a_res, dict) else {}
    aq_error = None if isinstance(a_res, dict) else f"{type(a_res).__name__}: {a_res}"
    hours = w.get("hourly", {})
    ah = a.get("hourly", {})
    n = len(hours.get("time", []))
    # air quality only forecasts 7 days; beyond that we persist the last known
    # value and flag it, rather than pretending to know the dust load
    last_aq: dict = {}
    rows = []
    for i in range(n):
        def g(k):
            src = ah if k in ah else hours
            arr = src.get(k) or []
            v = arr[i] if i < len(arr) else None
            if v is None and k in last_aq:
                return last_aq[k]
            if k in ("pm10", "pm2_5", "dust_ugm3", "aod") and v is not None:
                last_aq[k] = v
            return v
        def g_raw(k):
            arr = (ah if k in ah else hours).get(k) or []
            return arr[i] if i < len(arr) else None
        rows.append({
            "time": hours["time"][i],
            "temp_c": g("temperature_2m"),
            "rh_pct": g("relative_humidity_2m"),
            "dewpoint_c": g("dew_point_2m"),
            "wind_ms": g("wind_speed_10m"),
            "gust_ms": g("wind_gusts_10m"),
            "wind_dir": g("wind_direction_10m"),
            "precip_mm": g("precipitation"),
            "ghi_wm2": g("shortwave_radiation"),
            "dni_wm2": g("direct_normal_irradiance"),
            "dhi_wm2": g("diffuse_radiation"),
            "cloud_pct": g("cloud_cover"),
            "pm10": g("pm10"),
            "pm2_5": g("pm2_5"),
            "dust_ugm3": g("dust"),
            "aod": g("aerosol_optical_depth"),
            "aq_measured": g_raw("dust") is not None,
        })
    out = {
        "source": "Open-Meteo forecast + air-quality API (CC-BY-4.0, no key)",
        "latitude": lat, "longitude": lon, "timezone": "Asia/Riyadh",
        "elevation_m": w.get("elevation"),
        "hourly": rows,
        "daily": (w.get("daily") or {}),
        "aq_horizon_days": aq_days,
        "aq_error": aq_error,
        "fetched_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    cache_set(key, out)
    return out


async def openmeteo_archive_daily(lat: float, lon: float, start: str, end: str, ttl: float = 86400):
    """Historical daily met for a point (used for the site-vs-site reference)."""
    key = f"om_ar_{lat:.3f}_{lon:.3f}_{start}_{end}"
    if (v := cache_get(key, ttl)) is not None:
        return v
    j = await _get_json("https://archive-api.open-meteo.com/v1/archive", {
        "latitude": lat, "longitude": lon, "start_date": start, "end_date": end,
        "daily": FORECAST_DAILY, "timezone": "Asia/Riyadh", "wind_speed_unit": "ms"})
    cache_set(key, j)
    return j


async def openmeteo_satellite_radiation(lat: float, lon: float, lat_ok=None):
    """Open-Meteo satellite radiation (EUMETSAT/MSG-derived) — independent of
    ground stations, useful to cross-check the irradiance forecast."""
    day = (datetime.now(RIYADH) - timedelta(days=3)).date().isoformat()
    key = f"om_sat_{lat:.2f}_{lon:.2f}_{day}"
    if (v := cache_get(key, 3600)) is not None:
        return v
    try:
        j = await _get_json("https://satellite-api.open-meteo.com/v1/archive", {
            "latitude": lat, "longitude": lon, "hourly": "shortwave_radiation",
            "start_date": day, "end_date": day, "timezone": "Asia/Riyadh"})
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}", "source": "satellite-api.open-meteo.com"}
    cache_set(key, j)
    return j


# ------------------------------------------------------------------ NASA POWER
async def power_larc_daily(lat: float, lon: float, start: str, end: str, ttl: float = 86400):
    key = f"power_{lat:.2f}_{lon:.2f}_{start}_{end}"
    if (v := cache_get(key, ttl)) is not None:
        return v
    url = "https://power.larc.nasa.gov/api/temporal/daily/point"
    params = {"parameters": "T2M,RH2M,WS10M,PRECTOTCORR,ALLSKY_SFC_SW_DWN",
              "community": "RE", "longitude": lon, "latitude": lat,
              "start": start, "end": end, "format": "JSON"}
    j = await _get_json(url, params)
    cache_set(key, j)
    return j


# ------------------------------------------------------------------ AERONET
async def aeronet_stations(ttl: float = 604800):
    key = "aeronet_sites_v3"
    if (v := cache_get(key, ttl)) is not None:
        return v
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        r = await c.get("https://aeronet.gsfc.nasa.gov/aeronet_locations_v3.txt",
                        headers={"User-Agent": HTTP_USER_AGENT})
        r.raise_for_status()
        text = r.text
    stations = []
    for line in text.splitlines()[2:]:
        parts = line.split(",")
        if len(parts) < 4:
            continue
        try:
            stations.append({"name": parts[0].strip(), "lon": float(parts[1]),
                             "lat": float(parts[2]), "elev_m": float(parts[3])})
        except ValueError:
            continue
    out = {"source": "AERONET v3 site list (NASA, open)", "count": len(stations),
           "stations": stations}
    cache_set(key, out)
    return out


def _haversine(a_lat, a_lon, b_lat, b_lon):
    R = 6371.0
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp = math.radians(b_lat - a_lat)
    dl = math.radians(b_lon - a_lon)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


async def aeronet_nearest(lat: float, lon: float, k: int = 3, max_km: float = 1500):
    st = await aeronet_stations()
    scored = []
    for s in st["stations"]:
        d = _haversine(lat, lon, s["lat"], s["lon"])
        if d <= max_km:
            scored.append({**s, "distance_km": round(d, 1)})
    scored.sort(key=lambda s: s["distance_km"])
    in_ksa = [s for s in scored if (KSA_BBOX["south"] <= s["lat"] <= KSA_BBOX["north"]
                                     and KSA_BBOX["west"] <= s["lon"] <= KSA_BBOX["east"])]
    return {"source": "AERONET v3 site list (NASA, open)",
            "total_stations_worldwide": st["count"],
            "nearest": scored[:k], "inside_saudi": in_ksa[:8],
            "note": "AERONET level-1.5/2.0 data downloads require a free NASA login; only the open site list is used here."}


# ------------------------------------------------------------------ NASA GIBS
TILE_SIZE = 256          # GIBS WMTS tile edge in pixels


def _gibs_url(layer: str, tms: str, day: str, z: int, x: int, y: int) -> str:
    return f"{GIBS_BASE}/{layer}/default/{day}/{tms}/{z}/{y}/{x}.png"


async def gibs_tile(layer: str, day: str, z: int, x: int, y: int):
    """Fetch one GIBS tile, walking back in time until imagery exists.

    MODIS/AIRS layers are daily and have gaps (clouds, orbit coverage); MERRA-2
    layers are monthly. So we retry the same day-of-month on earlier days and
    snap monthly layers to the 1st. Returns (bytes, effective_day, content_type)
    or (None, None, None) when nothing is available.
    """
    meta = next((l for l in GIBS_LAYERS if l["id"] == layer), None)
    if meta is None:
        return None, None, None
    tms = meta["tms"]
    candidates = []
    try:
        d0 = datetime.strptime(day, "%Y-%m-%d").date()
    except ValueError:
        d0 = datetime.now(RIYADH).date()
    if meta["kind"] == "monthly":
        m = d0.replace(day=1)
        for _ in range(0, 25):
            candidates.append(m.isoformat())
            m = (m - timedelta(days=1)).replace(day=1)
    else:
        for back in range(0, 21):
            candidates.append((d0 - timedelta(days=back)).isoformat())
    key = f"gibs_{layer}_{day}_{z}_{x}_{y}"
    cached = cache_get(key, 604800)
    if cached is not None:
        return (bytes.fromhex(cached["hex"]), cached["day"], "image/png") if cached.get("hex") else (None, None, None)
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True) as c:
        for cand in candidates:
            try:
                r = await c.get(_gibs_url(layer, tms, cand, z, x, y),
                                headers={"User-Agent": HTTP_USER_AGENT})
                if r.status_code == 200 and len(r.content) > 100:
                    cache_set(key, {"day": cand, "hex": r.content.hex()})
                    return r.content, cand, r.headers.get("content-type", "image/png")
            except Exception:
                continue
    cache_set(key, {"hex": None})
    return None, None, None


async def gibs_mosaic(layer: str, day: str, lat: float, lon: float, zoom: int,
                      width: int, height: int, fmt: str = "JPEG"):
    """Stitch GIBS tiles into one image centred on (lat, lon).

    A single 256 px tile stretched across a page looks like a blurry screenshot;
    a stitched mosaic looks like a satellite view. Returns (bytes, image_format,
    effective_date) or (None, None, None). Cached on disk because the same view
    is requested on every page load.
    """
    from datetime import datetime as _dt

    from PIL import Image

    zoom = int(max(3, min(9, zoom)))
    width = int(max(160, min(2048, width)))
    height = int(max(120, min(1400, height)))
    day = day or datetime.now(RIYADH).date().isoformat()
    key = f"mosaic_{layer}_{day}_{lat:.3f}_{lon:.3f}_{zoom}_{width}x{height}"
    if (v := cache_get(key, 604800)) is not None:
        import base64
        return base64.b64decode(v["b64"]), v["fmt"], v["day"]

    meta = next((l for l in GIBS_LAYERS if l["id"] == layer), None)
    if meta is None:
        return None, None, None
    tms = meta["tms"]

    # pixel-space window in the WMTS grid
    scale = TILE_SIZE * (2 ** zoom)
    cpx = (lon + 180.0) / 360.0 * scale
    s = math.sin(math.radians(lat))
    cpy = (0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)) * scale
    x0, y0 = cpx - width / 2.0, cpy - height / 2.0
    tx0, ty0 = int(x0 // TILE_SIZE), int(y0 // TILE_SIZE)
    tx1, ty1 = int((x0 + width) // TILE_SIZE), int((y0 + height) // TILE_SIZE)
    if (tx1 - tx0 + 1) * (ty1 - ty0 + 1) > 64:
        return None, None, None

    canvas = Image.new("RGB", ((tx1 - tx0 + 1) * TILE_SIZE, (ty1 - ty0 + 1) * TILE_SIZE), (6, 11, 22))
    eff_day = None
    sem = asyncio.Semaphore(4)

    async def one(tx, ty):
        nonlocal eff_day
        async with sem:
            data, eff, _ = await gibs_tile(layer, day, zoom, tx, ty)
        if data is None:
            return
        eff_day = eff_day or eff
        try:
            tile_img = Image.open(io.BytesIO(data)).convert("RGBA")
        except Exception:
            return
        canvas.paste(tile_img, ((tx - tx0) * TILE_SIZE, (ty - ty0) * TILE_SIZE), tile_img)

    await asyncio.gather(*(one(tx, ty) for tx in range(tx0, tx1 + 1) for ty in range(ty0, ty1 + 1)))

    left, top = int(round(x0 - tx0 * TILE_SIZE)), int(round(y0 - ty0 * TILE_SIZE))
    crop = canvas.crop((left, top, left + width, top + height))
    buf = io.BytesIO()
    if fmt.upper() == "PNG":
        crop.save(buf, "PNG", optimize=True)
        out_fmt = "PNG"
    else:
        crop.save(buf, "JPEG", quality=88, optimize=True)
        out_fmt = "JPEG"
    payload = buf.getvalue()
    import base64
    cache_set(key, {"b64": base64.b64encode(payload).decode(), "fmt": out_fmt,
                    "day": eff_day or day, "bytes": len(payload)})
    return payload, out_fmt, (eff_day or day)


def gibs_available_dates():
    """The newest sensible date per layer, based on the capabilities defaults we
    parsed (data is published with a 1-3 day latency)."""
    today = datetime.now(RIYADH).date()
    nightly = (today - timedelta(days=3)).isoformat()
    monthly = today.replace(day=1).isoformat()
    return {l["id"]: (monthly if l["kind"] == "monthly" else nightly) for l in GIBS_LAYERS}


# ------------------------------------------------------------------ open buckets
async def s3_listing(bucket: str, prefix: str = "", max_keys: int = 5, ttl: float = 900):
    key = f"s3_{bucket}_{prefix}_{max_keys}"
    if (v := cache_get(key, ttl)) is not None:
        return v
    url = f"https://{bucket}.s3.amazonaws.com/"
    params = {"list-type": "2", "max-keys": max_keys}
    if prefix:
        params["prefix"] = prefix
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        r = await c.get(url, params=params, headers={"User-Agent": HTTP_USER_AGENT})
    out = {"bucket": bucket, "prefix": prefix, "status": r.status_code,
           "bytes": len(r.content), "keys": []}
    if r.status_code == 200:
        import re
        out["keys"] = re.findall(r"<Key>([^<]+)</Key>", r.text)[:max_keys]
    cache_set(key, out)
    return out


async def ecmwf_open_listing(ttl: float = 1800):
    key = "ecmwf_open_listing"
    if (v := cache_get(key, ttl)) is not None:
        return v
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
            r = await c.get("https://data.ecmwf.int/forecasts/",
                            headers={"User-Agent": HTTP_USER_AGENT})
        import re
        runs = sorted(set(re.findall(r"(\d{8})/", r.text)))[-3:]
        out = {"source": "ECMWF open data (data.ecmwf.int)", "status": r.status_code,
               "latest_runs": runs}
    except Exception as e:
        out = {"source": "ECMWF open data (data.ecmwf.int)",
               "status": None, "error": f"{type(e).__name__}: {e}"}
    cache_set(key, out)
    return out


# ------------------------------------------------------------------ registry
# One row per source, with the live probe that decides its status colour on the
# dashboard. `access` is 'open' or the env var that unlocks it.
SOURCE_REGISTRY = [
    {"id": "openmeteo", "name": "Open-Meteo Forecast API", "access": "open",
     "url": "https://api.open-meteo.com/v1/forecast?latitude=24.71&longitude=46.67&hourly=temperature_2m&forecast_days=1",
     "provides": "hourly weather, wind, gusts, rain, humidity", "used_for": "cleaning & performance forecast"},
    {"id": "openmeteo_air", "name": "Open-Meteo Air Quality (CAMS-derived)", "access": "open",
     "url": "https://air-quality-api.open-meteo.com/v1/air-quality?latitude=24.71&longitude=46.67&hourly=dust,aerosol_optical_depth&forecast_days=1",
     "provides": "dust, PM10, PM2.5, aerosol optical depth forecasts", "used_for": "dust-event detection, soiling input"},
    {"id": "openmeteo_sat", "name": "Open-Meteo Satellite Radiation", "access": "open",
     "url": "https://satellite-api.open-meteo.com/v1/archive?latitude=24.71&longitude=46.67&hourly=shortwave_radiation&start_date=2026-01-01&end_date=2026-01-01",
     "provides": "satellite-derived irradiance", "used_for": "cross-checking solar resource"},
    {"id": "power", "name": "NASA POWER (LARC)", "access": "open",
     "url": "https://power.larc.nasa.gov/api/temporal/daily/point?parameters=T2M&community=RE&latitude=24.71&longitude=46.67&start=20260101&end=20260102&format=JSON",
     "provides": "satellite/reanalysis meteorology, long history", "used_for": "site climatology"},
    {"id": "gibs_modis", "name": "NASA GIBS — MODIS aerosol (Terra)", "access": "open",
     "probe": "gibs:MODIS_Terra_Aerosol", "url": f"{GIBS_BASE}/MODIS_Terra_Aerosol/default/2026-01-01/GoogleMapsCompatible_Level6/4/6/10.png",
     "provides": "daily aerosol optical depth imagery", "used_for": "map layer: dust/aerosol plume tracking"},
    {"id": "gibs_merra2", "name": "NASA GIBS — MERRA-2 dust", "access": "open",
     "probe": "gibs:MERRA2_Dust_Surface_Mass_Concentration_Monthly", "url": f"{GIBS_BASE}/MERRA2_Dust_Surface_Mass_Concentration_Monthly/default/2026-01-01/GoogleMapsCompatible_Level6/4/6/10.png",
     "provides": "MERRA-2 dust surface mass concentration rasters", "used_for": "map layer: seasonal dust loading"},
    {"id": "gibs_airs", "name": "NASA GIBS — AIRS dust score", "access": "open",
     "probe": "gibs:AIRS_L2_Dust_Score_Day", "url": f"{GIBS_BASE}/AIRS_L2_Dust_Score_Day/default/2026-01-01/GoogleMapsCompatible_Level6/4/6/10.png",
     "provides": "AIRS dust score", "used_for": "map layer: atmospheric dust"},
    {"id": "aeronet", "name": "AERONET (NASA)", "access": "open",
     "url": "https://aeronet.gsfc.nasa.gov/aeronet_locations_v3.txt",
     "provides": "ground sun-photometer station list (data needs free NASA login)", "used_for": "ground-truth validation of AOD"},
    {"id": "himawari9", "name": "NOAA Himawari-9 (AWS open data)", "access": "open",
     "url": "https://noaa-himawari9.s3.amazonaws.com/?list-type=2&max-keys=2",
     "provides": "10-minute geostationary imagery over the Middle East", "used_for": "rapid dust-storm nowcasting"},
    {"id": "gfs", "name": "NOAA GFS (AWS open data)", "access": "open",
     "url": "https://noaa-gfs-bdp-pds.s3.amazonaws.com/?list-type=2&max-keys=2",
     "provides": "global forecast model output", "used_for": "wind & dust-transport cross-check"},
    {"id": "ecmwf", "name": "ECMWF open data", "access": "open",
     "url": "https://data.ecmwf.int/forecasts/",
     "provides": "open IFS forecast runs", "used_for": "multi-model ensemble check"},
    {"id": "cams_ads", "name": "Copernicus ADS — CAMS global forecasts", "access": "COP_ADS_API_KEY",
     "url": "https://ads.atmosphere.copernicus.eu/api", "provides": "CAMS aerosol/dust forecasts (NetCDF/GRIB)",
     "used_for": "highest-quality dust forecast once a key is supplied"},
    {"id": "soda", "name": "CAMS Radiation Service (SoDa)", "access": "SODA_ACCOUNT",
     "url": "https://www.soda-pro.com/web-services/radiation/cams-radiation-service",
     "provides": "CAMS radiation time series", "used_for": "irradiance history once registered"},
    {"id": "sentinel5p", "name": "Copernicus Data Space — Sentinel-5P", "access": "CDSE_ACCOUNT",
     "url": "https://dataspace.copernicus.eu/", "provides": "TROPOMI aerosol/NO2/UVAI products",
     "used_for": "sensor-level aerosol index once registered"},
    {"id": "merra2_disc", "name": "NASA GES DISC — MERRA-2", "access": "EARTHDATA_LOGIN",
     "url": "https://disc.gsfc.nasa.gov/datasets?project=MERRA-2", "provides": "MERRA-2 NetCDF files",
     "used_for": "full-resolution dust reanalysis (imagery already served via GIBS)"},
    {"id": "mcd19a2", "name": "LAADS DAAC — MCD19A2 MAIAC AOD", "access": "EARTHDATA_LOGIN",
     "url": "https://ladsweb.modaps.eosdis.nasa.gov/missions-and-measurements/products/MCD19A2/",
     "provides": "1 km MAIAC AOD HDF", "used_for": "fine-scale AOD (imagery served via GIBS)"},
    {"id": "nsrdb", "name": "NREL NSRDB", "access": "NSRDB_API_KEY",
     "url": "https://developer.nrel.gov/api/nsrdb/v2/solar/psm3-download.csv",
     "provides": "high-resolution solar resource (PSM3)", "used_for": "bankable yield studies"},
    {"id": "ptree", "name": "JAXA P-Tree (Himawari)", "access": "PTREE_ACCOUNT",
     "url": "https://www.eorc.jaxa.jp/ptree/", "provides": "Himawari standard products",
     "used_for": "alternative geostationary archive"},
    {"id": "ems", "name": "Copernicus Emergency Management", "access": "CDSE_ACCOUNT",
     "url": "https://emergency.copernicus.eu/", "provides": "rapid mapping activations",
     "used_for": "post-storm impact mapping"},
    {"id": "dust_aemet", "name": "AEMET dust forecast (Spain, open)", "access": "open",
     "url": "https://dust.aemet.es/", "provides": "SDS-WAS dust forecast products",
     "used_for": "independent regional dust-model comparison"},
]


async def source_status(refresh: bool = False, ttl: float = 1800):
    """Probe every registry row for real and report what actually happened."""
    cached = None if refresh else cache_get("source_status", ttl)
    if cached:
        return cached
    sem = asyncio.Semaphore(4)

    async def probe(row):
        r = {**row, "checked_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        if row["access"] != "open":
            r.update({"status": "gated", "http": None,
                      "detail": f"needs {row['access']} in backend/.env (not supplied)"})
            return r
        try:
            async with sem:
                # GIBS rows are raster layers, not plain URLs: probe a real tile at
                # the freshest date the layer actually has.
                probe_spec = row.get("probe", "")
                if probe_spec.startswith("gibs:"):
                    layer = probe_spec.split(":", 1)[1]
                    z, x, y = 5, 20, 12          # Arabian peninsula tile
                    day = gibs_available_dates().get(layer)
                    data, eff, _ = await gibs_tile(layer, day, z, x, y)
                    ok = data is not None
                    r.update({"status": "live" if ok else "no_data",
                              "http": 200 if ok else 204,
                              "bytes": len(data) if data else 0,
                              "effective_date": eff,
                              "detail": (f"tile {z}/{x}/{y} OK, effective date {eff}"
                                         if ok else "no tile returned")})
                    return r
                async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True) as c:
                    resp = await c.get(row["url"], headers={"User-Agent": HTTP_USER_AGENT})
            r.update({"status": "live" if resp.status_code == 200 else "error",
                      "http": resp.status_code, "bytes": len(resp.content),
                      "detail": f"HTTP {resp.status_code}, {len(resp.content):,} bytes"})
        except Exception as e:
            r.update({"status": "unreachable", "http": None, "bytes": 0,
                      "detail": f"{type(e).__name__}: {e}"})
        return r

    rows = await asyncio.gather(*(probe(x) for x in SOURCE_REGISTRY))
    out = {"checked_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "open_live": sum(1 for x in rows if x["status"] == "live"),
           "open_total": sum(1 for x in rows if x["access"] == "open"),
           "gated": sum(1 for x in rows if x["status"] == "gated"),
           "sources": rows}
    cache_set("source_status", out)
    return out


# ------------------------------------------------------------------ helpers
def nearest_site(lat: float, lon: float, max_km: float = 400):
    best, best_d = None, 1e9
    for s in SITES:
        d = _haversine(lat, lon, s["lat"], s["lon"])
        if d < best_d:
            best, best_d = s, d
    if best and best_d <= max_km:
        return {**best, "distance_km": round(best_d, 1)}
    return None


def site_by_id(sid: str):
    return next((s for s in SITES if s["id"] == sid), None)


def daily_rollup(forecast: dict) -> list[dict]:
    """Collapse hourly rows into per-day aggregates the soiling model needs."""
    days: dict[str, dict] = {}
    for h in forecast.get("hourly", []):
        d = h["time"][:10]
        row = days.setdefault(d, {"date": d, "n": 0, "ghi_kwh_m2": 0.0, "temp_max": None,
                                  "temp_mean": 0.0, "rh_mean": 0.0, "wind_max": 0.0,
                                  "gust_max": 0.0, "precip_mm": 0.0, "pm10": [], "dust": [],
                                  "aod": [], "peak_ghi": 0.0, "temp_cell_max": None})
        row["n"] += 1
        row["ghi_kwh_m2"] += (h.get("ghi_wm2") or 0) / 1000.0
        row["peak_ghi"] = max(row["peak_ghi"], h.get("ghi_wm2") or 0)
        t = h.get("temp_c")
        if t is not None:
            row["temp_mean"] += t
            row["temp_max"] = t if row["temp_max"] is None else max(row["temp_max"], t)
            cell = t + (h.get("ghi_wm2") or 0) * 0.028
            row["temp_cell_max"] = cell if row["temp_cell_max"] is None else max(row["temp_cell_max"], cell)
        row["rh_mean"] += h.get("rh_pct") or 0
        row["wind_max"] = max(row["wind_max"], h.get("wind_ms") or 0)
        row["gust_max"] = max(row["gust_max"], h.get("gust_ms") or 0)
        row["precip_mm"] += h.get("precip_mm") or 0
        if h.get("pm10") is not None:
            row["pm10"].append(h["pm10"])
        if h.get("dust_ugm3") is not None:
            row["dust"].append(h["dust_ugm3"])
        if h.get("aod") is not None:
            row["aod"].append(h["aod"])
    out = []
    for d in sorted(days):
        r = days[d]
        n = max(r["n"], 1)
        out.append({
            "date": r["date"],
            "irradiation_kwh_m2": round(r["ghi_kwh_m2"], 2),
            "tair_max_c": r["temp_max"], "tair_mean_c": round(r["temp_mean"] / n, 1),
            "tcell_max_c": round(r["temp_cell_max"], 1) if r["temp_cell_max"] is not None else None,
            "rh_mean_pct": round(r["rh_mean"] / n, 1),
            "wind_max_ms": round(r["wind_max"], 1), "gust_max_ms": round(r["gust_max"], 1),
            "precip_mm": round(r["precip_mm"], 1),
            "pm10_ugm3": round(sum(r["pm10"]) / len(r["pm10"]), 1) if r["pm10"] else None,
            "dust_ugm3": round(sum(r["dust"]) / len(r["dust"]), 1) if r["dust"] else None,
            "aod": round(sum(r["aod"]) / len(r["aod"]), 3) if r["aod"] else None,
            "peak_ghi_wm2": round(r["peak_ghi"], 1),
        })
    return out
