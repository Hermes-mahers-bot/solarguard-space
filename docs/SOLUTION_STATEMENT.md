# Solution statement (submission copy)

Plain text for pasting. No em dashes, no numeric claims, no phrase we cannot
defend.

## PASTE THIS (one box)

SolarGuard Space is an agentic AI platform that uses satellite data to tell solar
plants when to clean.

It reads live feeds from NASA, ECMWF and Open-Meteo: satellite imagery, dust,
aerosol, wind, sun and rain. We train our own AI models in-house on that data, using
years of Saudi weather and dust records we collected ourselves. The models are a
machine learning ensemble of gradient boosted trees and a neural network, and they are
physics informed. They predict sandstorms before they arrive, along with tomorrow's
output and how much dirt will be sitting on the glass. A year long simulation works out
the best cleaning threshold for each site, and a pricing engine turns the dust into
riyals. The agentic AI copilot answers an operator's questions and can act on the
dashboard. It moves the map to a site, switches the satellite layer, and shows which
sources each answer came from.

Nothing is installed on site. No sensors, no inverter hardware, no proprietary
equipment. Everything runs on open data, and because it is API first and CPU only it
fits a rooftop system or a utility scale farm. In our simulation it lowers cleaning
costs and uses less water, because the schedule cleans less often. Dust is invisible.
We made it visible and forecastable, and we put a price on it.

## Short fallback (if the field is small)

An agentic AI and satellite platform for solar operators. We train our own AI models
in-house on Earth observation data we collected, and pair them with a physics informed
engine. They predict sandstorms and next day output, a simulation auto optimises the
cleaning schedule, and an agentic AI copilot acts on the dashboard instead of just
answering questions. No hardware and no sensors, keyless and scalable. It lowers
cleaning cost and water use, and puts a price on invisible dust.

---

## INTERNAL. Phrase by phrase: kept, removed, and why

Not for the submission. This is what to say if a judge presses on any wording.

### Kept, and defensible today

| Phrase | Why it holds |
|---|---|
| "agentic AI" | the copilot calls tools in a loop (up to 3 rounds, 4 calls each) and executes actions on the page. `place_site` moves the map, `show_satellite_layer` switches the layer. It is not a chat wrapper. |
| "satellite data" | inputs are NASA GIBS imagery, AERONET ground truth, CAMS dust and ERA5 meteorology. |
| "we train our own AI models" | three forecasting models, trained by `ml/ai_train.py` and served by `backend/sg_ai.py`. |
| "years of Saudi weather and dust records we collected ourselves" | `ml/harvest_ai_daily.py` downloads them. The result is `data/ai/daily.csv`. Coverage is in `data/ai/harvest_report.json`. |
| "machine learning ensemble of gradient boosted trees and a neural network" | literally those two families, hand written in numpy, no ML library and no GPU. |
| "physics informed" | the output target is a documented PV model on measured irradiance and air temperature, and a calibrated physics engine runs beside the AI and makes the cleaning decision. |
| "predict sandstorms before they arrive" | measured on held out days: AUC 0.952, 0.929 and 0.931 at 1, 2 and 3 days ahead, catching 69, 61 and 69 percent of storms. It also beats the "tomorrow looks like today" baseline at 2 and 3 days. |
| "tomorrow's output and how much dirt will be sitting on the glass" | output MAE 0.234 kWh per kWp, which is 7.7 percent of the mean day, R2 0.949. Soiling MAE 3.17 points, R2 0.974. |
| "year long simulation works out the best cleaning threshold" | `sg_soiling.py` scores about 21 cleaning policies over a simulated year and returns the best trigger for each site. |
| "pricing engine turns the dust into riyals" | the report returns a verdict plus money at risk, crew cost, and payback in days. |
| "agentic AI copilot", "which sources each answer came from" | 10 tools, and BM25 over 672 indexed chunks (606 of them research papers) with sources returned for each answer. |
| "nothing is installed on site" | no hardware. 12 of the 20 feeds need no key at all. |
| "fits a rooftop system or a utility scale farm" | the same endpoints are tested from 100 kWp to 300 MWp. Only the nameplate size changes. |
| "lowers cleaning costs and uses less water" | written as "in our simulation", because no plant has deployed it yet. The finding is that at a dusty east coast site the tuned policy cleans less often and still costs less, so both cost and water fall. |

### Removed, and the honest reason

| Phrase | Why it is gone |
|---|---|
| "research-grade accuracy" | Unquantified, and "research-grade" is not a standard anyone can check. Replaced by naming what is predicted, plus the measured AUC and MAE if asked. |
| "built from scratch on data we harvested and labelled ourselves" | Two problems. "From scratch" overstates it, because the implementation is ours but the methods are standard and well known. "Labelled ourselves" invites the wrong conclusion, since the storm label is a measured PM10 threshold rather than an annotation, and the other two labels are formulas we wrote. Both are documented, which is the defensible version. |
| "saves millions of litres of water" | That figure is projected by our own simulation, not measured on a real farm. Kept only as the relative statement "uses less water, because the schedule cleans less often". |
| "forecasting sandstorms days ahead" | Kept in substance but softened to "before they arrive". The specific number of days is defensible (1, 2 and 3 with those AUCs). It was removed from the submission only to avoid implying a precise horizon without the caveat that the 1 day persistence baseline is slightly better on F1. Say that if asked, it makes the answer stronger. |
