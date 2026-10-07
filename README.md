# SolarGuard Space

Dust-soiling forecasting and cleaning-scheduling for Saudi solar plants. The app reads
open satellite dust and weather feeds, estimates how much output an array is losing to
soiling, prices the lost generation against the cost of a cleaning crew, and tells the
operator the day a crew is worth sending. It ships a homepage, an operator dashboard, a
BM25-retrieved literature assistant backed by DeepSeek, two from-scratch numpy prediction
models, and a calibrated physics fallback. Everything here is measured against live feeds
— no mock data path exists in the request handlers.

- Live: https://space-marines.aimaher.com/solarguard/ (as of 2026-10-07 the same HTML also
  answers at the domain root — see [Deployment](#deployment))
- Landing page source: `public/index.html`; operator dashboard: `public/dashboard.html`
- Reference site used throughout this document: Dammam 100 MWp, east coast.

Screenshot of the live homepage (`public/index.html`), captured from
`https://space-marines.aimaher.com/solarguard/` on 2026-10-07: the page renders with H1
"Dust is eating your solar output." and the live source table shows `12 of 12 open feeds
answered HTTP 200`. Captured copies: `/home/hermes2/screenshots/home-hero.png`,
`/home/hermes2/screenshots/dash-top.png`.

---

## Architecture

```
  browser
    |
    |  public/index.html          public/dashboard.html
    |  assets/css/solarguard.css
    |  assets/js/sg-core.js  (API client, formatters, canvas charts, dust field)
    |  assets/js/sg-home.js  (homepage controller)      -> dynamically imports ./sg-scrollstory.js
    |  assets/js/sg-scrollstory.js (canvas scroll storyboard; no three.js, no CDN)
    |  assets/js/sg-dashboard.js (operator dashboard)   -> dynamic import sg-realmaps, canvas fallback
    |  assets/js/sg-realmaps.js  (Leaflet 1.9.4 + Carto/OSM basemap + GIBS overlay)
    |  assets/js/sg-map.js       (dependency-free canvas map, fallback)
    |  assets/js/sg-3d.js        (canvas globe + panel rig; no three.js)
    |  every fetch is a relative "api/..." request
    v
  FastAPI sub-app   backend/sg_app.py   (sg_app = FastAPI(...))
    |   /api/health /api/version /api/ai/status /api/sites
    |   /api/forecast /api/report /api/dust /api/aeronet /api/simulate
    |   /api/sources /api/satellite/{layers,tile,image} /api/buckets
    |   /api/rag/{stats,search} /api/model /api/knowledge
    |   /api/assistant  (POST)
    |   CORS + no-raise middleware; static mount registered LAST
    v
  -----------------------------------        ---------------------------------
  data layer  backend/sg_datasources.py      soiling engine backend/sg_soiling.py
    disk+memory TTL cache                      rate-anchored physics + PV yield
    Open-Meteo met + air quality               cleaning-policy optimiser
    NASA POWER / NASA GIBS raster proxy        rain wash-off, dew cementation
    AERONET / NOAA S3 / ECMWF / AEMET          reads models/gbrt.npz when loadable
    SOURCE_REGISTRY (20 probes)                        |
    v                                                  |
  external open feeds (no key)                    models/  (offline, trained by ml/)
                                                   gbrt.npz  mlp.npz  metrics.json
                                                   feature_meta.json  soiling_calibration.json
    ^                                                  ^
    |                                                  |
  agent  backend/sg_agent.py  (DeepSeek "Sol")   ml/train.py  ml/predict.py  ml/physics_soiling.py
    tool loop, 3 rounds max, up to 3 calls/round
    RAG  backend/sg_rag.py  BM25 over data/corpus + docs
```

---

## Data layer

Every row below is a live probe of the running deployment
(`curl -s https://space-marines.aimaher.com/solarguard/api/sources`, checked
2026-10-07T12:15:09Z). The registry (`backend/sg_datasources.py`, `SOURCE_REGISTRY`) has 20
rows: 12 open and 8 key-gated. The probe result was **12 of 12 open feeds answering, 8 gated**.

| Source | Access | Status (live) | Detail |
|---|---|---|---|
| Open-Meteo Forecast API | open | live | HTTP 200, 841 B |
| Open-Meteo Air Quality (CAMS-derived: pm10, pm2.5, dust, AOD) | open | live | HTTP 200, 1,029 B |
| Open-Meteo Satellite Radiation | open | live | HTTP 200, 850 B |
| NASA POWER (LARC) | open | live | HTTP 200, 495 B |
| NASA GIBS — MODIS aerosol (Terra) | open | live | tile 5/20/12 OK, effective date 2026-10-04 |
| NASA GIBS — MERRA-2 dust | open | live | tile 5/20/12 OK, effective date 2026-07-01 (monthly layer) |
| NASA GIBS — AIRS dust score | open | live | tile 5/20/12 OK, effective date 2026-10-04 |
| AERONET (NASA site list) | open | live | HTTP 200, 73,929 B |
| NOAA Himawari-9 (AWS open data) | open | live | HTTP 200, 1,001 B |
| NOAA GFS (AWS open data) | open | live | HTTP 200, 905 B |
| ECMWF open data | open | live | HTTP 200, 429,783 B |
| AEMET dust forecast (SDS-WAS) | open | live | HTTP 200, 41,458 B |
| Copernicus ADS — CAMS global forecasts | COP_ADS_API_KEY | gated | needs key in backend/.env (not supplied) |
| CAMS Radiation Service (SoDa) | SODA_ACCOUNT | gated | not supplied |
| Copernicus Data Space — Sentinel-5P | CDSE_ACCOUNT | gated | not supplied |
| NASA GES DISC — MERRA-2 | EARTHDATA_LOGIN | gated | not supplied |
| LAADS DAAC — MCD19A2 MAIAC AOD | EARTHDATA_LOGIN | gated | not supplied |
| NREL NSRDB | NSRDB_API_KEY | gated | not supplied |
| JAXA P-Tree (Himawari) | PTREE_ACCOUNT | gated | not supplied |
| Copernicus Emergency Management | CDSE_ACCOUNT | gated | not supplied |

Notes that matter:

- The 8 gated feeds are declared with the exact env var each one needs; the probe reports
  them as `gated`, never as `live`. No gated feed is faked.
- The homepage copy says "the nine we are missing" (`public/index.html`) but the registry
  has **8** gated rows — the page string is stale.
- `docs/DATA_SOURCES.md` is a separate, wider reconnaissance of 40 candidate sources (23
  open / 11 key-gated / 5 bot-blocked / 1 unreachable). It is not the same 20-row list the
  running app probes; do not read the two tallies as the same measurement.
- The GIBS tiles are fetched through this app (`/api/satellite/tile/...`), which walks back
  up to 21 days (daily layers) or 25 months (monthly layers) until imagery exists, then
  serves it. That is why the MERRA-2 effective date is a month start.
- Air quality only forecasts 7 days (`aq_horizon_days: 7` in every report); beyond that the
  last known dust value is persisted and flagged, not extrapolated silently.

Caching is a disk + memory TTL cache in `backend/sg_datasources.py` (`cache_get` /
`cache_set`). TTLs: forecast 900 s, forecast archive and POWER 86,400 s, AERONET 604,800 s,
GIBS tile/mosaic 604,800 s, S3 listing 900 s, ECMWF 1,800 s, source-status 1,800 s. See
`docs/ARCHITECTURE.md`.

---

## The soiling model

`backend/sg_soiling.py` is **rate-anchored**, not annual-anchored. Loss grows as an
exponential approach to an asymptote, over *effective dust days* rather than calendar days:

```
loss(t) = 100 * min(0.55, lmax * (1 - exp(-exposure / tau)))          # percent
tau     = lmax / (rate / 100)      # so dloss/dt at t=0 is exactly `rate` %/day
```

Exact constants from the file:

| Constant | Value |
|---|---|
| `CLIMATE_RATE_PCT_PER_DAY` | west 0.30, east 0.80, inland 0.50, highland 0.18 (%/day at t=0) |
| `CLIMATE_LMAX` | west 0.85, east 0.92, inland 0.90, highland 0.80 (never-clean asymptote) |
| `CLIMATE_DUST_BIAS` | west 0.85, east 1.25, inland 1.05, highland 0.70 |
| `tau` (derived) | west 283.33, east 115.00, inland 180.00, highland 444.44 days |
| `LITERATURE` (reference only) | west 15.0 %, east 45.0 %, inland 30.0 %, highland 12.0 % |
| `REFERENCE_PM10` | 120.0 µg/m³ |
| `RAIN_WASHOFF_MM` | 5.0 mm (a wash-off rain resets exposure to 15 %) |
| `PR_BASE` / `TEMP_COEFF` | 0.80 / -0.0040 per °C |
| `MAX_LOSS_FRAC` | 0.55 (loss ceiling; the file cites >50 % drop after six months uncleaned) |
| `MAX_EXPOSURE_DAYS` | 400 |

`dust_factor(day)` — one day's effective dust-days — is the product of the climate dust
bias, a PM10 ratio clamped to [0.20, 5.0] × 120 µg/m³, a wind/gust shape (deposition rises
to 8 m/s, then scours above it), a humidity multiplier (dew cementation above 25 % RH), and
an irradiance multiplier. It is clamped to [0.05, 3.5]. Seasonality is a two-peak Gaussian
over day-of-year (main peak day 60, secondary day 300) in `dust_season_factor`.

**How the published 15 % / 45 % / 12-36 % figures relate.** They are the *literature
reference band* for the climate class, quoted next to the simulated numbers, not the model's
own output. The model anchors the published **daily rate** (0.1-0.5 %/day typical, up to
~2 %/day in dust events) and lets real weather move the day-to-day shape. It does not
reproduce 45 % mean annual loss at weekly cleaning — it cannot, and the code says so: a
0.8 %/day east-coast rate under weekly cleaning gives a mean annual soiling loss of **4.61 %**
for Dammam (measured from the live annual simulation below), not 45 %. The gap is real and
is written up in `docs/MODEL_CARD.md` (the 45 %-class annual figures imply either far heavier
exposure than a 0.8 %/day anchor or longer cleaning intervals than one week). Both numbers
are shown to the operator, labelled, side by side.

---

## The cleaning-policy optimiser

`policy()` simulates a full 365-day year at the site (dust seasonality + irradiance curve,
no network) for every fixed calendar in {5, 7, 10, 14, 21, 30, 45, 60} days and 12 loss
thresholds {1, 2, 3, 4, 5, 6, 8, 10, 12, 15, 20, 25 %}, plus a never-clean baseline. It
**scores each policy on total cost = lost-generation value + cleaning spend** and keeps the
minimum. The operator's current habit is one of the candidates, so if adaptive cannot beat
it the answer says so (`beats_calendar`).

Dammam 100 MWp, live run
(`curl -s "https://space-marines.aimaher.com/solarguard/api/report?site=dammam&capacity_kwp=100000&cleaning_interval_days=10&horizon_days=10"`):

Model anchor for this site: climate `east`, `rate 0.8 %/day`, `tau 115.0 d`, `lmax 0.92`,
literature reference 45 % (KAUST east coast, weekly cleaning). Assumptions: tariff
0.18 SAR/kWh, cleaning 1,800 SAR/MWp, performance ratio 0.78, irradiation 7.2 / 5.0
kWh/m²/day summer / winter, rain not credited.

One simulated year at this site:

| Policy | Cleans/yr | Mean soiling loss | Energy lost | Cleaning spend | Total cost/yr |
|---|---|---|---|---|---|
| Weekly calendar | 52 | 4.61 % | 1,424,310 SAR | — | 10,784,310 SAR |
| Industry habit (10 d) | 36 | 6.23 % | 1,928,287 SAR | 6,480,000 SAR | 8,408,287 SAR |
| **SolarGuard tuned policy** | 18 | 11.09 % | 3,469,781 SAR | 3,240,000 SAR | **6,709,781 SAR** |
| Best fixed calendar (21 d) | 17 | 11.83 % | 3,667,759 SAR | 3,060,000 SAR | 6,727,759 SAR |
| Never clean | 0 | 50.94 % | 16,130,333 SAR | 0 SAR | 16,130,333 SAR |

Tuned trigger: 20 % loss. Adaptive beats the best fixed calendar by 17,978 SAR/yr
(`beats_calendar: true`). Annual saving versus the 10-day habit: 1,698,506 SAR; events saved
18/yr; water saved 4,500,000 L/yr (at 2,500 L per MWp per wet clean). The tuned policy wins on
*total* cost by cleaning less often and accepting more soiling loss — deliberately, because
cleaning costs more than the generation it recovers at this tariff.

Two things the numbers expose honestly:

- `opportunity.energy_kept_pct` is **-79.94** because the tuned policy loses *more* energy
  than the calendar; the saving is in crew spend, not energy. The live homepage renders this
  as "keeps -79.9 % more of the lost energy" — a confusing label that should be replaced.
- Over the 10-day *forecast horizon*, the adaptive policy makes 0 cleans and saves nothing
  versus the 10-day calendar (both lose 33,839.51 SAR): the 20 % trigger is not reached in
  10 days of measured weather. The adaptive win is an annual-optimisation result, not a
  within-horizon one.

The live verdict for this site on 2026-10-07: current loss 0.73 %, urgency 2.4/100, 7-day
money at risk 16,626.74 SAR against a 180,000 SAR crew → **WAIT** (payback 75.8 days).

---

## ML models

From `models/metrics.json` (generated 2026-10-07T12:14:53Z, wall clock 188.1 s). Two
hand-written pure-numpy models, CPU only, trained on `data/soiling_dataset.csv`.

Dataset: 30,672 rows in the training table, 29 features, 12 sites, dates 2019-01-01 to
2025-12-30, targets `soiling_loss_pct` (next-day) and `deposition_g_m2_day`. Time-split
cutoff 2024-08-06 → 24,528 train / 6,144 test rows.

Features (29, `models/feature_meta.json`): lat, lon, elevation_m, doy_sin, doy_cos, tmax_c,
tmin_c, tmean_c, rh_mean_pct, wind_max_kmh, gust_max_kmh, precip_mm, radiation_mj_m2,
et0_mm, pm10_mean_ugm3, pm2_5_mean_ugm3, dust_mean_ugm3, aod_mean, days_since_rain,
days_since_clean, plus causal rolling means/sums/max (3/7/30/90-day windows) and causal
expanding means of pm10, dust and AOD.

**Time split** (latest 20 % of calendar dates held out, n = 6,144):

| Model | Target | MAE | RMSE | R² | Bias |
|---|---|---|---|---|---|
| GBRT | soiling_loss_pct | 9.532 | 13.601 | 0.636 | -2.99 |
| GBRT | deposition_g_m2_day | 0.0620 | 0.1082 | 0.355 | -0.0198 |
| MLP | soiling_loss_pct | **7.973** | **11.636** | **0.733** | -3.46 |
| MLP | deposition_g_m2_day | 0.0719 | 0.1337 | 0.016 | -0.0394 |

**Leave-one-site-out** (each site held out in turn, trained on the other 11, n = 30,672):

| Model | Target | MAE | RMSE | R² | Bias |
|---|---|---|---|---|---|
| GBRT | soiling_loss_pct | **8.621** | **12.541** | **0.594** | +1.58 |
| GBRT | deposition_g_m2_day | 0.0537 | 0.1007 | -0.208 | +0.022 |
| MLP | soiling_loss_pct | 11.175 | 18.533 | 0.113 | -1.26 |
| MLP | deposition_g_m2_day | 0.0485 | 0.0769 | 0.296 | +0.003 |

Per-fold, the GBRT soiling-loss MAE ranges from 3.58 (Yanbu) to 26.97 (Riyadh, R² -1.57);
the MLP collapses on the Abha fold (MAE 48.29, R² -24.77), which is the clearest sign that
the MLP does not generalise geographically. The GBRT is the more honest of the two across
unseen sites.

Model config (`metrics.json → model_config`): GBRT — 40 trees, depth 3, learning rate 0.06,
subsample 0.85, colsample 0.7, 32 bins, min_samples_leaf 25. MLP — hidden 64-32, ReLU, Adam,
lr 3e-3, batch 128, 25 epochs, L2 1e-5. (The `ml/train.py` CLI defaults are larger —
`--trees 220 --epochs 160` — and `logs/exp_dep.log` records weaker variants at 200-250 trees
/ 150 epochs: native R² 0.379 / 0.312 / 0.137. The shipped metrics are the 40-tree run.)

**Honest limitation.** The labels are produced by `ml/physics_soiling.py`, a
literature-calibrated mass-balance model, **not** measured inverter or soiling-sensor data.
`metrics.json → dataset.label_provenance` says so: "physics_soiling.py literature-calibrated
labels (NOT measured field soiling)". The *inputs* are measured (Open-Meteo ERA5 meteorology
2019-2025; CAMS aerosol 2024-2025, with pre-2024 backfilled from a per-site climatology
fitted to that site's own 2024-25 data). So these metrics measure how well the ML reproduces
a physics model, not how well it predicts a real plant. See `docs/MODEL_CARD.md`.

**The ML path is currently inactive.** `backend/sg_soiling._ml_model()` loads
`models/gbrt.npz` via `ml/predict.py`, which calls `GBRT.from_npz`. On this box that raises
`KeyError: 'loss_base is not a file in the archive'` — the `.npz` on disk predates the
`to_npz` prefix fix documented in `ml/train.py` (the archive has unprefixed `base`,
`n_trees`, `depth`, `lr` plus `loss_*`/`dep_*` trees; the loader looks for `loss_base`).
Files: `models/*.npz` mtime 14:14:53, `ml/train.py` mtime 14:29:48. Consequence: the live
app reports `soiling_model: "physics"` (`/api/version`) and the dashboard shows "physics
serving". Fixing it requires re-running `python ml/train.py` with the current writer, or
patching the loader — neither is done. The metrics above are real output of a training run
whose artifacts no longer load.

---

## The agent

`backend/sg_agent.py` — a DeepSeek tool-calling agent named "Sol". Model id
`deepseek-flash` (overridable with `SOLARGUARD_MODEL`); key read server-side from
`backend/.env`, never sent to the browser. Live `/api/ai/status` confirms
`ai_enabled: true`, `model: deepseek-flash`.

Ten tools, by name:

| Tool | What it does |
|---|---|
| `list_sites` | Lists the 12 Saudi sites with coordinates, region, climate class, capacity. |
| `site_report` | Full report for a site (projection, output, cleaning verdict, money at risk) — the workhorse tool. |
| `get_dust_outlook` | Daily PM10, dust, AOD, peak wind/gust and dust-risk band for a point. |
| `compare_sites` | Two sites side by side: soiling loss, verdict, money at risk. |
| `nearest_aeronet` | Nearest AERONET sun-photometer stations (ground-truth AOD). |
| `satellite_layers` | The live GIBS raster layers and their freshest available date. |
| `source_health` | Live status of every data source (open/gated). |
| `search_literature` | BM25 search over the harvested soiling papers. |
| `place_site` | **Action**: move the dashboard map to a site. Returns a UI action. |
| `show_satellite_layer` | **Action**: switch the dashboard satellite layer/date. |

Retrieval is `backend/sg_rag.py`, a hand-written BM25 Okapi (k1 = 1.5, b = 0.75) in pure
Python — DeepSeek's public API has no embeddings endpoint and the box has no local embedding
model, so a lexical retriever is the honest choice and it matches the exact tokens operators
use (PM10, MAIAC, Sudair, SAR). Live index: **630 chunks**, 11,512 terms
(`curl -s .../solarguard/api/rag/stats`). The chunks come from `data/corpus/chunks.jsonl`
(606 lines) plus chunks of `docs/DATA_SOURCES.md` (15) and `docs/FACTS_SHEET.md` (9). The
index rebuilds automatically when corpus files change (`sg_rag.index()` stamps mtimes).

Tool-loop design (`MAX_TOOL_ROUNDS = 3`, `MAX_CALLS_PER_ROUND = 3`): each round the model
gets the tools; every tool call it declares **must** get a tool message back or the next
request is rejected with a 400, so calls beyond the per-round cap are answered with a
"skipped" note rather than dropped. Identical calls are served from a cache. If the model
spends its rounds gathering data and never writes prose, the agent makes one clean final call
with **no tool messages in the history at all** (carrying `tool_calls`/`tool` messages into a
tool-less call is what makes some gateways return an empty completion), and if that still
returns nothing it composes a deterministic answer from the real tool output
(`_fallback_summary`). The user never gets an empty bubble.

The token-budget pitfall is documented in the code comments: `deepseek-flash` is a
**reasoning model** — it emits `reasoning_content` before the visible answer, and those
thinking tokens count against `max_tokens`. Too small a budget yields a perfectly successful
HTTP 200 with an empty `content` field, which looks like a broken agent. Hence
`TOOL_ROUND_MAX_TOKENS = 2000` and `FINAL_ANSWER_MAX_TOKENS = 3200`, and `AGENT_TIMEOUT =
70 s`.

---

## Deployment

The app is a FastAPI **sub-application** (`sg_app = FastAPI(...)` in `backend/sg_app.py`,
`docs_url=None`). The site host (the `space-marines` FastAPI app) mounts it at `/solarguard`,
so every route is reachable at `https://space-marines.aimaher.com/solarguard/...`. The
sub-app keeps the host's contract: API routes registered **before** the static mount, the
static mount registered **last**, `/api/health` and `/api/version` always answer, and no
route may raise — failures come back as JSON so pages keep working. The host wraps the import
so a broken sub-app cannot take the main site down (guarded import); the sub-app also has its
own crash barrier middleware.

Verified live on 2026-10-07:

```
$ curl -s -o /dev/null -w '%{http_code} %{redirect_url}\n' https://space-marines.aimaher.com/solarguard
308 https://space-marines.aimaher.com/solarguard/      # bare path redirects to the slash form
$ curl -s -o /dev/null -w '%{http_code} %{content_type}\n' https://space-marines.aimaher.com/solarguard/
200 text/html; charset=utf-8
$ curl -s https://space-marines.aimaher.com/solarguard/api/version
{"service":"solarguard-space","version":"1.0.0","ai_model":"deepseek-flash","ai_configured":true,"soiling_model":"physics"}
```

The domain root now also serves the SolarGuard landing HTML and the SolarGuard API:
`https://space-marines.aimaher.com/` and `.../solarguard/` return byte-identical HTML
(10,758 B), and `/api/report` answers 200 at the root — while `/api/version` and
`/api/health` at the root still return the host's own `space-marines` identity. `/api/sg/status`
(used by the homepage) is a host-provided alias that reports the same agent/RAG facts
(`tool_count: 10`, `rag.chunks: 630`, `soiling_model: "physics-empirical"`). Full details,
including rollback and the exact verification commands, are in `docs/DEPLOYMENT.md`.

---

## Run it locally

```bash
cd /home/hermes2/solarguard-space
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt

# serve the sub-app on its own (URLs without the /solarguard prefix)
cd backend && python -m uvicorn sg_app:sg_app --host 127.0.0.1 --port 8099
# then: http://127.0.0.1:8099/  and  http://127.0.0.1:8099/api/health
```

Tests (both run against the real APIs and the real copilot, so they need network and the
DeepSeek key in `backend/.env`):

```bash
python3 tests/test_asgi.py      # in-process ASGI walk over every route; prints 5xx count
python3 tests/test_backend.py   # end-to-end: forecast, soiling, verdict, agent, RAG
```

Expected: `test_asgi.py` ends with `5xx count: 0`. Note it probes
`/assets/hero/turntable/001.jpg`, which currently 404s (see below). To retrain the ML models:
`python3 ml/build_dataset.py && python3 ml/train.py`; to re-fit the label model:
`python3 ml/physics_soiling.py --calibrate`.

---

## What is not done / would be next

Measured gaps, in rough priority order:

1. **The ML models do not load at runtime.** `models/gbrt.npz` raises
   `KeyError: 'loss_base'` in `GBRT.from_npz`; the archive predates the `to_npz` prefix fix.
   The deployed app serves physics only. Re-train with the current `ml/train.py` (or patch
   the loader), then re-verify `/api/version` reports `ml+physics`.
2. **Labels are not measured data.** The ML metrics are a physics-model reproduction test.
   The real fix is inverter/SCADA or DustIQ-sensor labels for at least one site.
3. **Rendered hero frames are not shipped.** `public/assets/hero/{turntable,dustwave,clean}/`
   exist but are empty (`find public/assets/hero -type f` = 0 files). `blender/encode.sh`
   would write `001.jpg` scroll frames there. `tests/test_asgi.py` probes
   `assets/hero/turntable/001.jpg` and gets 404. `renders/{turntable,dustwave,clean}/frames`
   hold 60 raw PNGs (38 MB) that nothing serves.
4. **The 47 curated facts in `data/knowledge.json` are not indexed.** `sg_rag.load_corpus`
   looks for `fact["statement"]`/`["fact"]`/`["text"]`, but the file stores the claim under
   `"claim"`, so all 47 are silently skipped. The BM25 index is literature + docs only.
5. **`energy_kept_pct` is a misleading metric** (negative = the tuned policy keeps *less*
   energy) and is rendered on the homepage as "keeps -79.9 % more of the lost energy".
   Replace with a cost-saving figure.
6. **Stale page copy**: "the nine we are missing" (`public/index.html`) vs 8 gated sources;
   no `README`/`LICENSE` existed before this documentation pass.
7. **8 key-gated feeds unimplemented** (CAMS on ADS, Sentinel-5P, MERRA-2 on GES DISC,
   MAIAC HDF, NSRDB, JAXA P-Tree, Copernicus EMS, SoDa). Each is declared with its env var,
   none is wired to a real client.
8. **`/api/sg/status` and `/api/version` disagree** on the soiling-model string
   (`physics-empirical` vs `physics`).
9. **No auth, open CORS, no rate limiting.** Deliberate for a public demo, not for a real
   deployment (see `docs/ARCHITECTURE.md` for the security model).

One documentation caveat: the front end was being edited concurrently while this document was
written. `public/assets/js/sg-scrollstory.js` (37,485 B), `sg-realmaps.js`, `map-test.html`
and `story-test.html` were all created at 14:38-14:41 on 2026-10-07, after the first read of
the tree; an early draft of this section wrongly reported `sg-scrollstory.js` as missing. All
front-end statements here were re-verified against the tree and the live site after those
edits (index.html 10,758 B, live `sg-scrollstory.js` → HTTP 200).

---

## Files in this repository

Source and data files. Bulk directories (`data/cache`, `renders/*/frames`) are summarised
rather than listed row by row.

| Path | Purpose |
|---|---|
| `README.md` | This document. |
| `requirements.txt` | Runtime Python dependencies with the versions installed on the box. |
| `.gitignore` | Excludes venv, caches, logs, renders and `.env`. |
| `LICENSE` | MIT, team space-Marines. |
| `backend/sg_app.py` | FastAPI sub-app: all `/api/*` routes, CORS + no-raise middleware, static mount. |
| `backend/sg_agent.py` | DeepSeek tool-calling agent: 10 tools, tool loop, fallback summariser, system prompt. |
| `backend/sg_config.py` | Paths, 12-site Saudi catalogue, economics constants, GIBS layer catalog, `.env` parser. |
| `backend/sg_datasources.py` | Live data layer: TTL disk/memory cache, Open-Meteo/POWER/GIBS/AERONET/S3/ECMWF, source registry and probe. |
| `backend/sg_soiling.py` | Rate-anchored soiling physics, PV yield, cleaning-policy optimiser, verdict, annual estimate, ML hook. |
| `backend/sg_rag.py` | Hand-written BM25 Okapi retriever over corpus + docs; index stats and citation block. |
| `backend/.env` | DeepSeek key + base URL. Gitignored; must never be committed. |
| `ml/build_dataset.py` | Builds `data/soiling_dataset.csv` from Open-Meteo archive + air-quality (2019-2025). |
| `ml/physics_soiling.py` | Literature-calibrated mass-balance label generator; fits per-site factors by bisection. |
| `ml/train.py` | From-scratch numpy GBRT + MLP training; time-split and leave-one-site-out evaluation; writes `models/`. |
| `ml/predict.py` | Pure-numpy inference API loading `models/*.npz`; economics and confidence helpers. |
| `harvest/probe_gibs.py` | Parses the NASA GIBS WMTS capabilities into `data/gibs_layers.json`. |
| `harvest/fetch_borders.py` | Downloads public-domain country outlines into `public/assets/data/borders.json`. |
| `data/build_corpus.py` | Extracts PDFs/HTML into `data/corpus/*.txt` and chunks them to `chunks.jsonl`. |
| `data/extract_pdfs.py` | PDF -> text with page markers (pymupdf). |
| `data/build_knowledge.py` | Emits `data/knowledge.json` (47 cited facts + 27 satellite use cases). |
| `data/gibs_layers.json` | Catalog of 8 GIBS dust/aerosol layers parsed from the live capabilities doc. |
| `data/knowledge.json` | Curated cited facts (schema 1.0). Not currently indexed — see gaps. |
| `data/soiling_dataset.csv` | 30,684-row merged daily training table (7.7 MB). |
| `data/soiling_dataset.csv.meta.json` | Build provenance: per-site row counts, AQ measured vs modelled days, columns. |
| `data/corpus/*.txt`, `data/corpus/chunks.jsonl` | Extracted literature text and its 606 pre-chunked lines. |
| `data/papers/*.pdf` | Four open-access source papers (IEA-PVPS, Energies x2, JMRT). |
| `data/weather/<site>.json` | Per-site cached met + daily air-quality pulls (12 files). |
| `data/_*.{json,md,html,sh,tsv}` | Raw acquisition evidence from the source probe / corpus build. |
| `data/cache/*` | 309 disk-cache blobs (GIBS tiles/mosaics, Open-Meteo, POWER, AERONET, source status). |
| `models/gbrt.npz` | Trained gradient-boosted trees (23 arrays). Does not load with the current loader. |
| `models/mlp.npz` | Trained MLP weights (13 arrays). |
| `models/metrics.json` | Real holdout metrics, model config, literature calibration, dataset provenance. |
| `models/feature_meta.json` | Feature order, defaults, ranges, scaler mean/std, training interval. |
| `models/soiling_calibration.json` | Per-site fitted `site_factor` and achieved annual loss for the label model. |
| `public/index.html` | Landing page (live at `/solarguard/`; loads `sg-home.js`). |
| `public/dashboard.html` | Operator dashboard: map, projection charts, cleaning plan, copilot panel (loads `sg-dashboard.js`). |
| `public/map-test.html` | Standalone harness for the real-map module (`sg-realmaps.js`). |
| `public/story-test.html` | Standalone bench for `sg-scrollstory.js`. |
| `public/assets/css/solarguard.css` | All styling. |
| `public/assets/js/sg-core.js` | Shared runtime: API client, formatters, canvas charts, dust field, toasts. |
| `public/assets/js/sg-home.js` | Homepage controller; drives source/model/impact tables from the live API; dynamically imports `sg-scrollstory.js`. |
| `public/assets/js/sg-scrollstory.js` | Canvas-2D scroll storyboard (own 3D→2D projection; no three.js/CDN). |
| `public/assets/js/sg-dashboard.js` | Dashboard state and re-render logic; dynamically imports `sg-realmaps.js`. |
| `public/assets/js/sg-realmaps.js` | Leaflet 1.9.4 + Carto/OSM basemap with the GIBS overlay. |
| `public/assets/js/sg-map.js` | Dependency-free canvas map (fallback when Leaflet is unreachable). |
| `public/assets/js/sg-3d.js` | Canvas globe and panel rig. Not currently imported by any page or module — the scroll story uses `sg-scrollstory.js`. |
| `public/assets/data/borders.json` | Public-domain country outlines for the map and 3D globe. |
| `public/assets/models/*.glb` | Two GLB assets (solar panel, globe). |
| `public/assets/hero/{turntable,dustwave,clean}/` | Empty directories for scroll-scrub frames (not yet populated). |
| `docs/DATA_SOURCES.md` | 40-source reconnaissance with per-source probe evidence and activation notes. |
| `docs/FACTS_SHEET.md` | Cited numbers digest (soiling rates, seasonality, mechanisms, Saudi context). |
| `docs/MODEL_CARD.md` | Soiling + ML model card. |
| `docs/ARCHITECTURE.md` | Modules, data flow, request lifecycle, caching, failure handling, security. |
| `docs/DEPLOYMENT.md` | Mount, guarded import, redirect, permissions, verification, rollback. |
| `tests/test_asgi.py` | In-process ASGI walk over every route; counts 5xx. |
| `tests/test_backend.py` | End-to-end backend test incl. the copilot. |
| `blender/build_scene.py` | Procedural Blender scene builder (Cycles CPU, headless). |
| `blender/render_anim.py` | Headless renderer for the turntable/dustwave/clean/stills sequences. |
| `blender/encode.sh` | Encodes frames to mp4/webp/gif and the `public/assets/hero/` scroll frames. |
| `logs/*.log`, `logs/*.json`, `logs/exp_dep.py` | Build/render logs and the log-space experiment script. |
| `logs/test_scene.blend` | Saved Blender scene (3.7 MB, gitignored). |
| `renders/turntable|dustwave|clean/frames/*.png` | 60 raw render frames (38 MB, gitignored). |
| `assets/`, `brand/` | Empty directories (no files). |
