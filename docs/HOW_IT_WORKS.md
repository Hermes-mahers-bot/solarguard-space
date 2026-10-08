# How SolarGuard Space works — the complete, plain-language walkthrough

Written so anyone on the team can explain any part of it without opening the code.
Three parts: **the data**, **the AI**, **the agent** — then a reference section that
lists every file, every endpoint and every number.

---

# PART 1 — THE DATA

## 1.1 The two kinds of data (do not mix them up)

**Kind A — "live".** Read from the internet the moment someone opens the page.
Nothing is copied to our disk, nothing is invented. Cached ~15 minutes so we don't
hammer free services.

**Kind B — "history".** Four years of the same measurements, downloaded once, saved
as a spreadsheet, and used to *teach* the AI. The AI learns from history; the product
runs on live data.

## 1.2 Every field we use, what it means, and why

| Field | Unit | Plain meaning | Why we care | Where it comes from |
|---|---|---|---|---|
| **PM10** | µg/m³ | weight of particles **smaller than 10 micrometres** in one cubic metre of air | this is the grit that lands on the glass | CAMS (via Open-Meteo) |
| **dust** | µg/m³ | **all** airborne dust, including the big coarse grains | coarse grains are heavy and settle fast, so this predicts what lands tonight | CAMS |
| **AOD** (aerosol optical depth) | number | how much sunlight the dust in the air is blocking: 0 = crystal clear, 1+ = thick haze | tells us dust is present over a wide area, not just at ground level | MODIS/MAIAC, CAMS |
| **wind gust** | m/s | the strongest burst of wind that day | wind is what **lifts** dust off the ground in the first place | ECMWF, NOAA GFS |
| **wind speed** | m/s | the average wind | separates a steady breeze from a gusty, dust-lifting day | ECMWF |
| **wind direction** | degrees | where the wind came from (0–360) | a north-easterly in Saudi Arabia means a *shamal*, the storm direction | ERA5 |
| **irradiation** | MJ/m²/day | the total sun energy that arrived on a flat surface that day | divide by 3.6 to get kWh/m² — this is "how much we could have made" | NASA POWER, ERA5 |
| **air temperature** | °C (max/min/mean) | how hot the day was | hot panels lose efficiency — about **0.38 % per °C** above 25 °C | ERA5 |
| **relative humidity** | % | how moist the air is | moisture makes dust **cement** onto glass, so it stops blowing off | ERA5 |
| **rain** | mm | how much rain fell | **the only free cleaning** — rain resets the glass | Open-Meteo |
| **PM2.5** | µg/m³ | the finer fraction (under 2.5 µm) | the fine dust that hazes the glass evenly | CAMS |
| **satellite imagery** | tiles | actual pictures of the dust plume over the Kingdom | this is what the dashboard map shows | NASA GIBS (MODIS, MERRA-2) |
| **AERONET** | AOD | readings from ground stations that physically look at the sky | used as **truth** to check whether the satellites are right | AERONET network |

## 1.3 Which feeds we use, and their status

**12 open feeds — answering today, no key or account needed:**
NASA GIBS (satellite imagery) · NASA POWER (irradiation, climate) · AERONET (ground
truth) · NOAA Himawari-9 (geostationary imagery) · NOAA GFS (forecast fields) ·
ECMWF open data · Open-Meteo forecast (weather) · Open-Meteo air quality (CAMS dust) ·
Open-Meteo archive (history) · AEMET SDS-WAS (dust forecasts) · public country
outlines (map shapes) · NASA GIBS WMTS capability catalogue.

**8 key-gated — the code is written, we just need the account:**
Copernicus ADS · Copernicus Data Space · NASA Earthdata · NREL NSRDB ·
JAXA P-Tree · Alaska Satellite Facility · ESA WorldCover · Sentinel Hub.

## 1.4 The history we downloaded for training

* **One row = one site on one day.** 21 raw columns.
* **18,348 rows** = **12 sites × 1,529 days** each, from **1 Aug 2022 to 7 Oct 2026**.
* **99.8 % of rows are complete**; every missing window is listed rather than filled
  with zeros.
