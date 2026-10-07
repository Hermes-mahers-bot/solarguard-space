#!/usr/bin/env bash
# Probe all 40 sources: record HTTP code, bytes, content-type, redirect, error.
OUT=/home/hermes2/solarguard-space/data/_probe.tsv
: > "$OUT"
probe() {
  local id="$1"; local url="$2"
  local res
  res=$(curl -sL --max-time 45 -A "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36" \
        -o /dev/null -w '%{http_code}\t%{size_download}\t%{content_type}\t%{url_effective}\t%{num_redirects}' "$url" 2>"$TMPERR") || true
  local err; err=$(tr '\n' ' ' < "$TMPERR" | cut -c1-200)
  printf '%s\t%s\t%s\t%s\n' "$id" "$url" "$res" "$err" >> "$OUT"
  printf '%-3s %-6s %-10s %s\n' "$id" "$(echo "$res" | cut -f1)" "$(echo "$res" | cut -f2)" "$url"
}
TMPERR=$(mktemp)

# --- Atmos / aerosol ---
probe 01 "https://ads.atmosphere.copernicus.eu/datasets/cams-global-atmospheric-composition-forecasts"
probe 02 "https://www.soda-pro.com/web-services/radiation/cams-radiation-service"
probe 03 "https://atmosphere.copernicus.eu/cams-aerosol-alerts-atmospheric-aerosol-data-your-fingertips"
probe 04 "https://noaa-himawari9.s3.amazonaws.com/?list-type=2&max-keys=3"
probe 05 "https://registry.opendata.aws/noaa-himawari/"
probe 06 "https://www.eorc.jaxa.jp/ptree/"
probe 07 "https://himawari8.nict.go.jp/"
probe 08 "https://www.ospo.noaa.gov/Products/imagery/index.html"
probe 09 "https://disc.gsfc.nasa.gov/datasets?project=MERRA-2"
probe 10 "https://ladsweb.modaps.eosdis.nasa.gov/missions-and-measurements/products/MCD19A2/"
probe 11 "https://dataspace.copernicus.eu/explore-data/data-collections/sentinel-data/sentinel-5p"
probe 12 "https://dust.aemet.es/"
probe 13 "https://aeronet.gsfc.nasa.gov/aeronet_locations_v3.txt"
probe 14 "https://aeronet.gsfc.nasa.gov/new_web/data.html"
probe 15 "https://giovanni.gsfc.nasa.gov/giovanni/"
probe 16 "https://power.larc.nasa.gov/docs/services/api/temporal/hourly/"
probe 17 "https://noaa-gfs-bdp-pds.s3.amazonaws.com/?list-type=2&max-keys=3"
probe 18 "https://data.ecmwf.int/forecasts/"
# --- Solar resource / tools ---
probe 19 "https://nsrdb.nrel.gov/"
probe 20 "https://globalsolaratlas.info/"
probe 21 "https://pvlib-python.readthedocs.io/en/stable/"
probe 22 "https://dataspace.copernicus.eu/"
probe 23 "https://browser.dataspace.copernicus.eu/"
probe 24 "https://search.asf.alaska.edu/"
probe 25 "https://emergency.copernicus.eu/"
# --- Papers ---
probe 26 "https://iea-pvps.org/wp-content/uploads/2023/01/IEA-PVPS-T13-21-2022-REPORT-Soiling-Losses-PV-Plants.pdf"
probe 27 "https://res.mdpi.com/d_attachment/energies/energies-15-08033/article_deploy/energies-15-08033.pdf"
probe 28 "https://res.mdpi.com/d_attachment/energies/energies-19-04373/article_deploy/energies-19-04373.pdf"
probe 29 "https://www.mdpi.com/1996-1073/15/21/8033"
probe 30 "https://www.mdpi.com/1996-1073/19/18/4373"
probe 31 "https://www.sciencedirect.com/science/article/pii/S2238785425027103"
probe 32 "https://repository.kaust.edu.sa/handle/10754/665153"
probe 33 "https://repository.kaust.edu.sa/handle/10754/696394"
probe 34 "https://www.kippzonen.com/products/dustiq-soiling-monitoring-system"
probe 35 "https://www.nrel.gov/pv/soiling.html"
probe 36 "https://www.windy.com/?dustsm,24.7,46.6,6"
probe 37 "https://www.ventusky.com/?p=24.7;46.6;5&l=dust"
# --- Others / APIs to test ---
probe 38 "https://api.open-meteo.com/v1/forecast?latitude=24.71&longitude=46.67"
probe 39 "https://air-quality-api.open-meteo.com/v1/air-quality?latitude=24.71&longitude=46.67&hourly=dust,aerosol_optical_depth,pm10&forecast_days=1"
probe 40 "https://power.larc.nasa.gov/api/temporal/hourly/point?parameters=T2M,WS10M&community=RE&longitude=46.67&latitude=24.71&start=20260101&end=20260101&format=JSON"
rm -f "$TMPERR"
echo "=== done -> $OUT ==="
