# Solution statement (submission copy)

## Main version — ~150 words

SolarGuard Space is an **agentic AI platform** that turns open **satellite data**
into a daily cleaning decision for solar plants.

We fuse **12 live feeds** — NASA satellite imagery, aerosol, dust and weather — with
a **machine-learning ensemble we trained ourselves**: gradient-boosted trees plus a
neural network, **physics-informed**, forecasting **sandstorms three days out at AUC
0.95** and tomorrow's output to within **7.7 %**.

A **digital-twin simulation** of a full year auto-tunes the cleaning threshold per
site, then a **prescriptive engine** converts dust into riyals. An **agentic AI
copilot** with 10 tools and **citation-grounded retrieval (RAG)** answers questions
and **acts on the dashboard** — it places sites, switches satellite layers, and
explains every number it gives.

No hardware. No inverter retrofits. No proprietary sensors. **Satellite to decision,
in one dashboard.** At Dammam it cuts cleaning spend by **1.7M SAR a year** and saves
**4.5M litres of water**.

## Short version — ~50 words

An **agentic AI + satellite** platform for solar. We fuse 12 open Earth-observation
feeds with **our own ML ensemble** (physics-informed; AUC 0.95 sandstorm forecast,
7.7 % output error), auto-optimise cleaning in a **digital-twin year simulation**, and
ship an **AI copilot that acts on the dashboard**. Saves 1.7M SAR and 4.5M litres a
year.

## One-liner — ~25 words

**Satellite + agentic AI** that tells Saudi solar plants exactly when to clean —
**our own trained model**, powered entirely by open **Earth-observation data**.

## Bullet version (if the form allows a list)

* **Multi-source data fusion** — 12 live open feeds: NASA satellite imagery, aerosol
  optical depth, dust, wind, sun and rain.
* **Our own trained models** — gradient-boosted trees + a neural network, written
  from scratch (no ML library, no GPU), physics-informed and error-bounded.
* **Predictive analytics** — P(sandstorm) at +1/+2/+3 days (AUC 0.95), tomorrow's
  energy output (±7.7 %), tomorrow's soiling loss (±8.4 %).
* **Digital-twin optimisation** — simulates a full year, auto-tunes the cleaning
  threshold per site.
* **Decision intelligence** — turns dust into riyals and returns one verdict:
  clean now, or wait.
* **Agentic AI copilot** — LLM with 10 tools + citation-grounded retrieval; it acts
  on the dashboard, not just chats.
* **Zero-hardware, keyless, scalable** — no sensors, no inverter retrofits,
  API-first, runs on CPU.
* **Impact** — 1.7M SAR/yr cheaper and 4.5M litres of water saved at one 100 MWp
  site; 1.5M+ SAR of generation protected per site-year.

## Closer (one line, for the end of a pitch)

**Dust is invisible. We made it measurable, predictable, and priced.**

---

## If a judge asks what each buzzword actually means

Keep this so no term is a bluff — every one is something we built and can show.

| We say | What it really is |
|---|---|
| **Satellite / Earth observation** | NASA GIBS imagery (MODIS aerosol, MERRA-2 dust), AERONET ground truth, ERA5/CAMS reanalysis |
| **Data fusion** | 12 live feeds merged into one 37-number vector per site per day |
| **Our own trained model** | Gradient-boosted trees + a 2-layer neural net, hand-written in numpy, trained on 18,348 site-days across 12 Saudi sites |
| **Machine learning / ensemble** | Two model families blended with weights set by measured accuracy (42 % trees / 58 % net) |
| **Physics-informed** | The output label is computed from a documented PV model on measured irradiance and air temperature; a calibrated physics engine sits alongside the AI and makes the decision |
| **AUC 0.95** | Pick a storm day and a calm day at random — the model ranks the storm day higher 95 times in 100 |
| **Forecasting at ±7.7 %** | Mean absolute error 0.234 kWh per kWp against a daily mean of about 3 kWh per kWp; the naive baseline is 11× worse |
| **Digital-twin simulation** | A full-year simulation across ~21 candidate cleaning policies; it picks the best trigger per site |
| **Prescriptive / decision intelligence** | It doesn't just show data — it returns one verdict and the day to send a crew |
| **Agentic AI** | An LLM that calls tools in a loop (up to 3 rounds, 4 calls each) and executes actions: moving the map, switching the satellite layer |
| **Citation-grounded retrieval (RAG)** | BM25 search over 676 chunks of harvested soiling research; answers come back with sources |
| **Zero-hardware / keyless** | No sensors, no inverter integration, no API key for 12 of the 20 sources — and the 8 gated ones are coded and waiting |