* **Why it starts in 2022:** the dust archive (CAMS) physically begins on
  **29 July 2022**. Earlier dates return empty values — we checked, and it is
  written in the code so nobody wonders later.
* **The 12 sites:** Dammam, Jeddah, Riyadh, NEOM, Sakaka, Tabuk, AlUla, AlJubail,
  Shaqra, Sudair, Abha, Yanbu.

## 1.5 The 37 numbers we feed the AI, per day (the "features")

Raw fields alone are not enough — dust builds up over days, so we add history. All
37, in plain language:

**Where (3):** latitude · longitude · elevation in metres.
**When (2):** the day of the year as a smooth wave (two numbers, so 31 Dec sits next
to 1 Jan instead of jumping).
**Today's weather (9):** max / min / mean temperature · humidity · max wind · max
gust · rain · wind direction · sun energy.
**Today's dust (6):** PM10 max · PM10 average · dust max · dust average · AOD · PM2.5.
**How long since (2):** days since it last rained (≥1 mm) · days since the last
storm day.
**History windows (10):** PM10 max over the last 3 / 7 / 30 days · dust average over
7 / 30 days · biggest gust over 7 / 30 days · rain total over 7 / 30 days · AOD
average over 7 days.
**Yesterday and before (4):** PM10 max 1, 2 and 3 days ago · dust average yesterday.
**Dust already on the glass (1):** an estimate of the fraction of sunlight the
current dirt is blocking.

**The rule that keeps this honest:** a row dated *today* is only allowed to use days
**up to today**. No looking at tomorrow. If we broke that rule, the AI would score
beautifully in testing and fail in real life.

---

# PART 2 — THE AI

## 2.1 What it predicts (three things)

1. **Will a sandstorm come?** A probability for **+1, +2 and +3 days** ahead.
2. **How much will the panels make?** Tomorrow's energy, in kWh and in kWh per kWp
   (per kilowatt of installed panels).
3. **How dirty will the glass be?** Tomorrow's soiling loss, as a % of output lost.

## 2.2 How it was trained — 7 steps in order

**Step 1 — Collect.** Downloaded 4 years of weather + dust for 12 sites → 18,348
daily rows. Saved as `data/ai/daily.csv`. Coverage report in
`data/ai/harvest_report.json`.

**Step 2 — Build the 37 numbers.** For every day, compute the 37 features listed
above, using only that day and the days before it.

**Step 3 — Define the answers (the "labels"). This took the most work.**
* **Sandstorm day** = that day's maximum PM10 is at least **three times that site's
  own normal (median)**, and never below **300 µg/m³**. This labels **10 %** of days.
* **Panel output tomorrow** = the measured sun energy × a standard panel formula
  (temperature losses × soiling loss). This is a **formula applied to measured
  weather — not a meter reading**, because no public Saudi inverter data exists. We
  state that openly instead of hiding it.
* **Soiling tomorrow** = how much dust the deposition formula says has accumulated
  since the last rain.

**Step 4 — Split the data honestly.**
* Train on everything before **1 Oct 2025** — 13,344 days.
* Tune on **Oct 2025 – Mar 2026** — 2,184 days.
* **Test on Apr – Oct 2026 — 2,244 days we never looked at.**
* Plus **leave-one-site-out**: hide an entire site, train on the other 11, then score
  on the hidden one. That is the "would this work at a new plant?" test.

**Step 5 — Train two different kinds of model, both written by hand in plain Python
(numpy).** No machine-learning library, no torch, no GPU — 4 CPU cores:
* **Gradient-boosted trees** — 300–320 small decision trees, each one fixing the
  previous ones' mistakes. Depth 3–4, learning rate 0.05–0.08, 32 buckets per
  feature, 85 % of rows sampled per tree, 70–75 % of features per tree. For the
  storm it uses **logistic loss** (because it must output a probability); for the two
  amounts it uses squared error.
* **A small neural network** — two hidden layers of 64 and 32 neurons, ReLU, trained
  with Adam at learning rate 0.003 for 120 passes over the data, batches of 128.
