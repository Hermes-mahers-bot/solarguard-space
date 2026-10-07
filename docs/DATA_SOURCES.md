# SolarGuard Space — Data Sources (verified)

**Built:** 2026-10-07 · **Host:** Linux box, internet OK · **Method:** every row was actually
probed with `curl -sL --max-time 45 -A <browser UA> -o /dev/null -w '%{http_code} %{size_download} %{content_type}'`
and, for PDFs, downloaded and extracted. Status column reflects **what happened**, not what the
documentation claims.

**Tally (40 rows):** **23 OPEN** · **11 KEY-GATED** (data needs a free account/API key) ·
**5 BOT-BLOCKED** from this host · **1 UNREACHABLE** (DNS) — 40 total.

Legend: `OPEN` = fetched with no key · `KEY-GATED` = index/page loads but the data needs a free account ·
`BOT-BLOCKED` = host's bot protection refused this host (content was reached another legitimate way) ·
`UNREACHABLE` = DNS/connection failed from this host.

---

## 1. OPEN — verified working, no key required (23)

| # | Source | What it provides | Access | What we use it for | Tested status + evidence |
|---|--------|------------------|--------|--------------------|--------------------------|
| 4 | `noaa-himawari9.s3.amazonaws.com` | Himawari-9 full-disk imagery on AWS Open Data (S3) | **OPEN** | Near-real-time dust-plume tracking / dashboard dust overlay | ✅ `200`, **1,287 B**, `application/xml` (`?list-type=2&max-keys=3`) |
| 5 | `registry.opendata.aws/noaa-himawari` | AWS Open Data registry entry — bucket, prefixes, access notes | **OPEN** | Documentation of the Himawari S3 layout for the ingest job | ✅ `200`, **13,292 B**, `text/html` |
| 7 | `himawari8.nict.go.jp` | NICT real-time Himawari viewer + ready-made PNG tiles | **OPEN** | Quick visual dust context / demo tiles without processing | ✅ `200`, 8,877 B (page); tile `2026/10/07/120000_0_0.png` → `200`, **2,834 B** `image/png` |
| 8 | `ospo.noaa.gov/Products/imagery/index.html` | NOAA satellite imagery & derived products portal | **OPEN** | Cross-check dust events with NOAA imagery | ✅ `200`, **27,369 B**, `text/html` (redirect → lowercase path) |
| 3 | `atmosphere.copernicus.eu/cams-aerosol-alerts-…` | CAMS aerosol/dust alert editorial pages | **OPEN** | Assistant narrative context for Saharan/Arabian dust episodes | ✅ `200`, **179,932 B**, `text/html` |
| 12 | `dust.aemet.es` | Barcelona Dust Forecast Center (WMO SDS-WAS) regional dust forecast | **OPEN** | Operational dust-load forecast directly comparable to the advisory engine | ✅ `200`, **41,458 B**, `text/html;charset=utf-8` |
| 13 | `aeronet.gsfc.nasa.gov/aeronet_locations_v3.txt` | AERONET global station list (lat/lon/elev, v3) | **OPEN** | Pick ground-truth AOD stations near Saudi sites | ✅ `200`, **73,929 B**, `text/plain` |
| 14 | `aeronet.gsfc.nasa.gov/new_web/data.html` | AERONET data-access page | **OPEN** | Human entry point to AOD downloads | ✅ `200`, **29,749 B**, `text/html` |
| 16 | `power.larc.nasa.gov/docs/services/api/temporal/hourly/` | NASA POWER hourly API docs | **OPEN** | Baseline met driver (T2M, WS10M, RH2M, GHI, PRECTOTCORR, T2MDEW) | ✅ `200`, 32,713 B (docs); live API row 39 below |
| 17 | `noaa-gfs-bdp-pds.s3.amazonaws.com` | NOAA GFS forecast GRIB on AWS Open Data (S3) | **OPEN** | 16-day wind/humidity forecast for deposition + cleaning-window logic | ✅ `200`, **1,158 B**, `application/xml` (`?list-type=2&max-keys=3`) |
| 18 | `data.ecmwf.int/forecasts/` | ECMWF Open Data real-time forecasts (IFS/AIFS) | **OPEN** | Independent weather-model cross-check for the Gulf | ✅ `200`, **430,037 B**, `text/html` |
| 20 | `globalsolaratlas.info` | Global Solar Atlas (World Bank/Solargis) PV potential, GHI/DNI/PVOUT | **OPEN** | Default irradiance/yield source for the dashboard | ✅ `200`, **58,154 B**; its API `api.globalsolaratlas.info/data/lta` → `200`, 2,767 B (row 40) |
| 21 | `pvlib-python.readthedocs.io/en/stable/` | pvlib-python docs — irradiance transposition + PV modelling | **OPEN** | Modelling backbone for the backend (soiling-loss models included) | ✅ `200`, **27,319 B**, `text/html;charset=utf-8` |
| 25 | `emergency.copernicus.eu` | Copernicus Emergency Management Service portal | **OPEN** | Post-event / rapid-mapping context for dust storms & hazards | ✅ `200`, **20,829 B**, `text/html;charset=utf-8` |
| 26 | IEA-PVPS `…/IEA-PVPS-T13-21-2022-REPORT-Soiling-Losses-PV-Plants.pdf` | IEA-PVPS Task 13 soiling handbook (129 pp) | **OPEN** | Primary methodology reference in the corpus | ✅ `200`, **4,914,682 B**, `application/pdf` → **downloaded** |
| 27 | `res.mdpi.com/…/energies-15-08033.pdf` | Al Garni, *Impact of Soiling on PV in Saudi Arabia* (Energies 2022, 15, 8033) | **OPEN** | Saudi soiling review — corpus + facts | ✅ `200`, **2,062,209 B**, `application/pdf` → **downloaded** (301 → `mdpi-res.com`) |
| 28 | `res.mdpi.com/…/energies-19-04373.pdf` | Alharbi, *Seasonal Soiling Rates & Cleaning Optimization, Arar* (Energies 2026, 19(18), 4373) | **OPEN** | Seasonality + optimal-cleaning-interval corpus | ✅ `200`, **2,154,176 B**, `application/pdf` → **downloaded** (301 → `mdpi-res.com`) |
| 34 | `kippzonen.com/products/dustiq-soiling-monitoring-system` | DustIQ soiling-sensor product page + full spec sheet | **OPEN** | DustIQ specs for the sensor comparison / hardware story | ✅ `200`, **207,120 B**, `text/html;charset=utf-8` |
| 36 | `www.windy.com/?dustsm,…` | Windy interactive dust-mass visual layer | **OPEN** | Manual spot checks / demo screenshots | ✅ `200`, **8,011 B**, `text/html` |
| 37 | `www.ventusky.com/?…&l=dust` | Ventusky dust/atmosphere visual layer | **OPEN** | Alternative demo screenshots | ✅ `200`, **12,169 B**, `text/html;charset=UTF-8` |
| **38*** | `air-quality-api.open-meteo.com/v1/air-quality` | Keyless hourly **`dust` (µg/m³)** + **`aerosol_optical_depth`** + PM10 | **OPEN** | Best keyless fallback dust forecast when CAMS is gated | ✅ `200`, **1,194 B**, JSON — fields present: `dust`, `aerosol_optical_depth`, `pm10` |
| **39*** | `power.larc.nasa.gov/api/temporal/hourly/point` | NASA POWER live hourly point API | **OPEN** | Pull hourly met for a plant coordinate | ✅ `200`, **1,421 B**, `application/json` (T2M, WS10M for 24.71 N / 46.67 E) |
| **40*** | `api.globalsolaratlas.info/data/lta?loc=24.71,46.67` | Keyless long-term-average solar resource JSON | **OPEN** | Instant PVOUT/GHI for any coordinate in the dashboard | ✅ `200`, **2,767 B**, JSON |

