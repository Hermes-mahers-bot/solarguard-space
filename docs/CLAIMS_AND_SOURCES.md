# Sources of our claims, and our 12 inputs

Every claim in our problem and solution statement, with the source that validates it,
or a correction where the claim as written does not hold. Sources 1 to 7 are the
papers we harvested into the repository (`data/corpus/`); each one can be downloaded
and checked.

---

# 1. THE PERCENTAGE CLAIM (the one to get right)

**Our claim as written:** "dust and sandstorms can cut solar panel output by 20-40% or
more".

**Verdict: defensible, but only with a condition attached.** The 20 to 40% band is
real, and it is Saudi-specific, but it describes **dust that has accumulated over
weeks without cleaning, or the aftermath of a sandstorm**. It is not the loss a plant
sees every day. If we write it as though it were the normal daily figure, a judge with
the same papers can take it apart.

### What the sources actually say

| Source | The number | What it refers to |
|---|---|---|
| **1. KAUST / Stenchikov et al. 2023**, Coarse Dust Soiling and Fine Dust Dimming Over the Arabian Peninsula | soiling accumulates about **12% per week**; **30-35% on the Saudi east coast** | accumulation over time at an uncleaned site |
| **2. MDPI Energies 2022, 15, 8033**, The Impact of Soiling on PV Module Performance in Saudi Arabia | **a single sandstorm cut module output by 20%**; across Saudi regions losses reported from **2% to 50%**; a Dhahran module **not cleaned for 6 months lost more than 50%** | a single storm event, and long-term neglect |
| **3. IEA-PVPS Task 13, 2022**, Soiling Losses, Impact on the Performance of PV Plants | **higher than 20%** in long dry periods of accumulation (Malaga); **45.8% in Kuwait over a 3 month period without cleaning** | dry-period accumulation |
| **4. JMRT**, Almarri et al., dust composition in arid coastal environments (Jubail, Saudi Arabia) | **48% power loss at 6 g/m²** of dust; humidity above 60% adds **15-30%** of loss through adhesion | heavy dust loading and cementation |

So the range is supported from four independent directions, and the "or more" is
supported by the Kuwait figure (45.8%) and the Dhahran six-month figure (more than
50%).

### Recommended wording (a correction, not a retreat)

> "In Saudi Arabia, dust accumulating between cleanings, and sandstorms, can cut solar
> panel output by 20 to 40 percent or more. A single sandstorm has been measured
> cutting module output by 20 percent, and soiling on the east coast accumulates at
> 30 to 35 percent within weeks when panels are not cleaned."

That version is fully supported. It keeps the 20 to 40% figure in the headline, and it
cannot be contradicted because each part names what it measures.

### One counter-argument to expect, and the answer