* **Then we blend them.** The weights come from whichever was more accurate on the
  validation months (storm: 42 % trees / 58 % network; output: about the same).
  Blending by measured skill means the pair can never be worse than the weaker one.

**Step 6 — Score it, and compare it to stupid baselines.** Because "94 % accurate"
means nothing if the obvious guess does the same.
* Baselines for storms: always guess the normal rate ("climatology"), and
  "tomorrow looks like today" (persistence).
* Baselines for amounts: "yesterday's sun repeats today", and "the average day".

**Step 7 — Serve it.** `/api/ai` asks Open-Meteo for **the last 92 days plus the
next few days**, rebuilds the **same 37 features**, and runs the models. 92 days is
the key trick: it is why the rolling-history numbers exist at prediction time, not
just in training.

## 2.3 Accuracy — the numbers to quote

| What | Result on days it never saw |
|---|---|
| Sandstorm, +1 day | catches **69 %** of storms, 75 % of alarms real, **AUC 0.952** |
| Sandstorm, +2 days | catches **61 %**, precision **85 %**, AUC 0.929 |
| Sandstorm, +3 days | catches **69 %**, precision 74 %, AUC 0.931 |
| Panel output, tomorrow | **±0.234 kWh per kWp = 7.7 % of the average day**, R² 0.949 |
| Soiling, tomorrow | **±3.17 percentage points = 8.4 %**, R² 0.974 |
| Any of these, at a site never seen | output ±0.429, soiling ±9.3, storm AUC 0.785 |

**Plain-language translations:**
* AUC 0.952 means: pick one storm day and one calm day at random, and the model
  ranks the storm day higher **95 times out of 100**.
* "±0.234 kWh/kWp" means: a 100 MWp plant, tomorrow, is predicted within about
  **±23,400 kWh**.
* "R² 0.949" means: the model explains 95 % of the day-to-day variation in output.
* Compare with the dumb baseline: carrying yesterday's sun forward is wrong by
  **2.572 kWh/kWp** — the AI is **11×** more accurate.

**The honest caveats we volunteer:**
1. At **+1 day**, the dumb rule "tomorrow looks like today" scores a slightly better
   F1 (0.743 vs 0.719) — because dust episodes last several days. The AI wins at +2
   and +3 days, and is far better calibrated (Brier 0.062 vs 0.132).