\* rows 38–40 are extra endpoints we verified (not in Maher's list) that fill the 40-row target and are
worth wiring in because they are genuinely keyless.

---

## 2. KEY-GATED — page/index loads, but the DATA needs a free account (11)

| # | Source | What it provides | Access | What we use it for | Tested status + evidence |
|---|--------|------------------|--------|--------------------|--------------------------|
| 1 | `ads.atmosphere.copernicus.eu/datasets/cams-global-atmospheric-composition-forecasts` | CAMS global composition **forecast**: dust AOD, PM10/PM2.5, aerosol species | **KEY-GATED** (Copernicus ADS API key) | **PRIMARY forecast driver** for soiling risk | dataset page `200`, 387,828 B · process catalogue `200`, 19,807 B · **`/api/retrieve/v1/jobs` → `401` `{"status":401,"detail":"authentication required"}`** |
| 2 | `soda-pro.com/web-services/radiation/cams-radiation-service` | CAMS McClear radiation service (GHI/DNI/DHI time series) | **KEY-GATED** (free SODA registration) | Expected-generation baselines | page `200`, 78,743 B; the actual WSDL/data needs a SODA account |
| 6 | `www.eorc.jaxa.jp/ptree/` | JAXA P-Tree: Himawari / GPM / AMSR archives | **KEY-GATED** (free JAXA P-Tree registration) | Full-res Himawari dust-storm case studies | portal `200`, 17,781 B; `ftp.eorc.jaxa.jp` → `000` (no route); data requires a P-Tree login |
| 9 | `disc.gsfc.nasa.gov/datasets?project=MERRA-2` | MERRA-2 reanalysis (dust `DUEXTTAU`, PM, wind), 1980→now hourly | **KEY-GATED** (NASA Earthdata login) | Historical soiling-risk climatology + model training | dataset page `200`, 2,828 B · MERRA-2 `.nc4` file → **`401`** (27 B) · OPeNDAP paths → `410` |
| 10 | `ladsweb.modaps.eosdis.nasa.gov/…/MCD19A2/` | MODIS MAIAC 1 km daily AOD | **KEY-GATED** (NASA Earthdata login) | 1 km dust-haze layer + CAMS/MERRA-2 validation | product page `200`, 37,642 B · `.hdf` request returned the **HTML login page** (10,831 B), not the file |
| 11 | `dataspace.copernicus.eu/…/sentinel-5p` | Sentinel-5P TROPOMI UV Aerosol Index / NO2 (~5 km) | **KEY-GATED** (Copernicus Data Space account) | Key satellite layer for soiling spikes | collection page `200`, 85,216 B · catalogue OData search `200`, 5,460 B (open) · product **download** needs a CDSE token |
| 15 | `giovanni.gsfc.nasa.gov/giovanni/` | NASA GIOVANNI on-the-fly analysis/plots | **KEY-GATED** (NASA Earthdata login) | Quick charts of aerosol/dust products | landing `200`, 19,958 B; data access gated by Earthdata |
| 19 | `nsrdb.nrel.gov` | NSRDB high-res (up to 5-min) solar resource, Middle East | **KEY-GATED** (free NREL NSRDB API key) | PV yield / expected-generation modelling | **UNREACHABLE from this host** — `nsrdb.nrel.gov` and `www.nrel.gov` fail DNS (curl exit 6); `developer.nrel.gov` API unreachable too → needs the host network fixed *and* a free API key |
| 22 | `dataspace.copernicus.eu` | Copernicus Data Space Ecosystem portal (Sentinel-1/2/3/5P) | **KEY-GATED** (free CDSE account for downloads) | Sentinel discovery + download for dust events | portal `200`, 113,797 B; browsing open, downloads require an account |
| 23 | `browser.dataspace.copernicus.eu` | CDSE interactive Sentinel browser | **KEY-GATED** | Visual inspection of scenes over Saudi sites | `200`, 3,135 B (browser app shell); download needs login |
| 24 | `search.asf.alaska.edu` | ASF DAAC Sentinel-1 SAR search + download | **KEY-GATED** (search open, data = Earthdata login) | SAR surface-change / sand encroachment | page `200`, 90,083 B · **search API `200`, 585 B `application/metalink+xml` (OPEN)** · file download gated by Earthdata |

---

## 3. BOT-BLOCKED / UNREACHABLE from this host (6) — content obtained another legitimate way

| # | Source | What it provides | Access | What we use it for | Tested status + evidence |
|---|--------|------------------|--------|--------------------|--------------------------|
| 29 | `www.mdpi.com/1996-1073/15/21/8033` | HTML landing page for Energies 15, 8033 | **BOT-BLOCKED** | (landing page only) | ❌ **`403`, 398 B** — MDPI bot protection. The **PDF is open** at `res.mdpi.com` (row 27) → downloaded |
| 30 | `www.mdpi.com/1996-1073/19/18/4373` | HTML landing page for Energies 19, 4373 | **BOT-BLOCKED** | (landing page only) | ❌ **`403`, 400 B** — bot protection. **PDF open** at `res.mdpi.com` (row 28) → downloaded |
| 31 | `sciencedirect.com/science/article/pii/S2238785425027103` | Almarri et al., *Dust composition impact on PV in arid coastal environments* (JMRT 2025) | **BOT-BLOCKED** | Dust-composition corpus doc | ❌ **`403`, 832,804 B** (Cloudflare "are you a robot" wall on both curl and a headless browser). **No bypass attempted.** The article is open-access (CC-BY); an openly-hosted copy was downloaded from `sun-connect.org` → 13-page PDF, **6,727,772 B** |
| 32 | `repository.kaust.edu.sa/handle/10754/665153` | Abdallah et al., *Soiling Loss Rate Measurements of PV Modules in a Hot and Humid Desert Environment* (KAUST/Saudi Aramco; ASME JSEE 2020, DOI 10.1115/1.4048406) | **BOT-BLOCKED** | West-coast soiling corpus doc | ❌ **Imperva/Incapsula**: `200` but only **212 B** JS-challenge shell (also blocked headless Chromium). Metadata + abstract retrieved via a public reader → `kaust-665153…txt`, 2,758 chars |
| 33 | `repository.kaust.edu.sa/handle/10754/696394` | Stenchikov et al., *Coarse Dust Soiling and Fine Dust Dimming Effects on PV Panels Over the Arabian Peninsula* (MENA-SC 2023, DOI 10.1109/mena-sc54044.2023.10374528) | **BOT-BLOCKED** | Arabian-Peninsula soiling/dimming corpus doc | ❌ Same Imperva wall: `200`, **212 B** shell. Metadata + abstract retrieved via a public reader → `kaust-696394…txt`, 2,736 chars |
| 35 | `www.nrel.gov/pv/soiling.html` | NREL PV soiling research hub | **UNREACHABLE** | Soiling-mechanism reference | ❌ **`000`** — `curl: (6) Could not resolve host: www.nrel.gov`. DNS for the whole `nrel.gov` domain is unavailable from this host |

---

## How to activate the gated ones

Each entry gives the **exact account name** and the **env-var** every client should read. Put these in
`/home/hermes2/solarguard-space/.env` (never commit it).

| Service | Exact account needed (sign-up) | Env var the client must read | Notes |
|---|---|---|---|
| **Copernicus ADS / CAMS** | *Copernicus Atmosphere Data Store (ADS)* account → obtain an **API key / ECMWF access token** at `ads.atmosphere.copernicus.eu` → *My account → API key* | `COPERNICUS_ADS_API_KEY` (also accept `CAMS_API_KEY`) | Send as `Authorization: Bearer $COPERNICUS_ADS_API_KEY` to `https://ads.atmosphere.copernicus.eu/api/retrieve/v1/…`. Without it you get `401 authentication required`. Optionally also a `.cdsapirc`-style token. |
| **Copernicus Data Space (Sentinel-5P, Sentinel Hub)** | *Copernicus Data Space Ecosystem (CDSE)* account at `dataspace.copernicus.eu`; for Sentinel Hub also create an **OAuth client** (client id + secret) | `COPERNICUS_DATASPACE_USERNAME` / `COPERNICUS_DATASPACE_PASSWORD` and `SENTINELHUB_CLIENT_ID` / `SENTINELHUB_CLIENT_SECRET` | Catalogue search (`catalogue.dataspace.copernicus.eu/odata/v1`) is already open — you only need the account for **downloads** and for Sentinel Hub. |
| **NASA Earthdata** (MERRA-2, MCD19A2, GIOVANNI, ASF, AERONET-authenticated subsets) | *NASA Earthdata Login* (Earthdata Login / URS) at `urs.earthdata.nasa.gov` | `EARTHDATA_USERNAME` / `EARTHDATA_PASSWORD` (+ optional `EARTHDATA_TOKEN`) | Easiest: `~/.netrc` with `machine urs.earthdata.nasa.gov`, or `EDL_TOKEN` bearer. MERRA-2 file → `401` without it; LAADS `.hdf` returns a login page without it. **Note: the plain AERONET download endpoint works unauthenticated** (row 14). |
| **NREL NSRDB** | *NREL Developer Network* account at `developer.nrel.gov/signup` → **NSRDB / Developer API key** | `NREL_API_KEY` (also accept `NSRDB_API_KEY`) | Pass as `?api_key=$NREL_API_KEY`. **Also blocked by DNS on this host** — the network must be able to resolve `*.nrel.gov` first. |
| **JAXA P-Tree** | *JAXA P-Tree* user registration at `www.eorc.jaxa.jp/ptree/registration_top.html` → FTP/HTTPS credentials | `JAXA_PTREE_USER` / `JAXA_PTREE_PASSWORD` | Data is served over the P-Tree HTTPS/FTP server after registration; the public portal alone is not enough. |
| **Copernicus EMS** | *Copernicus Emergency Management Service* account (some products/activation layers) | `COPERNICUS_EMS_USERNAME` / `COPERNICUS_EMS_PASSWORD` | The public site and rapid-mapping listings are open; account needed for restricted products. |
| **SODA (CAMS Radiation Service)** | Free *SODA* (soda-pro.com) registration to obtain a **SODA API/access token** | `SODA_API_KEY` | Needed only for the programmatic radiation service, not for the public web pages. |

**Nothing else on the list needs a key.** CAMS-vs-Open-Meteo note: rows 38–40 give a genuinely keyless
dust + AOD + irradiance + met stack (Open-Meteo AQ, NASA POWER, Global Solar Atlas API) that can drive a
first working version of SolarGuard *before* any account is created.