The same 2022 review (source 2) concludes that dust accumulation and cleaning costs
are **not a significant barrier** to large-scale solar in Saudi Arabia. A judge may
raise that. The answer, and it is a good one: **the physics is understood, the
decision is not.** Plants still clean on a calendar, and the published advice ("clean
monthly or less often, and immediately after a dust storm") is a rule of thumb rather
than a per-site calculation. Source 5 below is a 2026 paper on exactly this gap, which
shows it is still an open problem.

---

# 2. SOURCES OF OUR CLAIMS, NUMBERED

## Our problem statement

| # | Claim | Source that supports it | Notes |
|---|---|---|---|
| 1 | Dust and sandstorms can cut solar panel output by 20-40% or more | Sources 1, 2, 3, 4 | Correct the framing as shown above: accumulation and storm events, not the daily norm. |
| 2 | Operators have no reliable way to know when cleaning is worth the cost | Source 3 (the manual cost-versus-loss calculation is the described method); Source 5 (a 2026 paper still researching cleaning optimisation for Saudi plants) | Usable as written. This is a market-gap claim, and the literature supports that it is unsolved. |
| 3 | Most clean on fixed schedules or by guesswork | Source 3 (periodical or annual manual cleaning is described as standard practice where rain does not clean the panels) | Softly sourced. Keep it, but say "periodic schedules" rather than "most", unless we get an industry survey. |
| 4 | Cleaning too often wastes money, labour and scarce water | Source 3 (cleaning cost of about 0.2 EUR/m² per event; water scarcity pushes the industry toward dry cleaning) | Usable. |
| 5 | Cleaning can scratch the protective coating | Source 3 (abrasion studies: "in some cases considerable damage was caused by dry brush" cleaning) | Usable, and the source is specific about dry brushing. |
| 6 | Cleaning too late causes avoidable losses | Sources 1, 2, 3 | Usable. |
| 7 | Cleaning too late leaves hardened dust that is harder to remove | Source 3, chapter 2.2 "Cementation, Caking, Capillary Aging"; Source 4 (adhesion worsens with humidity) | Usable, and this is the strongest technical part of the problem statement. |
| 8 | Saudi Arabia has very little rain to wash panels naturally | World Bank, average precipitation in depth, Saudi Arabia (about **107 mm in 2023, 118 mm in 2024**); Source 3 ("in semiarid and arid desert regions, rainfall is scarce so there is no natural cleaning of the modules") | Usable. Our own harvest confirms it: rain days are rare at all 12 of our sites. |
| 9 | Saudi Arabia has frequent dust storms | Source 1 (the Arabian Peninsula as a major dust source region); Source 6 | Usable. |

## Our solution statement

| # | Claim | Evidence |
|---|---|---|
| 10 | Agentic AI platform | The assistant calls tools in a loop, up to 3 rounds, and executes actions on the page (`place_site`, `show_satellite_layer`). Code: `backend/sg_agent.py`. |
| 11 | Uses satellite data, from NASA, ECMWF and Open-Meteo | The 12 numbered inputs below, all live and keyless. |
| 12 | We train our own AI models in-house | `ml/ai_train.py` trains three models; `models/ai/metrics.json` holds the scores; `models/ai/*.npz` are the shipped weights. |
| 13 | Years of Saudi weather and dust records we collected ourselves | `ml/harvest_ai_daily.py` builds `data/ai/daily.csv`: 18,348 site-days, 12 sites, Aug 2022 to Oct 2026. |
| 14 | Machine learning ensemble of gradient boosted trees and a neural network | Both families are implemented and blended; see `ml/ai_train.py` and the metrics file. |
| 15 | Physics informed | The output target is a documented PV model driven by measured irradiance and air temperature, and a calibrated physics engine makes the cleaning decision. See `ml/ai_features.py` and `backend/sg_soiling.py`. |
| 16 | The model predicts sandstorms before they arrive | Measured on held-out days: AUC 0.952, 0.929, 0.931 at 1, 2 and 3 days; recall 69, 61 and 69%. |
| 17 | Predicts tomorrow's output and how much dirt is on the glass | Output MAE 0.234 kWh/kWp (7.7% of the mean day, R² 0.949); soiling MAE 3.17 points (R² 0.974). |
| 18 | A year-long simulation works out the best cleaning threshold | `backend/sg_soiling.py` scores about 21 candidate policies over a simulated year per site. |
| 19 | Prices the dust in riyals | The report returns money at risk, crew cost and payback in days. |
| 20 | The copilot shows which sources each answer came from | 672 indexed chunks (606 from the seven research sources below plus our own documentation), BM25 retrieval, citations returned with every answer. |
| 21 | Nothing is installed on site, no sensors, no inverter hardware | There is no on-site hardware in the architecture; the 12 open inputs need no key or account. |
| 22 | API first, CPU only, fits a rooftop system or a utility scale farm | The service is HTTP endpoints, trained and served on CPU; the same endpoints are exercised from 100 kWp to 300 MWp. |
| 23 | It lowers cleaning costs and uses less water, in our simulation | Stated as a simulation on purpose. At a 100 MWp east-coast site the tuned policy costs less than the industry habit and cleans less often, so both cost and water fall. |

**Two numbers in our own documentation needed correcting, and are now fixed:** the
retrieval index holds **672 chunks (606 of them research)**, not 676 as an earlier
draft said; and the harvest is **18,348 daily rows**, of which 17,772 are usable
samples after the history windows are built.

---

# 3. THE SEVEN SOURCES WE HOLD IN THE REPOSITORY

1. **Stenchikov, G., Mostamandi, S., Shevchenko, I., Ukhov, A., Osipov, S. (2023).**
   Coarse Dust Soiling and Fine Dust Dimming Effects on PV Panels Over the Arabian
   Peninsula. KAUST. https://repository.kaust.edu.sa/handle/10754/696394
2. **Energies 2022, 15, 8033.** The Impact of Soiling on PV Module Performance in
   Saudi Arabia. doi:10.3390/en15218033
3. **IEA-PVPS Task 13 (2022).** Soiling Losses, Impact on the Performance of
   Photovoltaic Power Plants. Report T13-21:2022.
   https://www.iea-pvps.org/wp-content/uploads/2023/01/IEA-PVPS-T13-21-2022-EXEC-SUMM-Soiling-Losses-PV-Plants.pdf
4. **Almarri et al.** Experimental and modeling study of dust composition impact on
   photovoltaic performance in arid coastal environments. J. Materials Research and
   Technology (JMRT). Imam Abdulrahman Bin Faisal University, Jubail.
   https://www.sciencedirect.com/science/article/pii/S2238785425027103
   (open access copy: https://www.sun-connect.org/wp-content/uploads/1-s2.0-S2238785425027103-main.pdf)
5. **Alharbi, F. R. (2026).** Seasonal Soiling Rates and Cleaning Optimization for PV
   Systems in Saudi Arabia: Arar Desert Climate. Energies 19, 4373.
6. **Abdullah, M., et al. (2020).** Soiling Loss Rate Measurements of Photovoltaic
   Modules in a Hot and Humid Desert Environment. J. Solar Energy Engineering.
   doi:10.1115/1.4048406 (KAUST, 15 months of measurements, Western Region)
7. **Kipp & Zonen, DustIQ.** Commercial soiling monitoring product page (reference for
   how the industry measures soiling today).
   https://www.kippzonen.com/products/dustiq-soiling-monitoring-system

**Plus, for the rainfall figure:** World Bank, Average precipitation in depth,
Saudi Arabia. https://data.worldbank.org/indicator/AG.LND.PRCP.MM?locations=SA

---

# 4. OUR 12 INPUTS

Live, keyless, read on every request. Cached about 15 minutes.

1. **NASA GIBS** satellite imagery tiles (MODIS aerosol, MERRA-2 dust).
   https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/1.0.0/WMTSCapabilities.xml
2. **NASA POWER** daily irradiance and climate.
   https://power.larc.nasa.gov/data-access-viewer/
3. **AERONET** ground stations measuring aerosol optical depth (our truth check).
   https://aeronet.gsfc.nasa.gov/cgi-bin/webtool_aod_v3
4. **NOAA Himawari-9** geostationary imagery, open S3 bucket.
   https://noaa-himawari9.s3.amazonaws.com/
5. **NOAA GFS** forecast fields, open S3 bucket.
   https://noaa-gfs-bdp-pds.s3.amazonaws.com/
6. **ECMWF open data** (wind and gust fields).
   https://data.ecmwf.int/forecasts/
7. **Open-Meteo forecast API** (temperature, humidity, wind, gust, rain, radiation).
   https://api.open-meteo.com/v1/forecast
8. **Open-Meteo air quality API** (CAMS: PM10, dust, aerosol optical depth, PM2.5).
   https://air-quality-api.open-meteo.com/v1/air-quality
9. **Open-Meteo archive API** (four years of history for training).
   https://archive-api.open-meteo.com/v1/archive
10. **AEMET SDS-WAS** Barcelona Dust Forecast Center (dust forecasts).
    https://dust.aemet.es/
11. **MODIS MAIAC** aerosol product MCD19A2 (served through GIBS).
    https://ladsweb.modaps.eosdis.nasa.gov/missions-and-measurements/products/MCD19A2/
12. **MERRA-2** aerosol reanalysis (served through GIBS).
    https://gmao.gsfc.nasa.gov/reanalysis/MERRA-2/

**Also used:** public domain country outlines for the map
(https://github.com/johan/world.geo.json), OpenStreetMap and CARTO map tiles for the
place picker, and Leaflet for rendering them.

**Eight more are coded and waiting on credentials:** Copernicus ADS, Copernicus Data
Space, NASA Earthdata (higher-rate imagery), NREL NSRDB, JAXA P-Tree, Alaska Satellite
Facility, ESA WorldCover, Sentinel Hub.