2. The output label is a formula, not a meter.
3. Soiling assumes **rain is the only cleaning** (so it differs from the physics
   engine's "since your last clean" number — both are shown, labelled separately).

## 2.4 The physics engine — the second, separate brain

The AI **predicts**; this engine **decides**. Four formulas, all documented:

1. **Dust landing** (g/m²/day) = 0.00042 × (0.42 × dust + 0.16 × PM10) × wind factor
   ÷ rain factor. (Gusty days lift more; rain washes the surface.)
2. **Soiling loss (%)** = 100 × (1 − e^(−mass ÷ 30)) × 0.98. Dust builds, then
   saturates. The 30 is calibrated so a month of dry dust = **10–35 % loss**, which
   matches the published Saudi range of **0.2–0.8 % per day**.
3. **Panel output** = sun energy (kWh/m²) × performance ratio, where the ratio =
   0.80 × (1 − 0.0038 × (cell temp − 25 °C)) × (1 − soiling loss). Cell temperature
   rises above air temperature with sun.
4. **Cleaning cost** = cost per pass × how many passes per year.

**The policy optimiser** tries about 21 cleaning rules over a simulated year and
picks the best one per site. For Dammam: **clean when loss passes 20 %** → 18 cleans
a year.

**The money, Dammam 100 MWp, one simulated year:**
| Policy | Cleans/yr | Mean loss | Net cost/yr |
|---|---|---|---|
| Clean weekly | 52 | 4.6 % | 10.78M SAR |
| **Today's industry habit (every 10 days)** | 36 | 6.2 % | **8.41M SAR** |
| **Our tuned policy** | 18 | 11.1 % | **6.71M SAR** |
| Never clean | 0 | 50.9 % | 16.13M SAR |

→ **1.70M SAR/yr cheaper**, 18 fewer passes, **4.5M litres of water** saved.
**The counter-intuitive finding:** our policy cleans *less* often and *accepts more
dust* — because at this site, cleaning costs more than the dust it removes.

---

# PART 3 — THE AGENT

## 3.1 What it is

A chat assistant called **Sol** inside the dashboard. Model: **DeepSeek
`deepseek-flash`** — a "reasoning" model, which is why we give it a large token
budget (it spends tokens thinking before answering).

## 3.2 How it works — the loop, step by step

1. You type a question in the dashboard chat.
2. We send the model: your question + a **system prompt** (who it is, the current
   site, its size, your cleaning cost, and the rule "always answer with numbers") +
   **10 tool definitions** written as JSON.
3. The model **does not answer yet**. It replies with **tool calls** — for example
   `site_report(site="dammam")`.
4. **Our server runs those tools** against the live data and hands the results back.
5. The model may call more tools (up to **3 rounds**, maximum **4 calls per round**;
   duplicate calls are blocked).
6. It writes the final answer, with the list of tools it used (**the tool trace**) and
   **citations** from the document search.

## 3.3 The 10 tools — exactly what it can use

**Reading the data:**
| Tool | What it does |
|---|---|
| `list_sites` | lists the 12 Saudi sites with their capacities and coordinates |
| `site_report` | the full forecast + money + cleaning verdict for one site |
| `get_dust_outlook` | the dust forecast, day by day, for one site |
| `compare_sites` | two or more sites side by side |
| `nearest_aeronet` | the closest ground-truth aerosol station and its readings |
| `satellite_layers` | the list of available satellite layers and dates |
| `source_health` | whether each data feed is answering |

**Knowledge:**
| Tool | What it does |
|---|---|
| `search_literature` | searches **672 indexed chunks** of harvested soiling research (606 of them from the seven papers) (KAUST, IEA-PVPS, MDPI…) using **BM25** — a keyword-ranking method: it scores how often your words appear in a chunk, weighted by how rare those words are (k1 = 1.5, b = 0.75). Every hit returns its source, so claims are cited. |

**Acting on the page (it doesn't just talk):**
| Tool | What it does |
|---|---|
| `place_site` | moves the map and re-prices a plant at a chosen location |
| `show_satellite_layer` | switches the satellite layer shown on the map |

## 3.4 What keeps it safe

* **No route may crash.** If a feed is down, the answer degrades, the page stays up.
* **A fallback answer.** If the model errors or returns nothing, we return a
  deterministic summary instead of an empty bubble.
* **Duplicates blocked** and a hard cap on rounds, so it cannot loop forever.
* **The API key lives only on the server** (`backend/.env`, never in the repo — we
  check the diff before every commit).

## 3.5 A real answer, from tonight's test

Asked: *"Should we clean Dammam this week?"*

> **WAIT** — Dammam sits at only 0.73 % soiling today (last clean ~0.9 days ago) and
> reaches 5.59 % by 12 Oct, so the next week's lost generation is just ~12,030 SAR
> against 180,000 SAR for one 100 MWp dry-cleaning pass — cleaning now would cost
> ~15× what it recovers, so hold until the 10–12 Oct dust pulse has blown through,
> then schedule the pass.

**The tool trace, in order (4 calls, all successful):** `site_report(dammam, 100 MWp)`
→ `get_dust_outlook(dammam, 7 days)` → `site_report(dammam, 7-day horizon, 10-day
habit)` → `site_report(dammam, 2-day horizon)`. That is the loop in action: it does
not guess, it fetches, then fetches again with different settings to check the
cleaning case before answering.

Answer length varies with the question: **~2,600 characters** for that open question,
and **520 characters** when the same question is asked with "answer in one
sentence". Everything above came back inside a single HTTP response
(`POST /api/assistant`), including `tool_trace`, `citations` and `elapsed_ms`.

---

# REFERENCE — every file, every endpoint, every command

## The pages
| File | What it is |
|---|---|
| `public/index.html` | homepage — sells the product, two scroll animations, no chat |
| `public/dashboard.html` | the working tool — two inputs, map, predictions, AI section |
| `public/technology.html` | the proof page — feeds, methods, model report card |
| `public/map-test.html`, `story-test.html` | dev harnesses for the map and animations |
| `public/assets/css/solarguard.css` | all styling |
| `public/assets/og.jpg` | the social preview image (a Blender render) |

## The JavaScript
| File | What it does |
|---|---|
| `sg-core.js` | API calls, number formatting, charts, dust particles, reveal-on-scroll |
| `sg-home.js` | homepage: starts both animations, fills the impact numbers |
| `sg-scrollstory.js` | animation 1 — sun, tilting panels, dust, cleaning pass |
| `sg-plume-story.js` | animation 2 — orbital view, shamal front crossing the Kingdom |
| `sg-dashboard.js` | dashboard logic: inputs, report, charts, AI section, chat |
| `sg-realmaps.js` | real map (Leaflet + OpenStreetMap + NASA overlay) |
| `sg-map.js` | hand-drawn canvas map, used automatically if the map library fails |
| `sg-tech.js` | fills the technology page tables |

## The backend (Python)
| File | What it does |
|---|---|
| `backend/sg_app.py` | every API endpoint |
| `backend/sg_config.py` | the 12 sites, satellite layers, credentials, cost presets |
| `backend/sg_datasources.py` | fetches live feeds, caches them on disk |
| `backend/sg_soiling.py` | the physics + economics engine and the policy optimiser |
| `backend/sg_ai.py` | runs the trained AI live (`/api/ai`) |
| `backend/sg_agent.py` | the DeepSeek agent, its prompt and its 10 tools |
| `backend/sg_rag.py` | the BM25 document search |
| `backend/.env` | the API keys — **never committed** |

## The machine learning
| File | What it does |
|---|---|
| `ml/ai_features.py` | defines the 37 features and the labels — **used by both the trainer and the server**, so they cannot drift apart |
| `ml/ai_train.py` | trains everything (run: `python3 ml/ai_train.py`, ~16 min) |
| `ml/harvest_ai_daily.py` | downloads the 4 years of history |
| `models/ai/*.npz` | the 5 trained models: storm +1, +2, +3, output, soiling |
| `models/ai/metrics.json` | the report card — every accuracy number |
| `models/ai/site_thresholds.json` | each site's own storm threshold |
| `data/ai/daily.csv` | the training table, 18,348 rows |
| `data/corpus/chunks.jsonl` | 672 indexed chunks the agent can quote (606 research, the rest our own docs) |

## The tests
| File | What it checks |
|---|---|
| `tests/test_ai.py` | 41 checks — including that the numbers the server builds match the ones the models were trained on |
| `tests/test_asgi.py` | every page and route through the real app (expects 0 server errors) |
| `tests/test_backend.py` | the live external feeds |
| `tests/verify_all.py` | full sweep: every endpoint, every page, desktop + phone |
| `tests/verify_model_consistency.py` | proves the shipped models and the report card came from the same training run |

## The API
| Endpoint | Returns |
|---|---|
| `/api/report?site=…&capacity_kwp=…` | the full forecast, economics and cleaning verdict |
| `/api/report?lat=…&lon=…` | the same, for a location the user tapped |
| `/api/ai?site=…` | **the AI's three predictions with their error bars** |
| `/api/ai/models` | the AI report card, machine-readable |
| `/api/sites` · `/api/forecast` · `/api/dust` · `/api/aeronet` | site list, weather, dust, ground truth |
| `/api/sources` | every feed and whether it is answering |
| `/api/satellite/layers` · `/api/satellite/tile/…` · `/api/satellite/image` | satellite catalogue, map tiles, stitched image |
| `/api/assistant` (POST) | **the agent** |
| `/api/rag/stats` · `/api/rag/search?q=…` | the document search |
| `/api/model` · `/api/sg/status` · `/api/health` | status and model information |

## The documents
`README.md` (everything) · `docs/PITCH.md` (judge brief) · `docs/MODEL_CARD.md` (what
the AI does, its error, and where it fails) · `docs/ARCHITECTURE.md` (how the pieces
connect) · `docs/DEPLOYMENT.md` (how it is served) · `docs/REAL_MAP.md` ·
`docs/SCROLL_STORY.md`.
