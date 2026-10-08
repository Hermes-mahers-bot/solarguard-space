# Solution statement (submission copy)

Every claim below is either measurable from our repository or is a plain description
of what the system does. No numbers, no unquantified superlatives.

## ⬛ PASTE THIS — one box

SolarGuard Space is an **agentic-AI, satellite-powered platform** for solar plants: it
turns open **Earth-observation data** into a single daily decision — clean now, or
wait.

We fuse live **open feeds** — NASA satellite imagery, aerosol, dust, wind, sun and rain
— and we **train our own AI models** on them: trained in-house on multi-year satellite
and weather data we harvested ourselves, with prediction targets we defined in the code
and documented. A **machine-learning ensemble** of gradient-boosted trees plus a neural
network, **physics-informed** and error-bounded, predicting **sandstorms in advance**
and **tomorrow's output and soiling loss**. A **digital-twin simulation** of a full
year **auto-tunes the cleaning threshold** for every site, and a **prescriptive engine**
prices the dust in riyals. An **agentic AI copilot** with a **full toolset** and
**citation-grounded retrieval (RAG)** answers questions and **acts on the dashboard** —
placing sites, switching satellite layers, and explaining its reasoning step by step.

**Zero hardware, zero inverter retrofits, zero proprietary sensors**: satellite to
decision in a single dashboard, API-first and CPU-only, so it scales from a rooftop to
a utility-scale farm. In our simulation it **lowers cleaning cost** and **cuts water use
by cleaning less often**, while protecting generation the owner cannot see. Dust is
invisible — we made it **measurable, predictable and priced**.

## Short fallback (if the field is small)

An **agentic AI + satellite** platform for solar operators. We **train our own AI
models** in-house on Earth-observation data we harvested ourselves, and pair them with a
**physics-informed engine** to predict **sandstorms and output**, **auto-optimise**
cleaning schedules in a **digital-twin simulation**, and ship an **agentic AI copilot
that acts on the dashboard** — not just answers. No hardware, no sensors, **keyless and
scalable**. It lowers cleaning cost and water use, and turns **invisible dust into a
priced, timed decision**.

---

## INTERNAL — phrase by phrase: kept, removed, and why

Not for the submission. This is what to say if a judge presses on any wording.

### Kept — defensible today

| Phrase | Why it holds |
|---|---|
| "agentic AI" | the copilot calls tools in a loop (up to 3 rounds, 4 calls each) and **executes actions** on the page: `place_site` moves the map, `show_satellite_layer` switches the layer. Not a chat wrapper. |
| "satellite-powered" | the inputs are NASA GIBS imagery, AERONET ground truth, CAMS dust and ERA5 meteorology. |
| "we train our own AI models" | three forecasting models, trained by `ml/ai_train.py` and served by `backend/sg_ai.py`. Ours, in-house. |
| "multi-year satellite and weather data we harvested ourselves" | `ml/harvest_ai_daily.py` downloads it; the result is `data/ai/daily.csv`. Coverage is in `data/ai/harvest_report.json`. |
| "prediction targets we defined in the code and documented" | honest wording for labels: the storm definition (PM10 ≥ 3× the site's own median, floored) and the two documented formulas are in `ml/ai_features.py` and `docs/MODEL_CARD.md`. |
| "gradient-boosted trees plus a neural network" | literally the two model families, both hand-written in numpy — no ML library, no GPU. |
| "physics-informed" | the output target is a documented PV model on measured irradiance and air temperature, and a calibrated physics engine runs beside the AI and makes the cleaning decision. |
| "predicting sandstorms in advance" | measured on held-out days: AUC 0.952 / 0.929 / 0.931 at +1 / +2 / +3 days, catching 69 / 61 / 69 % of storms, and it beats the "tomorrow looks like today" baseline at +2 and +3. |
| "tomorrow's output and soiling loss" | output MAE 0.234 kWh/kWp (7.7 % of the mean day, R² 0.949); soiling MAE 3.17 points (R² 0.974). |
| "digital-twin simulation … auto-tunes the cleaning threshold" | `sg_soiling.py` scores ~21 cleaning policies over a simulated year and returns the best trigger per site. |
| "prescriptive engine … prices the dust in riyals" | the report returns a verdict plus the money at risk, the crew cost and the payback in days. |
| "full toolset", "citation-grounded retrieval (RAG)" | 10 tools; BM25 over 676 research chunks, sources returned with each answer. |
| "zero hardware / no inverter retrofits" | nothing is installed on site; the 12 open feeds need no key at all. |
| "scales from a rooftop to a utility-scale farm" | the same endpoints are tested from 100 kWp to 300 MWp; the only input that changes is the nameplate size. |
| "lowers cleaning cost", "cuts water use by cleaning less often" | **stated as "in our simulation"** because no plant has deployed it yet. The finding: at a dusty east-coast site the tuned policy cleans less often and still costs less, so both cost and water fall. |

### Removed — and the honest reason

| Phrase | Why it is gone |
|---|---|
| **"research-grade accuracy"** | Unquantified, and "research-grade" is not a standard anyone can check. Replaced by naming what is predicted and, if asked, quoting the measured AUC and MAE. |
| **"built from scratch on data we harvested and labelled ourselves"** | Two problems. "From scratch" overstates it — the *implementation* is ours (numpy, no library) but the *methods* (gradient boosting, an MLP) are standard and well known. And "labelled ourselves" invites the wrong conclusion: the storm label is a **measured** PM10 threshold, not a human annotation, and the output/soiling labels are **formulas we wrote**. Both are documented, which is the defensible version. |
| **"saves millions of litres of water"** | It is a **projected** figure from our own simulation, not a measured saving on a real farm. Stating it as achieved would be a claim we cannot support. Kept only as the relative statement "cuts water use by cleaning less often". |
| "forecasting sandstorms days ahead" | Kept in substance but softened to "in advance". "Days ahead" is defensible (+1/+2/+3 with those AUCs) — it was removed from the submission only to avoid a specific number of days without the caveat that the +1-day persistence baseline is slightly better on F1. Say that if asked; it makes the answer stronger, not weaker. |
