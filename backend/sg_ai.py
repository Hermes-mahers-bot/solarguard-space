"""SolarGuard AI — live inference for the sandstorm, output and soiling models.

    from sg_ai import predict_site, ai_status
    out = predict_site(lat=26.43, lon=50.10, capacity_kwp=100_000, site_id="dammam")

WHAT THIS IS
------------
The trained models from ml/ai_train.py, served. It fetches the SAME feature vector
the models were trained on — by asking Open-Meteo for the last 92 days plus the
forecast instead of the historical archive — and then predicts:

    storm_t1/t2/t3   P(sandstorm) for the next 1, 2, 3 days
    output_t1        kWh for tomorrow, absolute and per kWp
    soiling_t1       optical loss % expected tomorrow

Feature construction is imported from ml/ai_features.py, the same module the
trainer uses, so training and serving cannot drift apart. tests/test_ai.py asserts
that parity, because silently divergent features are exactly what made the first
generation of models useless.

HONESTY NOTES, ON THE RECORD
  * The storm label is a definition (daily max PM10 >= 200 µg/m³). The models
    predict that definition, and the dashboard says which definition.
  * The output label is a documented PV model on measured irradiation and air
    temperature, not inverter telemetry.
  * Every prediction ships with the error measured on held-out data
    (models/ai/metrics.json). No prediction is served without its error bar.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
for p in (os.path.join(ROOT, "ml"), HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import ai_features as F                       # noqa: E402
import train as T                             # noqa: E402
import ai_train as AT                         # noqa: E402

AI_DIR = os.path.join(ROOT, "models", "ai")
THRESHOLDS_PATH = os.path.join(AI_DIR, "site_thresholds.json")
METRICS_PATH = os.path.join(AI_DIR, "metrics.json")
CACHE_TTL = 1800          # seconds; the forecast window barely moves inside 30 min

_thresholds: dict[str, float] | None = None
_thr_cache: dict[tuple, float] = {}
_bundles: dict[str, dict] = {}
_metrics: dict | None = None
_cache: dict[tuple, tuple[float, dict]] = {}
_parity_checked: dict[str, bool] = {}


# ═══════════════════════════════════════════════════════════ model loading
def _load_tree(z, prefix, kind: str):
    m = (AT.GBRTClassifier.__new__(AT.GBRTClassifier) if kind == "clf"
         else T.GBRT.__new__(T.GBRT))
    m.base = float(z[f"{prefix}_base"][0])
    m.learning_rate = float(z[f"{prefix}_learning_rate"][0]) if f"{prefix}_learning_rate" in z else 0.05
    m.l2 = float(z[f"{prefix}_l2"][0]) if f"{prefix}_l2" in z else 1.0
    m.max_depth = int(z[f"{prefix}_max_depth"][0]) if f"{prefix}_max_depth" in z else 4
    n_edge = int(z[f"{prefix}_n_edge"])
    m.edges = [np.asarray(z[f"{prefix}_edge_{j}"], float) for j in range(n_edge)]
    n_trees = int(z[f"{prefix}_n_trees"])
    m.trees = []
    for i in range(n_trees):
        m.trees.append({k: z[f"{prefix}_t{i}_{k}"]
                        for k in ("feat", "thr", "left", "right", "value")})
    m.rng = np.random.default_rng(0)
    return m


def _load_mlp(z, prefix):
    m = T.MLP.__new__(T.MLP)
    n = int(z[f"{prefix}_n_W"])
    m.W = [z[f"{prefix}_W{i}"] for i in range(n)]
    m.b = [z[f"{prefix}_b{i}"] for i in range(n)]
    return m


def _load_bundle(name: str, kind: str) -> dict | None:
    path = os.path.join(AI_DIR, f"{name}.npz")
    if not os.path.exists(path):
        return None
    z = np.load(path, allow_pickle=False)
    meta = json.loads(str(np.asarray(z["meta_json"]).ravel()[0]))
    out = {"kind": kind, "meta": meta,
           "mu": z["mu"], "sd": z["sd"],
           "scale": float(np.asarray(z["scale"]).ravel()[0]) if "scale" in z else 1.0,
           "w": tuple(np.asarray(z["w"], float)) if "w" in z else (0.5, 0.5)}
    if kind == "storm":
        out["tree"] = _load_tree(z, "clf", "clf")
    else:
        out["tree"] = _load_tree(z, "gbrt", "reg")
    out["mlp"] = _load_mlp(z, "mlp")
    return out


def _all() -> dict:
    if not _bundles:
        for name, kind in (("storm_t1", "storm"), ("storm_t2", "storm"), ("storm_t3", "storm"),
                           ("yield_t1", "reg"), ("soiling_t1", "reg")):
            b = _load_bundle(name, kind)
            if b is not None:
                _bundles[name] = b
    return _bundles


def metrics() -> dict:
    global _metrics
    if _metrics is None:
        try:
            with open(METRICS_PATH) as fh:
                _metrics = json.load(fh)
        except Exception:
            _metrics = {}
    return _metrics


def ai_available() -> bool:
    return len(_all()) >= 5


def _threshold_table() -> dict:
    """Per-site storm thresholds, re-read if missing.

    A live process that imported this module before the trainer wrote the file
    cached an empty table and then served a threshold of zero for every site —
    which is worse than a wrong number, because zero means "every day is a storm".
    Empirically it did exactly that, so the empty case is not cached.
    """
    global _thresholds
    if not _thresholds:
        try:
            with open(THRESHOLDS_PATH) as fh:
                table = {k: float(v) for k, v in json.load(fh).items() if float(v) > 0}
            if table:
                _thresholds = table
        except Exception:
            pass
    return _thresholds or {}


def _sites():
    try:
        import sg_config as C
        return C.SITES
    except Exception:
        return []


def site_threshold(lat: float, lon: float, site_id: str | None = None) -> tuple[float, str]:
    """The storm threshold for a coordinate: 3x that location's median PM10.

    For the twelve catalogued sites we ship the value measured over four years of
    CAMS data. For a coordinate the user tapped on the map we use the nearest
    catalogued site's climatology — stated as such rather than pretending to have
    four years of history for an arbitrary point.
    """
    key = (round(lat, 2), round(lon, 2))
    if key in _thr_cache:
        v = _thr_cache[key]
        return v, "cached"
    table = _threshold_table()
    if site_id and site_id in table and float(table[site_id]) > 0:
        v = float(table[site_id])
        _thr_cache[key] = v
        return v, "measured at this site"
    sites = _sites()
    if not sites or not table:
        return F.STORM_FLOOR, "national floor"
    def d2(s):
        return (float(s["lat"]) - lat) ** 2 + (float(s["lon"]) - lon) ** 2
    nearest = min(sites, key=d2)
    v = float(table.get(nearest["id"], 0) or 0)
    if v <= 0:
        v = F.STORM_FLOOR
    _thr_cache[key] = v
    return v, f"nearest monitored site ({nearest['name']})"


# ═══════════════════════════════════════════════════════════ live features
def _get_json(url: str, tries: int = 3) -> dict:
    import httpx
    last = None
    for i in range(tries):
        try:
            r = httpx.get(url, timeout=25.0)
            if r.status_code == 200:
                return r.json()
            last = f"HTTP {r.status_code}"
        except Exception as e:                       # noqa: BLE001
            last = f"{type(e).__name__}: {e}"
        time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"fetch failed ({last}) for {url.split('?')[0]}")


def fetch_daily_rows(lat: float, lon: float, past_days: int = 92, ahead: int = 10) -> list[dict]:
    """Weather + CAMS dust for the last `past_days` days AND the coming `ahead`
    days, merged into one daily row per date, in the training column order.

    The `past_days` window is the whole point: the models use 3/7/30-day rolling
    dust statistics, and this is where those come from at prediction time.
    """
    wx = _get_json(
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}&past_days={past_days}&forecast_days={ahead}"
        "&daily=shortwave_radiation_sum,temperature_2m_max,temperature_2m_min,"
        "temperature_2m_mean,relative_humidity_2m_mean,wind_speed_10m_max,"
        "wind_gusts_10m_max,precipitation_sum,wind_direction_10m_dominant"
        "&timezone=UTC&wind_speed_unit=ms")
    # the air-quality endpoint caps the forecast horizon at 7 days (10 returns
    # HTTP 400), which is plenty: we predict t+1..t+3.
    aq_ahead = min(ahead, 7)
    aq = _get_json(
        "https://air-quality-api.open-meteo.com/v1/air-quality"
        f"?latitude={lat}&longitude={lon}&past_days={past_days}&forecast_days={aq_ahead}"
        "&hourly=pm10,dust,aerosol_optical_depth,pm2_5&timezone=UTC")

    wd = wx["daily"]
    by_date: dict[str, dict] = {}
    for i, d in enumerate(wd["time"]):
        by_date[d] = {
            "date": d,
            "ghi_mj_m2": wd["shortwave_radiation_sum"][i],
            "tmax_c": wd["temperature_2m_max"][i],
            "tmin_c": wd["temperature_2m_min"][i],
            "tmean_c": wd["temperature_2m_mean"][i],
            "rh_mean_pct": wd["relative_humidity_2m_mean"][i],
            "wind_max_ms": wd["wind_speed_10m_max"][i],
            "gust_max_ms": wd["wind_gusts_10m_max"][i],
            "precip_mm": wd["precipitation_sum"][i],
            "wind_dir_deg": wd["wind_direction_10m_dominant"][i],
        }

    h = aq["hourly"]
    agg: dict[str, dict[str, list[float]]] = {}
    for i, ts in enumerate(h["time"]):
        day = ts[:10]
        vals = agg.setdefault(day, {"pm10": [], "dust": [], "aod": [], "pm25": []})
        for src, dst in (("pm10", "pm10"), ("dust", "dust"),
                         ("aerosol_optical_depth", "aod"), ("pm2_5", "pm25")):
            v = h.get(src, [None])[i] if i < len(h.get(src, [])) else None
            if v is not None:
                vals[dst].append(float(v))

    rows = []
    for d in sorted(by_date):
        r = by_date[d]
        a = agg.get(d)
        if not a or not a["pm10"]:
            continue                                   # no dust data -> unusable row
        r["pm10_max"] = max(a["pm10"])
        r["pm10_mean"] = sum(a["pm10"]) / len(a["pm10"])
        r["dust_max"] = max(a["dust"]) if a["dust"] else None
        r["dust_mean"] = (sum(a["dust"]) / len(a["dust"])) if a["dust"] else None
        r["aod_max"] = max(a["aod"]) if a["aod"] else None
        r["aod_mean"] = (sum(a["aod"]) / len(a["aod"])) if a["aod"] else None
        r["pm25_mean"] = (sum(a["pm25"]) / len(a["pm25"])) if a["pm25"] else None
        if r["dust_max"] is None:                      # fall back so the row stays usable
            r["dust_max"] = 0.45 * r["pm10_max"]
            r["dust_mean"] = 0.30 * r["pm10_mean"]
        if r["aod_mean"] is None and r["aod_max"] is not None:
            r["aod_mean"] = r["aod_max"]
        r["site"] = "live"
        r["lat"], r["lon"] = lat, lon
        r["elevation_m"] = 0.0
        r["doy"] = float(datetime.strptime(d, "%Y-%m-%d").timetuple().tm_yday)
        rows.append(r)
    return rows


def _vector(bundle: dict, feats: dict) -> np.ndarray:
    return np.array([[feats[k] for k in F.FEATURES]], float)


def _predict_bundle(bundle: dict, feats: dict) -> tuple[float, float]:
    X = _vector(bundle, feats)
    if bundle["kind"] == "storm":
        p_mlp = float(np.clip(bundle["mlp"].predict((X - bundle["mu"]) / bundle["sd"])[0, 0], 0, 1))
        p_tree = float(bundle["tree"].predict_proba(X)[0])
    else:
        p_mlp = float(bundle["mlp"].predict((X - bundle["mu"]) / bundle["sd"])[0, 0] * bundle["scale"])
        p_tree = float(bundle["tree"].predict(X)[0])
    wg, wm = bundle["w"]
    blended = wg * p_tree + wm * p_mlp
    return float(blended), float(p_tree)


# ═══════════════════════════════════════════════════════════ public API
def _level(p: float, thr: float) -> str:
    if p >= max(thr, 0.5):
        return "storm likely"
    if p >= thr:
        return "watch"
    if p >= 0.6 * thr:
        return "watch"
    return "quiet"


def predict_site(lat: float, lon: float, capacity_kwp: float = 100_000.0,
                 site_id: str = "live", nodata_ok: bool = False) -> dict:
    """Live predictions for one coordinate. Never raises: returns {'ok': False,
    'error': ...} if the models or the upstream feeds are unavailable, because the
    dashboard must keep working when a feed is down."""
    key = (round(lat, 3), round(lon, 3), round(capacity_kwp))
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_TTL:
        return hit[1]
    try:
        bundles = _all()
        if len(bundles) < 5:
            return {"ok": False, "error": "AI models are not trained yet "
                                          "(run ml/ai_train.py)"}
        rows = fetch_daily_rows(lat, lon)
        if len(rows) < 45:
            return {"ok": False, "error": f"only {len(rows)} usable days of history "
                                          f"(need 45+ for the rolling features)"}
        idx = len(rows) - 1 - 3        # leave the last 3 days as the prediction horizon
        thr, thr_src = site_threshold(lat, lon, site_id)
        feats = F.build_features(rows, idx, storm_thr=thr)
        as_of = rows[idx]["date"]

        storm = {}
        for h in (1, 2, 3):
            b = bundles.get(f"storm_t{h}")
            if not b:
                continue
            p, p_tree = _predict_bundle(b, feats)
            # NB: name this p_thr, not thr. It is the classifier's probability
            # cut-off, and an earlier version reused the name `thr` here, silently
            # overwriting the site's PM10 threshold computed above — which the
            # report then printed as "0 µg/m³".
            p_thr = float(b["meta"].get("threshold", 0.5))
            storm[f"t{h}"] = {"p": round(p, 3), "level": _level(p, p_thr),
                              "threshold": round(p_thr, 3)}
        if storm:
            worst = max(storm.values(), key=lambda s: s["p"])
            storm["headline"] = worst["level"]
            storm["max_p"] = worst["p"]

        ym = bundles["yield_t1"]
        y_kwp, _ = _predict_bundle(ym, feats)
        y_kwp = max(0.0, min(y_kwp, 12.0))              # guard: 12 kWh/kWp/day is the desert ceiling
        sm = bundles["soiling_t1"]
        soil, _ = _predict_bundle(sm, feats)
        soil = max(0.0, min(soil, 65.0))                # guard: clamp to physically sane loss

        m = metrics()
        y_err = (m.get("regressors", {}).get("yield_t1", {}).get("ensemble", {}) or {}).get("mae")
        s_err = (m.get("regressors", {}).get("soiling_t1", {}).get("ensemble", {}) or {}).get("mae")
        storm_m = (m.get("classifier", {}).get("storm_t1", {}) or {}).get("test_tuned", {}) or {}

        out = {
            "ok": True,
            "as_of": as_of,
            "site_id": site_id,
            "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "history_days": len(rows),
            "storm": storm,
            "output": {
                "kwh_per_kwp": round(y_kwp, 2),
                "kwh": round(y_kwp * capacity_kwp, 1),
                "mwh": round(y_kwp * capacity_kwp / 1000.0, 2),
                "error_kwh_per_kwp": y_err,
                "error_pct_of_mean": (m.get("regressors", {}).get("yield_t1", {})
                                      .get("ensemble", {}) or {}).get("mae_pct_of_mean"),
                "label_note": "documented PV model on measured irradiation + air temperature",
            },
            "soiling": {
                "loss_pct": round(soil, 2),
                "error_points": s_err,
                "unit": "% optical loss",
                # Say the assumption out loud: this is the AI's own label, which
                # accumulates deposition until rain washes it off. The physics
                # engine answers a different question (loss since the operator's
                # last clean), so the two numbers differ by design and must never
                # be presented as the same quantity.
                "assumes": "no cleaning — the only reset is rain wash-off",
                "label_note": ("deposition model on measured PM10/dust/gust/rain; label, "
                               "not inverter data"),
            },
            "observed_now": {
                "pm10_ugm3": round(F._f(rows[idx].get("pm10_max")), 1),
                "dust_ugm3": round(F._f(rows[idx].get("dust_max")), 1),
                "aod": round(F._f(rows[idx].get("aod_mean")), 3),
                "gust_ms": round(F._f(rows[idx].get("gust_max_ms")), 1),
                "rain_mm": round(F._f(rows[idx].get("precip_mm")), 1),
            },
            "skill": {
                "storm_recall_pct": storm_m.get("recall_pct"),
                "storm_precision_pct": storm_m.get("precision_pct"),
                "storm_auc": storm_m.get("auc"),
                "storm_brier": storm_m.get("brier"),
                "evaluated_on": f"held-out test block, n={storm_m.get('n')}",
            },
            "model": {"kind": "gradient-boosted trees + MLP, numpy, trained here",
                      "features": len(F.FEATURES),
                      "blend": list(ym["w"]),
                      "storm_threshold_ugm3": round(thr, 0),
                      "storm_threshold_source": thr_src},
            "notes": [
                "Features come from the same code path as training (ml/ai_features.py).",
                f"Storm here = PM10 ≥ {thr:.0f} µg/m³, i.e. 3× the median of this "
                f"location's own dust record ({thr_src}) — a definition, stated openly.",
                "Output label is a PV model on measured weather, not inverter data.",
            ],
        }
        _cache[key] = (time.time(), out)
        return out
    except Exception as e:                              # noqa: BLE001
        if nodata_ok:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def ai_status() -> dict:
    m = metrics()
    return {
        "available": ai_available(),
        "models": sorted(_all().keys()),
        "trained_utc": m.get("generated_utc"),
        "samples": m.get("n_samples"),
        "sites": m.get("n_sites"),
        "date_range": m.get("date_range"),
        "storm_definition": m.get("storm_definition"),
        "metrics": {
            "storm_t1": (m.get("classifier", {}).get("storm_t1", {}) or {}).get("test_tuned"),
            "storm_t3": (m.get("classifier", {}).get("storm_t3", {}) or {}).get("test_tuned"),
            "yield_t1": (m.get("regressors", {}).get("yield_t1", {}) or {}).get("ensemble"),
            "soiling_t1": (m.get("regressors", {}).get("soiling_t1", {}) or {}).get("ensemble"),
        },
        "loso_mean": m.get("leave_one_site_out_mean"),
        "n_features": len(F.FEATURES),
        "thresholds": _threshold_table(),
        "thresholds_source": THRESHOLDS_PATH,
        "thresholds_file_present": os.path.exists(THRESHOLDS_PATH),
        "split_sizes": m.get("splits"),
        # the yardsticks, exposed so the skill numbers can be judged rather than
        # taken on trust: persistence (tomorrow = today) and climatology
        "baselines": {
            "storm_t1_persistence": (m.get("classifier", {}).get("storm_t1", {}) or {})
                                    .get("baseline_persistence"),
            "storm_t1_climatology_brier": (m.get("classifier", {}).get("storm_t1", {}) or {})
                                          .get("baseline_climatology_brier"),
            "note": ("Persistence is a strong baseline for dust because events last several "
                     "days; the model only earns its keep beyond day +1, and that comparison "
                     "is in metrics.json."),
        },
    }


if __name__ == "__main__":                              # quick manual check
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--lat", type=float, default=26.43)
    ap.add_argument("--lon", type=float, default=50.10)
    ap.add_argument("--capacity", type=float, default=100_000)
    a = ap.parse_args()
    print(json.dumps(ai_status(), indent=1))
    print(json.dumps(predict_site(a.lat, a.lon, a.capacity), indent=1))
