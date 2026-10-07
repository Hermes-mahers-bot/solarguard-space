# SolarGuard Space — the brief for judges

Six parts. Each one: **what it is**, **the steps we took**, **the proof** you can
show. Everything quoted here was produced by the code in this repository and is
reproducible from it.

Live: **https://space-marines.aimaher.com/** · Dashboard:
**https://space-marines.aimaher.com/dashboard.html** · Report card:
**/api/ai/models**

---

## Part 1 — The problem, and the product decision

**What it is.** A Saudi solar plant loses output to dust. Cleaning costs money, and
cleaning on a fixed calendar is wrong in both directions: too often wastes crews and
water, too rarely burns generation. The product answers one question per site per
day: **clean now, or wait** — and puts a number on both.

**The steps we took.**
1. Chose the customer: a plant operator with a budget (fleet, per monitored MWp) and
   a second tier for home/farm/rooftop. Prices are on the homepage.
2. Decided what we could *honestly* compute with open data only: dust load, soiling
   loss, the energy and riyals that loss costs, and the day a crew pays for itself.
3. Decided what we would **not** fake: no inverter telemetry exists publicly for
   Saudi plants, so we say so instead of inventing a meter reading.
4. Reframed the deliverable from a dashboard to a *decision tool* — the dashboard
   is evidence, the verdict is the product.

**The proof.** Dammam, 100 MWp, as of today: cleaning loss 0.73 % → verdict **WAIT**,
because 16,627 SAR is at risk over 7 days against a 180,000 SAR crew. Over a
simulated year the same site: a fixed 10-day habit costs **8.41M SAR**, our tuned
policy **6.71M** — a **1.70M SAR/yr** difference, 18 fewer passes and **4.5M litres
of water**. The counter-intuitive finding we will lead with: at an east-coast site,
**cleaning costs more than the dust it removes**, so our policy cleans *less* often
than the industry habit.

---

## Part 2 — The data layer: 12 open feeds, 8 waiting on credentials

**What it is.** Everything the product knows comes from satellites and weather
services. No mock data, no hand-typed numbers.

**The steps we took.**
1. Probed every candidate source for whether it answers **without a key**: NASA GIBS
   (MODIS aerosol, MERRA-2 dust, MAIAC), NASA POWER (irradiation, climate), AERONET
   (ground-truth aerosol), NOAA Himawari-9 and GFS open buckets, ECMWF open data,
   Open-Meteo (weather + CAMS-derived dust), AEMET SDS-WAS.
2. Wrote key-**ready** clients for the eight that need credentials (Copernicus ADS,
   Copernicus Data Space, NASA Earthdata, NREL NSRDB, JAXA P-Tree, ASF…) so the day
   an account exists, a key drops in and the pipeline extends.
3. Built a disk-cached fetch layer with TTLs and last-known-value fallback, so a
   dead feed degrades a number instead of breaking a page.
4. Harvested four years of history for the AI: **18,348 site-days** across 12 Saudi
   sites (Sep 2022 – Oct 2026), from Open-Meteo's CAMS dust archive + ERA5 weather.
   Note the constraint we discovered and documented: **CAMS history starts
   29 Jul 2022**, so that is where our training window starts.

**The proof.** The technology page lists every source with its live state; the
harvest report `data/ai/harvest_report.json` carries per-column coverage (99.8 % of
rows complete) and every failure. Attribution for the imagery is on the map
(© OpenStreetMap, © CARTO, NASA GIBS).

---

## Part 3 — The models: an AI that predicts, an engine that decides

**What it is.** Two layers, deliberately separate. The **AI predicts**; the
**physics + economics engine decides**. They are never blended, and the dashboard
labels which is which.

**The steps we took.**
1. **Physics engine** (`sg_soiling.py`): dust deposition → mass on glass →
   saturating optical loss → PV yield → cleaning cost. Calibrated per climate class
   against published Saudi soiling rates (0.2–0.8 %/day; KAUST east 45 %, west 15 %).
2. **Policy optimiser**: scores ~21 candidate cleaning policies over a simulated
   year and returns the best trigger per site (Dammam: clean at 20 % loss → 18
   cleans/yr).
3. **The AI** (`ml/ai_train.py` → `backend/sg_ai.py`): hand-written numpy
   gradient-boosted trees + a small neural net, blended by measured skill. It
   predicts three things:
   - **Will a sandstorm come** — probability for +1, +2, +3 days
   - **How much the panels will output** tomorrow — kWh and kWh per kWp
   - **How dirty the glass will be** tomorrow — soiling loss
4. Ran it on a strict **time split** (train < 2025-10-01, validation to 2026-03-31,
   untouched test to today) **plus leave-one-site-out**, so we can show it works on
   a site it has never seen.

**The proof — the error percentages, all on held-out data:**

| Predicts | Result |
|---|---|
| Sandstorm +1 / +2 / +3 days | recall 69 / 61 / 69 %, precision 75 / 85 / 74 %, **AUC 0.952 / 0.929 / 0.931** |
| Panel output tomorrow | **MAE 0.234 kWh/kWp = 7.7 % of the mean**, R² 0.949 — the naive baseline is 11× worse (2.572) |
| Soiling tomorrow | **MAE 3.17 points = 8.4 %**, R² 0.974 (baseline 26.1) |
| Unseen site (leave-one-site-out) | output MAE 0.429, soiling 9.3, storm AUC 0.785 |

---

## Part 4 — The product on screen: two animations, a place-picker, one agent

**What it is.** Three surfaces: a homepage that sells, a dashboard that decides, a
technology page that proves.

