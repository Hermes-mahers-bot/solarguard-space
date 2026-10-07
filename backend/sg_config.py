"""
SolarGuard Space — shared configuration.

Everything the backend needs to know about paths, the Saudi site catalogue,
dust/aerosol layers, and the DeepSeek credentials, in one importable place.

Nothing here is secret except the contents of backend/.env, which is read from
disk at runtime and never printed, logged, or sent to a browser.
"""
from __future__ import annotations

import os
from pathlib import Path

# ---------------------------------------------------------------- paths
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent                      # /home/hermes2/solarguard-space
PUBLIC = ROOT / "public"
DATA = ROOT / "data"
CACHE = DATA / "cache"
MODELS = ROOT / "models"
CORPUS = DATA / "corpus"
DOCS = ROOT / "docs"

for _p in (CACHE, MODELS, CORPUS):
    _p.mkdir(parents=True, exist_ok=True)

VERSION = "1.0.0"
SERVICE = "solarguard-space"


# ---------------------------------------------------------------- env
def _load_env() -> dict:
    """Tiny hand-rolled .env parser (no dependency, same convention as the
    space-marines backend). First readable file wins."""
    env: dict = {}
    for candidate in (HERE / ".env", ROOT.parent / "space-marines" / "backend" / ".env"):
        try:
            raw = candidate.read_text()
        except OSError:
            continue
        found = False
        for line in raw.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            found = True
        if found:
            env["_source"] = str(candidate)
    for k in ("DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


ENV = _load_env()
DEEPSEEK_KEY = ENV.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE = ENV.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
DEEPSEEK_MODEL = os.environ.get("SOLARGUARD_MODEL", "deepseek-flash")

HTTP_TIMEOUT = 25.0        # hard timeout on every outbound call
HTTP_USER_AGENT = "SolarGuardSpace/1.0 (hackathon; contact: space-marines)"

# ---------------------------------------------------------------- Saudi sites
# Curated Saudi solar locations. `climate` drives the soiling prior:
#   west = Red Sea coast (low dust, high humidity), east = Gulf coast
#   (heavy dust + humidity + cementation), inland = central desert.
SITES = [
    {"id": "sakaka",   "name": "Sakaka Solar PV",      "lat": 29.97, "lon": 40.20, "region": "Al Jouf",         "climate": "inland", "capacity_mwp": 300,  "note": "Saudi Aramco / Marubeni 300 MW plant"},
    {"id": "sudair",   "name": "Sudair Solar PV",      "lat": 25.55, "lon": 45.55, "region": "Riyadh Province", "climate": "inland", "capacity_mwp": 1500, "note": "1.5 GW, PIF / ACWA Power"},
    {"id": "riyadh",   "name": "Riyadh (industrial)",  "lat": 24.71, "lon": 46.67, "region": "Riyadh Province", "climate": "inland", "capacity_mwp": 50,   "note": "urban inland reference site"},
    {"id": "jeddah",   "name": "Jeddah (Red Sea)",     "lat": 21.49, "lon": 39.19, "region": "Makkah Province", "climate": "west",   "capacity_mwp": 100,  "note": "west-coast reference, ~15% soiling loss (KAUST)"},
    {"id": "yanbu",    "name": "Yanbu Industrial City","lat": 24.09, "lon": 38.06, "region": "Madinah Province","climate": "west",   "capacity_mwp": 120,  "note": "west coast + heavy industry"},
    {"id": "dammam",   "name": "Dammam / Eastern Prov","lat": 26.43, "lon": 50.10, "region": "Eastern Province","climate": "east",   "capacity_mwp": 200,  "note": "east coast, ~45% soiling loss (KAUST)"},
    {"id": "jubail",   "name": "Al Jubail",            "lat": 27.00, "lon": 49.66, "region": "Eastern Province","climate": "east",   "capacity_mwp": 180,  "note": "east coast, dust + petrochemical haze"},
    {"id": "neom",     "name": "NEOM",                 "lat": 27.99, "lon": 35.25, "region": "Tabuk Province",  "climate": "west",   "capacity_mwp": 400,  "note": "giga-project, coastal desert"},
    {"id": "alula",    "name": "AlUla",                "lat": 26.61, "lon": 37.92, "region": "Madinah Province","climate": "inland", "capacity_mwp": 60,   "note": "inland heritage region"},
    {"id": "tabuk",    "name": "Tabuk",                "lat": 28.38, "lon": 36.57, "region": "Tabuk Province",  "climate": "inland", "capacity_mwp": 90,   "note": "north-west inland"},
    {"id": "abha",     "name": "Abha (Asir highlands)", "lat": 18.22, "lon": 42.50, "region": "Asir Province",  "climate": "highland","capacity_mwp": 40,  "note": "high elevation, more rain, less dust"},
    {"id": "shaqra",   "name": "Shaqra",               "lat": 25.25, "lon": 45.25, "region": "Riyadh Province", "climate": "inland", "capacity_mwp": 30,   "note": "dust-belt inland reference"},
]

CLIMATE_PRIOR_LOSS = {"west": 15.0, "east": 45.0, "inland": 30.0, "highland": 12.0}

# ---------------------------------------------------------------- economics
TARIFF_SAR_PER_KWH = 0.18          # Saudi industrial/commercial reference tariff

# Cleaning cost is the single most sensitive assumption in the whole economics, so
# it is explicit and switchable. Reference point: IEA-PVPS T13-21:2022 "Soiling
# Losses" works its example at 0.2 EUR/m2 of module surface per cleaning, which for
# 17.5 %-efficient modules is ~5,100 SAR per MWp per event. Saudi conditions differ:
# dry/waterless brushing and robotic fleets are far cheaper per pass than European
# manual washing, and labour is cheaper, so the default is the Saudi dry-cleaning
# regime and the others stay one click away in the dashboard.
CLEANING_PRESETS = {
    "dry_saudi":    {"sar_per_mwp": 1800.0, "label": "Dry / waterless brush (Saudi default)"},
    "robotic":      {"sar_per_mwp": 600.0,  "label": "Robotic fleet, amortised"},
    "manual_iea":   {"sar_per_mwp": 5100.0, "label": "Manual contractor (IEA 0.2 EUR/m2)"},
}
CLEANING_COST_SAR_PER_MWP = CLEANING_PRESETS["dry_saudi"]["sar_per_mwp"]
MODULE_EFFICIENCY = 0.175          # 17.5 % modules -> 5.71 m2 of glass per kWp
WATER_LITRES_PER_MWP_WET_CLEAN = 2500.0
# What operators do today: the 300 MW Sakaka plant in Saudi Arabia cleans each row
# on average every 10 days with a brush tractor and water pumps, and Sudair (1.5 GW)
# is moving to robotic cleaning — Q. Sakaka/Sudair notes, Energies 2022, 15, 8033.
DEFAULT_CLEANING_INTERVAL_DAYS = 10

# ---------------------------------------------------------------- GIBS layers
# NASA GIBS: open WMTS satellite imagery, no API key. The catalog is parsed from
# the live capabilities document by harvest/probe_gibs.py into data/gibs_layers.json.
GIBS_BASE = "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best"
GIBS_LAYERS = [
    {"id": "MODIS_Terra_Aerosol", "label": "MODIS Aerosol Optical Depth (Terra)", "tms": "GoogleMapsCompatible_Level6", "kind": "daily", "unit": "AOD"},
    {"id": "MODIS_Aqua_Aerosol_Optical_Depth_3km", "label": "MODIS AOD 3km (Aqua)", "tms": "GoogleMapsCompatible_Level6", "kind": "daily", "unit": "AOD"},
    {"id": "MODIS_Combined_MAIAC_L2G_AerosolOpticalDepth", "label": "MAIAC AOD 1km (combined)", "tms": "GoogleMapsCompatible_Level8", "kind": "daily", "unit": "AOD"},
    {"id": "MODIS_Terra_AOD_Deep_Blue_Land", "label": "MODIS Deep Blue AOD over land", "tms": "GoogleMapsCompatible_Level6", "kind": "daily", "unit": "AOD"},
    {"id": "AIRS_L2_Dust_Score_Day", "label": "AIRS Dust Score (day)", "tms": "GoogleMapsCompatible_Level6", "kind": "daily", "unit": "index"},
    {"id": "MERRA2_Dust_Surface_Mass_Concentration_Monthly", "label": "MERRA-2 Dust Surface Mass (monthly)", "tms": "GoogleMapsCompatible_Level6", "kind": "monthly", "unit": "µg/m³"},
    {"id": "MERRA2_Total_Aerosol_Optical_Thickness_550nm_Extinction_Monthly", "label": "MERRA-2 AOT 550nm (monthly)", "tms": "GoogleMapsCompatible_Level6", "kind": "monthly", "unit": "AOT"},
    {"id": "MERRA2_Total_Dust_Deposition_Dry_Wet_Monthly", "label": "MERRA-2 Dust Deposition dry+wet (monthly)", "tms": "GoogleMapsCompatible_Level6", "kind": "monthly", "unit": "kg/m²s"},
]

# Saudi Arabia bounding box used to constrain map tiles and coverage checks
KSA_BBOX = {"south": 16.0, "north": 32.5, "west": 34.0, "east": 56.0}
