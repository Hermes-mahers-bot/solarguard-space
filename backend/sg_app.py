"""
SolarGuard Space — the API + page server.

This is a Starlette/FastAPI sub-application. It is mounted by the site host at
`/solarguard`, so every route below is reachable at
`https://space-marines.aimaher.com/solarguard/...`.

Design rules kept from the host site's contract:
  * every `/api/*` route is registered BEFORE the static mount
  * `/api/health` and `/api/version` always answer
  * no route may raise: failures come back as JSON so the pages keep working
  * secrets are read from disk at runtime and never reach the browser
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import sg_agent
import sg_datasources as ds
import sg_rag
import sg_soiling as soil
from sg_config import (CLEANING_PRESETS, CORPUS, DATA, DEFAULT_CLEANING_INTERVAL_DAYS,
                       GIBS_LAYERS, MODELS, PUBLIC, SERVICE, SITES, TARIFF_SAR_PER_KWH, VERSION)

RIYADH = timezone(timedelta(hours=3))

sg_app = FastAPI(title="SolarGuard Space API", docs_url=None, redoc_url=None)


@sg_app.middleware("http")
async def cors_and_no_raise(request: Request, call_next):
    """CORS + a crash barrier.

    CORS is open because this API is a public demo: it lets the map/animation
    modules be developed and inspected from any origin (a local test page, a
    teammate's machine) without a proxy. Nothing secret is served from here —
    the DeepSeek key stays server-side.
    """
    if request.method == "OPTIONS":
        return Response(status_code=204, headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "content-type",
            "Access-Control-Max-Age": "86400",
        })
    try:
        resp = await call_next(request)
    except Exception as e:                      # pragma: no cover - safety net
        return JSONResponse(status_code=500,
                            content={"error": "internal", "detail": f"{type(e).__name__}: {e}",
                                     "path": request.url.path})
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp


# ------------------------------------------------------------------ meta
@sg_app.get("/api/health")
def health():
    now = datetime.now(timezone.utc)
    return {"status": "ok", "service": SERVICE, "version": VERSION,
            "utc": now.isoformat(timespec="seconds"),
            "riyadh": now.astimezone(RIYADH).isoformat(timespec="seconds")}


@sg_app.get("/api/version")
def version():
    return {"service": SERVICE, "version": VERSION,
            "ai_model": sg_agent.DEEPSEEK_MODEL,
            "ai_configured": bool(sg_agent.DEEPSEEK_KEY),
            "soiling_model": ("ml+physics" if soil.ml_available() else "physics")}


@sg_app.get("/api/sg/status")
def sg_status():
    """SolarGuard's own status, under a path the host app does not shadow.

    The host owns /api/health, /api/version and /api/ai/status at the domain root,
    so the front-end reads this instead of those when it wants SolarGuard facts.
    """
    rag = sg_rag.stats()
    return {"service": SERVICE, "version": VERSION,
            "ai_enabled": bool(sg_agent.DEEPSEEK_KEY), "model": sg_agent.DEEPSEEK_MODEL,
            "soiling_model": ("ml+physics" if soil.ml_serving() else "physics-empirical"),
            "ml_models_loaded": soil.ml_available(),
            "ml_note": ("ML models are trained and evaluated but need 90-day rolling dust "
                        "features the forecast horizon does not have; physics serves. "
                        "See docs/MODEL_CARD.md."),
            "tools": [t["function"]["name"] for t in sg_agent.TOOLS],
            "tool_count": len(sg_agent.TOOLS),
            "rag": {"retriever": rag["retriever"], "chunks": rag["chunks"]},
            "key_source": "backend/.env (server-side only)"}


@sg_app.get("/api/ai/status")
def ai_status():
    return {"ai_enabled": bool(sg_agent.DEEPSEEK_KEY),
            "model": sg_agent.DEEPSEEK_MODEL,
            "retriever": sg_rag.stats()["retriever"],
            "tools": [t["function"]["name"] for t in sg_agent.TOOLS],
            "key_source": "backend/.env (server-side only)"}


@sg_app.get("/api/sites")
def sites():
    return {"sites": SITES, "count": len(SITES),
            "tariff_sar_per_kwh": TARIFF_SAR_PER_KWH,
            "cleaning_presets": CLEANING_PRESETS,
            "module_efficiency": 0.175,
            "water_litres_per_mwp_wet_clean": 2500.0,
            "default_cleaning_interval_days": DEFAULT_CLEANING_INTERVAL_DAYS}


# ------------------------------------------------------------------ forecast / report
def _resolve(site: str | None, lat: float | None, lon: float | None, name: str | None = None):
    if site:
        for s in SITES:
            if site.lower() == s["id"] or site.lower() in s["name"].lower():
                return dict(s), None
    if lat is not None and lon is not None:
        near = ds.nearest_site(float(lat), float(lon))
        if near and near.get("distance_km", 999) <= 60:
            return dict(near), None
        return ({"id": "custom", "name": name or f"{float(lat):.2f}°N {float(lon):.2f}°E",
                 "lat": float(lat), "lon": float(lon), "region": "custom location",
                 "climate": "inland", "capacity_mwp": None, "custom": True}, None)
    return None, "pass ?site=<id> or ?lat=..&lon=.."


@sg_app.get("/api/forecast")
async def forecast(site: str | None = None, lat: float | None = None, lon: float | None = None,
                   days: int = Query(7, ge=1, le=16)):
    s, err = _resolve(site, lat, lon, None)
    if err:
        return JSONResponse(status_code=400, content={"error": "bad_request", "detail": err})
    fc = await ds.openmeteo_forecast(s["lat"], s["lon"], days=days)
    return {"site": s, "hourly": fc["hourly"], "daily": ds.daily_rollup(fc),
            "elevation_m": fc.get("elevation_m"), "source": fc["source"],
            "fetched_utc": fc["fetched_utc"]}


@sg_app.get("/api/report")
async def report(site: str | None = None, lat: float | None = None, lon: float | None = None,
                 name: str | None = None, capacity_kwp: float | None = None,
                 cleaning_interval_days: int = DEFAULT_CLEANING_INTERVAL_DAYS,
                 horizon_days: int = Query(14, ge=3, le=16),
                 cost_per_mwp_sar: float | None = None):
    """The dashboard's main call: everything needed to render one site."""
    s, err = _resolve(site, lat, lon, name)
    if err:
        return JSONResponse(status_code=400, content={"error": "bad_request", "detail": err})
    cap = float(capacity_kwp or (s.get("capacity_mwp") or 1) * 1000)
    rep = await sg_agent.build_report(s, cap, int(cleaning_interval_days), int(horizon_days),
                                      cost_per_mwp=cost_per_mwp_sar)
    return rep


@sg_app.get("/api/dust")
async def dust(site: str | None = None, lat: float | None = None, lon: float | None = None,
               days: int = Query(7, ge=1, le=16)):
    s, err = _resolve(site, lat, lon, None)
    if err:
        return JSONResponse(status_code=400, content={"error": "bad_request", "detail": err})
    return await sg_agent._run_tool("get_dust_outlook", {"lat": s["lat"], "lon": s["lon"], "days": days}, [])


@sg_app.get("/api/aeronet")
async def aeronet(lat: float, lon: float):
    return await ds.aeronet_nearest(lat, lon)


# ------------------------------------------------------------------ sources & satellite
@sg_app.get("/api/sources")
async def sources(refresh: int = 0):
    return await ds.source_status(refresh=bool(refresh))


@sg_app.get("/api/satellite/layers")
def satellite_layers():
    return {"layers": GIBS_LAYERS, "dates": ds.gibs_available_dates(),
            "attribution": "NASA GIBS / EOSDIS (MODIS, MAIAC, AIRS, MERRA-2) — open, no key",
            "endpoint": "/api/satellite/tile/{layer}/{date}/{z}/{x}/{y}.png"}


@sg_app.get("/api/satellite/tile/{layer}/{day}/{z}/{x}/{y}.png")
async def satellite_tile(layer: str, day: str, z: int, x: int, y: int):
    data, eff_day, ctype = await ds.gibs_tile(layer, day, z, x, y)
    if not data:
        return Response(status_code=204)
    return Response(content=data, media_type=ctype or "image/png",
                    headers={"X-Effective-Date": eff_day or "",
                             "Cache-Control": "public, max-age=86400"})


@sg_app.get("/api/satellite/image")
async def satellite_image(layer: str, date: str | None = None, lat: float = 24.2, lon: float = 45.0,
                          zoom: int = 5, width: int = 1024, height: int = 640, fmt: str = "jpeg"):
    """A stitched satellite mosaic over any point — the crisp version of the
    tiles, used for the homepage preview and the date filmstrip."""
    data, out_fmt, eff_day = await ds.gibs_mosaic(layer, date or "", lat, lon, zoom, width, height, fmt)
    if not data:
        return JSONResponse(status_code=404, content={"error": "no_imagery",
                            "detail": f"{layer} has no tiles near {lat},{lon} at zoom {zoom}"})
    return Response(content=data, media_type=f"image/{out_fmt.lower()}",
                    headers={"X-Effective-Date": eff_day,
                             "X-Imagery-Source": "NASA GIBS (open, no key)",
                             "Cache-Control": "public, max-age=86400"})


@sg_app.get("/api/buckets")
async def buckets():
    """Open S3 buckets we monitor (Himawari-9, GFS) — proof the geostationary
    imagery pipeline is reachable, without mirroring petabytes."""
    h9, gfs, ec = await ds.s3_listing("noaa-himawari9", max_keys=3), \
        ds.s3_listing("noaa-gfs-bdp-pds", max_keys=3), await ds.ecmwf_open_listing()
    return {"himawari9": h9, "gfs": gfs, "ecmwf": ec,
            "note": "Buckets are browsed live; we do not mirror them (the Himawari-9 "
                    "archive alone is petabytes). Tiles/fields we need are fetched on demand."}


# ------------------------------------------------------------------ RAG + model
@sg_app.get("/api/rag/stats")
def rag_stats():
    return sg_rag.stats()


@sg_app.get("/api/rag/search")
def rag_search(q: str, k: int = 6):
    return {"query": q, "hits": sg_rag.search(q, k=k)}


@sg_app.get("/api/model")
def model_card():
    p = MODELS / "metrics.json"
    if not p.exists():
        return {"model": "physics-empirical (literature-calibrated)",
                "ml": None,
                "note": "The trained ML model is not present yet; the physics model is serving."}
    try:
        m = json.loads(p.read_text())
    except Exception as e:
        return {"error": str(e)}
    return {"ml": m, "models_loaded": soil.ml_available(),
            "active": "ml+physics" if soil.ml_serving() else "physics-empirical",
            "note": ("Trained ML models are present and evaluated (see metrics above). The live "
                     "product is served by the physics model: the ML feature set needs 90-day "
                     "rolling dust means, which a 14-day forecast horizon does not contain.")}


@sg_app.get("/api/knowledge")
def knowledge():
    p = DATA / "knowledge.json"
    if not p.exists():
        return {"facts": [], "note": "knowledge base not built yet"}
    try:
        return json.loads(p.read_text())
    except Exception as e:
        return {"error": str(e)}


# ------------------------------------------------------------------ assistant
class AskBody(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    history: list[dict] = []
    site: str | None = None
    lat: float | None = None
    lon: float | None = None
    capacity_kwp: float | None = None


@sg_app.post("/api/assistant")
async def assistant(body: AskBody):
    site_ctx = None
    if body.site or (body.lat is not None and body.lon is not None):
        s, _ = _resolve(body.site, body.lat, body.lon, None)
        site_ctx = s
    t0 = time.time()
    out = await sg_agent.ask(body.question, history=body.history, site=site_ctx,
                             capacity_kwp=body.capacity_kwp)
    out["elapsed_ms"] = int((time.time() - t0) * 1000)
    return out


class SimBody(BaseModel):
    """Deterministic interactive simulation used by the dashboard sliders."""
    site: str | None = None
    lat: float | None = None
    lon: float | None = None
    capacity_kwp: float = 1000.0
    cleaning_interval_days: int = DEFAULT_CLEANING_INTERVAL_DAYS
    horizon_days: int = 14
    cost_per_mwp_sar: float | None = None


@sg_app.post("/api/simulate")
async def simulate(body: SimBody):
    s, err = _resolve(body.site, body.lat, body.lon, None)
    if err:
        return JSONResponse(status_code=400, content={"error": "bad_request", "detail": err})
    rep = await sg_agent.build_report(s, body.capacity_kwp, body.cleaning_interval_days,
                                      body.horizon_days,
                                      cost_per_mwp=body.cost_per_mwp_sar)
    return rep


# ------------------------------------------------------------------ pages (MUST stay last)
sg_app.mount("/", StaticFiles(directory=str(PUBLIC), html=True), name="sg-public")