**The steps we took.**
1. **Homepage** in a restrained editorial style — big type, hairline rules, copy
   that reveals as you scroll, and **two hand-written scroll animations**: a
   ground-level scene (sun arcs, array tilts to track it, dust buries it, a cleaning
   bar sweeps back) and a second in a different language (an orbital plot: satellite
   pass, a shamal front crossing the Kingdom right-to-left, sites reddening as it
   passes). Both are dependency-free canvas — no CDN, so the hero cannot break on
   stage.
2. **Dashboard** rebuilt for an owner, not an engineer: **two inputs only** (cost of
   one cleaning pass, nameplate capacity) with everything else derived; the map sits
   second and is the **place-picker** (tap anywhere and it prices a plant there,
   using real OSM/CARTO tiles with NASA GIBS dust laid over them); the AI section
   carries the three predictions with their error bars next to the physics verdict.
3. **The agent "Sol"** — DeepSeek with **ten tools** over the live data plus BM25
   retrieval over a harvested soiling-literature corpus, and it **acts on the page**
   (moves the map, switches the satellite layer).
4. Wrote an offline fallback for the map (hand-drawn canvas, same interface) so a
   CDN failure costs polish, not the product.

**The proof.** Load the homepage and scroll once — both animations are scroll-driven
and the second one's caption changes as you move. On the dashboard, tap the Empty
Quarter: the numbers, the water figure and the AI section all move to that location.
In the agent, ask "should we clean Dammam this week" and watch the tool trace.

---

## Part 5 — Verification: how we know it works, and what we admit

**What it is.** The part that usually decides a technical hackathon. We tested, and
we wrote down what failed.

**The steps we took.**
1. **Two test suites.** `tests/test_asgi.py` exercises every route through the real
   application (0 server errors) and `tests/test_ai.py` runs 41 checks — including a
   guard that the feature vector the server builds is byte-for-byte the shape the
   models were trained on.
2. **The storm definition took three attempts**, and all three are documented: a
   PM10 threshold of 200 µg/m³ labelled **36 %** of days "storms" (that is just dust
   in the air); 1000 µg/m³ left **7 of 12 sites with no events at all** (the model
   would be reading the site name off the coordinates); the CAMS `dust` column
   labelled **62 %**. What ships is `PM10 ≥ 3 × that site's own median, floored at
   300` → 10 % of days, with events at every site and a peak in the Feb–May shamal
   season.
3. **Two label bugs were caught by checking distributions, not metrics** — a
   mass-to-loss scale that made a dry month a 90 % loss, and a mean/accumulation
   mix-up that dragged every output label to 0.8 kWh/kWp. Both are written into the
   code and the model card.
4. **We retired our own first-generation models** and deleted them: they were
   trained on 90-day rolling features the serving path could not build, so they
   answered from training defaults and reported 20–45 % soiling loss the day *after*
   a clean. The guard test in item 1 exists because of them.
5. **We report the baselines that beat us**: at +1 day the naive "tomorrow looks
   like today" rule scores a slightly better F1 (0.743 vs 0.719), because dust
   episodes last several days. The AI wins at +2/+3 and is far better calibrated
   (Brier 0.06 vs 0.13)

**The proof.** `docs/MODEL_CARD.md` (failure modes, per-site weaknesses: Abha
highland and Jeddah coastal dust are the two sites where our regressions degrade —
reported, not averaged away), plus `models/ai/metrics.json` and the test outputs.

---

## Part 6 — Deployment and the repository

**What it is.** Everything is live on a real domain and reproducible from a public
repo, from one box with **no GPU**.

**The steps we took.**
1. Mounted the app at the **domain root** inside a guarded `try/except` in the host
   application — if SolarGuard ever fails to import, the domain serves the previous
   site instead of going blank. The original team page moved to `/mission/` and
   still works.
2. Trained the entire AI **on 4 CPU cores with no GPU**: no torch, no sklearn — the
   gradient boosting, the neural net, the PV model and the policy optimiser are all
   hand-written numpy.
3. Documented every technology, source, method and limitation in `README.md` plus
   five docs (`MODEL_CARD`, `ARCHITECTURE`, `DEPLOYMENT`, `REAL_MAP`,
   `SCROLL_STORY`).
4. Kept secrets server-side only (`backend/.env`, gitignored) and verified before
   every commit that no key is in the diff.
5. Shipped it: **github.com/Hermes-mahers-bot/solarguard-space**.

**The proof.** The public repo and the live URL. `git log` shows the work in order,
including the model we retired and why.

---

## If you have 60 seconds

> Dust silently costs a Saudi solar plant most of its margin, and owners clean on a
> calendar instead of on evidence. We built SolarGuard Space: it reads twelve open
> satellite and weather feeds, trains its own AI on four years of Saudi dust — which
> predicts sandstorms three days out at AUC 0.95 and tomorrow's output to within
> 7.7 % — and turns all of it into one answer per site per day: clean now, or wait.
> At Dammam our tuned policy saves **1.70M SAR and 4.5M litres of water a year**
> against the industry habit. Everything is live, everything is tested, and the
> model card says exactly where it fails.

## Three questions judges ask, and the honest answers

* **"Is the AI just a formula?"** The AI predicts; a calibrated physics model
  decides. Two separate layers, labelled on screen, never blended — and the labels
  the AI learned on are documented as formulas on measured weather, because no
  inverter data exists publicly.
* **"How do we know it generalises?"** Leave-one-site-out: we hide an entire site
  and score on it. Storm AUC holds at 0.785; the regressions degrade on the two
  climatological outliers, and we show that rather than quote the average.
* **"What happens when a feed dies, or the AI is wrong?"** No route may raise; a
  dead feed degrades a number. Every prediction ships with the error it made on
  held-out data, and if the AI is unavailable the page says so and falls back to the
  physics engine.
